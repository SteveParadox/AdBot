import time

import pytest
from fastapi.responses import HTMLResponse

from app import fixture
from app.agent.contracts import Decision, Verification
from app.agent.model import ModelClient
from app.agent.research import comparison_entities
from app.config import settings
from app.jobs import claim
from app.worker import execute
from test_browser import fixture_server  # noqa: F401


def test_literal_comparison_keeps_three_subjects():
    assert comparison_entities("Compare Cedar, Juniper, and Cypress on warranty and availability.") == [
        "Cedar", "Juniper", "Cypress",
    ]


@fixture.app.get("/research-proof/{fixture_page}", response_class=HTMLResponse)
def research_page(fixture_page: str):
    if fixture_page == "first":
        return (
            '<article><h1>North Station</h1><section><p>North Station operates weekday departures '
            'every fifteen minutes from the central concourse.</p></section></article>'
            '<nav><a href="/research-proof/second">South Station</a>'
            '<a href="/research-proof/empty">Other listing</a></nav>'
        )
    content = (
        '<div role="main"><h2>South Station</h2><dl><dt>Weekday departures</dt><dd>'
        'South Station schedules weekday departures every thirty minutes from its east wing.'
        '</dd></dl></div>' if fixture_page == "second" else
        '<p>Browse the directory to find weekday departures and other general transport information.</p>'
    )
    return content + '<nav><a href="/research-proof/first#top">North Station</a></nav>'


@pytest.mark.browser
@pytest.mark.parametrize("incomplete", [False, True])
async def test_research_captures_sources_before_deciding_and_verifies_coverage(client, target, fixture_server, monkeypatch, incomplete):  # noqa: F811
    monkeypatch.setattr(settings(), "ai_provider", "local")
    decisions = 0
    objective = "Compare North Station and South Station on weekday departures"
    registration = {key: target[key] for key in ("name", "allowed_domains", "configuration")}
    registration.update(base_url="http://127.0.0.1:8765/research-proof/first", authorized=True)
    registration["configuration"].update(screenshots=False, max_duration_seconds=120)
    assert client.patch("/api/websites/" + target["id"], json=registration).status_code == 200
    scope = {"website_id": target["id"], "objective": objective, "max_steps": 5}
    job = client.post("/api/agent/tasks", json=scope).json()["id"]

    async def assess(self, kind, payload, schema, *_args, **_kwargs):
        nonlocal decisions
        if kind == "plan":
            return schema.model_validate(payload["seed_plan"])
        if kind == "verify":
            observed = payload["evidence"]
            checks = []
            for criterion in payload["success_criteria"]:
                cited = [row["id"] for row in observed if any(entity in criterion for entity in row["entities"])]
                if criterion == "Compare the requested subjects on weekday departures":
                    cited = [row["id"] for row in observed] if len(observed) == 2 else []
                met = bool(cited) and (not incomplete or "for North Station" in criterion)
                checks.append({"criterion": criterion, "met": met, "evidence_ids": cited if met else []})
            return Verification(complete=not incomplete, explanation="Reviewed source coverage", checks=checks)
        assert kind == "decide"
        decisions += 1
        saved = client.get(f"/api/agent/tasks/{job}").json()
        observed = saved["memory"]["evidence"]
        assert observed and all(row["id"].startswith("dom-") for row in observed)
        defaults = {"observation": "Read the rendered source", "reason": "Compare observed service",
                    "confidence": 1, "expected_result": "Verify both departure schedules"}
        if decisions <= 1 or (incomplete and decisions == 2):
            ending = ("/empty" if incomplete else "/second") if decisions == 1 else "/first#top"
            if decisions == 1:
                href = next(e["href"] for e in payload["current_page"]["elements"] if (e.get("href") or "").endswith(ending))
            else:
                assert not any((e.get("href") or "").endswith(ending) for e in payload["current_page"]["elements"])
                href = "http://127.0.0.1:8765/research-proof" + ending
            return Decision(decision="NAVIGATE", url=href, **defaults)
        if incomplete:
            return Decision(decision="FAIL", text="South Station is unavailable", **defaults)
        return Decision(decision="COMPLETE", claims=[{"text": "North has more frequent weekday departures.",
                                                       "evidence_ids": [row["id"] for row in observed]}], **defaults)

    monkeypatch.setattr(ModelClient, "request", assess)
    started = time.monotonic()
    await execute(*claim())
    result = client.get(f"/api/agent/tasks/{job}").json()
    assert result["status"] == ("failed" if incomplete else "completed"), result.get("error_message")
    assert len(result["memory"]["evidence"]) == (1 if incomplete else 2)
    assert result["result"]["verification"]["complete"] is not incomplete
    if incomplete:
        assert result["result"]["partial"]
        assert any("South Station" in item for item in result["result"]["verification"]["missing_criteria"])
        assert len(result["result"]["claims"]) == 1
        steps = client.get(f"/api/agent/tasks/{job}/steps").json()["items"]
        assert any("already observed" in item["outcome"].get("error", "") for item in steps)
    else:
        assert decisions == 1
        assert set(result["memory"]["research_coverage"]["entities"]) == {"North Station", "South Station"}
    print(f"research fixture partial={incomplete} elapsed={time.monotonic() - started:.2f}s decisions={decisions}")
