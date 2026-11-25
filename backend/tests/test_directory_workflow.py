import json
import time
from collections import Counter

import pytest
from sqlalchemy import select

from app import fixture
from app.config import settings
from app.db import AgentStep, transaction
from app.jobs import claim
from app.worker import execute
from test_browser import fixture_server  # noqa: F401
from testsupport.directory_fixture import EXPECTED, RECORD_COUNT, router

fixture.app.include_router(router)


@pytest.mark.browser
@pytest.mark.parametrize("case,steps,completed", [("normal", 20, True), ("cycle", 20, False), ("normal", 3, False)])
async def test_directory_workflow(client, target, fixture_server, monkeypatch, case, steps, completed):  # noqa: F811
    from app.agent.model import ModelClient

    cfg = settings()
    monkeypatch.setattr(cfg, "ai_provider", "local")
    monkeypatch.setattr(cfg, "ai_model", "unavailable-fixture-provider")
    calls = []

    async def unavailable(*args, **kwargs):
        calls.append(True)
        pytest.fail("Directory navigation, collection and verification must work without a provider")

    monkeypatch.setattr(ModelClient, "request", unavailable)
    data = {key: target[key] for key in ("name", "base_url", "allowed_domains", "configuration")}
    url = "http://127.0.0.1:8765/execution-fixture"
    if case == "cycle":
        url += "/tools?case=cycle"
    data.update(base_url=url, authorized=True)
    data["configuration"] = {**data["configuration"], "delay_seconds": 0.1, "max_pages": 20,
                             "max_duration_seconds": 180, "screenshots": False}
    assert client.patch("/api/websites/" + target["id"], json=data).status_code == 200
    response = client.post("/api/agent/tasks", json={
        "website_id": target["id"], "objective": "List all AI chatbots.", "max_steps": steps,
        "max_tokens": 2000, "mode": "supervised", "memory_enabled": False,
    })
    assert response.status_code == 201, response.text
    identifier = response.json()["id"]
    item = claim()
    assert item[0] == identifier
    started = time.monotonic()
    await execute(*item)
    elapsed = time.monotonic() - started
    result = client.get("/api/agent/tasks/" + identifier).json()
    assert result["status"] == ("completed" if completed else "failed"), result.get("error_message")
    assert calls == [] and result["model_calls"] == 0
    assert result["prompt_tokens"] == result["completion_tokens"] == 0
    answer = result["result"]
    assert answer["verification"]["complete"] is completed
    assert answer["partial"] is not completed
    names = {claim["text"] for claim in answer["claims"]}
    assert names <= EXPECTED and len(names) == len(answer["claims"])
    ids = {e["id"] for e in answer["evidence"]}
    assert ids == {key for claim in answer["claims"] for key in claim["evidence_ids"]}
    assert all(e["source_url"].startswith("http://127.0.0.1:8765/execution-fixture/tool/") for e in answer["evidence"])
    with transaction() as session:
        trace = session.scalars(select(AgentStep).where(AgentStep.job_id == identifier)).all()
        assert all(step.observation["observation_metrics"]["included"] <= 24 for step in trace)
        assert not any("All tags" in step.decision.get("reason", "") for step in trace)
        max_observation = max(step.observation["observation_metrics"]["characters"] for step in trace)
        phase_ms = Counter()
        for step in trace:
            for event in step.outcome.get("trace", []):
                phase_ms[event["phase"]] += event.get("duration_ms", 0)
    if completed:
        assert names == EXPECTED
        assert answer["directory"]["unique_records"] == RECORD_COUNT
        assert answer["directory"]["unknown"] == 0 and answer["directory"]["pages"] == 8
    elif case == "cycle":
        assert answer["directory"]["repeated_pages"] == 1
    else:
        assert "step budget" in answer["verification"]["explanation"]
    print("DIRECTORY_RECEIPT " + json.dumps({"case": case, "seconds": round(elapsed, 2), "verified": completed,
        "max_observation_characters": max_observation, "unique_records": answer["directory"]["unique_records"],
        "matched_records": len(names), "evidence": len(ids), "model_calls": 0, "tokens": 0, "phase_ms": dict(phase_ms)}), flush=True)
