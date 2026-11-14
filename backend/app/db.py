import time
import uuid
from contextlib import contextmanager

from sqlalchemy import CheckConstraint, JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import settings


def uid():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Website(Base):
    __tablename__ = "websites"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(120))
    base_url: Mapped[str] = mapped_column(Text)
    allowed_domains: Mapped[list] = mapped_column(JSON)
    configuration: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time, onupdate=time.time)


class Workflow(Base):
    __tablename__ = "workflows"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    website_id: Mapped[str] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    definition: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Job(Base):
    __tablename__ = "automation_jobs"
    __table_args__ = (UniqueConstraint("owner", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    website_id: Mapped[str] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    job_type: Mapped[str] = mapped_column(String(16), default="crawl")
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    snapshot: Mapped[dict] = mapped_column(JSON)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    completed_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    pages_visited: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    action_index: Mapped[int] = mapped_column(Integer, default=0)
    execution_state: Mapped[dict] = mapped_column(JSON, default=dict)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    pause_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[float] = mapped_column(Float, default=0, index=True)


class Frontier(Base):
    __tablename__ = "discovered_links"
    __table_args__ = (UniqueConstraint("job_id", "normalized_url"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("automation_jobs.id", ondelete="CASCADE"), index=True)
    source_page_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discovered_url: Mapped[str] = mapped_column(Text)
    normalized_url: Mapped[str] = mapped_column(String(2048))
    depth: Mapped[int] = mapped_column(Integer, default=0)
    crawl_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)


class PageVisit(Base):
    __tablename__ = "page_visits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("automation_jobs.id", ondelete="CASCADE"), index=True)
    frontier_id: Mapped[int | None] = mapped_column(
        ForeignKey("discovered_links.id", ondelete="SET NULL"), unique=True, nullable=True
    )
    requested_url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str] = mapped_column(Text)
    page_title: Mapped[str] = mapped_column(Text, default="")
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    navigation_duration_ms: Mapped[float] = mapped_column(Float)
    visited_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    screenshot_path: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Schedule(Base):
    __tablename__ = "schedules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    website_id: Mapped[str] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    workflow_id: Mapped[str | None] = mapped_column(ForeignKey("workflows.id", ondelete="RESTRICT"), nullable=True)
    cron_expression: Mapped[str | None] = mapped_column(String(100), nullable=True)
    timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    next_run_at: Mapped[float] = mapped_column(Float, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AutomationEvent(Base):
    __tablename__ = "automation_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("automation_jobs.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    timestamp: Mapped[float] = mapped_column(Float, default=time.time)


class Lease(Base):
    __tablename__ = "leases"
    name: Mapped[str] = mapped_column(String(300), primary_key=True)
    token: Mapped[str] = mapped_column(String(36), default="")
    expires_at: Mapped[float] = mapped_column(Float, default=0)


class AgentTask(Base):
    __tablename__ = "agent_tasks"
    job_id: Mapped[str] = mapped_column(ForeignKey("automation_jobs.id", ondelete="CASCADE"), primary_key=True)
    objective: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(16))
    options: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    pending_step_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory: Mapped[dict] = mapped_column(JSON, default=dict)
    encrypted_session: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    model_calls: Mapped[int] = mapped_column(Integer, default=0)
    model_latency_ms: Mapped[float] = mapped_column(Float, default=0)


class AgentStep(Base):
    __tablename__ = "agent_steps"
    __table_args__ = (UniqueConstraint("job_id", "number"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("agent_tasks.job_id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    observation: Mapped[dict] = mapped_column(JSON)
    decision: Mapped[dict] = mapped_column(JSON, default=dict)
    outcome: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="observed")
    approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    user_answer: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class AgentMemory(Base):
    __tablename__ = "agent_memories"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    website_id: Mapped[str] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    source_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("automation_jobs.id", ondelete="SET NULL"), nullable=True
    )
    objective: Mapped[str] = mapped_column(Text)
    content: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    expires_at: Mapped[float] = mapped_column(Float, index=True)


class ContentSection(Base):
    __tablename__ = "content_sections"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    draft: Mapped[dict] = mapped_column(JSON)
    published: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time, onupdate=time.time)


class UserAgentConfig(Base):
    __tablename__ = "user_agent_config"
    __table_args__ = (CheckConstraint("id = 1"), CheckConstraint("revision >= 0"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)


class UserAgentAudit(Base):
    __tablename__ = "user_agent_audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    administrator: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[float] = mapped_column(Float, default=time.time)


engine = create_engine(
    settings().database_url,
    pool_pre_ping=True,
    **(
        {"connect_args": {"check_same_thread": False, "timeout": 30}}
        if settings().database_url.startswith("sqlite")
        else {}
    ),
)
if engine.dialect.name == "sqlite":

    @event.listens_for(engine, "connect")
    def sqlite_pragmas(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")


Session = sessionmaker(engine, expire_on_commit=False)


@contextmanager
def transaction():
    with Session.begin() as session:
        yield session


def emit(session, job_id, kind, message, **details):
    session.add(AutomationEvent(job_id=job_id, event_type=kind, message=message, details=details))
