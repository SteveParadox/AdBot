import asyncio
import time
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.automation import Policy
from app.config import settings
from app.coordination import assign, shared_retry
from app.db import Job, NetworkAssignment, Session
from app.jobs import claim
from app.outbound import Manager, Service, OutboundUnavailable
from test_automation import configure, finish, queue
from test_outbound import configured


def test_runtime_proxy_policy_cannot_override_operator_routing(monkeypatch):
    routing = Manager(configured(), True)
    monkeypatch.setattr("app.outbound.manager", lambda: routing)
    assert Policy(proxy_strategies={"browser": "weighted"}).proxy_strategies["browser"] == "weighted"
    with pytest.raises(ValidationError):
        Policy(proxy_strategies={"browser": "fixed"})
    routing.config.services["browser"] = Service(endpoints=["a"])
    with pytest.raises(ValidationError):
        Policy(proxy_strategies={"browser": "random"})
    with pytest.raises(ValidationError):
        Service(strategy="fixed", stable=False, endpoints=["a", "b"])


def test_proxy_weights_and_latency_strategy(monkeypatch):
    config = configured("weighted")
    config.endpoints[1].weight = 9
    routing = Manager(config, True)

    def choose(items, weights, k):
        assert weights == [1, 9] and k == 1
        return [items[-1]]

    monkeypatch.setattr("app.outbound.random.choices", choose)
    assert routing.select("browser", "session").id == "b"
    routing = Manager(configured("latency"), True)
    routing.states["a"]["latency_ms"] = 10
    routing.states["b"]["latency_ms"] = 100
    assert routing.select("browser", "session").id == "a"


async def test_approved_failover_persists_route_and_identity(client, target, monkeypatch):
    routing = Manager(configured(allow_failover=True), True)
    identifier = queue(client, target)
    identifier, token = claim()
    runner = SimpleNamespace(id=identifier, token=token, cfg={"browser": "chromium"})
    identity = assign(runner, routing)

    async def via(endpoint, *_):
        if endpoint.id == "a":
            raise TimeoutError()
        return "reader", "writer"

    monkeypatch.setattr(routing, "via", via)
    assert await routing.connect("browser", identifier, ["8.8.8.8"], 443) == ("reader", "writer")
    with Session() as session:
        row = session.get(NetworkAssignment, identifier)
        assert row.endpoint == "b" and row.user_agent == identity


async def test_authenticated_sessions_fail_closed_on_route_loss(client, target, monkeypatch):
    routing = Manager(configured(allow_failover=True), True)
    identifier = queue(client, target)
    identifier, token = claim()
    runner = SimpleNamespace(
        id=identifier, token=token, cfg={"browser": "chromium"}, options={"session_persistence": True}
    )
    assign(runner, routing)
    calls = []

    async def via(endpoint, *_):
        calls.append(endpoint.id)
        raise TimeoutError()

    monkeypatch.setattr(routing, "via", via)
    with pytest.raises(OutboundUnavailable):
        await routing.connect("browser", identifier, ["8.8.8.8"], 443)
    assert calls == ["a"]
    routing.release("browser", identifier)
    assert not routing.strict_sessions and not routing.assignment_tokens


def test_shared_stale_success_cannot_erase_observed_failure():
    routing = Manager(configured(), True)
    endpoint = routing.config.endpoints[0]
    started = time.monotonic() - 1
    routing.record(endpoint, started, TimeoutError())
    deadline = shared_retry(endpoint)
    # Another process's connection started before the failure was observed.
    other = Manager(configured(), True)
    other.record(endpoint, started + 0.5)
    assert shared_retry(endpoint) == deadline


async def test_running_job_obeys_global_pause_resume_and_emergency(client, target, monkeypatch):
    from app.browser import Runner
    from app.worker import execute
    from conftest import KEY

    monkeypatch.setattr(settings(), "content_admin_keys", KEY)
    actions = []

    async def run(self):
        while True:
            await self.gate.wait()
            actions.append("read")
            await asyncio.sleep(0.02)

    monkeypatch.setattr(Runner, "run", run)
    identifier = queue(client, target)
    task = asyncio.create_task(execute(*claim()))

    async def status(value):
        for _ in range(50):
            with Session() as session:
                if session.get(Job, identifier).status == value:
                    return
            await asyncio.sleep(0.05)
        pytest.fail("Worker did not reach " + value)

    try:
        await asyncio.sleep(0.1)
        configure(client, paused=True)
        await status("paused")
        count = len(actions)
        await asyncio.sleep(0.15)
        assert len(actions) == count
        configure(client, paused=False)
        await status("running")
        await asyncio.sleep(0.05)
        assert len(actions) > count
        configure(client, emergency_stop=True)
        await asyncio.wait_for(task, 5)
        await status("cancelled")
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_retry_cannot_bypass_failed_dependency(client, target):
    parent = queue(client, target)
    child = queue(client, target, depends_on=parent, priority=4)
    finish(parent, "failed")
    assert claim() is None
    response = client.post(f"/api/jobs/{child}/retry")
    assert response.status_code == 201, response.text
    assert response.json()["depends_on"] == parent and response.json()["priority"] == 4
    assert claim() is None


def test_agent_dependencies_use_same_queue(client, target, monkeypatch):
    monkeypatch.setattr(settings(), "ai_provider", "local")
    parent = queue(client, target)
    response = client.post(
        "/api/agent/tasks",
        json={"website_id": target["id"], "objective": "Read the page title", "depends_on": parent, "priority": 8},
    )
    assert response.status_code == 201, response.text
    assert response.json()["depends_on"] == parent and response.json()["priority"] == 8
    assert claim()[0] == parent
    finish(parent)
    assert claim()[0] == response.json()["id"]
