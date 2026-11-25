import hashlib
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter
from sqlalchemy import delete, select, update, func, or_
from sqlalchemy.orm import aliased
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
    NetworkAssignment,
    WorkerHeartbeat,
)

TERMINAL = {"completed", "failed", "cancelled"}


def check_capacity(session):
    from .automation import get_policy
    policy=get_policy(session,lock=True)
    if session.scalar(select(func.count()).select_from(Job).where(Job.status=='queued'))>=policy.max_backlog:
        raise ValueError("Queue capacity reached; wait for backlog to drain")


def make_job(session, website: Website, workflow: Workflow | None = None, key=None, priority=0, depends_on=None, dataset_id=None, extract=True):
    payload = {"website_id": website.id, "workflow_id": workflow.id if workflow else None}
    if dataset_id:
        payload['dataset_id'] = dataset_id
    if priority or depends_on:
        payload.update(priority=priority,depends_on=depends_on)
    if depends_on:
        parent=session.get(Job,depends_on)
        if not parent or parent.owner!=website.owner or parent.job_type == "research":
            raise ValueError("Dependency must be an existing job owned by this workspace")
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    if key:
        old = session.scalar(select(Job).where(Job.owner == website.owner, Job.idempotency_key == key))
        if old:
            if old.payload_hash != digest:
                raise ValueError("Idempotency key was used for a different request")
            return old
    check_capacity(session)
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
        priority=priority, depends_on=depends_on,
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
    extraction_id = dataset_id or website.configuration.get('extraction_dataset_id')
    if extraction_id and extract:
        from .extraction.service import snapshot as extraction_snapshot
        extraction_snapshot(session,job,extraction_id)
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
        from .automation import get_policy
        control=get_policy(session,lock=True)
        if control.paused or control.emergency_stop:
            return None
        parent=aliased(Job)
        failed=session.scalars(select(Job).where(Job.status=='queued',select(parent.id).where(parent.id==Job.depends_on,parent.status.in_(['failed','cancelled'])).exists()).limit(200)).all()
        for child in failed:
            child.status='failed'
            child.completed_at=now
            child.error_message='Dependency did not complete successfully'
            emit(session,child.id,'dependency_failed',child.error_message)
        session.flush()
        jobs = session.scalars(
            select(Job)
            .where(Job.status == "queued", Job.cancel_requested.is_(False),Job.job_type.not_in(control.disabled),
                   or_(Job.job_type == "research", Job.website_id.not_in(control.disabled_websites)),
                   or_(control.enabled,Job.manual_release.is_(True)),
                   or_(Job.depends_on.is_(None),select(parent.id).where(parent.id==Job.depends_on,parent.status=='completed').exists()))
            .order_by((Job.priority + (now - Job.created_at) / settings().priority_aging_seconds).desc(),Job.created_at)
        ).yield_per(50)
        for job in jobs:
            if job.job_type == "agent":
                active_agents = session.scalar(select(func.count()).select_from(Job).where(
                    Job.job_type == "agent", Job.status.in_(["running", "paused", "waiting_user"]),
                    Job.lease_until > now,
                ))
                if active_agents >= settings().max_concurrent_agents:
                    continue
            if job.job_type in control.disabled or (not control.enabled and not job.manual_release):
                continue
            if job.depends_on:
                parent=session.get(Job,job.depends_on)
                if not parent or parent.status in {'failed','cancelled'}:
                    job.status='failed'
                    job.completed_at=now
                    job.error_message='Dependency did not complete successfully'
                    emit(session,job.id,'dependency_failed',job.error_message)
                    continue
                if parent.status!='completed':
                    continue
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
                if job.job_type == "agent" and not any(
                    acquire(session, f"agent-slot:{i}", token, now)
                    for i in range(settings().max_concurrent_agents)
                ):
                    savepoint.rollback()
                    continue
                if not all(acquire(session, name, token, now) for name in names):
                    savepoint.rollback()
                    continue
                slot = next(
                    (i for i in range(min(control.concurrency, settings().max_browser_sessions)) if acquire(session, f"slot:{i}", token, now)), None
                )
                if slot is None:
                    savepoint.rollback()
                    return None
                changed = session.execute(
                    update(Job)
                    .where(Job.id == job.id, Job.status == "queued", Job.cancel_requested.is_(False))
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
        from .automation import get_policy
        recovery_limit=get_policy(session).recovery_retries
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
                    last
                    and (last.status == "executing" or (last.outcome or {}).get("uncertain_submission"))
                    and last.decision.get("decision") in {"CLICK", "TYPE", "SEARCH", "PRESS_KEY", "SET_CHECKED", "SELECT_OPTION"}
                )
                task = session.get(AgentTask, job.id)
                task.pending_step_id = None
                if last and last.status in {"executing", "waiting_user"}:
                    last.status = "interrupted"
                    last.outcome = {"error": "Worker lease expired before a durable action outcome",
                                    "uncertain_submission": unsafe}
            job.status = (
                "cancelled" if job.cancel_requested else "failed" if unsafe or job.retry_count >= recovery_limit else "queued"
            )
            job.retry_count += 1
            if job.status in TERMINAL:
                if job.job_type == "research":
                    job.execution_state = {k: v for k, v in job.execution_state.items() if k != "research_checkpoint"}
                job.completed_at = now
                job.error_message = (
                    "Worker lease expired; manual review required" if unsafe else "Worker recovery limit reached"
                )
                from .failures import diagnose
                job.execution_state = {**job.execution_state, "failure": diagnose(session, job, job.error_message)}
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
            session.execute(update(NetworkAssignment).where(NetworkAssignment.job_id==job_id,NetworkAssignment.token==token).values(expires_at=now+settings().lease_seconds))
            session.execute(update(Lease).where(Lease.token == token).values(expires_at=now + settings().lease_seconds))
        return bool(changed)


def owned_job(session, job_id, token, *, write=False):
    if write and session.get_bind().dialect.name == "sqlite":
        # SQLite ignores FOR UPDATE. Acquire its write lock before reading a
        # lease that will guard changes to another row.
        changed = session.execute(update(Job).where(
            Job.id == job_id, Job.lease_token == token, Job.lease_until > time.time(),
            Job.status.not_in(TERMINAL),
        ).values(lease_token=token)).rowcount
        if not changed:
            raise InterruptedError("Worker lease lost")
    job = session.scalar(select(Job).where(Job.id==job_id).with_for_update())
    if not job or job.lease_token != token or job.lease_until <= time.time() or job.status in TERMINAL:
        raise InterruptedError("Worker lease lost")
    return job


def next_occurrence(expression, timezone, base):
    return croniter(expression, datetime.fromtimestamp(base, ZoneInfo(timezone))).get_next(datetime).timestamp()


def tick(now=None):
    now = now or time.time()
    count = 0
    with transaction() as session:
        from .automation import get_policy
        control=get_policy(session,lock=True)
        if not control.enabled or control.paused or control.emergency_stop or 'schedules' in control.disabled:
            return 0
        schedules = session.scalars(
            select(Schedule)
            .where(Schedule.enabled.is_(True), Schedule.next_run_at <= now,Schedule.website_id.not_in(control.disabled_websites))
            .order_by(Schedule.next_run_at)
            .limit(100)
        ).all()
        for item in schedules:
            if session.scalar(select(func.count()).select_from(Job).where(Job.status=="queued"))>=control.max_backlog:
                break
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
            from .db import ExtractionSchedule
            binding = session.get(ExtractionSchedule,item.id)
            make_job(session, site, workflow, f"schedule:{item.id}:{due:.6f}",dataset_id=binding.dataset_id if binding else None)
            count += 1
    return count


def cleanup():
    cutoff = time.time() - settings().retention_days * 86400
    with transaction() as session:
        from .extraction.exporter import cleanup as extraction_cleanup
        extraction_cleanup(session)
        session.execute(delete(WorkerHeartbeat).where(WorkerHeartbeat.expires_at<time.time()-86400))
        session.execute(delete(Lease).where(Lease.expires_at<time.time()-3600))
        session.execute(delete(AgentMemory).where(AgentMemory.expires_at < time.time()))
        child=aliased(Job)
        retained=select(child.depends_on).where(child.depends_on.is_not(None))
        session.execute(delete(Job).where(Job.status.in_(TERMINAL), Job.completed_at < cutoff,Job.id.not_in(retained)))
        from .db import ResearchConversation, ResearchTask
        session.execute(delete(ResearchConversation).where(
            ResearchConversation.updated_at < cutoff,
            ~select(ResearchTask.job_id).where(ResearchTask.conversation_id == ResearchConversation.id).exists(),
        ))
    root = settings().artifact_dir
    if root.exists():
        for path in list(root.glob("*.png")) + list(root.glob("*.bin")):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
            except FileNotFoundError:
                pass
