import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select

from app.concurrency import IOExecutor
from app.db import AgentStep, AgentTask, Job, Lease, transaction
from app.extraction.persistence import save_page
from app.jobs import claim
from app.provider_quota import reserve, settle, cooldown, QuotaBlocked
from app.worker import execute
from conftest import OTHER_AUTH
from test_extraction import setup_dataset, normalized


def test_shared_quota_atomic_admission_and_settlement():
    def attempt(_):
        try:
            reserve("shared-test", 20, 3, 100, now=120)
            return True
        except QuotaBlocked:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(12))) == 3
    receipt = reserve("tokens", 90, 0, 100, now=120)
    with pytest.raises(QuotaBlocked):
        reserve("tokens", 20, 0, 100, now=120)
    settle("tokens", receipt, 10)
    reserve("tokens", 20, 0, 100, now=120)
    reserve("shared-test", 20, 3, 100, now=180)
    cooldown("cooldown", 30)
    with pytest.raises(QuotaBlocked):
        reserve("cooldown", 1, 0, 0)


async def test_blocking_operation_keeps_loop_responsive_and_measures():
    entered, release = threading.Event(), threading.Event()
    def operation():
        entered.set()
        release.wait(2)
    async with IOExecutor(1) as io:
        task = asyncio.create_task(io.run(operation))
        while not entered.is_set():
            await asyncio.sleep(.001)
        started = time.monotonic()
        await asyncio.sleep(.02)
        assert not task.done()
        release.set()
        await task
        assert time.monotonic() - started < 1
        assert io.snapshot()["operations"] == 1
        assert io.snapshot()["work_ms"] >= 15


async def test_filtered_export_numeric_order_and_ownership(client, target):
    _, dataset = setup_dataset(client, target)
    source = client.post(f"/api/extraction/datasets/{dataset['id']}/run").json()
    job_id, token = claim()
    records = []
    for index, price in enumerate(["$100", "$9", "$20", "$9"]):
        value = normalized(name=f"item{index}", price=price)
        value["data"]["product_url"] += str(index)
        value["identity"] += str(index)
        records.append(value)
    save_page(job_id, token, "https://example.org/catalog", records)
    with transaction() as session:
        session.get(Job, source["id"]).status = "completed"
        session.get(Job, source["id"]).lease_until = 0
        for lease in session.scalars(select(Lease).where(Lease.token == token)):
            lease.expires_at = 0
    options = {"format": "json", "query": {"filters": [{"field": "price", "op": "lt", "value": "30"}], "sort": [{"field": "price", "direction": "asc"}], "limit": 2}}
    response = client.post(f"/api/extraction/datasets/{dataset['id']}/exports", json=options)
    assert response.status_code == 201, response.text
    await execute(*claim())
    result = client.get(f"/api/extraction/exports/{response.json()['job_id']}/download")
    assert result.status_code == 200, result.text
    assert [r["data"]["price"] for r in result.json()["records"]] == ["9", "9"]
    assert client.post(f"/api/extraction/datasets/{dataset['id']}/exports", json=options, headers=OTHER_AUTH).status_code == 404
    options["query"]["sort"][0]["field"] = "unknown"
    assert client.post(f"/api/extraction/datasets/{dataset['id']}/exports", json=options).status_code == 422


def test_uncertain_submission_diagnostic_never_advises_retry(client, target):
    from app.failures import diagnose
    identifier = client.post("/api/jobs", json={"website_id": target["id"]}).json()["id"]
    with transaction() as session:
        job = session.get(Job, identifier)
        job.job_type = "agent"
        session.add(AgentTask(job_id=identifier, objective="Test diagnostics", mode="autonomous", options={}))
        session.flush()
        session.add(AgentStep(job_id=identifier, number=1, observation={}, decision={"decision": "CLICK"}, status="failed", outcome={"uncertain_submission": True}))
        session.flush()
        value = diagnose(session, job, "Agent stopped")
        assert value["category"] == "uncertain_submission"
        assert value["retry_eligible"] is False
        job.execution_state = {"failure": value}
    result = client.get(f"/api/jobs/{identifier}").json()
    assert result["failure"] == value
    assert client.get(f"/api/jobs/{identifier}", headers=OTHER_AUTH).status_code == 404



def test_cheapest_query_preview_persistence_and_bad_fields(client, target, monkeypatch):
    from app.config import settings
    from app.db import AgentTask
    monkeypatch.setattr(settings(), "ai_provider", "local")
    _, dataset = setup_dataset(client, target)
    body = {"website_id": target["id"], "dataset_id": dataset["id"], "objective": "Export the cheapest ten products as CSV."}
    preview = client.post("/api/agent/preview", json=body)
    assert preview.status_code == 200, preview.text
    query = preview.json()["specification"]["dataset_query"]
    assert query["sort"] == [{"field": "price", "direction": "asc"}]
    assert query["limit"] == 10
    result = client.post("/api/agent/tasks", json=body, headers={"Idempotency-Key": "cheapest-test"})
    assert result.status_code == 201, result.text
    assert client.post("/api/agent/tasks", json=body, headers={"Idempotency-Key": "cheapest-test"}).json()["id"] == result.json()["id"]
    with transaction() as session:
        assert session.get(AgentTask, result.json()["id"]).options["dataset_query"] == query
    body["dataset_query"] = {"sort": [{"field": "unknown"}]}
    assert client.post("/api/agent/preview", json=body).status_code == 422
    assert client.post("/api/agent/tasks", json=body).status_code == 422


async def test_worker_slow_heartbeat_does_not_block_loop(client, target, monkeypatch):
    from app import worker
    identifier = client.post("/api/jobs", json={"website_id": target["id"]}).json()["id"]
    item = claim()
    original = worker.heartbeat
    entered = threading.Event()
    def slow_heartbeat(*args):
        entered.set()
        time.sleep(.15)
        return original(*args)
    class FastRunner:
        def __init__(self, *args):
            self.cfg = target["configuration"]
            self.gate = asyncio.Event()
        async def run(self):
            while not entered.is_set():
                await asyncio.sleep(.001)
            await asyncio.sleep(.06)
    monkeypatch.setattr(worker, "heartbeat", slow_heartbeat)
    monkeypatch.setattr(worker, "Runner", FastRunner)
    ticks = 0
    task = asyncio.create_task(execute(*item))
    while not task.done():
        await asyncio.sleep(.01)
        ticks += 1
    await task
    assert ticks >= 8
    assert client.get(f"/api/jobs/{identifier}").json()["status"] == "completed"



async def test_agent_query_artifact_verifies_selected_scope(client, target, monkeypatch):
    from app.config import settings
    from app.agent.runner import AgentRunner
    monkeypatch.setattr(settings(), "ai_provider", "local")
    _, dataset = setup_dataset(client, target)
    response = client.post("/api/agent/tasks", json={"website_id": target["id"], "dataset_id": dataset["id"], "objective": "Export the cheapest one product as JSON."})
    assert response.status_code == 201, response.text
    job_id, token = claim()
    records = []
    for index, price in enumerate(["$100", "$9", "$20"]):
        value = normalized(name=f"item{index}", price=price)
        value["data"]["product_url"] += str(index)
        value["identity"] += str(index)
        records.append(value)
    save_page(job_id, token, "https://example.org/catalog", records)
    runner = AgentRunner(job_id, token)
    for node in runner.memory["planning"]["plan"]["subtasks"]:
        if node["kind"] not in {"export", "verify"}:
            node["status"] = "completed"
    await runner.export_dataset()
    result = runner.artifact_verification_context()
    assert result["rows"] == 1
    assert result["records"][0]["price"] == "9"


@pytest.mark.parametrize("message,expected", [("Navigation failed", "navigation"), ("Provider throttling: quota", "provider_throttling"), ("Extraction required fields missing", "extraction")])
async def test_worker_failure_diagnostics(client, target, monkeypatch, message, expected):
    from app import worker
    identifier = client.post("/api/jobs", json={"website_id": target["id"]}).json()["id"]
    class FailedRunner:
        def __init__(self, *args):
            self.cfg = target["configuration"]
            self.gate = asyncio.Event()
        async def run(self):
            raise RuntimeError(message)
    monkeypatch.setattr(worker, "Runner", FailedRunner)
    await execute(*claim())
    result = client.get(f"/api/jobs/{identifier}").json()
    assert result["status"] == "failed"
    assert result["failure"]["category"] == expected
    assert result["failure"]["suggested_recovery"]



def test_query_compiler_does_not_reverse_negative_or_conditional_instructions():
    from app.extraction.query import resolve_query
    from test_extraction import definition
    for objective in ("Do not export the cheapest ten products", "Exclude the cheapest ten products", "If approved, export the cheapest ten products", "Export the cheapest ten products except refurbished items"):
        assert resolve_query(objective, definition()) is None
    assert resolve_query("Export the cheapest ten products as CSV.", definition())["limit"] == 10



@pytest.mark.parametrize("mode", ["requests", "tokens"])
async def test_denied_provider_admission_does_not_count_model_calls(monkeypatch, mode):
    from app.config import settings
    from app.agent.model import ModelClient, ModelQuotaExceeded
    from app.provider_quota import identity
    from pydantic import BaseModel
    cfg = settings()
    monkeypatch.setattr(cfg, "ai_provider", "local")
    monkeypatch.setattr(cfg, "ai_base_url", "http://127.0.0.1:9999/v1")
    monkeypatch.setattr(cfg, "ai_model", "test-model")
    monkeypatch.setattr(cfg, "ai_fallback_provider", "disabled")
    monkeypatch.setattr(cfg, "ai_provider_rpm", 1 if mode == "requests" else 0)
    monkeypatch.setattr(cfg, "ai_provider_tpm", 1 if mode == "tokens" else 0)
    if mode == "requests":
        reserve(identity(cfg.ai_base_url, cfg.ai_api_key.get_secret_value()), 1, 1, 0)
    class Reply(BaseModel):
        status: str
    calls = []
    with pytest.raises(ModelQuotaExceeded):
        await ModelClient().request("decide", {"objective": "Test admission"}, Reply, lambda *args: calls.append(args))
    assert calls == []



def test_workflow_diagnostic_uses_last_completed_checkpoint(client, target):
    from app.failures import diagnose
    identifier = client.post("/api/jobs", json={"website_id": target["id"]}).json()["id"]
    with transaction() as session:
        job = session.get(Job, identifier)
        job.job_type = "workflow"
        job.snapshot = {**job.snapshot, "workflow": {"steps": [{"action": "OPEN_URL"}, {"action": "SCROLL"}, {"action": "CLICK"}]}}
        job.action_index = 2
        value = diagnose(session, job, "Navigation failed")
        assert value["last_successful_action"] == {"action": "SCROLL", "step": 2}
        assert value["retry_eligible"] is False
