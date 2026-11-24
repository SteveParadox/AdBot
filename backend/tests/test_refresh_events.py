"""Workspace SSE cursor replay and tenant isolation without wall-clock waits."""
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


def read_events(owner, cursor):
    async def read():
        response = await workspace_events(DisconnectAfterBatch(), owner, cursor)
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
