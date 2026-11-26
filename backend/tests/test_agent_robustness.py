"""Regressions for runner ownership, durable outcomes and browser recovery."""
import asyncio
import threading
from contextlib import contextmanager
from unittest.mock import AsyncMock

import pytest
from playwright.async_api import Dialog, Error as BrowserError, async_playwright
from sqlalchemy import select

from app.agent.contracts import Decision
from app.agent.controller import Controller
from app.agent.runner import AgentRunner
from app.browser import BrowserCrashed
from app.db import AgentMemory, AgentStep, Job, Lease, transaction
from app.failures import diagnose
from app.jobs import claim, recover_expired
from app.worker import execute
import test_agent as agent_fixtures
from test_agent import new_task, set_url

agent_config = agent_fixtures.agent_config
agent_servers = agent_fixtures.agent_servers


def decision(action, **kwargs):
    return Decision(observation="Observed page", decision=action, reason="Regression check",
                    confidence=1, expected_result="Expected state", **kwargs)


async def test_duplicate_dispatch_launches_only_one_runner(client, target, monkeypatch):
    response = client.post("/api/jobs", json={"website_id": target["id"]})
    assert response.status_code == 201, response.text
    lease = claim()
    started, release = asyncio.Event(), asyncio.Event()
    launches = []

    class FakeRunner:
        def __init__(self, *args):
            self.cfg = {"max_duration_seconds": 20}
            self.gate = asyncio.Event()
            self.gate.set()

        async def run(self):
            launches.append(1)
            started.set()
            await release.wait()

    monkeypatch.setattr("app.worker.Runner", FakeRunner)
    first = asyncio.create_task(execute(*lease))
    try:
        await asyncio.wait_for(started.wait(), 5)
        await asyncio.wait_for(execute(*lease), 5)
        assert launches == [1]
        with transaction() as session:
            assert session.get(Job, lease[0]).status == "running"
            assert session.get(Lease, "execution:" + lease[0]).expires_at > 0
    finally:
        release.set()
        await first
    with transaction() as session:
        assert session.get(Job, lease[0]).status == "completed"
        assert session.get(Lease, "execution:" + lease[0]).expires_at == 0


@pytest.mark.parametrize("step_status", ["executing", "failed"])
def test_expired_uncertain_action_is_never_requeued(client, target, agent_config, step_status):
    task = new_task(client, target)
    identifier, token = claim()
    with transaction() as session:
        session.get(Job, identifier).lease_until = 1
        session.add(AgentStep(job_id=identifier, number=1, observation={}, status=step_status,
                              decision={"decision": "CLICK"}, outcome={"uncertain_submission": step_status == "failed"}))
    recover_expired()
    with transaction() as session:
        assert session.get(Job, task["id"]).status == "failed"
        assert session.get(Job, task["id"]).execution_state["failure"]["category"] == "uncertain_submission"


@pytest.mark.browser
async def test_restore_active_tab_histories_and_tab_health(client, target, agent_config, agent_servers):
    new_task(client, target)
    runner = AgentRunner(*claim())
    root = target["base_url"].rstrip("/")
    runner.memory["tabs"] = [
        {"tab_id": "old-first", "url": root + "/agent/news", "purpose": "Research",
         "history": [root, root + "/agent/news"]},
        {"tab_id": "old-second", "url": root + "/agent/catalog", "purpose": "Catalog",
         "history": [root, root + "/agent/catalog"]},
    ]
    runner.memory["active_tab"] = "old-first"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            context = await browser.new_context()
            page = await context.new_page()
            controller = Controller(runner, context, page, runner.memory)
            runner.controller = controller

            async def navigate(url):
                await controller.page.goto(url)
                controller.tabs[controller.active]["history"].append(url)

            controller.navigate = navigate
            runner.permitted = AsyncMock(side_effect=lambda url: url)
            await runner.restore_tabs(controller)
            assert controller.active == "t1" and controller.page == page
            assert page.url == root + "/agent/news"
            assert [t["purpose"] for t in controller.tabs.values()] == ["Research", "Catalog"]
            assert [t["history"] for t in controller.tabs.values()] == [t["history"] for t in runner.memory["tabs"]]
            assert "old-second" not in controller.tabs
            background = next(t["page"] for key, t in controller.tabs.items() if key != "t1")
            await background.goto(root + "/missing")
            assert runner.response_for(page).status == 200
            assert runner.response_for(background).status == 404
            await background.close()
            controller.prune_tabs()
            assert list(controller.tabs) == ["t1"]
            controller.navigate = AsyncMock(side_effect=BrowserError("Navigation failed"))
            with pytest.raises(BrowserError):
                await controller.act(decision("OPEN_TAB", url=root + "/bad"), runner.options)
            assert controller.active == "t1" and controller.page == page
            assert list(controller.tabs) == ["t1"]
            assert len(context.pages) == 1
            controller.crashed_pages.add(page)
            with pytest.raises(BrowserCrashed):
                await controller.observe()
        finally:
            await browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("error_type", [BrowserError, RuntimeError])
async def test_uncertain_dispatch_survives_unobservable_page(
    client, target, agent_config, agent_servers, monkeypatch, error_type,
):
    set_url(client, target, "/agent/news")
    task = new_task(client, target)
    original = Controller.act
    dispatches = []

    async def fail_after_dispatch(self, action, options, approved=False):
        if action.decision == "CLICK":
            self.engine.dispatch_started = True
            dispatches.append(action)
            await self.page.close()
            raise error_type("Renderer gone after dispatched input")
        return await original(self, action, options, approved)

    monkeypatch.setattr(Controller, "act", fail_after_dispatch)
    await execute(*claim())
    result = client.get("/api/agent/tasks/" + task["id"]).json()
    assert result["status"] == "failed" and not result["result"]
    assert len(dispatches) == 1
    with transaction() as session:
        step = session.scalar(select(AgentStep).where(AgentStep.job_id == task["id"]).order_by(AgentStep.number.desc()))
        assert step.status == "failed"
        assert step.outcome["uncertain_submission"] is True
        assert not step.outcome.get("replanning")
        diagnostic = session.get(Job, task["id"]).execution_state["failure"]
        assert diagnostic["category"] == "uncertain_submission"
        assert diagnostic["automatic_retry_scheduled"] is False


@pytest.mark.browser
@pytest.mark.parametrize("failure", ["checkpoint", "cleanup", "cancel"])
async def test_verified_candidate_is_not_published_after_failure(
    client, target, agent_config, agent_servers, monkeypatch, failure,
):
    set_url(client, target, "/agent/news")
    task = new_task(client, target, memory_enabled=True)
    original_checkpoint, original_run = AgentRunner.checkpoint, AgentRunner.run
    reached = []

    async def checkpoint(self, controller):
        recent = self.memory["recent_actions"]
        if failure == "checkpoint" and recent and recent[-1]["action"] == "COMPLETE":
            reached.append("verified")
            raise RuntimeError("Injected checkpoint failure")
        await original_checkpoint(self, controller)

    async def run(self):
        await original_run(self)
        reached.append("verified")
        if failure == "cleanup":
            raise RuntimeError("Injected browser cleanup failure")
        if failure == "cancel":
            with transaction() as session:
                session.get(Job, self.id).cancel_requested = True

    monkeypatch.setattr(AgentRunner, "checkpoint", checkpoint)
    monkeypatch.setattr(AgentRunner, "run", run)
    await execute(*claim())
    assert reached == ["verified"]
    result = client.get("/api/agent/tasks/" + task["id"]).json()
    assert result["status"] == ("cancelled" if failure == "cancel" else "failed"), result
    assert not result["result"]
    with transaction() as session:
        assert not session.scalar(select(AgentMemory).where(AgentMemory.source_job_id == task["id"]))
    logs = client.get("/api/jobs/" + task["id"] + "/logs").json()["items"]
    assert not any(event["event_type"] == "goal_verified" for event in logs)


async def test_runner_without_verification_cannot_complete(client, target, agent_config, monkeypatch):
    task = new_task(client, target)
    monkeypatch.setattr(AgentRunner, "run", AsyncMock())
    await execute(*claim())
    result = client.get("/api/agent/tasks/" + task["id"]).json()
    assert result["status"] == "failed" and not result["result"]
    assert "without a durable verified result" in result["error_message"]


@pytest.mark.browser
async def test_step_transactions_run_off_loop_and_publish_once(
    client, target, agent_config, agent_servers, monkeypatch,
):
    loop_thread = threading.get_ident()
    database_threads = []

    @contextmanager
    def checked_transaction():
        database_threads.append(threading.get_ident())
        assert threading.get_ident() != loop_thread, "Agent SQL blocked the event loop"
        with transaction() as session:
            yield session

    monkeypatch.setattr("app.agent.runner.transaction", checked_transaction)
    set_url(client, target, "/agent/news")
    task = new_task(client, target, memory_enabled=True)
    await execute(*claim())
    result = client.get("/api/agent/tasks/" + task["id"]).json()
    assert result["status"] == "completed", result
    assert result["result"]["verification"]["complete"] is True
    assert len(database_threads) >= 10
    logs = client.get("/api/jobs/" + task["id"] + "/logs").json()["items"]
    assert sum(event["event_type"] == "goal_verified" for event in logs) == 1
    with transaction() as session:
        memories = session.scalars(select(AgentMemory).where(AgentMemory.source_job_id == task["id"])).all()
        assert len(memories) == 1
        assert memories[0].content == result["result"]


@pytest.mark.parametrize("uncertain", [False, True])
def test_diagnostics_respect_uncertainty_flag_value(client, target, agent_config, uncertain):
    task = new_task(client, target)
    with transaction() as session:
        session.add(AgentStep(job_id=task["id"], number=1, observation={}, status="failed",
                              decision={"decision": "CLICK"},
                              outcome={"error": "Target is disabled", "uncertain_submission": uncertain}))
        session.flush()
        diagnostic = diagnose(session, session.get(Job, task["id"]), "Target is disabled")
        assert (diagnostic["category"] == "uncertain_submission") is uncertain


async def test_cancelled_inflight_input_keeps_manual_review_diagnostic(client, target, agent_config, monkeypatch):
    task = new_task(client, target)
    started = asyncio.Event()

    async def run(self):
        with transaction() as session:
            session.add(AgentStep(job_id=self.id, number=1, observation={}, status="executing",
                                  decision={"decision": "CLICK"}))
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(AgentRunner, "run", run)
    execution = asyncio.create_task(execute(*claim()))
    try:
        await asyncio.wait_for(started.wait(), 5)
        response = client.post("/api/jobs/" + task["id"] + "/cancel")
        assert response.status_code == 200, response.text
        await asyncio.wait_for(execution, 5)
    finally:
        execution.cancel()
        await asyncio.gather(execution, return_exceptions=True)
    with transaction() as session:
        job = session.get(Job, task["id"])
        assert job.status == "cancelled"
        diagnostic = job.execution_state["failure"]
        assert diagnostic["category"] == "uncertain_submission"
        assert not diagnostic["retry_eligible"]
        assert not diagnostic["automatic_retry_scheduled"]


@pytest.mark.browser
async def test_initial_agent_tab_dismisses_each_dialog_once(client, target, agent_config, monkeypatch):
    new_task(client, target)
    runner = AgentRunner(*claim())
    dismissed, results = [], []
    original_dismiss = Dialog.dismiss

    async def dismiss(dialog):
        dismissed.append(dialog.message)
        await original_dismiss(dialog)

    async def execute_page(page, context):
        Controller(runner, context, page, runner.memory)
        results.append(await page.evaluate("confirm('Continue?')"))

    monkeypatch.setattr(Dialog, "dismiss", dismiss)
    monkeypatch.setattr(runner, "execute_page", execute_page)
    await runner.run()
    assert results == [False]
    assert dismissed == ["Continue?"]
@pytest.mark.asyncio
async def test_extract_accepts_a_paraphrase_supported_by_an_earlier_observation(client, target, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings(), "ai_provider", "local")
    payload = {"website_id": target["id"], "objective": "Find the service hours"}
    job = client.post("/api/agent/tasks", json=payload).json()["id"]
    other = client.post("/api/agent/tasks", json=payload).json()["id"]
    runner = AgentRunner(*claim())
    assert runner.id == job
    quote = "The service opens\nat 08:00 on weekdays."
    old_url = "http://127.0.0.1:8765/hours"
    with transaction() as session:
        earlier = AgentStep(job_id=job, number=1, observation={"url": old_url, "text": quote})
        private = AgentStep(job_id=other, number=1, observation={"url": old_url, "text": "Other task evidence."})
        session.add_all([earlier, private])
        session.flush()
        source_id = earlier.id
    page = {"url": "http://127.0.0.1:8765/locations", "text": "Locations", "viewport_text": ""}
    action = Decision(decision="EXTRACT", observation="Earlier source", reason="Capture hours", confidence=1,
                      expected_result="Source-backed hours", text="Weekday service starts at 8 am.",
                      source_quote="THE SERVICE OPENS AT 08:00 ON WEEKDAYS.")
    evidence = await runner.extract(action, page, 9000)
    assert evidence["url"] == old_url and evidence["step_id"] == source_id
    assert evidence["quote"] == quote and evidence["summary"] == action.text
    inferred = await runner.extract(action.model_copy(update={"source_quote": None}), page, 9002)
    assert inferred["id"] == evidence["id"] and inferred["quote"] == quote
    with pytest.raises(ValueError, match="not found"):
        await runner.extract(action.model_copy(update={"source_quote": "Other task evidence."}), page, 9001)
