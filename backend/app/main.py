import asyncio
import hashlib
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .privacy import PrivacyMiddleware, install_redaction
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import case, func, select, text
from sqlalchemy.exc import IntegrityError

from .config import settings
from .db import AutomationEvent, Frontier, Job, PageVisit, Schedule, Session, Website, Workflow, emit, transaction
from .jobs import TERMINAL, make_job, next_occurrence
from .schemas import JobInput, ScheduleInput, SchedulePatch, WebsiteInput, WorkflowInput
from .security import Policy
from .api_support import Limit, Offset, Owner, collection, output, owned, workflow_for
from .api_support import rate_windows as rate_windows
from .agent.api import router as agent_router
from .content import router as content_router
from .outbound import manager
from .network_api import router as network_router
from .user_agents import router as user_agent_router

logger = logging.getLogger("adbot.api")
logging.basicConfig(level=logging.INFO, format="%(message)s")
install_redaction()


@asynccontextmanager
async def lifespan(app):
    app.state.redis = None
    routing = None
    try:
        if settings().redis_url:
            from redis.asyncio import Redis

            app.state.redis = Redis.from_url(settings().redis_url)
            await app.state.redis.ping()
        routing = manager()
        routing.start()
        yield
    finally:
        if routing:
            await routing.close()
        if app.state.redis:
            await app.state.redis.aclose()


app = FastAPI(title="AdBot — Authorized Website Automation", version="1.0.0", lifespan=lifespan,
              docs_url=None if settings().environment == "production" else "/docs",
              redoc_url=None if settings().environment == "production" else "/redoc",
              openapi_url=None if settings().environment == "production" else "/openapi.json")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings().cors_origins.split(","),
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Last-Event-ID"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=[h.strip() for h in settings().allowed_hosts.split(",")])


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse({"detail": [{"loc": e["loc"], "type": e["type"], "msg": "Invalid value"} for e in exc.errors()]}, status_code=422)


app.include_router(user_agent_router)
app.include_router(network_router)
app.include_router(content_router)
app.include_router(agent_router)


@app.middleware("http")
async def headers(request, call_next):
    started = time.monotonic()
    # Bound JSON input independently of Pydantic validation. Streaming requests
    # cannot bypass this check by omitting Content-Length.
    if request.method in {"POST", "PATCH"}:
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 262144:
                return JSONResponse({"detail": "Request body too large"}, status_code=413)
        request._body = bytes(body)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    logger.info(
        json.dumps(
            {
                "event": "request",
                "method": request.method,
                "route": getattr(request.scope.get("route"), "path", "unmatched"),
                "status": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
        )
    )
    return response


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/ready")
async def ready(request: Request):
    try:
        with Session() as session:
            session.execute(text("SELECT 1 FROM websites LIMIT 1"))
            session.execute(text("SELECT revision FROM user_agent_config LIMIT 1"))
        if settings().redis_url:
            await request.app.state.redis.ping()
    except Exception:
        raise HTTPException(503, "Service temporarily unavailable") from None
    return {"status": "ready"}


@app.get("/api/websites")
def websites(owner: Owner, offset: Offset = 0, limit: Limit = 100):
    with Session() as session:
        return collection(
            session, select(Website).where(Website.owner == owner).order_by(Website.created_at.desc()), offset, limit
        )


@app.post("/api/websites", status_code=201)
async def add_website(data: WebsiteInput, owner: Owner):
    try:
        await Policy(data.allowed_domains).resolve(data.base_url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with transaction() as session:
        site = Website(owner=owner, **data.model_dump(exclude={"authorized"}))
        session.add(site)
        session.flush()
        return output(site)


@app.get("/api/websites/{identifier}")
def website(identifier: str, owner: Owner):
    with Session() as session:
        return output(owned(session, Website, identifier, owner))


@app.patch("/api/websites/{identifier}")
async def edit_website(identifier: str, data: WebsiteInput, owner: Owner):
    try:
        await Policy(data.allowed_domains).resolve(data.base_url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with transaction() as session:
        site = owned(session, Website, identifier, owner)
        for k, v in data.model_dump(exclude={"authorized"}).items():
            setattr(site, k, v)
        session.flush()
        return output(site)


@app.delete("/api/websites/{identifier}", status_code=204)
def delete_website(identifier: str, owner: Owner):
    with transaction() as session:
        site = owned(session, Website, identifier, owner)
        active = session.scalar(
            select(Job.id).where(Job.website_id == identifier, Job.status.not_in(TERMINAL)).limit(1)
        )
        if active:
            raise HTTPException(409, "Cancel active jobs before deleting this website")
        # Schedules reference workflows with RESTRICT; remove them first.
        for schedule in session.scalars(select(Schedule).where(Schedule.website_id == identifier)):
            session.delete(schedule)
        session.flush()
        session.delete(site)


@app.post("/api/jobs", status_code=201)
async def start_job(
    data: JobInput,
    request: Request,
    owner: Owner,
    idempotency_key: Annotated[str | None, Header(max_length=160)] = None,
):
    try:
        with transaction() as session:
            site = owned(session, Website, data.website_id, owner)
            workflow = workflow_for(session, data.workflow_id, site.id, owner)
            job = make_job(session, site, workflow, idempotency_key)
            result = output(job)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except IntegrityError:
        with Session() as session:
            existing = session.scalar(select(Job).where(Job.owner == owner, Job.idempotency_key == idempotency_key))
            if not existing:
                raise HTTPException(409, "Concurrent request conflict; retry") from None
            expected = hashlib.sha256(json.dumps(data.model_dump(), sort_keys=True).encode()).hexdigest()
            if existing.payload_hash != expected:
                raise HTTPException(409, "Idempotency key was used for a different request") from None
            result = output(existing)
    redis = getattr(request.app.state, "redis", None)
    if redis:
        try:
            await redis.lpush("adbot:wakeup", "job")
            await redis.ltrim("adbot:wakeup", 0, 99)
        except Exception:
            pass  # Database queue remains durable even if wakeup delivery fails.
    return result


@app.get("/api/jobs")
def jobs(owner: Owner, offset: Offset = 0, limit: Limit = 100, status: str | None = None):
    with Session() as session:
        query = select(Job).where(Job.owner == owner).order_by(Job.created_at.desc())
        if status:
            query = query.where(Job.status == status)
        return collection(session, query, offset, limit)


@app.get("/api/jobs/{identifier}")
def job(identifier: str, owner: Owner):
    with Session() as session:
        item = owned(session, Job, identifier, owner)
        data = output(item)
        data["discovered_count"] = session.scalar(
            select(func.count()).select_from(Frontier).where(Frontier.job_id == identifier)
        )
        return data


@app.post("/api/jobs/{identifier}/cancel")
def cancel_job(identifier: str, owner: Owner):
    with transaction() as session:
        item = owned(session, Job, identifier, owner)
        if item.status not in TERMINAL:
            item.cancel_requested = True
            if item.status == "queued":
                item.status, item.completed_at = "cancelled", time.time()
            emit(session, identifier, "cancellation_requested", "Cancellation requested")
        return output(item)


@app.post("/api/jobs/{identifier}/pause")
def pause_job(identifier: str, owner: Owner):
    return pause_resume(identifier, owner, True)


@app.post("/api/jobs/{identifier}/resume")
def resume_job(identifier: str, owner: Owner):
    return pause_resume(identifier, owner, False)


def pause_resume(identifier, owner, pause):
    with transaction() as session:
        item = owned(session, Job, identifier, owner)
        if item.status not in {"running", "paused", "waiting_user"}:
            raise HTTPException(409, "Job must be running or paused")
        item.pause_requested = pause
        emit(session, identifier, "pause_requested" if pause else "resume_requested", "Control requested")
        return output(item)


@app.post("/api/jobs/{identifier}/retry", status_code=201)
def retry_job(identifier: str, owner: Owner):
    with transaction() as session:
        item = owned(session, Job, identifier, owner)
        if item.job_type == "agent":
            raise HTTPException(409, "Create a new agent task explicitly after reviewing its outcomes")
        if item.status not in {"failed", "cancelled"}:
            raise HTTPException(409, "Only failed or cancelled jobs can be retried")
        if "workflow" in item.snapshot and any(s["action"] == "CLICK" for s in item.snapshot["workflow"]["steps"]):
            raise HTTPException(409, "Review CLICK results and explicitly launch a new job")
        job = Job(
            owner=owner,
            website_id=item.website_id,
            snapshot=item.snapshot,
            job_type=item.job_type,
            retry_count=item.retry_count + 1,
        )
        session.add(job)
        session.flush()
        session.add(
            Frontier(job_id=job.id, discovered_url=item.snapshot["base_url"], normalized_url=item.snapshot["base_url"])
        )
        emit(session, job.id, "queued", "Manual retry queued", previous_job_id=item.id)
        return output(job)


@app.get("/api/jobs/{identifier}/pages")
def pages(
    identifier: str, owner: Owner, offset: Offset = 0, limit: Limit = 100, q: str = "", http_status: int | None = None
):
    with Session() as session:
        owned(session, Job, identifier, owner)
        query = select(PageVisit).where(PageVisit.job_id == identifier).order_by(PageVisit.id)
        if q:
            query = query.where(PageVisit.requested_url.contains(q, autoescape=True))
        if http_status:
            query = query.where(PageVisit.http_status == http_status)
        return collection(session, query, offset, limit)


@app.get("/api/jobs/{identifier}/logs")
def logs(identifier: str, owner: Owner, after: int = 0, limit: Limit = 100):
    with Session() as session:
        owned(session, Job, identifier, owner)
        return collection(
            session,
            select(AutomationEvent)
            .where(AutomationEvent.job_id == identifier, AutomationEvent.id > after)
            .order_by(AutomationEvent.id),
            0,
            limit,
        )


@app.get("/api/jobs/{identifier}/events")
async def events(
    identifier: str,
    request: Request,
    owner: Owner,
    last_event_id: Annotated[str | None, Header()] = None,
    after: int = 0,
):
    with Session() as session:
        owned(session, Job, identifier, owner)
    try:
        cursor = max(after, int(last_event_id or "0"))
    except ValueError:
        raise HTTPException(422, "Last-Event-ID must be an integer") from None

    async def stream():
        nonlocal cursor
        deadline = time.monotonic() + 55
        while time.monotonic() < deadline and not await request.is_disconnected():
            with Session() as session:
                job = owned(session, Job, identifier, owner)
                batch = session.scalars(
                    select(AutomationEvent)
                    .where(AutomationEvent.job_id == identifier, AutomationEvent.id > cursor)
                    .order_by(AutomationEvent.id)
                    .limit(100)
                ).all()
                terminal = job.status in TERMINAL
                for event in batch:
                    cursor = event.id
                    yield f"id: {cursor}\nevent: progress\ndata: {json.dumps(output(event))}\n\n"
            if terminal and not batch:
                return
            if not batch:
                yield ": heartbeat\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@app.get("/api/artifacts/{name}")
def artifact(name: str, owner: Owner):
    if Path(name).name != name or not name.endswith((".png", ".bin")) or len(name) > 150:
        raise HTTPException(404, "Artifact not found")
    with Session() as session:
        owned(session, Job, name[:36], owner)
    root = settings().artifact_dir.resolve()
    path = (root / name).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(404, "Artifact not found or retention expired")
    return FileResponse(
        path,
        media_type="image/png" if name.endswith(".png") else "application/octet-stream",
        filename=name if name.endswith(".bin") else None,
    )


@app.get("/api/workflows")
def workflows(owner: Owner, offset: Offset = 0, limit: Limit = 100):
    with Session() as session:
        return collection(
            session, select(Workflow).join(Website).where(Website.owner == owner).order_by(Workflow.name), offset, limit
        )


@app.post("/api/workflows", status_code=201)
def add_workflow(data: WorkflowInput, owner: Owner):
    with transaction() as session:
        site = owned(session, Website, data.website_id, owner)
        for step in data.definition.steps:
            if step.action == "OPEN_URL":
                try:
                    Policy(site.allowed_domains, site.configuration).check(step.url)
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from exc
        item = Workflow(**data.model_dump())
        session.add(item)
        session.flush()
        return output(item)


@app.patch("/api/workflows/{identifier}")
def edit_workflow(identifier: str, data: WorkflowInput, owner: Owner):
    with transaction() as session:
        item = owned(session, Workflow, identifier, owner)
        if item.website_id != data.website_id:
            raise HTTPException(422, "A workflow cannot move between websites")
        site = owned(session, Website, data.website_id, owner)
        for step in data.definition.steps:
            if step.action == "OPEN_URL":
                try:
                    Policy(site.allowed_domains, site.configuration).check(step.url)
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from exc
        for key, value in data.model_dump().items():
            setattr(item, key, value)
        item.version += 1
        session.flush()
        return output(item)


@app.delete("/api/workflows/{identifier}", status_code=204)
def delete_workflow(identifier: str, owner: Owner):
    with transaction() as session:
        item = owned(session, Workflow, identifier, owner)
        if session.scalar(select(Schedule.id).where(Schedule.workflow_id == identifier).limit(1)):
            raise HTTPException(409, "Remove dependent schedules first")
        session.delete(item)


def schedule_values(data):
    if data.cron_expression:
        return data.model_dump(exclude={"run_at"}) | {
            "next_run_at": next_occurrence(data.cron_expression, data.timezone, time.time())
        }
    stamp = data.run_at.timestamp()
    if stamp <= time.time():
        raise HTTPException(422, "run_at must be in the future")
    return data.model_dump(exclude={"run_at"}) | {"next_run_at": stamp}


@app.post("/api/schedules", status_code=201)
def add_schedule(data: ScheduleInput, owner: Owner):
    with transaction() as session:
        owned(session, Website, data.website_id, owner)
        workflow_for(session, data.workflow_id, data.website_id, owner)
        item = Schedule(**schedule_values(data))
        session.add(item)
        session.flush()
        return output(item)


@app.get("/api/schedules")
def schedules(owner: Owner, offset: Offset = 0, limit: Limit = 100):
    with Session() as session:
        return collection(
            session,
            select(Schedule).join(Website).where(Website.owner == owner).order_by(Schedule.next_run_at),
            offset,
            limit,
        )


@app.patch("/api/schedules/{identifier}")
def edit_schedule(identifier: str, data: SchedulePatch, owner: Owner):
    with transaction() as session:
        item = owned(session, Schedule, identifier, owner)
        from datetime import datetime, timezone

        merged = {
            "website_id": item.website_id,
            "workflow_id": item.workflow_id,
            "cron_expression": item.cron_expression,
            "timezone": item.timezone,
            "enabled": item.enabled,
            "run_at": datetime.fromtimestamp(max(item.next_run_at, time.time() + 1), timezone.utc),
        }
        merged.update(data.model_dump(exclude_unset=True))
        try:
            validated = ScheduleInput(**merged)
        except ValueError:
            raise HTTPException(422, "Invalid schedule configuration") from None
        for key, value in schedule_values(validated).items():
            setattr(item, key, value)
        session.flush()
        return output(item)


@app.delete("/api/schedules/{identifier}", status_code=204)
def delete_schedule(identifier: str, owner: Owner):
    with transaction() as session:
        session.delete(owned(session, Schedule, identifier, owner))


@app.get("/api/analytics/overview")
def overview(owner: Owner):
    with Session() as session:
        counts = dict(
            session.execute(select(Job.status, func.count()).where(Job.owner == owner).group_by(Job.status)).all()
        )
        visits = select(PageVisit).join(Job).where(Job.owner == owner).subquery()
        total, avg = session.execute(
            select(func.count(), func.avg(visits.c.navigation_duration_ms)).select_from(visits)
        ).one()
        status = session.execute(select(visits.c.http_status, func.count()).group_by(visits.c.http_status)).all()
        failures = (
            session.scalar(
                select(func.sum(case(((visits.c.http_status >= 400) | visits.c.error.is_not(None), 1), else_=0)))
            )
            or 0
        )
        scheduled = dict(
            session.execute(
                select(Job.status, func.count())
                .where(Job.owner == owner, Job.idempotency_key.like("schedule:%"))
                .group_by(Job.status)
            ).all()
        )
        finished_scheduled = sum(scheduled.get(s, 0) for s in TERMINAL)
        # Epoch-day buckets work identically on SQLite and PostgreSQL.
        day = func.floor(visits.c.visited_at / 86400) * 86400
        trend = session.execute(
            select(day.label("day"), func.count())
            .where(visits.c.visited_at > time.time() - 30 * 86400)
            .group_by(day)
            .order_by(day)
        ).all()
        return {
            "websites": session.scalar(select(func.count()).select_from(Website).where(Website.owner == owner)),
            "jobs": sum(counts.values()),
            "statuses": counts,
            "pages": total,
            "average_ms": avg or 0,
            "failure_rate": failures / total if total else 0,
            "scheduled_jobs": sum(scheduled.values()),
            "scheduled_success_rate": scheduled.get("completed", 0) / finished_scheduled
            if finished_scheduled
            else None,
            "http_statuses": [{"status": s or "network error", "count": c} for s, c in status],
            "daily_pages": [{"day": d, "count": c} for d, c in trend],
        }


@app.get("/api/analytics/websites")
def website_analytics(owner: Owner):
    with Session() as session:
        return [
            {
                "id": site.id,
                "name": site.name,
                "jobs": session.scalar(select(func.count()).select_from(Job).where(Job.website_id == site.id)),
                "pages": session.scalar(
                    select(func.count()).select_from(PageVisit).join(Job).where(Job.website_id == site.id)
                ),
                "discovered": session.scalar(
                    select(func.count()).select_from(Frontier).join(Job).where(Job.website_id == site.id)
                ),
            }
            for site in session.scalars(select(Website).where(Website.owner == owner))
        ]

# Outermost: cover body-size, CORS, host-validation and application errors alike.
app.add_middleware(PrivacyMiddleware)
