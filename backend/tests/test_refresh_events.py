"""Workspace SSE cursor replay and tenant isolation without wall-clock waits."""
import pytest
import asyncio
import json

from sqlalchemy import select

from app.db import AutomationEvent, Job, Session, emit, transaction
from app.main import workspace_events


class DisconnectAfterBatch:
    def __init__(self):
        self.calls = 0

    async def is_disconnected(self):
        self.calls += 1
        return self.calls > 1


@pytest.fixture(autouse=True)
def clear_event_batches():
    from app.realtime import _batches
    _batches.clear()
    from app.traffic import _workspaces
    _workspaces.clear()
    yield
    _batches.clear()


def read_events(owner, cursor, change_cursor=None):
    async def read():
        request = DisconnectAfterBatch()
        if change_cursor is not None:
            request.headers = {"X-Resource-Cursor": str(change_cursor)}
        response = await workspace_events(request, owner, cursor)
        messages = []
        async for message in response.body_iterator:
            for line in message.splitlines():
                if line.startswith("data: "):
                    messages.append(json.loads(line[6:]))
        return messages
    return asyncio.run(read())


def test_workspace_replay_filters_owners_and_resumes_after_cursor(client, target):
    job = client.post("/api/jobs", json={"website_id": target["id"]}).json()
    with Session() as session:
        owner = session.get(Job, job["id"]).owner
        first = session.scalar(select(AutomationEvent.id).where(AutomationEvent.job_id == job["id"]))
    with transaction() as session:
        other = Job(owner="different-owner", website_id=target["id"], snapshot={})
        session.add(other)
        session.flush()
        emit(session, other.id, "private", "must not leak")
        emit(session, job["id"], "completed", "owned update")
    events = read_events(owner, str(first))
    assert events[0]["event_type"] == "sync"
    assert [event["event_type"] for event in events[1:]] == ["completed"]
    assert events[1]["id"] > first
    assert all("owner" not in event for event in events)
    assert len(read_events(owner, str(events[1]["id"]))) == 1


def test_workspace_first_connection_reconciles_without_replaying_entire_history(client, target):
    job = client.post("/api/jobs", json={"website_id": target["id"]}).json()
    with Session() as session:
        owner = session.get(Job, job["id"]).owner
    events = read_events(owner, None)
    assert len(events) == 1
    assert events[0]["event_type"] == "sync"
    assert events[0]["id"] > 0


def test_workspace_events_auth_and_cursor_validation(client):
    assert client.get("/api/events", headers={"Authorization": ""}).status_code == 401
    assert client.get("/api/events", headers={"Last-Event-ID": "invalid"}).status_code == 422


def test_log_tail_returns_latest_events_in_ascending_order(client, target):
    job = client.post("/api/jobs", json={"website_id": target["id"]}).json()
    with transaction() as session:
        for number in range(5):
            emit(session, job["id"], "progress", str(number))
    tail = client.get(f"/api/jobs/{job['id']}/logs?limit=2&tail=true").json()
    assert tail["total"] == 6
    assert [event["message"] for event in tail["items"]] == ["3", "4"]
    default = client.get(f"/api/jobs/{job['id']}/logs?limit=2").json()
    assert default["items"][0]["event_type"] == "queued"


def test_workspace_snapshot_is_authoritative_and_filters_injected_step_references(client, target, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings(), "ai_provider", "local")
    from app.db import AgentStep
    from app.realtime import read_batch
    from conftest import OTHER_AUTH
    task = client.post("/api/agent/tasks", json={"website_id": target["id"], "objective": "Find the fixture title"}).json()
    other_site = client.post("/api/websites", headers=OTHER_AUTH, json={
        "name":"Other", "base_url":"http://127.0.0.1:8765/", "allowed_domains":["127.0.0.1"], "authorized":True,
    }).json()
    other = client.post("/api/agent/tasks", headers=OTHER_AUTH, json={"website_id":other_site["id"],"objective":"Other private task"}).json()
    with transaction() as session:
        own = session.get(Job, task["id"])
        owner = own.owner
        own.status = "completed"
        step = AgentStep(job_id=task["id"], number=1, observation={}, decision={}, outcome={}, status="succeeded")
        private = AgentStep(job_id=other["id"], number=1, observation={"private":"must not leak"}, decision={}, outcome={})
        session.add_all([step, private])
        session.flush()
        emit(session, task["id"], "agent_action_completed", "one", step_id=step.id)
        emit(session, task["id"], "completed", "done", step_id=private.id)
    messages, _changes = read_batch(owner, 0, 0)
    resource = messages[-1]["resource"]
    assert resource["job"]["status"] == "completed"
    assert resource["task"]["status"] == "completed"
    assert "memory" not in resource["task"]
    assert len(resource["steps"]) == 1
    assert resource["steps"][0]["job_id"] == task["id"]
    assert "must not leak" not in json.dumps(messages)


def test_resource_changes_are_durable_scoped_and_read_only_previews_emit_none(client, target):
    from app.db import ResourceChange
    from app.realtime import read_batch
    from conftest import OTHER_AUTH
    with Session() as session:
        from app.db import Website
        owner = session.get(Website,target["id"]).owner
    before, changes = read_batch(owner, 0, 0)
    assert any(row["path"].startswith("/websites") for row in changes)
    assert len(changes[0]["request_id"]) == 32
    assert read_batch("different-owner", 0, 0) == ([], [])
    count = len(changes)
    client.post("/api/agent/preview", json={"website_id":target["id"],"objective":"Preview fixture task"})
    with Session() as session:
        assert len(session.scalars(select(ResourceChange)).all()) == count
    assert client.get("/api/admin/traffic", headers=OTHER_AUTH).json().get("endpoints", {}) == {}


def test_agent_task_collection_query_count_is_constant(client, target, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings(), "ai_provider", "local")
    from sqlalchemy import event as sql_event
    from app.db import engine
    for index in range(8):
        assert client.post("/api/agent/tasks", json={"website_id":target["id"],"objective":f"Read fixture title {index}"}).status_code == 201
    queries = []
    def count(*_args):
        queries.append(1)
    sql_event.listen(engine, "before_cursor_execute", count)
    try:
        response = client.get("/api/agent/tasks?limit=25")
    finally:
        sql_event.remove(engine, "before_cursor_execute", count)
    assert response.json()["total"] == 8
    assert len(queries) == 3


def test_request_diagnostics_correlate_without_exposing_credentials(client):
    from conftest import KEY
    response = client.get("/api/websites")
    assert len(response.headers["X-Request-ID"]) == 32
    assert KEY not in response.text
    metrics = client.get("/api/admin/traffic").json()
    assert metrics["requests"] >= 1
    assert metrics["sql_queries"] >= 2
    assert "p95" in metrics["latency_ms_last_128"]
    assert KEY not in json.dumps(metrics)


def test_notification_is_rolled_back_with_the_write(client, target):
    from app.db import ResourceChange
    with Session() as session:
        before = len(session.scalars(select(ResourceChange)).all())
    response = client.post("/api/workflows", json={"website_id":target["id"],"name":"Invalid", "definition":{"steps":[{"action":"EVALUATE"}]}})
    assert response.status_code == 422
    with Session() as session:
        assert len(session.scalars(select(ResourceChange)).all()) == before


def test_oversized_snapshots_request_targeted_reconciliation(client, target, monkeypatch):
    from app.config import settings
    from app.db import AgentStep
    from app.realtime import read_batch
    monkeypatch.setattr(settings(), "ai_provider", "local")
    task = client.post("/api/agent/tasks", json={"website_id":target["id"],"objective":"Inspect fixture title"}).json()
    with transaction() as session:
        job = session.get(Job,task["id"])
        owner = job.owner
        step = AgentStep(job_id=job.id,number=1,observation={"large":"x"*1_100_000},decision={},outcome={})
        session.add(step)
        session.flush()
        emit(session,job.id,"agent_observed","Observed",step_id=step.id)
    messages, _ = read_batch(owner,0,0)
    assert not messages[-1]["snapshot_batch"]
    assert "resource" not in messages[-1]
    assert messages[-1]["details"]["job_type"] == "agent"


def test_replay_batches_and_owner_cache_are_bounded(client, target):
    from app.realtime import read_batch, _batches, MAX_BATCHES
    job = client.post("/api/jobs",json={"website_id":target["id"]}).json()
    with transaction() as session:
        owner = session.get(Job,job["id"]).owner
        for index in range(120):
            emit(session,job["id"],"progress",str(index))
    first, _ = read_batch(owner,0,0)
    assert len(first) == 100
    second, _ = read_batch(owner,first[-1]["id"],0)
    assert len(second) == 21
    for index in range(MAX_BATCHES+3):
        assert read_batch(f"empty-owner-{index}",0,0) == ([], [])
    assert len(_batches) == MAX_BATCHES


def test_parent_deletion_publishes_a_scoped_transactional_tombstone(client, target):
    from app.db import ResourceChange, Website
    identifier = target["id"]
    assert client.delete("/api/websites/"+identifier).status_code == 204
    with Session() as session:
        assert session.get(Website,identifier) is None
        rows = session.scalars(select(ResourceChange).order_by(ResourceChange.id)).all()
        assert rows[-1].path == f"/websites/{identifier}/deleted"
        assert len(rows[-1].request_id) == 32


def test_resource_retention_gap_requests_a_full_snapshot_reconciliation(client, target):
    from sqlalchemy import delete
    from app.db import ResourceChange, Website
    with transaction() as session:
        owner = session.get(Website,target["id"]).owner
        session.execute(delete(ResourceChange))
        session.add(ResourceChange(id=100,owner=owner,path="/workflows",request_id="a"*32))
    events = read_events(owner,"0",5)
    assert events[0]["details"]["reset"] is True
    assert events[0]["change_cursor"] == 100


def test_idle_stream_poll_uses_one_sql_query_for_both_durable_logs(client, target):
    from sqlalchemy import event as sql_event
    from app.db import engine, Website
    from app.realtime import read_batch
    with Session() as session:
        owner = session.get(Website,target["id"]).owner
    queries = []
    def count(*_args):
        queries.append(1)
    sql_event.listen(engine,"before_cursor_execute",count)
    try:
        assert read_batch(owner,1_000_000,1_000_000) == ([], [])
        assert len(queries) == 1
        assert read_batch(owner,1_000_000,1_000_000) == ([], [])
        assert len(queries) == 1
    finally:
        sql_event.remove(engine,"before_cursor_execute",count)


def test_postgresql_repairs_commit_order_gaps_over_the_existing_socket(client, target, monkeypatch):
    from app.db import Website, engine
    import app.main as main_module
    with Session() as session:
        owner = session.get(Website,target["id"]).owner
    moment = [100.0]
    monkeypatch.setattr(main_module.time,"monotonic",lambda:moment[0])
    monkeypatch.setattr(engine.dialect,"name","postgresql")
    async def read():
        response = await workspace_events(DisconnectAfterBatch(),owner,"0")
        initial = await anext(response.body_iterator)
        assert "server_epoch" in initial
        moment[0] += 61
        repair = await anext(response.body_iterator)
        assert '"snapshot_gap": true' in repair
        await response.body_iterator.aclose()
    asyncio.run(read())


def test_explicit_file_change_notice_is_not_published_twice(client, target):
    from app.db import ResourceChange, Website
    from app.realtime import publish_change
    from app.traffic import request_counters
    with Session() as session:
        owner = session.get(Website,target["id"]).owner
        before = len(session.scalars(select(ResourceChange)).all())
    binding = request_counters.set({"owner":owner,"method":"POST","path":"/api/admin/user-agents","request_id":"a"*32,"sql_queries":0})
    try:
        publish_change(owner,"/api/admin/user-agents","a"*32)
    finally:
        request_counters.reset(binding)
    with Session() as session:
        assert len(session.scalars(select(ResourceChange)).all()) == before+1
