import asyncio
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update, func

from app.automation import supervise, pulse, watch_configuration
from app.config import settings
from app.coordination import assign, next_counter, publish_health, shared_retry, route_changed
from app.db import Job, Lease, NetworkAssignment, OperationalEvent, Schedule, Session, transaction
from app.jobs import claim, heartbeat, recover_expired, tick, cleanup
from app.outbound import Manager
from app.user_agents import Document, Profile, resolve
from conftest import KEY, OTHER_AUTH
from test_outbound import configured


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setattr(settings(), "content_admin_keys", KEY)


def configure(client, **changes):
    current = client.get("/api/admin/automation").json()
    result = client.post(
        "/api/admin/automation", json={"revision": current["revision"], "policy": current["policy"] | changes}
    )
    assert result.status_code == 200, result.text
    return result.json()


def queue(client, target, **values):
    response = client.post("/api/jobs", json={"website_id": target["id"], **values})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def finish(identifier, status="completed"):
    with transaction() as session:
        job = session.get(Job, identifier)
        job.status = status
        job.completed_at = time.time()
        session.execute(update(Lease).where(Lease.token == job.lease_token).values(expires_at=0))


def test_controls_authorization_revision_and_history(client, admin):
    path = "/api/admin/automation"
    assert client.get(path, headers=OTHER_AUTH).status_code == 403
    assert client.post(path, json={"revision": 0, "policy": {}}, headers=OTHER_AUTH).status_code == 403
    old = client.get(path).json()
    assert old["counts"] == {} and old["workers"] == [] and old["sessions"] == 0
    configure(client, paused=True)
    assert client.post(path, json={"revision": old["revision"], "policy": old["policy"]}).status_code == 409
    current = client.get(path).json()
    assert current["policy"]["paused"] and current["revision"] == 1
    assert current["policy_history"][0]["details"]["approved_policy"]["paused"]
    assert KEY not in str(current)
    assert (
        client.post(path, json={"revision": 1, "policy": {"concurrency": settings().max_concurrency + 1}}).status_code
        == 422
    )
    assert client.post(path, json={"revision": 1, "policy": {"recovery_retries": 4}}).status_code == 422
    client.headers.clear()
    assert client.get(path).status_code == 401


def test_manual_release_pause_and_emergency_stop(client, target, admin):
    configure(client, enabled=False)
    identifier = queue(client, target)
    assert claim() is None
    assert client.post(f"/api/admin/automation/jobs/{identifier}/release", headers=OTHER_AUTH).status_code == 403
    assert client.post(f"/api/admin/automation/jobs/{identifier}/release").status_code == 200
    configure(client, paused=True)
    assert claim() is None
    configure(client, paused=False)
    assert claim()[0] == identifier
    queued = queue(client, target)
    configure(client, emergency_stop=True)
    assert claim() is None
    with Session() as session:
        assert session.get(Job, identifier).cancel_requested
        assert session.get(Job, queued).status == "cancelled"
    configure(client, emergency_stop=False, enabled=True)
    with Session() as session:
        assert session.get(Job, queued).status == "cancelled"


def test_priority_dependency_and_failed_parent(client, target):
    parent = queue(client, target, priority=-10)
    child = queue(client, target, priority=10, depends_on=parent)
    independent = queue(client, target, priority=2)
    assert claim()[0] == independent
    finish(independent)
    assert claim()[0] == parent
    finish(parent)
    assert claim()[0] == child
    finish(child)
    failed = queue(client, target)
    dependent = queue(client, target, depends_on=failed)
    finish(failed, "failed")
    assert claim() is None
    with Session() as session:
        assert session.get(Job, dependent).status == "failed"
        assert "Dependency" in session.get(Job, dependent).error_message


def test_cross_workspace_dependencies_are_rejected(client, target):
    parent = queue(client, target)
    data = {k: target[k] for k in ("name", "base_url", "allowed_domains", "configuration")}
    data["authorized"] = True
    other = client.post("/api/websites", json=data, headers=OTHER_AUTH).json()
    response = client.post("/api/jobs", json={"website_id": other["id"], "depends_on": parent}, headers=OTHER_AUTH)
    assert response.status_code == 409


def test_disabled_integration_and_schedule_backpressure(client, target, admin):
    with transaction() as session:
        schedule = Schedule(website_id=target["id"], next_run_at=time.time() - 10)
        session.add(schedule)
        session.flush()
        schedule_id = schedule.id
    configure(client, disabled_websites=[target["id"]])
    identifier = queue(client, target)
    assert claim() is None and tick() == 0
    configure(client, disabled_websites=[], max_backlog=1)
    assert tick() == 0
    with Session() as session:
        assert session.get(Schedule, schedule_id).enabled
    finish(identifier)
    assert tick() == 1 and tick() == 0


def test_backpressure_covers_retries_agents_and_idempotent_reuse(client, target, admin, monkeypatch):
    configure(client, max_backlog=1)
    first = client.post("/api/jobs", json={"website_id": target["id"]}, headers={"Idempotency-Key": "one"})
    assert first.status_code == 201
    assert (
        client.post("/api/jobs", json={"website_id": target["id"]}, headers={"Idempotency-Key": "one"}).json()["id"]
        == first.json()["id"]
    )
    assert client.post("/api/jobs", json={"website_id": target["id"]}).status_code == 409
    finish(first.json()["id"], "failed")
    queue(client, target)
    assert client.post(f"/api/jobs/{first.json()['id']}/retry").status_code == 409
    monkeypatch.setattr(settings(), "ai_provider", "local")
    assert (
        client.post(
            "/api/agent/tasks", json={"website_id": target["id"], "objective": "Read the page title"}
        ).status_code
        == 409
    )


def test_recovery_budget_and_assignment_expiration(client, target, admin):
    configure(client, recovery_retries=0)
    identifier = queue(client, target)
    identifier, token = claim()
    runner = SimpleNamespace(id=identifier, token=token, cfg={"browser": "chromium"})
    routing = Manager(enabled=False)
    assign(runner, routing)
    assert heartbeat(identifier, token)
    with transaction() as session:
        session.get(Job, identifier).lease_until = time.time() - 1
        session.get(NetworkAssignment, identifier).expires_at = time.time() - 1
    supervise("scheduler-test")
    with Session() as session:
        assert session.get(Job, identifier).status == "failed"
        assert not session.get(NetworkAssignment, identifier).active
    with pytest.raises(InterruptedError):
        assign(runner, routing)


def test_shared_counter_is_atomic_across_threads_and_processes():
    with ThreadPoolExecutor(max_workers=8) as executor:
        values = list(executor.map(lambda _: next_counter("ua:browser"), range(32)))
    assert sorted(values) == list(range(32))
    result = subprocess.run(
        [sys.executable, "-c", "from app.coordination import next_counter; print(next_counter('ua:browser'))"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert int(result.stdout.strip()) == 32
    assert next_counter("ua:browser") == 33


def test_managers_share_rotation_and_unhealthy_endpoints():
    first, second = Manager(configured(), True), Manager(configured(), True)
    assert first.select("browser", "one").id == "a"
    assert second.select("browser", "two").id == "b"
    endpoint = first.config.endpoints[0]
    now = time.time()
    publish_health(endpoint, now, now + 100)
    publish_health(endpoint, now - 1, 0)
    assert shared_retry(endpoint) > now
    assert Manager(configured(), True).select("browser", "three").id == "b"
    publish_health(endpoint, now + 1, 0)
    assert shared_retry(endpoint) == 0
    # Both approved routes become eligible again after shared health validation.
    ids = {Manager(configured(), True).select("browser", str(i)).id for i in range(2)}
    assert ids == {"a", "b"}


@pytest.mark.parametrize(
    "strategy", ["manual", "round_robin", "random", "weighted", "sticky", "compatibility", "scheduled"]
)
def test_identity_strategies_and_compatibility(monkeypatch, strategy):
    from app import user_agents

    monkeypatch.setattr(settings(), "user_agent_rotatable_services", "browser")
    monkeypatch.setattr("app.outbound.manager", lambda: Manager(enabled=False))
    values = {"rotation": strategy, "profiles": ["a", "b"], "fallback": "fail"}
    if strategy == "manual":
        values = {"rotation": "manual", "profile": "a", "fallback": "fail"}
    doc = Document(
        profiles=[
            Profile(id="a", name="A", value="Chromium/1", clients=["chromium"]),
            Profile(id="b", name="B", value="Firefox/1", clients=["firefox"]),
        ],
        services={"browser": values},
    )
    monkeypatch.setattr(user_agents, "read", lambda: doc)
    assert resolve("browser", client="chromium", session_key="one") == "Chromium/1"
    assert resolve("browser", client="chromium", session_key="one") == "Chromium/1"
    with pytest.raises(ValueError, match="compatible"):
        resolve("browser", client="webkit")


def test_weighted_selection_uses_configured_weights(monkeypatch):
    from app import user_agents

    monkeypatch.setattr(settings(), "user_agent_rotatable_services", "browser")
    monkeypatch.setattr("app.outbound.manager", lambda: Manager(enabled=False))
    doc = Document(
        profiles=[Profile(id=k, name=k, value=k + "/1") for k in ("a", "b")],
        services={"browser": {"rotation": "weighted", "profiles": ["a", "b"], "weights": {"a": 1, "b": 9}}},
    )
    monkeypatch.setattr(user_agents, "read", lambda: doc)

    def choose(items, weights, k):
        assert weights == [1, 9] and k == 1
        return [items[-1]]

    monkeypatch.setattr(user_agents.random, "choices", choose)
    assert resolve("browser", client="chromium") == "b/1"


def test_assignment_survives_revisions_and_new_worker_tokens(client, target, monkeypatch):
    from app import user_agents

    identifier = queue(client, target)
    identifier, token = claim()
    first = SimpleNamespace(id=identifier, token=token, cfg={"browser": "chromium"})
    routing = Manager(enabled=False)
    monkeypatch.setattr(user_agents, "read", lambda: Document(global_value="Initial/1"))
    assert assign(first, routing) == "Initial/1"
    monkeypatch.setattr(user_agents, "read", lambda: Document(global_value="Updated/2"))
    assert assign(first, routing) == "Initial/1"
    with transaction() as session:
        job = session.get(Job, identifier)
        job.lease_until = time.time() - 1
        session.execute(update(Lease).values(expires_at=0))
    recover_expired()
    recovered, new_token = claim()
    assert recovered == identifier and new_token != token
    second = SimpleNamespace(id=identifier, token=new_token, cfg=first.cfg)
    assert assign(second, Manager(enabled=False)) == "Initial/1"
    with pytest.raises(InterruptedError):
        assign(first, routing)
    with pytest.raises(InterruptedError):
        route_changed(identifier, "unapproved", token)
    with Session() as session:
        row = session.get(NetworkAssignment, identifier)
        assert row.token == new_token and row.endpoint is None


def test_fixed_operator_identity_cannot_change_existing_session(client, target, monkeypatch):
    identifier = queue(client, target)
    identifier, token = claim()
    runner = SimpleNamespace(id=identifier, token=token, cfg={"browser": "chromium"})
    routing = Manager(enabled=False)
    assign(runner, routing)
    monkeypatch.setattr(settings(), "user_agent_fixed_identities", {"browser": "Mandatory/2"})
    with pytest.raises(ValueError, match="mandatory"):
        assign(runner, routing)


async def test_configuration_watcher_applies_committed_revision(client, admin):
    from app import user_agents

    task = asyncio.create_task(watch_configuration())
    try:
        await asyncio.sleep(0.05)
        response = client.post("/api/admin/user-agents", json={"revision": 0, "global_value": "Revision/2"})
        assert response.status_code == 200, response.text
        # Simulate another process retaining its pre-save cache.
        user_agents._cache = Document(global_value="Old/1")
        user_agents._cache_until = time.monotonic() + 100
        for _ in range(30):
            if user_agents.read().global_value == "Revision/2":
                break
            await asyncio.sleep(0.1)
        assert user_agents.read().global_value == "Revision/2"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_supervisor_real_heartbeats_alerts_and_retention(client, target, admin):
    configure(client, max_backlog=1)
    queue(client, target)
    supervise("scheduler-test")
    supervise("scheduler-test")
    pulse("worker-test", "worker", {"active_jobs": 0})
    response = client.get("/api/admin/automation").json()
    assert {w["role"] for w in response["workers"]} == {"worker", "scheduler"}
    assert response["counts"]["queued"] == 1
    codes = [e["code"] for e in response["events"]]
    assert codes.count("queue_backlog") == 1 and codes.count("no_live_workers") == 1
    assert all("process_cpu_seconds" in w["state"] for w in response["workers"])
    parent = response["jobs"][0]["id"]
    configure(client, max_backlog=2)
    child = queue(client, target, depends_on=parent)
    with transaction() as session:
        for identifier in (parent, child):
            row = session.get(Job, identifier)
            row.status = "completed"
            row.completed_at = 0
    cleanup()
    with Session() as session:
        assert session.get(Job, parent) is not None and session.get(Job, child) is None
        assert session.scalar(select(func.count()).select_from(OperationalEvent)) > 0
    cleanup()
    with Session() as session:
        assert session.get(Job, parent) is None


def test_automation_migration_preserves_existing_job_history(tmp_path):
    from sqlalchemy import create_engine, text

    env = dict(os.environ, ADBOT_DATABASE_URL="sqlite:///" + str(tmp_path / "automation.db"))

    def migrate(*args):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            env=env,
            cwd=Path(__file__).parents[1],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    migrate("upgrade", "f19c00000001")
    engine = create_engine(env["ADBOT_DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO websites (id,owner,name,base_url,allowed_domains,configuration,created_at,updated_at) VALUES ('site','owner','Retained','https://example.test','[]','{}',0,0)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO automation_jobs (id,owner,website_id,job_type,status,snapshot,payload_hash,created_at,pages_visited,retry_count,action_index,execution_state,cancel_requested,pause_requested,lease_until) VALUES ('job','owner','site','crawl','completed','{}','',0,0,0,0,'{}',false,false,0)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO automation_events (job_id,event_type,message,details,timestamp) VALUES ('job','completed','Retained event','{}',0)"
            )
        )
    migrate("upgrade", "head")
    migrate("upgrade", "head")
    migrate("check")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT priority FROM automation_jobs WHERE id='job'")) == 0
        assert connection.scalar(text("SELECT count(*) FROM automation_events WHERE job_id='job'")) == 1
        assert connection.scalar(text("SELECT count(*) FROM automation_control")) == 1
    migrate("downgrade", "f19c00000001")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM automation_events WHERE job_id='job'")) == 1
    migrate("upgrade", "head")
    engine.dispose()
