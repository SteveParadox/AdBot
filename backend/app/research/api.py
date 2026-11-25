"""Authenticated, owner-scoped research jobs and conversation history."""

import hashlib
import json
import time
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from ..api_support import Limit, Offset, Owner, collection, output
from ..concurrency import database_call
from ..config import settings
from ..db import Job, ResearchConversation, ResearchTask, Session, emit, transaction
from ..jobs import TERMINAL, check_capacity
from .contracts import Mode, Question, Strict, budget_for, route
from .evidence import country_from
from .runner import previous_turns
from .search import configured_providers

router = APIRouter(prefix="/api/research/v1", tags=["web research"])
Key = Annotated[str | None, Header(alias="Idempotency-Key", min_length=1, max_length=160)]


class ConversationInput(Strict):
    title: str = Field(default="", max_length=160)


def task_row(session, identifier, owner):
    row = session.execute(
        select(Job, ResearchTask).join(ResearchTask, ResearchTask.job_id == Job.id)
        .where(Job.id == identifier, Job.owner == owner, Job.job_type == "research")
    ).first()
    if row is None:
        raise HTTPException(404, "Research task not found")
    return row


def conversation(session, identifier, owner, *, lock=False):
    query = select(ResearchConversation).where(ResearchConversation.id == identifier, ResearchConversation.owner == owner)
    item = session.scalar(query.with_for_update() if lock else query)
    if item is None:
        raise HTTPException(404, "Research conversation not found")
    return item


def task_output(job, task, full=False):
    result = {
        "id": job.id, "conversation_id": task.conversation_id, "question": task.question,
        "intent": task.intent, "mode": task.mode, "status": job.status,
        "created_at": job.created_at, "started_at": job.started_at, "completed_at": job.completed_at,
        "error": job.error_message, "quality": task.result.get("quality"),
    }
    if full:
        result["result"] = {k: v for k, v in task.result.items() if k not in {"search_results", "evidence"}}
        result["budget"] = task.budget
    return result


def existing(session, owner, key, digest):
    if not key:
        return None
    job = session.scalar(select(Job).where(Job.owner == owner, Job.idempotency_key == key))
    if job:
        if job.job_type != "research" or job.payload_hash != digest:
            raise HTTPException(409, "Idempotency key was used for a different request")
        return task_output(job, session.get(ResearchTask, job.id), full=True)
    return None


def enqueue(data, owner, key, retry_of=None):
    if not settings().research_enabled:
        raise HTTPException(503, "Research is disabled. Configure ADBOT_RESEARCH_ENABLED on the server.")
    values = data.model_dump(mode="json")
    digest = hashlib.sha256(json.dumps([values, retry_of], sort_keys=True).encode()).hexdigest()
    try:
        with transaction() as session:
            previous = existing(session, owner, key, digest)
            if previous:
                return previous
            # Queue capacity also locks the shared automation control row. This
            # serializes new work with other enqueue paths and worker claims.
            check_capacity(session)
            previous = existing(session, owner, key, digest)
            if previous:
                return previous
            if data.conversation_id:
                thread = conversation(session, data.conversation_id, owner, lock=True)
                active = session.scalar(select(Job.id).join(ResearchTask, ResearchTask.job_id == Job.id).where(
                    ResearchTask.conversation_id == thread.id, Job.status.not_in(TERMINAL)
                ).limit(1))
                if active:
                    raise HTTPException(409, "Finish or stop the current turn before sending another message")
            else:
                thread = ResearchConversation(owner=owner)
                session.add(thread)
                session.flush()
            if not thread.title:
                thread.title = data.question[:160]
            thread.updated_at = time.time()
            history = previous_turns(session, thread.id, owner)
            intent, mode = route(data, history)
            budget = budget_for(mode)
            values.update(conversation_id=thread.id, country=country_from(data.question, data.country)
                          or (history[-1].get("country") if intent == "follow_up" and history else None))
            job = Job(owner=owner, job_type="research", website_id=None, idempotency_key=key, payload_hash=digest,
                      snapshot={"allowed_domains": [], "configuration": {"max_duration_seconds": budget.seconds}})
            session.add(job)
            session.flush()
            task = ResearchTask(job_id=job.id, conversation_id=thread.id, mode=mode.value, intent=intent,
                                question=values, budget=budget.model_dump())
            session.add(task)
            emit(session, job.id, "research_queued", "Research queued", mode=mode.value)
            session.flush()
            return task_output(job, task, full=True)
    except IntegrityError:
        with Session() as session:
            previous = existing(session, owner, key, digest)
            if previous:
                return previous
        raise HTTPException(409, "Concurrent research update; retry with the same key") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/query", status_code=202)
async def query(data: Question, owner: Owner, request: Request, key: Key = None):
    return await submit(data, owner, request, key)


async def submit(data, owner, request, key, retry_of=None):
    result = await database_call(enqueue, data, owner, key, retry_of)
    redis = getattr(request.app.state, "redis", None)
    if redis:
        try:
            await redis.lpush("adbot:wakeup", result["id"])
        except Exception:
            pass  # The SQL job remains queued without a Redis wakeup.
    return result


@router.get("/tasks")
def tasks(owner: Owner, offset: Offset = 0, limit: Limit = 25):
    with Session() as session:
        query = select(Job, ResearchTask).join(ResearchTask, ResearchTask.job_id == Job.id).where(Job.owner == owner)
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        rows = session.execute(query.order_by(Job.created_at.desc(), Job.id).offset(offset).limit(limit))
        return {"items": [task_output(job, task) for job, task in rows], "total": total}


@router.get("/tasks/{identifier}")
def task(identifier: str, owner: Owner):
    with Session() as session:
        return task_output(*task_row(session, identifier, owner), full=True)


@router.get("/tasks/{identifier}/events")
async def events(identifier: str, owner: Owner, request: Request,
                 last_event_id: Annotated[str | None, Header()] = None, after: int = Query(default=0, ge=0)):
    await database_call(task, identifier, owner)
    from ..main import events as job_events
    return await job_events(identifier, request, owner, last_event_id, after)


def task_results(identifier, owner, field, offset, limit):
    with Session() as session:
        _, task = task_row(session, identifier, owner)
        items = task.result.get(field, [])
        return {"items": items[offset:offset + limit], "total": len(items)}


@router.get("/tasks/{identifier}/sources")
def sources(identifier: str, owner: Owner, offset: Offset = 0, limit: Limit = 100):
    return task_results(identifier, owner, "sources", offset, limit)


@router.get("/tasks/{identifier}/evidence")
def evidence(identifier: str, owner: Owner, offset: Offset = 0, limit: Limit = 100):
    return task_results(identifier, owner, "evidence", offset, limit)


@router.get("/tasks/{identifier}/search-results")
def search_results(identifier: str, owner: Owner, offset: Offset = 0, limit: Limit = 100):
    return task_results(identifier, owner, "search_results", offset, limit)


@router.post("/tasks/{identifier}/cancel")
def cancel(identifier: str, owner: Owner):
    with Session() as session:
        task_row(session, identifier, owner)
    from ..main import cancel_job
    return cancel_job(identifier, owner)


@router.post("/tasks/{identifier}/retry", status_code=202)
async def retry(identifier: str, owner: Owner, request: Request, key: Key = None):
    original = await database_call(task, identifier, owner)
    if original["status"] not in {"cancelled", "failed"} and original["quality"] != "partial":
        raise HTTPException(409, "Retry is available for failed, cancelled or partial research")
    return await submit(Question.model_validate(original["question"]), owner, request, key, retry_of=identifier)


@router.get("/conversations")
def conversations(owner: Owner, offset: Offset = 0, limit: Limit = 40):
    with Session() as session:
        query = select(ResearchConversation).where(ResearchConversation.owner == owner).order_by(
            ResearchConversation.updated_at.desc(), ResearchConversation.id)
        return collection(session, query, offset, limit)


@router.post("/conversations", status_code=201)
def create_conversation(data: ConversationInput, owner: Owner):
    if not settings().research_enabled:
        raise HTTPException(503, "Research is disabled")
    with transaction() as session:
        item = ResearchConversation(owner=owner, title=data.title)
        session.add(item)
        session.flush()
        return output(item)


@router.get("/conversations/{identifier}")
def get_conversation(identifier: str, owner: Owner, offset: Offset = 0, limit: Limit = 25):
    with Session() as session:
        item = conversation(session, identifier, owner)
        query = select(Job, ResearchTask).join(ResearchTask, ResearchTask.job_id == Job.id).where(
            ResearchTask.conversation_id == item.id, Job.owner == owner)
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        rows = session.execute(query.order_by(ResearchTask.created_at.desc(), Job.id.desc()).offset(offset).limit(limit))
        return output(item) | {"messages": [task_output(job, row, full=True) for job, row in reversed(rows.all())], "total": total}


@router.post("/conversations/{identifier}/messages", status_code=202)
async def message(identifier: str, data: Question, owner: Owner, request: Request, key: Key = None):
    if data.conversation_id and data.conversation_id != identifier:
        raise HTTPException(422, "Conversation ID differs from the path")
    return await submit(data.model_copy(update={"conversation_id": identifier}), owner, request, key)


@router.delete("/conversations/{identifier}", status_code=204)
def delete_conversation(identifier: str, owner: Owner):
    with transaction() as session:
        item = conversation(session, identifier, owner, lock=True)
        identifiers = select(ResearchTask.job_id).where(ResearchTask.conversation_id == item.id)
        if session.scalar(select(Job.id).where(Job.id.in_(identifiers), Job.owner == owner,
                                              Job.status.not_in(TERMINAL)).limit(1)):
            raise HTTPException(409, "Stop active research before deleting this conversation")
        session.execute(delete(Job).where(Job.id.in_(identifiers), Job.owner == owner))
        session.delete(item)


def recent_runs(owner):
    with Session() as session:
        return session.execute(select(Job.status, ResearchTask.result, Job.completed_at).join(
            ResearchTask, ResearchTask.job_id == Job.id
        ).where(Job.owner == owner, Job.status.in_(TERMINAL)).order_by(Job.completed_at.desc()).limit(50)).all()


@router.get("/providers")
def providers(owner: Owner):
    names = configured_providers()
    health = {}
    for _, result, finished in recent_runs(owner):
        metrics = result.get("metrics", {})
        for name in names:
            used = metrics.get("provider_requests", {}).get(name, 0)
            if used and name not in health:
                failed = metrics.get("provider_failures", {}).get(name, 0)
                limited = metrics.get("provider_rate_limits", {}).get(name, 0)
                health[name] = {"last_checked": finished, "requests": used, "errors": failed, "rate_limited": limited}
    return {
        "enabled": settings().research_enabled,
        "model_configured": settings().ai_provider != "disabled",
        "providers": [{"name": name, **health.get(name, {})} for name in names],
        "budgets": {mode: budget_for(mode).model_dump() for mode in Mode if mode != Mode.AUTO},
    }


@router.get("/metrics")
def metrics(owner: Owner):
    rows = recent_runs(owner)
    samples = [result["metrics"] for _, result, _ in rows if "metrics" in result]
    return {
        "sampled": len(rows), "completed": sum(status == "completed" for status, _, _ in rows),
        "partial": sum(result.get("quality") == "partial" for _, result, _ in rows),
        "samples": samples,
    }
