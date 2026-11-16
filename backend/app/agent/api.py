import hashlib
import json
import time
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..config import settings
from ..db import AgentMemory, AgentStep, AgentTask, Job, PageVisit, Session, Website, emit, transaction
from ..jobs import make_job
from ..api_support import Limit, Offset, Owner, collection, output, owned
from .contracts import ReviewInput, TaskInput

router = APIRouter(prefix="/api/agent", tags=["autonomous agent"])


def task_for(session, identifier, owner):
    job = owned(session, Job, identifier, owner)
    task = session.get(AgentTask, identifier)
    if not task:
        raise HTTPException(404, "Agent task not found")
    return job, task


def task_output(job, task):
    return output(job) | {
        "traffic_kind": "automated",
        "automation_session_id": job.id,
        "objective": task.objective,
        "mode": task.mode,
        "options": task.options,
        "result": task.result,
        "pending_step_id": task.pending_step_id,
        "memory": task.memory,
        "prompt_tokens": task.prompt_tokens,
        "completion_tokens": task.completion_tokens,
        "model_calls": task.model_calls,
        "model_latency_ms": task.model_latency_ms,
    }


@router.get("/config")
def configuration(owner: Owner):
    cfg = settings()
    return {
        "provider": cfg.ai_provider,
        "model": cfg.ai_model,
        "fallback_provider": cfg.ai_fallback_provider,
        "fallback_model": cfg.ai_fallback_model if cfg.ai_fallback_provider != "disabled" else None,
        "configured": cfg.ai_provider != "disabled",
        "max_steps": cfg.agent_max_steps,
        "max_tokens": cfg.agent_max_tokens,
        "memory_enabled": cfg.agent_memory_enabled,
        "visual_reasoning": cfg.agent_visual_reasoning,
        "session_persistence": cfg.browser_session_persistence,
        "max_tabs": cfg.agent_max_tabs,
        "max_concurrency": cfg.max_concurrency,
    }


@router.post("/tasks", status_code=201)
def create_task(data: TaskInput, owner: Owner, idempotency_key: Annotated[str | None, Header(max_length=160)] = None):
    cfg = settings()
    if cfg.ai_provider == "disabled":
        raise HTTPException(503, "Configure an AI provider on the server before starting an agent task")
    if data.visual_reasoning and not cfg.agent_visual_reasoning:
        raise HTTPException(422, "Visual reasoning is not enabled by the server")
    if data.session_persistence and not cfg.browser_session_persistence:
        raise HTTPException(422, "Encrypted session persistence is not enabled by the server")
    options = data.model_dump(exclude={'priority','depends_on'})
    options["max_steps"] = min(data.max_steps, cfg.agent_max_steps)
    options["max_tokens"] = min(data.max_tokens, cfg.agent_max_tokens)
    options["memory_enabled"] = data.memory_enabled and cfg.agent_memory_enabled
    request_values=data.model_dump(exclude={'priority','depends_on'}) if not data.priority and not data.depends_on else data.model_dump()
    digest = hashlib.sha256(json.dumps(request_values, sort_keys=True).encode()).hexdigest()
    try:
        with transaction() as session:
            website = owned(session, Website, data.website_id, owner)
            if idempotency_key:
                previous = session.scalar(select(Job).where(Job.owner == owner, Job.idempotency_key == idempotency_key))
                if previous:
                    if previous.job_type != "agent" or previous.payload_hash != digest:
                        raise HTTPException(409, "Idempotency key was used for a different request")
                    return task_output(previous, session.get(AgentTask, previous.id))
            job = make_job(session, website,priority=data.priority,depends_on=data.depends_on)
            job.job_type = "agent"
            job.idempotency_key, job.payload_hash = idempotency_key, digest
            task = AgentTask(job_id=job.id, objective=data.objective, mode=data.mode, options=options)
            session.add(task)
            session.flush()
            emit(session, job.id, "agent_queued", "Goal-driven task queued", objective=data.objective)
            return task_output(job, task)
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from None
    except IntegrityError:
        with Session() as session:
            old = session.scalar(select(Job).where(Job.owner == owner, Job.idempotency_key == idempotency_key))
            if old and old.job_type == "agent" and old.payload_hash == digest:
                return task_output(old, session.get(AgentTask, old.id))
        raise HTTPException(409, "Concurrent task creation conflict; retry with the same key") from None


@router.get("/tasks")
def tasks(owner: Owner, offset: Offset = 0, limit: Limit = 25):
    with Session() as session:
        query = select(Job).where(Job.owner == owner, Job.job_type == "agent").order_by(Job.created_at.desc())
        rows = session.scalars(query.offset(offset).limit(limit)).all()
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        return {"items": [task_output(j, session.get(AgentTask, j.id)) for j in rows], "total": total}


@router.get("/tasks/{identifier}")
def task(identifier: str, owner: Owner):
    with Session() as session:
        return task_output(*task_for(session, identifier, owner))


@router.get("/tasks/{identifier}/steps")
def steps(identifier: str, owner: Owner, offset: Offset = 0, limit: Limit = 100):
    with Session() as session:
        task_for(session, identifier, owner)
        return collection(
            session, select(AgentStep).where(AgentStep.job_id == identifier).order_by(AgentStep.number), offset, limit
        )


@router.post("/tasks/{identifier}/review")
def review(identifier: str, data: ReviewInput, owner: Owner):
    with transaction() as session:
        job, task = task_for(session, identifier, owner)
        step = session.get(AgentStep, data.step_id)
        if (
            job.status not in {"running", "paused", "waiting_user"}
            or not step
            or step.job_id != identifier
            or task.pending_step_id != step.id
            or step.status != "waiting_user"
            or step.approved is not None
        ):
            raise HTTPException(409, "This review is stale or already answered")
        step.approved, step.user_answer = data.approved, data.answer
        emit(
            session,
            identifier,
            "review_answered",
            "User approved action" if data.approved else "User declined action",
            step_id=step.id,
        )
        return {"accepted": True}


@router.get("/memories")
def memories(owner: Owner, offset: Offset = 0, limit: Limit = 25):
    with Session() as session:
        return collection(
            session,
            select(AgentMemory)
            .where(AgentMemory.owner == owner, AgentMemory.expires_at > time.time())
            .order_by(AgentMemory.created_at.desc()),
            offset,
            limit,
        )


@router.delete("/memories/{identifier}", status_code=204)
def delete_memory(identifier: str, owner: Owner):
    with transaction() as session:
        item = session.get(AgentMemory, identifier)
        if not item or item.owner != owner:
            raise HTTPException(404, "Memory not found")
        session.delete(item)


@router.get("/metrics")
def metrics(owner: Owner):
    with Session() as session:
        jobs = session.scalars(select(Job).where(Job.owner == owner, Job.job_type == "agent")).all()
        counts = {status: sum(j.status == status for j in jobs) for status in {j.status for j in jobs}}
        finished = [j for j in jobs if j.completed_at]
        tasks = session.scalars(select(AgentTask).join(Job).where(Job.owner == owner)).all()
        calls = sum(t.model_calls for t in tasks)
        steps = session.execute(
            select(AgentStep.status, func.count())
            .join(AgentTask)
            .join(Job)
            .where(Job.owner == owner)
            .group_by(AgentStep.status)
        ).all()
        visits = session.scalars(select(PageVisit).join(Job).where(Job.owner == owner, Job.job_type == "agent")).all()
        total_steps = sum(n for _, n in steps)
        return {
            "traffic_kind": "automated",
            "tasks": len(jobs),
            "statuses": counts,
            "success_rate": counts.get("completed", 0) / len(finished) if finished else None,
            "average_seconds": sum(j.completed_at - j.started_at for j in finished if j.started_at) / len(finished)
            if finished
            else 0,
            "steps": dict(steps),
            "average_steps": sum(n for _, n in steps) / len(jobs) if jobs else 0,
            "tokens": sum(t.prompt_tokens + t.completion_tokens for t in tasks),
            "model_calls": calls,
            "average_model_latency_ms": sum(t.model_latency_ms for t in tasks) / calls if calls else 0,
            "navigation_failure_rate": sum(
                bool(p.error) or (p.http_status is not None and p.http_status >= 400) for p in visits
            )
            / len(visits)
            if visits
            else None,
            "action_replan_rate": dict(steps).get("failed", 0) / total_steps if total_steps else 0,
            "recovery_attempts": sum(j.retry_count for j in jobs),
            "uninterrupted_session_rate": sum(j.retry_count == 0 for j in jobs) / len(jobs) if jobs else None,
        }
