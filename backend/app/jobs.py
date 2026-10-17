import hashlib
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from .config import settings
from .db import (
    AgentMemory,
    AgentStep,
    AgentTask,
    Frontier,
    Job,
    Lease,
    Schedule,
    Website,
    Workflow,
    emit,
    transaction,
    uid,
)

TERMINAL = {"completed", "failed", "cancelled"}


def make_job(session, website: Website, workflow: Workflow | None = None, key=None):
    payload = {"website_id": website.id, "workflow_id": workflow.id if workflow else None}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    if key:
        old = session.scalar(select(Job).where(Job.owner == website.owner, Job.idempotency_key == key))
        if old:
            if old.payload_hash != digest:
                raise ValueError("Idempotency key was used for a different request")
            return old
    snapshot = {
        "base_url": website.base_url,
        "allowed_domains": website.allowed_domains,
        "configuration": website.configuration,
    }
    if workflow:
        if workflow.website_id != website.id or not workflow.enabled:
            raise ValueError("Workflow must be enabled and belong to this website")
        snapshot["workflow"] = workflow.definition
        snapshot["workflow_version"] = workflow.version
    job = Job(
        owner=website.owner,
        website_id=website.id,
        snapshot=snapshot,
        job_type="workflow" if workflow else "crawl",
        idempotency_key=key,
        payload_hash=digest,
    )
    session.add(job)
    session.flush()
    session.add(Frontier(job_id=job.id, discovered_url=website.base_url, normalized_url=website.base_url))
    emit(session, job.id, "queued", "Job queued")
    return job


def acquire(session, name, token, now):
    if session.execute(
        update(Lease)
        .where(Lease.name == name, Lease.expires_at <= now)
        .values(token=token, expires_at=now + settings().lease_seconds)
    ).rowcount:
        return True
    if session.get(Lease, name):
        return False
    try:
        with session.begin_nested():
            session.add(Lease(name=name, token=token, expires_at=now + settings().lease_seconds))
            session.flush()
        return True
    except IntegrityError:
        return False


def claim():
    now, token = time.time(), uid()
    with transaction() as session:
        jobs = session.scalars(
            select(Job)
            .where(Job.status == "queued", Job.cancel_requested.is_(False))
            .order_by(Job.created_at)
            .limit(50)
        ).all()
        for job in jobs:
            # Conservatively lock every allowed domain for the whole job. Wildcard
            # targets share the registrable suffix lock with explicit subdomains.
            domains = job.snapshot["allowed_domains"]
            names = sorted(
                {
                    "domain:" + d.removeprefix("*.").split(".")[-2] + "." + d.split(".")[-1]
                    if "." in d
                    else "domain:" + d
                    for d in domains
                }
            )
            with session.begin_nested() as savepoint:
                if not all(acquire(session, name, token, now) for name in names):
                    savepoint.rollback()
                    continue
                slot = next(
                    (i for i in range(settings().max_concurrency) if acquire(session, f"slot:{i}", token, now)), None
                )
                if slot is None:
                    savepoint.rollback()
                    continue
                changed = session.execute(
                    update(Job)
                    .where(Job.id == job.id, Job.status == "queued")
                    .values(
                        status="running",
                        lease_token=token,
                        lease_until=now + settings().lease_seconds,
                        started_at=job.started_at or now,
                    )
                ).rowcount
                if not changed:
                    savepoint.rollback()
                    continue
                emit(session, job.id, "started", "Worker acquired job")
                return job.id, token
    return None


def recover_expired():
    now = time.time()
    with transaction() as session:
        jobs = session.scalars(
            select(Job).where(Job.status.in_(["running", "paused", "waiting_user"]), Job.lease_until < now)
        ).all()
        for job in jobs:
            if not session.execute(
                update(Job)
                .where(Job.id == job.id, Job.lease_until < now, Job.status.in_(["running", "paused", "waiting_user"]))
                .values(lease_token=None, lease_until=0)
            ).rowcount:
                continue
            # CLICK cannot safely be replayed after an ambiguous crash.
            unsafe = job.job_type == "workflow" and any(
                s["action"] == "CLICK" for s in job.snapshot["workflow"]["steps"]
            )
            if job.job_type == "agent":
                last = session.scalar(
                    select(AgentStep).where(AgentStep.job_id == job.id).order_by(AgentStep.number.desc()).limit(1)
                )
                unsafe = bool(
                    last and last.status == "executing" and last.decision.get("decision") in {"CLICK", "TYPE", "SEARCH"}
                )
                task = session.get(AgentTask, job.id)
                task.pending_step_id = None
                if last and last.status in {"executing", "waiting_user"}:
                    last.status = "interrupted"
                    last.outcome = {"error": "Worker lease expired before a durable action outcome"}
            job.status = (
                "cancelled" if job.cancel_requested else "failed" if unsafe or job.retry_count >= 3 else "queued"
            )
            job.retry_count += 1
            if job.status in TERMINAL:
                job.completed_at = now
                job.error_message = (
                    "Worker lease expired; manual review required" if unsafe else "Worker recovery limit reached"
                )
            session.execute(
                update(Frontier)
                .where(Frontier.job_id == job.id, Frontier.crawl_status == "visiting")
                .values(crawl_status="pending")
            )
            emit(session, job.id, "recovered", "Expired worker lease recovered", status=job.status)


def heartbeat(job_id, token):
    with transaction() as session:
        now = time.time()
        changed = session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.lease_token == token,
                Job.lease_until > now,
                Job.status.in_(["running", "paused", "waiting_user"]),
            )
            .values(lease_until=now + settings().lease_seconds)
        ).rowcount
        if changed:
            session.execute(update(Lease).where(Lease.token == token).values(expires_at=now + settings().lease_seconds))
        return bool(changed)


def owned_job(session, job_id, token):
    job = session.get(Job, job_id)
    if not job or job.lease_token != token or job.lease_until <= time.time() or job.status in TERMINAL:
        raise InterruptedError("Worker lease lost")
    return job


def next_occurrence(expression, timezone, base):
    return croniter(expression, datetime.fromtimestamp(base, ZoneInfo(timezone))).get_next(datetime).timestamp()


def tick(now=None):
    now = now or time.time()
    count = 0
    with transaction() as session:
        schedules = session.scalars(
            select(Schedule)
            .where(Schedule.enabled.is_(True), Schedule.next_run_at <= now)
            .order_by(Schedule.next_run_at)
            .limit(100)
        ).all()
        for item in schedules:
            due = item.next_run_at
            changes = (
                {"next_run_at": next_occurrence(item.cron_expression, item.timezone, now)}
                if item.cron_expression
                else {"enabled": False}
            )
            if not session.execute(
                update(Schedule)
                .where(Schedule.id == item.id, Schedule.next_run_at == due, Schedule.enabled.is_(True))
                .values(**changes)
            ).rowcount:
                continue
            site = session.get(Website, item.website_id)
            workflow = session.get(Workflow, item.workflow_id) if item.workflow_id else None
            if item.workflow_id and (not workflow or not workflow.enabled):
                item.enabled = False
                continue
            make_job(session, site, workflow, f"schedule:{item.id}:{due:.6f}")
            count += 1
    return count


def cleanup():
    cutoff = time.time() - settings().retention_days * 86400
    with transaction() as session:
        session.execute(delete(AgentMemory).where(AgentMemory.expires_at < time.time()))
        session.execute(delete(Job).where(Job.status.in_(TERMINAL), Job.completed_at < cutoff))
    root = settings().artifact_dir
    if root.exists():
        for path in list(root.glob("*.png")) + list(root.glob("*.bin")):
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
