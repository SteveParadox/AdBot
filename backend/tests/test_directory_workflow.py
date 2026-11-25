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
from testsupport.directory_fixture import CONVERSATION_DESCRIPTION, EXPECTED, RECORD_COUNT, router

fixture.app.include_router(router)


@pytest.mark.browser
@pytest.mark.parametrize("case,steps,completed", [
    ("normal", 20, True), ("cycle", 20, False), ("normal", 3, False), ("recovery", 20, True), ("rankings", 20, True),
])
async def test_directory_workflow(client, target, fixture_server, monkeypatch, case, steps, completed):  # noqa: F811
    from app.agent.model import ModelClient

    cfg = settings()
    monkeypatch.setattr(cfg, "ai_provider", "disabled")
    calls = []

    async def unavailable(*args, **kwargs):
        calls.append(True)
        pytest.fail("Directory navigation, collection and verification must work without a provider")

    monkeypatch.setattr(ModelClient, "request", unavailable)
    data = {key: target[key] for key in ("name", "base_url", "allowed_domains", "configuration")}
    url = "http://127.0.0.1:8765/execution-fixture"
    if case == "cycle":
        url += "/tools?case=cycle"
    elif case == "recovery":
        url += "/recovery"
    elif case == "rankings":
        url += "/rankings"
    data.update(base_url=url, authorized=True)
    data["configuration"] = {**data["configuration"], "delay_seconds": 0.1, "max_pages": 20,
                             "max_duration_seconds": 180, "screenshots": False}
    assert client.patch("/api/websites/" + target["id"], json=data).status_code == 200
    response = client.post("/api/agent/tasks", json={
        "website_id": target["id"], "objective": "Give me a comprehensive list of conversational AI platforms.", "max_steps": steps,
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
        if case == "rankings":
            first = min(trace, key=lambda step: step.number)
            assert first.observation["directory"]["kind"] == "rankings"
            assert first.decision["url"].endswith("/execution-fixture/tools")
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
        assert answer["directory"]["repeated_pages"] >= 1
        assert answer["directory"]["unique_records"] < RECORD_COUNT
    else:
        assert "step budget" in answer["verification"]["explanation"]
    if case == "recovery":
        assert answer["directory"]["repeated_pages"] >= 1
        assert answer["directory"]["recovery_actions"] >= 1
    print("DIRECTORY_RECEIPT " + json.dumps({"case": case, "seconds": round(elapsed, 2), "verified": completed,
        "max_observation_characters": max_observation, "unique_records": answer["directory"]["unique_records"],
        "matched_records": len(names), "evidence": len(ids), "model_calls": 0, "tokens": 0, "phase_ms": dict(phase_ms)}), flush=True)


@pytest.mark.browser
@pytest.mark.parametrize("kind,objective", [
    ("semantic", "List all AI chatbots."),
    ("semantic", "Give me a comprehensive list of language tutors."),
    ("table", "Extract all rows from the table."),
])
async def test_unlandmarked_extraction(client, target, fixture_server, monkeypatch, kind, objective):  # noqa: F811
    from app.agent.classification import AssessmentBatch
    from app.agent.model import ModelClient
    from app.agent.routing import RouteAssessment

    inferred = "language tutors" in objective
    monkeypatch.setattr(settings(), "ai_provider", "local" if kind == "semantic" else "disabled")
    monkeypatch.setattr(settings(), "ai_model", "fixture-classifier")
    calls = []

    async def assess(self, request_kind, payload, *args, **kwargs):
        calls.append(request_kind)
        if request_kind == "route":
            assert inferred and payload["objective"] == objective
            return RouteAssessment(exhaustive_inventory=True, entity_phrase="language tutors")
        assert request_kind == "classify" and len(payload["records"]) == 2
        return AssessmentBatch(records=[
            {"id": row["id"], "classification": "match" if row["name"] == "Ask" else "excluded",
             "evidence": 1}
            for row in payload["records"]
        ])

    monkeypatch.setattr(ModelClient, "request", assess)
    patch = client.patch("/api/websites/" + target["id"], json={
        "name": target["name"], "allowed_domains": target["allowed_domains"],
        "base_url": f"http://127.0.0.1:8765/execution-fixture/{kind}", "authorized": True,
        "configuration": {**target["configuration"], "delay_seconds": 0.1, "screenshots": False},
    })
    assert patch.status_code == 200, patch.text
    response = client.post("/api/agent/tasks", json={
        "website_id": target["id"], "objective": objective, "max_steps": 5,
        "max_tokens": 2000, "mode": "supervised", "memory_enabled": False,
    })
    assert response.status_code == 201, response.text
    identifier = response.json()["id"]
    item = claim()
    assert item[0] == identifier
    await execute(*item)
    task = client.get("/api/agent/tasks/" + identifier).json()
    assert task["status"] == "completed", task.get("error_message")
    answer = task["result"]
    assert answer["verification"]["complete"]
    if kind == "semantic":
        assert calls == (["route", "classify"] if inferred else ["classify"])
        assert [claim["text"] for claim in answer["claims"]] == ["Ask"]
        assert [evidence["classification_quote"] for evidence in answer["evidence"]] == [CONVERSATION_DESCRIPTION]
    else:
        assert calls == []
        assert answer["strategy"] == "table_extraction"
        assert [row["headers"] for row in answer["directory"]["records"]] == [["Day", "Time"], ["Day", "Time"]]
        assert [row["cells"] for row in answer["directory"]["records"]] == [["Monday", "09:00"], ["Tuesday", "11:00"]]


@pytest.mark.browser
async def test_directory_snapshot_cache_invalidates_on_document_mutation(monkeypatch):
    from types import SimpleNamespace

    from playwright.async_api import async_playwright

    from app.agent import semantic_observer

    monkeypatch.setattr(semantic_observer, "time", SimpleNamespace(monotonic=lambda: 1, perf_counter=time.perf_counter))
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()
            await page.set_content("<p>2 products</p><div><div><a href='https://example.test/a'>One</a>"
                                   "<p>The first directory entry describes a useful product.</p></div>"
                                   "<div><a href='https://example.test/b'>Two</a>"
                                   "<p>The second directory entry describes another product.</p></div></div>")
            observer = semantic_observer.Observer()
            first = await observer.observe(page, "t1", directory=True)
            cached = await observer.observe(page, "t1", directory=True)
            assert not first["observation_metrics"]["collection_cache_hit"]
            assert cached["observation_metrics"]["collection_cache_hit"]
            assert cached["directory"] == first["directory"]
            assert len(cached["directory"]["rows"]) == 2
            await page.locator("a").first.evaluate("(element) => element.textContent = 'Updated'")
            changed = await observer.observe(page, "t1", directory=True)
            assert not changed["observation_metrics"]["collection_cache_hit"]
            assert changed["directory"]["rows"][0]["name"] == "Updated"
        finally:
            await browser.close()
