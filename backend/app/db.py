import time
import uuid
from contextlib import contextmanager

from sqlalchemy import Index, CheckConstraint, JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.orm import Session as OrmSession, DeclarativeBase, Mapped, mapped_column, sessionmaker

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
    __table_args__ = (
        UniqueConstraint("owner", "idempotency_key"),
        CheckConstraint(
            "(job_type = 'research' AND website_id IS NULL) OR (job_type != 'research' AND website_id IS NOT NULL)",
            name="ck_job_website_scope",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    website_id: Mapped[str | None] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    depends_on: Mapped[str | None] = mapped_column(ForeignKey("automation_jobs.id"), nullable=True)
    manual_release: Mapped[bool] = mapped_column(Boolean, default=False)
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


class ResearchConversation(Base):
    __tablename__ = "research_conversations"
    __table_args__ = (Index("ix_research_conversations_owner_activity", "owner", "updated_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)


class ResearchTask(Base):
    __tablename__ = "research_tasks"
    __table_args__ = (Index("ix_research_tasks_conversation_created", "conversation_id", "created_at"),)
    job_id: Mapped[str] = mapped_column(ForeignKey("automation_jobs.id", ondelete="CASCADE"), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("research_conversations.id", ondelete="RESTRICT"))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    question: Mapped[dict] = mapped_column(JSON)
    mode: Mapped[str] = mapped_column(String(20))
    intent: Mapped[str] = mapped_column(String(24))
    budget: Mapped[dict] = mapped_column(JSON)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)


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
    __table_args__ = (Index("ix_automation_events_job_cursor", "job_id", "id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("automation_jobs.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    timestamp: Mapped[float] = mapped_column(Float, default=time.time)


class ResourceChange(Base):
    __tablename__ = "resource_changes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    path: Mapped[str] = mapped_column(String(240))
    request_id: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)


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
    revision: Mapped[str] = mapped_column(String(36), default=uid)
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


class AutomationControl(Base):
    __tablename__ = "automation_control"
    __table_args__ = (CheckConstraint('id=1',name='automation_control_singleton'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    policy: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)


class OperationalEvent(Base):
    __tablename__ = "operational_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(80), index=True)
    severity: Mapped[str] = mapped_column(String(16))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    role: Mapped[str] = mapped_column(String(16))
    state: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[float] = mapped_column(Float, index=True)


class ProviderQuota(Base):
    __tablename__ = "provider_quotas"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window: Mapped[int] = mapped_column(Integer, default=0)
    requests: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cooldown_until: Mapped[float] = mapped_column(Float, default=0)


class SelectionCounter(Base):
    __tablename__ = "selection_counters"
    name: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


class SharedProxyHealth(Base):
    __tablename__ = "shared_proxy_health"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    retry_at: Mapped[float] = mapped_column(Float, default=0)
    observed_at: Mapped[float] = mapped_column(Float, default=0)


class NetworkAssignment(Base):
    __tablename__ = "network_assignments"
    job_id: Mapped[str] = mapped_column(ForeignKey("automation_jobs.id", ondelete="CASCADE"), primary_key=True)
    token: Mapped[str] = mapped_column(String(36))
    user_agent: Mapped[str] = mapped_column(String(2048))
    endpoint: Mapped[str | None] = mapped_column(String(40), nullable=True)
    expires_at: Mapped[float] = mapped_column(Float, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ExtractionSchema(Base):
    __tablename__ = 'extraction_schemas'
    __table_args__ = (UniqueConstraint('owner', 'family', 'version'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    family: Mapped[str] = mapped_column(String(36), default=uid)
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(120))
    definition: Mapped[dict] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Dataset(Base):
    __tablename__ = 'datasets'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    website_id: Mapped[str] = mapped_column(ForeignKey('websites.id', ondelete='CASCADE'), index=True)
    schema_id: Mapped[str] = mapped_column(ForeignKey('extraction_schemas.id', ondelete='RESTRICT'))
    name: Mapped[str] = mapped_column(String(120))
    options: Mapped[dict] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)


class ExtractionRun(Base):
    __tablename__ = 'extraction_runs'
    job_id: Mapped[str] = mapped_column(ForeignKey('automation_jobs.id', ondelete='CASCADE'), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey('datasets.id', ondelete='CASCADE'), index=True)
    schema_id: Mapped[str] = mapped_column(ForeignKey('extraction_schemas.id', ondelete='RESTRICT'))
    status: Mapped[str] = mapped_column(String(24), default='queued')
    valid_count: Mapped[int] = mapped_column(Integer, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, default=0)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    finalized: Mapped[bool] = mapped_column(Boolean, default=False)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class ExtractionSchedule(Base):
    __tablename__ = 'extraction_schedule_bindings'
    schedule_id: Mapped[str] = mapped_column(ForeignKey('schedules.id', ondelete='CASCADE'), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey('datasets.id', ondelete='CASCADE'), index=True)


class ExtractedRecord(Base):
    __tablename__ = 'extracted_records'
    __table_args__ = (UniqueConstraint('dataset_id', 'identity'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    dataset_id: Mapped[str] = mapped_column(ForeignKey('datasets.id', ondelete='CASCADE'), index=True)
    identity: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON)
    original: Mapped[dict] = mapped_column(JSON)
    provenance: Mapped[dict] = mapped_column(JSON)
    validation_status: Mapped[str] = mapped_column(String(24), index=True)
    status: Mapped[str] = mapped_column(String(24), default='active', index=True)
    first_seen: Mapped[float] = mapped_column(Float, default=time.time)
    last_seen: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    last_job_id: Mapped[str | None] = mapped_column(ForeignKey('automation_jobs.id', ondelete='SET NULL'), nullable=True)
    missing_count: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class RecordRevision(Base):
    __tablename__ = 'record_revisions'
    __table_args__ = (UniqueConstraint('record_id', 'number'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_id: Mapped[str] = mapped_column(ForeignKey('extracted_records.id', ondelete='CASCADE'), index=True)
    number: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSON)
    provenance: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class ExtractionObservation(Base):
    __tablename__ = 'extraction_observations'
    __table_args__ = (UniqueConstraint('job_id', 'fingerprint'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey('extraction_runs.job_id', ondelete='CASCADE'), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))


class ExtractionIssue(Base):
    __tablename__ = 'extraction_issues'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey('extraction_runs.job_id', ondelete='CASCADE'), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(32))
    details: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class DataChange(Base):
    __tablename__ = 'data_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey('datasets.id', ondelete='CASCADE'), index=True)
    record_id: Mapped[str] = mapped_column(ForeignKey('extracted_records.id', ondelete='CASCADE'), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    details: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)


class DatasetExport(Base):
    __tablename__ = 'dataset_exports'
    job_id: Mapped[str] = mapped_column(ForeignKey('automation_jobs.id', ondelete='CASCADE'), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey('datasets.id', ondelete='CASCADE'), index=True)
    format: Mapped[str] = mapped_column(String(8))
    options: Mapped[dict] = mapped_column(JSON)
    filename: Mapped[str | None] = mapped_column(String(80), nullable=True)
    rows: Mapped[int] = mapped_column(Integer, default=0)
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[float] = mapped_column(Float)


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


@event.listens_for(engine, "before_cursor_execute")
def count_request_queries(_connection, _cursor, _statement, _parameters, _context, _many):
    from .traffic import request_counters
    counters = request_counters.get()
    if counters is not None:
        counters["sql_queries"] += 1


_notice_cleanup_at = 0.0


@event.listens_for(OrmSession, "before_commit")
def publish_transaction_notice(session):
    """Commit cache notices atomically with API writes, including ORM bulk updates."""
    global _notice_cleanup_at
    from .traffic import request_counters
    from .realtime import resource_path
    context = request_counters.get()
    if not context or not context.get("owner") or context.get("method") not in {"POST", "PATCH", "PUT", "DELETE"}:
        return
    path = resource_path(context.get("path", ""), context.get("method", "POST"))
    transaction_id = session.get_transaction()
    if not path or session.info.get("notice_transaction") is transaction_id:
        return
    session.info["notice_transaction"] = transaction_id
    session.add(ResourceChange(owner="*" if path == "/admin/content" else context["owner"],
                               path=path, request_id=context["request_id"]))
    context["change_published"] = True
    if time.monotonic() > _notice_cleanup_at:
        from sqlalchemy import delete
        _notice_cleanup_at = time.monotonic() + 60
        session.execute(delete(ResourceChange).where(ResourceChange.created_at < time.time() - 86400))
