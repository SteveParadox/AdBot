"""Owner-scoped, bounded snapshot batches over the existing durable SQL log."""
import json
import time
from threading import Lock
from collections import OrderedDict

from sqlalchemy import select, delete, literal, union_all

from .api_support import output
from .db import AutomationEvent, AgentStep, AgentTask, Job, DatasetExport, ResourceChange, Session, transaction
from .agent.api import task_output

# Only serialized data, keyed by authenticated owner and cursors; no live Sessions.
# A small TTL joins identical reads from simultaneous tabs/API sessions in this worker.
_batches = OrderedDict()
_batch_lock = Lock()
MAX_BATCHES = 64


def resource_path(path, method="POST"):
    parts = path.removeprefix("/api/").split("/")
    root = parts[0]
    if root in {"websites", "workflows", "schedules"}:
        return "/" + "/".join(parts[:2]) + ("/deleted" if method == "DELETE" else "")
    if root == "extraction" and len(parts) > 1:
        if parts[1] not in {"schemas", "datasets"} or parts[-1] == "validate":
            return None
        return "/" + "/".join(parts[:4]) + ("/deleted" if method == "DELETE" else "")
    if root == "agent" and len(parts) > 1 and parts[1] == "memories":
        return "/" + "/".join(parts[:3])
    if root == "admin" and len(parts) > 1 and parts[1] in {"content", "automation", "user-agents"}:
        return "/" + "/".join(parts[:2])
    return None


def publish_change(owner, path, request_id="", method="POST"):
    path = resource_path(path, method)
    if not path:
        return
    with transaction() as session:
        # This explicit file-write fallback already supplies its notice. The ORM
        # hook must not add a second notice for the same request transaction.
        session.info["notice_transaction"] = session.get_transaction()
        session.add(ResourceChange(owner="*" if path == "/admin/content" else owner, path=path, request_id=request_id))
        # Bounded retention is independent of job history retention. Indexed cutoff.
        session.execute(delete(ResourceChange).where(ResourceChange.created_at < time.time() - 86400))


def read_batch(owner, cursor, change_cursor):
    key = (owner, cursor, change_cursor)
    now = time.monotonic()
    with _batch_lock:
        cached = _batches.get(key)
    if cached and cached[0] > now:
        return cached[1]
    with Session() as session:
        event_ids = select(AutomationEvent.id, literal("event").label("kind")).join(Job).where(
            Job.owner == owner, Job.job_type != "research", AutomationEvent.id > cursor,
        ).order_by(AutomationEvent.id).limit(100).subquery()
        change_ids = select(ResourceChange.id, literal("change").label("kind")).where(
            ResourceChange.owner.in_([owner, "*"]), ResourceChange.id > change_cursor,
        ).order_by(ResourceChange.id).limit(100).subquery()
        identifiers = session.execute(union_all(select(event_ids), select(change_ids))).all()
        events_to_load = [identifier for identifier, kind in identifiers if kind == "event"]
        changes_to_load = [identifier for identifier, kind in identifiers if kind == "change"]
        rows = session.execute(select(AutomationEvent, Job).join(Job).where(
            Job.owner == owner, AutomationEvent.id.in_(events_to_load),
        ).order_by(AutomationEvent.id)).all() if events_to_load else []
        changes = session.scalars(select(ResourceChange).where(
            ResourceChange.owner.in_([owner, "*"]), ResourceChange.id.in_(changes_to_load),
        ).order_by(ResourceChange.id)).all() if changes_to_load else []
        messages = [output(event) | {"snapshot_batch": True} for event, _job in rows]
        latest = {}
        step_ids = set()
        for index, (event, job) in enumerate(rows):
            latest[job.id] = (index, job)
            if isinstance(event.details.get("step_id"), int):
                step_ids.add(event.details["step_id"])
        agent_ids = [identifier for identifier, (_index, job) in latest.items() if job.job_type == "agent"]
        tasks = {task.job_id: task for task in session.scalars(select(AgentTask).where(
            AgentTask.job_id.in_(agent_ids),
        ))} if agent_ids else {}
        # Steps are selected through the owner's jobs; an injected step ID cannot leak.
        steps = session.scalars(select(AgentStep).join(Job, AgentStep.job_id == Job.id).where(
            Job.owner == owner, AgentStep.id.in_(step_ids),
        )).all() if step_ids else []
        exports = {row.job_id: row.dataset_id for row in session.scalars(select(DatasetExport).where(
            DatasetExport.job_id.in_([identifier for identifier, (_index, job) in latest.items() if job.job_type == "export"])
        ))} if any(job.job_type == "export" for _index, job in latest.values()) else {}
        for job_id, (index, job) in latest.items():
            resource = {"job": output(job), "dataset_id": exports.get(job_id) or (job.snapshot.get("extraction") or {}).get("dataset_id")}
            if job_id in tasks:
                values = task_output(job, tasks[job_id])
                # Large session memory is read on demand, not broadcast at each action.
                resource["task"] = {k: v for k, v in values.items() if k not in {"memory", "options", "objective", "mode"}}
                resource["steps"] = [output(step) for step in steps if step.job_id == job_id]
            messages[index]["resource"] = resource
        change_messages = [{"id": row.id, "path": row.path, "request_id": row.request_id} for row in changes]
    payload = (messages, change_messages)
    # Enforce a memory bound as well as a count bound. Huge snapshots fall back to GET.
    if len(json.dumps(payload)) > 1_000_000:
        for message in messages:
            resource = message.pop("resource", None)
            if resource:
                message["details"] = {**message["details"], "job_type": resource["job"]["job_type"],
                                      "dataset_id": resource.get("dataset_id")}
            message["snapshot_batch"] = False
    with _batch_lock:
        _batches[key] = (now + 0.5, payload)
        _batches.move_to_end(key)
        while len(_batches) > MAX_BATCHES:
            _batches.popitem(last=False)
    return payload
