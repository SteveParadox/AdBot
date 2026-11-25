"""Lease-fenced runner for the shared durable worker."""

import asyncio
import time

from sqlalchemy import select

from ..concurrency import database_call
from ..config import ResearchBudget, settings
from ..db import Job, ResearchTask, Session, emit, transaction
from ..jobs import owned_job
from .contracts import Question
from .service import Research


def previous_turns(session, conversation_id, owner, before=float("inf")):
    rows = session.execute(
        select(ResearchTask)
        .join(Job, Job.id == ResearchTask.job_id)
        .where(ResearchTask.conversation_id == conversation_id, ResearchTask.created_at < before,
               Job.owner == owner, Job.status == "completed")
        .order_by(ResearchTask.created_at.desc(), ResearchTask.job_id.desc()).limit(4)
    ).scalars().all()
    return [{
        "question": row.question["question"], "mode": row.mode, "country": row.question.get("country"),
        "answer": row.result.get("answer", "")[:600], "sources": row.result.get("sources", [])[:3],
        "products": row.result.get("products", [])[:5],
    } for row in reversed(rows)]


class ResearchRunner:
    def __init__(self, job_id, token):
        self.id, self.token = job_id, token
        self.gate = asyncio.Event()
        self.usage_lock = asyncio.Lock()
        self.gate.set()
        with Session() as session:
            job = owned_job(session, job_id, token)
            task = session.get(ResearchTask, job_id)
            self.owner, self.mode, self.intent, self.started = job.owner, task.mode, task.intent, job.started_at
            self.question = Question.model_validate(task.question)
            self.budget = ResearchBudget.model_validate(task.budget)
            self.usage = dict(task.usage)
            self.history = previous_turns(session, task.conversation_id, job.owner, task.created_at)
        self.cfg = {"max_duration_seconds": self.budget.seconds}
        self.result = None

    def event(self, name, message, details):
        with transaction() as session:
            job = owned_job(session, self.id, self.token)
            if job.cancel_requested:
                raise asyncio.CancelledError
            emit(session, self.id, name, message, **details)

    async def publish(self, name, message, **details):
        await database_call(self.event, name, message, details)

    def record_usage(self, delta):
        with transaction() as session:
            job = owned_job(session, self.id, self.token)
            if job.cancel_requested:
                raise asyncio.CancelledError
            task = session.get(ResearchTask, self.id)
            task.usage = {**task.usage, **{key: task.usage.get(key, 0) + value for key, value in delta.items()}}

    async def charge(self, **delta):
        async with self.usage_lock:
            await database_call(self.record_usage, delta)

    async def run(self):
        if not settings().research_enabled:
            raise RuntimeError("Public research is disabled by the operator")
        deadline = time.monotonic() + max(0.1, self.budget.seconds - (time.time() - self.started))
        engine = Research(self.owner, self.question, self.mode, self.intent, self.budget,
                          deadline, self.history, self.publish, self.gate, usage=self.usage, charge=self.charge)
        self.result = await engine.run()

    def persist(self, session):
        task = session.get(ResearchTask, self.id)
        if self.result is None:
            raise RuntimeError("Research ended without a durable result")
        task.result = self.result
        for index, paragraph in enumerate(self.result["answer"].split("\n\n")[:30]):
            if paragraph:
                emit(session, self.id, "answer_chunk", "Verified answer segment", index=index, text=paragraph)
