import time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update, func
from sqlalchemy.exc import IntegrityError
from .content import Admin
from .api_support import owned
from .automation import Policy, get_policy, event
from .db import AutomationControl, OperationalEvent, WorkerHeartbeat, Job, NetworkAssignment, Session, transaction

router = APIRouter(prefix="/api/admin/automation")


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    policy: Policy


@router.get("")
def status(admin: Admin):
    with Session() as session:
        row = session.get(AutomationControl, 1)
        counts = dict(session.execute(select(Job.status, func.count()).group_by(Job.status)).all())
        workers = [
            {"id": r.id, "role": r.role, "state": r.state, "expires_at": r.expires_at}
            for r in session.scalars(select(WorkerHeartbeat).where(WorkerHeartbeat.expires_at > time.time()))
        ]
        events = [
            {"id": r.id, "code": r.code, "severity": r.severity, "details": r.details, "created_at": r.created_at}
            for r in session.scalars(select(OperationalEvent).order_by(OperationalEvent.id.desc()).limit(50))
        ]
        last = session.scalar(select(func.max(Job.completed_at)).where(Job.status == "completed"))
        history = [
            {"id": r.id, "code": r.code, "severity": r.severity, "details": r.details, "created_at": r.created_at}
            for r in session.scalars(
                select(OperationalEvent)
                .where(OperationalEvent.code == "policy_changed")
                .order_by(OperationalEvent.id.desc())
                .limit(20)
            )
        ]
        jobs = [
            {"id": r.id, "status": r.status, "kind": r.job_type, "priority": r.priority, "depends_on": r.depends_on}
            for r in session.scalars(select(Job).where(Job.owner == admin).order_by(Job.created_at.desc()).limit(20))
        ]
        return {
            "revision": row.revision if row else 0,
            "policy": get_policy(session).model_dump(),
            "counts": counts,
            "workers": workers,
            "sessions": session.scalar(
                select(func.count())
                .select_from(NetworkAssignment)
                .where(NetworkAssignment.active.is_(True), NetworkAssignment.expires_at > time.time())
            ),
            "last_success": last,
            "events": events,
            "policy_history": history,
            "jobs": jobs,
        }


@router.post("")
def configure(data: Change, admin: Admin):
    try:
        with transaction() as session:
            values = dict(policy=data.policy.model_dump(), revision=data.revision + 1, updated_at=time.time())
            row = session.get(AutomationControl, 1)
            if row:
                changed = session.execute(
                    update(AutomationControl)
                    .where(AutomationControl.id == 1, AutomationControl.revision == data.revision)
                    .values(**values)
                ).rowcount
                if not changed:
                    raise HTTPException(409, "Control policy changed; reload")
            else:
                if data.revision != 0:
                    raise HTTPException(409, "Control policy changed; reload")
                session.add(AutomationControl(id=1, **values))
            if data.policy.emergency_stop:
                session.execute(
                    update(Job)
                    .where(Job.status.not_in(["completed", "failed", "cancelled"]))
                    .values(cancel_requested=True)
                )
                session.execute(
                    update(Job).where(Job.status == "queued").values(status="cancelled", completed_at=time.time())
                )
            event(
                session,
                "policy_changed",
                administrator=admin,
                revision=data.revision + 1,
                approved_policy=data.policy.model_dump(),
            )
        from .outbound import manager

        manager().policy_until = 0
        return {"revision": data.revision + 1}
    except IntegrityError:
        raise HTTPException(409, "Control policy changed; reload") from None


@router.post("/jobs/{identifier}/release")
def release(identifier: str, admin: Admin):
    with transaction() as session:
        job = owned(session, Job, identifier, admin)
        if job.status != "queued":
            raise HTTPException(409, "Only queued jobs can be manually released")
        job.manual_release = True
        event(session, "manual_release", job_id=job.id, administrator=admin)
    return {"released": True}
