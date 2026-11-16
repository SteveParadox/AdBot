"""Control and supervision for the existing queue/worker/scheduler, not a second scheduler."""

import os
import time
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, update, func
from .config import settings
from .db import AutomationControl, OperationalEvent, WorkerHeartbeat, Job, NetworkAssignment, transaction


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    paused: bool = False
    emergency_stop: bool = False
    concurrency: int = Field(1, ge=1, le=8)
    recovery_retries: int = Field(3, ge=0, le=3)
    max_backlog: int = Field(1000, ge=1, le=100000)
    disabled: list[Literal["crawl", "workflow", "agent", "schedules"]] = Field(default_factory=list)
    disabled_websites: list[Annotated[str, Field(min_length=1, max_length=36)]] = Field(
        default_factory=list, max_length=1000
    )
    health_interval_seconds: int = Field(
        default_factory=lambda: settings().outbound_health_interval_seconds, ge=10, le=3600
    )
    proxy_strategies: dict[
        Literal["browser", "ai", "ai_local"],
        Literal["round_robin", "random", "weighted", "sticky", "fixed", "health", "latency", "scheduled"],
    ] = Field(default_factory=dict)
    maintenance_enabled: bool = True
    notifications: bool = True

    @model_validator(mode="after")
    def caps(self):
        if self.concurrency > settings().max_concurrency:
            raise ValueError("Concurrency exceeds operator limit")
        if self.proxy_strategies:
            from .outbound import manager

            routing = manager()
            for name, strategy in self.proxy_strategies.items():
                base = routing.config.services.get(name) if routing.enabled else None
                if base is None or base.mode != "required":
                    raise ValueError("Only existing required proxy integrations can be configured")
                if (base.stable or not base.allow_rotation) and strategy != base.strategy:
                    raise ValueError("Operator-fixed routing cannot be changed")
                if strategy == "fixed" and len(base.endpoints) != 1:
                    raise ValueError("Fixed routing requires a single approved endpoint")
        return self


def get_policy(session=None, lock=False):
    if session is None:
        with transaction() as current:
            return get_policy(current)
    query = select(AutomationControl).where(AutomationControl.id == 1)
    if lock:
        query = query.with_for_update()
    row = session.scalar(query)
    values = dict(row.policy) if row else {}
    values["concurrency"] = min(values.get("concurrency", settings().max_concurrency), settings().max_concurrency)
    return Policy.model_validate(values)


def event(session, code, severity="info", **details):
    session.add(OperationalEvent(code=code, severity=severity, details=details))


def alert(session, code, **details):
    # Supervisor instances share a locked control row and a notification window.
    if not session.scalar(
        select(OperationalEvent.id)
        .where(OperationalEvent.code == code, OperationalEvent.created_at > time.time() - 60)
        .limit(1)
    ):
        event(session, code, "warning", **details)


def pulse(identifier, role, state):
    with transaction() as session:
        from .user_agents import cached_revision
        control=session.get(AutomationControl,1)
        values = dict(
            role=role,
            state={"pid": os.getpid(), "process_cpu_seconds": time.process_time(),
                   "user_agent_revision":cached_revision(),"policy_revision":control.revision if control else 0,**state},
            expires_at=time.time() + 45,
        )
        if not session.execute(
            update(WorkerHeartbeat).where(WorkerHeartbeat.id == identifier).values(**values)
        ).rowcount:
            session.add(WorkerHeartbeat(id=identifier, **values))


def supervise(identifier):
    from .jobs import recover_expired

    # Existing recovery uses compare-and-swap fencing and is safe across schedulers/workers.
    recover_expired()
    with transaction() as session:
        policy = get_policy(session, lock=True)
        session.execute(
            update(NetworkAssignment)
            .where(NetworkAssignment.expires_at < time.time(), NetworkAssignment.active.is_(True))
            .values(active=False)
        )
        count = session.scalar(select(func.count()).select_from(Job).where(Job.status == "queued"))
        if count >= policy.max_backlog and policy.notifications:
            alert(session, "queue_backlog", queued=count)
        workers = session.scalar(
            select(func.count())
            .select_from(WorkerHeartbeat)
            .where(WorkerHeartbeat.role == "worker", WorkerHeartbeat.expires_at > time.time())
        )
        if (
            count
            and not workers
            and policy.enabled
            and not policy.paused
            and not policy.emergency_stop
            and policy.notifications
        ):
            alert(session, "no_live_workers", queued=count, action="Check worker supervisor and database connectivity")
        failed = session.scalars(select(Job).where(Job.status == "failed", Job.completed_at > time.time() - 60)).all()
        if failed and policy.notifications:
            # This is a durable in-app notification, never an unsolicited email/webhook.
            alert(
                session, "recent_job_failures", count=len(failed), action="Review failed jobs and their execution logs"
            )
    pulse(identifier, "scheduler", {"queued": count, "last_check": time.time()})


async def watch_configuration():
    import asyncio
    import logging
    from .db import UserAgentConfig, Session
    from .user_agents import invalidate, read

    revision = None
    delay = 1
    while True:
        try:
            with Session() as session:
                row = session.get(UserAgentConfig, 1)
                current = row.revision if row else 0
            if current != revision:
                invalidate()
                read()  # Validate the complete committed document before caching it.
                revision = current
            delay = 1
        except Exception as exc:
            logging.getLogger("adbot.automation").error("configuration_sync_failed: %s", type(exc).__name__)
            delay = min(30, delay * 2)
        await asyncio.sleep(delay)
