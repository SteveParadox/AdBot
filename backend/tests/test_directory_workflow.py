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
from conftest import OTHER_AUTH
from test_browser import fixture_server  # noqa: F401
from testsupport.directory_fixture import CONVERSATION_DESCRIPTION, EXPECTED, RECORD_COUNT, router

fixture.app.include_router(router)


@pytest.mark.browser
@pytest.mark.parametrize("case,steps,completed", [
    ("normal", 20, True), ("cycle", 20, False), ("normal", 3, False), ("recovery", 20, True), ("rankings", 20, True),
    ("reload", 20, True),
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
    elif case in {"recovery", "rankings", "reload"}:
        url += f"/{case}"
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
        if case == "reload":
            assert sum(step.decision.get("reason", "").startswith("Reload the observed catalog") for step in trace) == 1
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
    if case in {"recovery", "reload"}:
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
        "base_url": f"http://127.0.0.1:8765/execution-fixture/{'tutors' if inferred else kind}", "authorized": True,
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
@pytest.mark.parametrize("misleading", [False, True])
async def test_prompt_inventory_verifies_source_and_match_evidence(client, target, fixture_server, monkeypatch, misleading):  # noqa: F811
    from app.agent.classification import AssessmentBatch
    from app.agent.model import ModelClient

    monkeypatch.setattr(settings(), "ai_provider", "local")
    classified = []

    async def assess(self, kind, payload, *args, **kwargs):
        assert kind == "classify" and payload["record_types"] == ["prompts"] and payload["topic"] == "business"
        rows = payload["records"]
        classified.extend(row["name"] for row in rows)
        return AssessmentBatch(records=[
            {"id": row["id"], "evidence": 1,
             "classification": "match" if misleading or row["name"] == "Proposal Writer" else "excluded"}
            for row in rows
        ])

    monkeypatch.setattr(ModelClient, "request", assess)
    site = {key: target[key] for key in ("name", "allowed_domains", "configuration")}
    site.update(base_url="http://127.0.0.1:8765/execution-fixture/prompt-hub", authorized=True)
    site["configuration"].update(screenshots=False, max_duration_seconds=60)
    assert client.patch("/api/websites/" + target["id"], json=site).status_code == 200
    response = client.post("/api/agent/tasks", json={
        "website_id": target["id"], "objective": "List all business prompts.", "max_steps": 5,
    })
    identifier = response.json()["id"]
    await execute(*claim())
    task = client.get(f"/api/agent/tasks/{identifier}").json()
    assert task["status"] == ("failed" if misleading else "completed"), task.get("error_message")
    assert task["execution"]["entity"] == "semantic:business prompts"
    assert task["execution"]["collection_kind"] == "prompts"
    assert task["planning"]["route"] == task["execution"]["strategy"] == "directory_collection"
    assert task["result"]["directory"]["unique_records"] == 3
    assert set(classified) == {"Explore the Sky"}
    assert [claim["text"] for claim in task["result"]["claims"]] == ["Proposal Writer"]
    dimensions = task["result"]["verification"]["dimensions"]
    assert dimensions["source_relevance"] and dimensions["directory_coverage"] and dimensions["extraction_complete"]
    assert dimensions["entity_correctness"] is (not misleading)
    assert dimensions["objective_satisfied"] is (not misleading)
    steps = client.get(f"/api/agent/tasks/{identifier}/steps").json()["items"]
    assert steps[0]["observation"]["directory"]["kind"] == "products"
    assert steps[0]["decision"]["url"].endswith("/prompt-catalog")
    assert steps[-1]["decision"]["decision"] == "VERIFY_COLLECTION"
    assert all(span["duration_ms"] >= 0 for span in steps[-1]["outcome"]["trace"])
    assert task["memory"]["planning"]["last_observation"]["step"] == steps[-1]["number"]


@pytest.mark.browser
async def test_filtered_source_has_a_durable_unverified_result(client, target, fixture_server, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings(), "ai_provider", "disabled")
    site = {key: target[key] for key in ("name", "allowed_domains", "configuration")}
    site.update(base_url="http://127.0.0.1:8765/execution-fixture/prompt-catalog?category=sales", authorized=True)
    site["configuration"].update(screenshots=False, max_duration_seconds=60)
    assert client.patch("/api/websites/" + target["id"], json=site).status_code == 200
    response = client.post("/api/agent/tasks", json={
        "website_id": target["id"], "objective": "List all business prompts.", "max_steps": 5,
    })
    identifier = response.json()["id"]
    await execute(*claim())
    saved = client.get(f"/api/agent/tasks/{identifier}").json()
    assert saved["status"] == "failed" and saved["model_calls"] == 0
    result = saved["result"]
    assert result["partial"] and result["directory"]["unique_records"] == 0
    assert not any(result["verification"]["dimensions"].values())
    assert "filtered" in result["verification"]["explanation"]


@pytest.mark.browser
@pytest.mark.parametrize("capture_available", [True, False])
async def test_in_place_pagination_reports_content_and_saves_final_preview(
    client, target, fixture_server, monkeypatch, capture_available,  # noqa: F811
):
    from app.agent.runner import AgentRunner

    monkeypatch.setattr(settings(), "ai_provider", "disabled")
    if not capture_available:
        async def unavailable(self, page):
            raise OSError("Fixture capture unavailable")

        monkeypatch.setattr(AgentRunner, "screenshot", unavailable)
    site = {key: target[key] for key in ("name", "allowed_domains", "configuration")}
    site.update(base_url="http://127.0.0.1:8765/execution-fixture/in-place", authorized=True)
    site["configuration"].update(screenshots=False, max_duration_seconds=60)
    assert client.patch("/api/websites/" + target["id"], json=site).status_code == 200
    response = client.post("/api/agent/tasks", json={
        "website_id": target["id"], "objective": "List all AI chatbots.", "max_steps": 5,
    })
    assert response.status_code == 201, response.text
    identifier = response.json()["id"]
    await execute(*claim())

    task = client.get("/api/agent/tasks/" + identifier).json()
    assert task["status"] == "completed", task.get("error_message")
    assert task["model_calls"] == task["prompt_tokens"] == task["completion_tokens"] == 0
    assert {row["text"] for row in task["result"]["claims"]} == {"First chatbot", "Second chatbot"}
    steps = client.get(f"/api/agent/tasks/{identifier}/steps").json()["items"]
    page_turn = next(step for step in steps if step["decision"].get("decision") == "CLICK")
    assert page_turn["outcome"]["url_changed"] is False
    assert page_turn["outcome"]["content_changed"] is True
    assert page_turn["outcome"]["page_changed"] is True
    logs = client.get(f"/api/jobs/{identifier}/logs").json()["items"]
    event = next(event for event in logs if event["event_type"] == "agent_action_completed")
    assert event["details"]["url_changed"] is False and event["details"]["content_changed"] is True
    captures = [step["observation"]["screenshot_path"] for step in steps if step["observation"]["screenshot_path"]]
    if capture_available:
        assert captures == [steps[-1]["observation"]["screenshot_path"]]
        preview = client.get("/api/artifacts/" + captures[0])
        assert preview.status_code == 200 and preview.content.startswith(b"\x89PNG")
        assert client.get("/api/artifacts/" + captures[0], headers=OTHER_AUTH).status_code == 404
        assert any(event["event_type"] == "agent_preview_captured" for event in logs)
    else:
        assert captures == []


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
