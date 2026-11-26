import json
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
    if fixture_page in {"first", "long", "conflict"}:
        noise = "".join(f"<p>Unrelated archived informational paragraph number {i} contains general announcements.</p>"
                        for i in range(300)) if fixture_page == "long" else ""
        return (
            f'<article>{noise}<h1>North Station</h1><section><p>North Station operates weekday departures '
            'every fifteen minutes from the central concourse.</p></section></article>'
            f'<nav><a href="/research-proof/{ {"long": "dynamic", "conflict": "contradiction"}.get(fixture_page, "second")}">South Station</a>'
            '<a href="/research-proof/empty">Other listing</a></nav>'
        )
    if fixture_page == "dynamic":
        rendered = "<h2>South Station weekday departures</h2><table><tr><td>Weekday departures</td><td>30 min</td></tr></table>"
        return f'<main></main><script>document.querySelector("main").innerHTML = {json.dumps(rendered)}</script>'
    if fixture_page == "contradiction":
        return ("<main><p>North Station operates weekday departures every sixty minutes from the central concourse.</p>"
                "<p>South Station schedules weekday departures every thirty minutes from the east wing.</p></main>")
    content = (
        '<div role="main"><h2>South Station</h2><dl><dt>Weekday departures</dt><dd>'
        'South Station schedules weekday departures every thirty minutes from its east wing.'
        '</dd></dl><p>South Station preserves several century-old heritage photographs in its waiting room.</p>'
        '</div>' if fixture_page == "second" else
        '<p>Browse the directory to find weekday departures and other general transport information.</p>'
    )
    return content + '<nav><a href="/research-proof/first#top">North Station</a></nav>'


@pytest.mark.browser
@pytest.mark.parametrize("first,incomplete", [("first", False), ("first", True), ("long", False), ("conflict", False)])
async def test_research_captures_sources_before_deciding_and_verifies_coverage(client, target, fixture_server, monkeypatch, first, incomplete):  # noqa: F811
    monkeypatch.setattr(settings(), "ai_provider", "local")
    decisions = 0
    conflict = first == "conflict"
    objective = "Compare North Station and South Station on weekday departures"
    registration = {key: target[key] for key in ("name", "allowed_domains", "configuration")}
    registration.update(base_url=f"http://127.0.0.1:8765/research-proof/{first}", authorized=True)
    registration["configuration"].update(screenshots=False, max_duration_seconds=120)
    assert client.patch("/api/websites/" + target["id"], json=registration).status_code == 200
    scope = {"website_id": target["id"], "objective": objective, "max_steps": 5}
    job = client.post("/api/agent/tasks", json=scope).json()["id"]

    async def assess(self, kind, payload, schema, *_args, **_kwargs):
        nonlocal decisions
        if kind == "plan":
            return schema.model_validate(payload["seed_plan"])
        if kind == "verify":
            if first == "first" and not incomplete:
                assert any("heritage" in row["quote"] for row in payload["evidence"])
            observed = [row for row in payload["evidence"] if "heritage" not in row["quote"]]
            if first == "long":
                assert any("30 min" in row["quote"] and row["url"].endswith("/dynamic") for row in observed)
            if conflict:
                assert any("sixty minutes" in row["quote"] for row in observed)
                assert "disagree" in payload["instructions"]
            checks = []
            for criterion in payload["success_criteria"]:
                cited = [row["id"] for row in observed if any(entity in criterion for entity in row["entities"])]
                if criterion == "Compare the requested subjects on weekday departures":
                    cited = [row["id"] for row in observed] if len(observed) == 2 else []
                met = bool(cited) and (not incomplete or "for North Station" in criterion)
                if conflict and not criterion.startswith("Source evidence"):
                    met = False
                checks.append({"criterion": criterion, "met": met, "evidence_ids": cited if met else []})
            return Verification(complete=not incomplete and not conflict, explanation="Reviewed source coverage", checks=checks)
        assert kind == "decide"
        decisions += 1
        saved = client.get(f"/api/agent/tasks/{job}").json()
        observed = saved["memory"]["evidence"]
        assert observed and all(row["id"].startswith("dom-") for row in observed)
        if decisions == 1:
            assert saved["planning"]["plan"]["subtasks"][0]["status"] != "completed"
            assert any("fifteen minutes" in row["quote"] and row["url"].endswith(first) for row in observed)
        defaults = {"observation": "Read the rendered source", "reason": "Compare observed service",
                    "confidence": 1, "expected_result": "Verify both departure schedules"}
        if decisions <= 1 or (incomplete and decisions == 2):
            destination = "/empty" if incomplete else "/" + {"long": "dynamic", "conflict": "contradiction"}.get(first, "second")
            ending = destination if decisions == 1 else "/first#top"
            if decisions == 1:
                href = next(e["href"] for e in payload["current_page"]["elements"] if (e.get("href") or "").endswith(ending))
            else:
                assert not any((e.get("href") or "").endswith(ending) for e in payload["current_page"]["elements"])
                href = "http://127.0.0.1:8765/research-proof" + ending
            return Decision(decision="NAVIGATE", url=href, **defaults)
        if incomplete or conflict:
            return Decision(decision="FAIL", text="South Station is unavailable", **defaults)
        return Decision(decision="COMPLETE", claims=[{"text": "North has more frequent weekday departures.",
                                                       "evidence_ids": [row["id"] for row in observed]}], **defaults)

    monkeypatch.setattr(ModelClient, "request", assess)
    started = time.monotonic()
    await execute(*claim())
    result = client.get(f"/api/agent/tasks/{job}").json()
    assert result["status"] == ("failed" if incomplete or conflict else "completed"), result.get("error_message")
    assert len(result["memory"]["evidence"]) == (1 if incomplete else 2 if first == "long" else 3)
    assert result["result"]["verification"]["complete"] is (not incomplete and not conflict)
    if incomplete:
        assert result["result"]["partial"]
        assert any("South Station" in item for item in result["result"]["verification"]["missing_criteria"])
        assert len(result["result"]["claims"]) == 1
        steps = client.get(f"/api/agent/tasks/{job}/steps").json()["items"]
        assert any("already observed" in item["outcome"].get("error", "") for item in steps)
    elif conflict:
        assert objective in result["result"]["verification"]["missing_criteria"]
        assert result["result"]["partial"]
    else:
        assert decisions == 1
        assert set(result["memory"]["research_coverage"]["entities"]) == {"North Station", "South Station"}
        published = {identifier for row in result["result"]["claims"] for identifier in row["evidence_ids"]}
        assert all(set(node["evidence_ids"]) <= published for node in result["planning"]["plan"]["subtasks"])
    print(f"research fixture partial={incomplete} elapsed={time.monotonic() - started:.2f}s decisions={decisions}")



def test_recommendation_relevance_ignores_generic_tool_overlap():
    from app.agent.research import topical_match, capture_evidence, coverage

    objective = "what are best tools for Content creation"
    irrelevant = "Best AI Coding Tools for Developers"
    relevant = "Research-driven content generation tools assist writers."
    assert not topical_match(objective, irrelevant)
    assert topical_match(objective, relevant)
    assert topical_match(objective, "Perplexity supports research-driven content production.")
    store = []
    observation = {"url": "https://example.test/", "research_chunks": [
        {"quote": irrelevant, "entities": [], "heading": "Rankings"},
        {"quote": relevant, "entities": [], "heading": "Writing"},
    ]}
    assert capture_evidence(observation, store, 1, [], [objective]) == 1
    assert coverage(store, [], [objective])["criteria"][objective] == [store[0]["id"]]


def test_literal_citation_repair_and_paraphrase_requires_independent_check():
    from app.agent.contracts import Claim
    from app.agent.research import repair_exact_citations, claim_verification_criteria, verification_failures

    text = "Atlas creates images from text descriptions."
    evidence = {"a": {"quote": text}, "b": {"quote": "Generic software market commentary."}}
    claims = [Claim(text=text, evidence_ids=["b"]),
              Claim(text="Atlas generates pictures from prompts.", evidence_ids=["b"])]
    repair_exact_citations(claims, evidence)
    assert claims[0].evidence_ids == ["a"]
    assert claims[1].evidence_ids == ["b"]
    required = claim_verification_criteria(claims, evidence)
    criterion = next(iter(required))
    assert required[criterion] == {"b"}
    verdict = Verification(complete=True, explanation="Supported", checks=[
        {"criterion": criterion, "met": True, "evidence_ids": ["a"]},
    ])
    assert any("citation mismatch" in issue for issue in verification_failures(verdict, [criterion], set(evidence), required))
    assert verification_failures(verdict, ["Different criterion"], set(evidence), {})


def test_completion_retry_fingerprint_changes_when_citations_change():
    from app.agent.memory import action_key

    before = {"decision": "COMPLETE", "claims": [{"text": "A fact", "evidence_ids": ["wrong"]}]}
    after = {"decision": "COMPLETE", "claims": [{"text": "A fact", "evidence_ids": ["right"]}]}
    assert action_key(before) != action_key(after)



async def test_duplicate_research_extraction_returns_existing_evidence():
    from app.agent.runner import AgentRunner

    runner = object.__new__(AgentRunner)
    quote = "Atlas generates illustrations from text."
    url = "https://example.test/tools"
    runner.memory = {"evidence": [{"id": "dom-original", "url": url, "quote": quote, "step_id": 1}]}
    decision = Decision(observation="Read the source", reason="Reuse observed evidence",
                        decision="EXTRACT", text=quote, confidence=1, expected_result="Existing evidence")
    outcome = await runner.extract(decision, {"url": url, "text": quote}, 2)
    assert outcome["already_collected"] is True
    assert outcome["id"] == "dom-original"
    assert len(runner.memory["evidence"]) == 1
