"""Lease-fenced runner for the shared durable worker."""

import asyncio
import time

from sqlalchemy import select

from ..concurrency import database_call
from ..config import ResearchBudget, settings
from ..db import Job, ResearchConversation, ResearchTask, Session, emit, transaction
from ..jobs import owned_job
from .contracts import Question
from .memory import MAX_ENTITIES, MAX_SOURCES, MAX_TURNS, build_context
from .service import Research


def previous_turns(session, conversation_id, owner, before=float("inf")):
    rows = session.execute(
        select(ResearchTask.job_id, ResearchTask.question, ResearchTask.mode,
               ResearchTask.result["answer"].as_string().label("answer"),
               ResearchTask.result["sources"].label("sources"),
               ResearchTask.result["products"].label("products"),
               ResearchTask.result["conversation_memory"].label("memory"))
        .join(Job, Job.id == ResearchTask.job_id)
        .join(ResearchConversation, ResearchConversation.id == ResearchTask.conversation_id)
        .where(ResearchTask.conversation_id == conversation_id, ResearchTask.created_at < before,
               ResearchConversation.owner == owner, Job.owner == owner, Job.status == "completed")
        .order_by(ResearchTask.created_at.desc(), ResearchTask.job_id.desc()).limit(MAX_TURNS)
    ).all()
    return [{
        "id": row.job_id, "question": row.question["question"], "mode": row.mode,
        "country": row.question.get("country"), "freshness": row.question.get("freshness"),
        "answer": (row.answer or "")[:900],
        "sources": [{k: source.get(k) for k in ("id", "title", "url")} for source in (row.sources or [])[:MAX_SOURCES]],
        "products": [{k: product.get(k) for k in ("name", "model", "url", "source_id")}
                     for product in (row.products or [])[:MAX_ENTITIES]],
        "memory": row.memory,
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
            self.conversation = task.conversation_id
            self.saved = job.execution_state.get("research_checkpoint")
            self.reference_at = job.snapshot.get("research_reference_at", task.created_at)
            self.prior_queries = job.snapshot.get("research_prior_queries", [])
            self.semantic_route = job.snapshot.get("research_semantic_route", False)
            before = job.snapshot.get("research_history_before", task.created_at)
            self.context = job.snapshot.get("research_context")
            self.history = [] if self.context is not None else previous_turns(session, task.conversation_id, job.owner, before)
            if self.context is None:
                self.context = build_context(self.question, self.history, self.intent, self.mode)
        self.cfg = {"max_duration_seconds": self.budget.seconds}
        self.result = None

    def event(self, name, message, details):
        with transaction() as session:
            job = owned_job(session, self.id, self.token, write=True)
            if job.cancel_requested:
                raise asyncio.CancelledError
            emit(session, self.id, name, message, **details)

    async def publish(self, name, message, **details):
        await database_call(self.event, name, message, details)

    def record_usage(self, delta):
        with transaction() as session:
            job = owned_job(session, self.id, self.token, write=True)
            if job.cancel_requested:
                raise asyncio.CancelledError
            task = session.get(ResearchTask, self.id)
            task.usage = {**task.usage, **{key: task.usage.get(key, 0) + value for key, value in delta.items()}}

    async def charge(self, **delta):
        async with self.usage_lock:
            await database_call(self.record_usage, delta)

    def record_checkpoint(self, state):
        with transaction() as session:
            job = owned_job(session, self.id, self.token, write=True)
            if job.cancel_requested:
                raise asyncio.CancelledError
            job.execution_state = {**job.execution_state, "research_checkpoint": state}

    async def checkpoint(self, state):
        await database_call(self.record_checkpoint, state)

    async def run(self):
        if not settings().research_enabled:
            raise RuntimeError("Public research is disabled by the operator")
        deadline = time.monotonic() + max(0.1, self.budget.seconds - (time.time() - self.started))
        engine = Research(self.owner, self.question, self.mode, self.intent, self.budget,
                          deadline, self.history, self.publish, self.gate, usage=self.usage, charge=self.charge,
                          context=self.context, conversation=self.conversation, checkpoint=self.checkpoint, saved=self.saved,
                          reference_at=self.reference_at, prior_queries=self.prior_queries, semantic_route=self.semantic_route)
        self.result = await engine.run()

    def persist(self, session):
        task = session.get(ResearchTask, self.id)
        if self.result is None:
            raise RuntimeError("Research ended without a durable result")
        task.result = self.result
        task.mode = self.result.get("effective_mode", task.mode)
        job = session.get(Job, self.id)
        job.execution_state = {key: value for key, value in job.execution_state.items() if key != "research_checkpoint"}
        for index, paragraph in enumerate(self.result["answer"].split("\n\n")[:30]):
            if paragraph:
                emit(session, self.id, "answer_chunk", "Verified answer segment", index=index, text=paragraph)
