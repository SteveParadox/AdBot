import json
import os
import time

import pytest
from fastapi import Request
from fastapi.responses import HTMLResponse

from app.agent.contracts import Decision, Verification
from app.agent.discovery import objective_query, task_token_allowance
from app.agent.model import ModelBudgetExceeded, ModelContextExceeded
from app.agent.planning import evaluate, initial_plan, needs_model_plan, specification
from app.agent.research import comparison_coverage, comparison_dimensions, comparison_entities
from app.agent.routing import select_route
from app.agent.runner import AgentRunner
from app.fixture import app as browser_fixture
from app.jobs import claim
from app.worker import execute
from test_agent import agent_config, agent_servers, new_task, set_url  # noqa: F401
from testsupport.model_fixture import app as model_fixture


@pytest.mark.parametrize("objective", [
    "Tell me about Amber Relay", "What is Amber Relay?", "How does Amber Relay work?",
    "Who developed Amber Relay?", "What are the features of Amber Relay?",
    "Where can I find Amber Relay?", "How much does Amber Relay cost?",
    "Is Amber Relay suitable for recording?",
])
def test_informational_routing(objective):
    assert select_route(objective, {}).name == "informational"
    assert not needs_model_plan(specification(objective, [objective], {}, []))
    assert objective_query(objective) == "Amber Relay"


def test_search_permission_and_complexity_are_independent():
    options = {"mode": "autonomous", "allow_search_input": True, "allow_form_input": False}
    assert specification("Amber Relay", [], options, [])["permissions"]["read_search"]
    assert not specification("Amber Relay", ["Never use site search"], options, [])["permissions"]["read_search"]
    spec = specification("Tell me about Amber Relay using independent sources", [], options, [])
    assert needs_model_plan(spec)


async def test_comparison_uses_previously_observed_subject_link_for_missing_dimension():
    objective = "Compare Cedar and Cypress across warranty and battery life"
    assert comparison_entities(objective) == ["Cedar", "Cypress"]
    assert comparison_dimensions(objective) == ["warranty", "battery life"]
    evidence = [
        {"id": "a", "quote": "Cedar has a two-year warranty and a battery life of 10 hours."},
        {"id": "b", "quote": "Cypress has a one-year warranty."},
    ]
    assert comparison_coverage(evidence, ["Cedar", "Cypress"], ["warranty", "battery life"]) == {
        "Cedar": {"warranty": ["a"], "battery life": ["a"]},
        "Cypress": {"warranty": ["b"], "battery life": []},
    }
    runner = object.__new__(AgentRunner)
    runner.comparison_mode = True
    runner.recommendation_mode = False
    runner.objective = objective
    runner.options = {"success_criteria": [objective]}
    runner.memory = {"evidence": evidence, "visited_urls": [], "planning": initial_plan(
        specification(objective, [objective], runner.options, ["example.test"])
    ), "comparison_links": {"https://example.test/support/device-45": "Cypress battery life"}}

    class FixturePolicy:
        def check(self, url):
            assert url.startswith("https://example.test/")
            return url

    runner.policy = FixturePolicy()
    action = await runner.research_decision({"url": "https://example.test/comparison", "elements": []})
    assert action.decision == "NAVIGATE" and action.url.endswith("/device-45")


async def test_comprehensive_single_source_can_synthesize_a_scoped_comparison():
    objective = "Compare Cedar and Cypress on warranty"
    url = "https://example.test/comparison"
    runner = object.__new__(AgentRunner)
    runner.comparison_mode = True
    runner.recommendation_mode = False
    runner.objective = objective
    runner.options = {"success_criteria": [objective]}
    runner.memory = {"evidence": [
        {"id": "cedar", "url": url, "quote": "Cedar includes a two-year warranty."},
        {"id": "cypress", "url": url, "quote": "Cypress includes a one-year warranty."},
        {"id": "other", "url": url, "quote": "Juniper includes a three-year warranty."},
    ], "planning": initial_plan(specification(objective, [objective], runner.options, ["example.test"]))}

    async def ask(kind, payload, schema):
        assert kind == "synthesize"
        assert {row["id"] for row in payload["evidence"]} == {"cedar", "cypress"}
        assert payload["subjects"] == ["Cedar", "Cypress"]
        return schema(claims=[{"text": "Cedar's warranty lasts twice as long as Cypress's.",
                               "evidence_ids": ["cedar", "cypress"]}])

    runner.ask_model = ask
    action = await runner.research_decision({"url": url, "elements": []})
    assert action.decision == "COMPLETE" and "Juniper" not in action.claims[0].text


async def test_recommendation_uses_relevant_observed_destination_without_a_model():
    runner = object.__new__(AgentRunner)
    runner.comparison_mode = False
    runner.recommendation_mode = True
    runner.objective = "Recommend an audio restoration utility"
    runner.options = {"success_criteria": [runner.objective]}
    runner.memory = {"evidence": [], "visited_urls": []}

    class FixturePolicy:
        def check(self, url):
            if not url.startswith("https://example.test/"):
                raise ValueError("URL outside fixture scope")
            return url

    runner.policy = FixturePolicy()
    action = await runner.research_decision({"url": "https://example.test/catalog", "elements": [
        {"role": "link", "actionable": True, "name": "Audio restoration utilities", "href": "https://outside.test/tools"},
        {"role": "link", "actionable": True, "name": "Audio restoration utilities", "href": "https://example.test/audio"},
    ]})
    assert action.decision == "NAVIGATE" and action.url == "https://example.test/audio"


@pytest.mark.parametrize("objective,reason,verified,expected", [
    ("Tell me about Amber Relay", "Task does not authorize form input", True, "completed"),
    ("Tell me about Amber Relay", "Task does not authorize form input", False, "blocked"),
    ("Tell me about Amber Relay", "Review denied", True, "blocked"),
    ("Submit a request for Amber Relay", "Task does not authorize form input", True, "blocked"),
])
def test_reconcile_only_eligible_blocked_collection(objective, reason, verified, expected):
    state = initial_plan(specification(objective, [objective], {}, ["example.test"]))
    state["research_evidence_required"] = True
    research, collect, verify = state["plan"]["subtasks"]
    collect.update(status="blocked", outcome=reason)
    state["plan"]["subtasks"] = [verify, collect, research]
    evaluate(state, {"url": "https://example.test"}, [{"id": "passage"}], verified=verified)
    assert collect["status"] == expected
    assert (verify["status"] == "completed") == (expected == "completed")


@pytest.mark.parametrize("joiner", [" ... ", " ", "\n\n"])
async def test_compound_quote_retains_independent_exact_passages(joiner):
    runner = object.__new__(AgentRunner)
    runner.memory = {"evidence": []}
    first, second = "Amber Relay records local audio.", "Offline storage holds 20 hours."
    page = {"url": "https://example.test", "text": f"{first}\nHeading\n{second}"}
    decision = Decision(decision="EXTRACT", observation="Two sections", reason="Collect exact text",
                        confidence=1, expected_result="Two distinct sources", text="Recording and storage",
                        source_quote=f"{first}{joiner}{second}")
    result = await runner.extract(decision, page, 1)
    assert [row["quote"] for row in result["passages"]] == [first, second]
    assert len(set(result["evidence_ids"])) == 2
    assert (await runner.extract(decision, page, 2))["evidence_ids"] == result["evidence_ids"]
    assert len(runner.memory["evidence"]) == 2


async def test_verification_batches_preserve_all_citations():
    runner = object.__new__(AgentRunner)
    offered = []

    async def ask(_kind, payload, _schema):
        criteria = payload["success_criteria"]
        if len(criteria) > 1:
            raise ModelContextExceeded("Fixture context limit")
        ids = {row["id"] for row in payload["evidence"]}
        offered.append(ids)
        return Verification(complete=True, explanation="Fixture verifier",
                            checks=[{"criterion": criteria[0], "met": True, "evidence_ids": sorted(ids)}])

    runner.ask_model = ask
    result = await runner.verify_research({
        "success_criteria": ["Claim 1: The device records", "Claim 2: The device stores audio"],
        "claims": [{"text": "The device records"}, {"text": "The device stores audio"}],
        "evidence": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
    }, {"Claim 1: The device records": {"a", "b"}, "Claim 2: The device stores audio": {"c"}})
    assert result.complete and offered == [{"a", "b"}, {"c"}]


async def test_oversized_objective_check_preserves_independently_verified_claim():
    runner = object.__new__(AgentRunner)
    objective, claim = "Compare a long set of options", "Claim 1: The relay records audio"

    async def ask(_kind, payload, _schema):
        criteria = payload["success_criteria"]
        if objective in criteria:
            raise ModelContextExceeded("Objective exceeds provider context")
        return Verification(complete=True, explanation="Claim supported",
                            checks=[{"criterion": claim, "met": True, "evidence_ids": ["a"]}])

    runner.ask_model = ask
    result = await runner.verify_research({
        "success_criteria": [objective, claim],
        "claims": [{"text": "The relay records audio"}],
        "evidence": [{"id": "a"}],
    }, {claim: {"a"}})
    assert not result.complete
    assert [check.met for check in result.checks] == [False, True]


async def test_rejected_claims_cannot_publish_or_repeat_verification():
    runner = object.__new__(AgentRunner)
    evidence = {"id": "source", "quote": "Amber Relay records audio.", "url": "https://example.test", "step_id": 1}
    runner.memory = {"evidence": [evidence]}
    runner.snapshot = {}
    runner.options = {}
    runner.controller = None
    runner.objective = "How much does Amber Relay cost?"
    runner.research_mode = True
    runner.research_criteria = lambda: [runner.objective]
    runner.artifact_verification_context = lambda: None
    calls = []

    async def ask(_kind, payload, _schema):
        calls.append(payload)
        return Verification(complete=False, explanation="Source does not specify pricing",
                            checks=[{"criterion": item, "met": False} for item in payload["success_criteria"]])

    async def checkpoint(_controller):
        pass

    runner.ask_model = ask
    runner.checkpoint = checkpoint
    decision = Decision(decision="COMPLETE", observation="Read the product description", reason="Answer",
                        confidence=1, expected_result="Evidence-based price",
                        claims=[{"text": "Amber Relay costs $50.", "evidence_ids": ["source"]}])
    with pytest.raises(ValueError, match="Goal verification incomplete"):
        await runner.complete(decision)
    assert "research_partial" not in runner.memory
    with pytest.raises(ValueError, match="Completion already failed"):
        await runner.complete(decision.model_copy(deep=True))
    assert len(calls) == 1


async def test_exhausted_verification_budget_retains_only_observed_sources():
    runner = object.__new__(AgentRunner)
    runner.memory = {"evidence": [
        {"id": "source", "quote": "Amber Relay records audio.", "url": "https://example.test", "step_id": 1},
    ]}
    runner.controller = None
    runner.deadline = time.time()
    runner.objective = "How much does Amber Relay cost?"
    runner.research_mode = True
    runner.research_criteria = lambda: [runner.objective]

    async def exhausted(*_args):
        raise ModelBudgetExceeded("Final verification cannot fit")

    async def checkpoint(_controller):
        pass

    runner.execute_steps = exhausted
    runner.checkpoint = checkpoint
    with pytest.raises(ModelBudgetExceeded):
        await runner.execute_page(None, None)
    partial = runner.memory["research_partial"]
    assert partial["partial"] and not partial["verification"]["complete"]
    assert not partial["claims"] and partial["evidence"] == runner.memory["evidence"]


def test_finalization_reservation_and_provider_diagnostic():
    from app.agent.model import provider_rejection_category

    def allowance(estimate):
        return task_token_allowance(30000, 4000, fallback_reserve=1000, primary=False,
                                    purpose="decide", finalization_estimate=estimate)

    assert allowance(2000) == (24000, 0, 2000)
    assert allowance(8000) == (18000, 0, 8000)
    assert provider_rejection_category('response_format rejected: "private source text"') == "structured output"
    assert provider_rejection_category("private source text") is None


PASSAGE = "Amber Relay is an offline audio recorder for field interviews and lectures."
OBJECTIVE = "Tell me about Amber Relay"


@browser_fixture.get("/orchestration/{variant}", response_class=HTMLResponse)
def orchestration_page(variant: str, q: str = ""):
    if variant == "source" or q and variant != "alternate":
        return f"<main><h1>Amber Relay</h1><article><p>{PASSAGE}</p></article></main>"
    fallback = '<a href="/orchestration/source">Browse the index</a>'
    if variant in {"native", "alternate"}:
        return f'<form role="search"><input name="q" type="search" aria-label="Search"><button>Search</button></form>{fallback}'
    return f"""<div role="search"><input id="query" type="search" aria-label="Search"></div>
    <main></main>{fallback}
    <script>query.addEventListener('input', async () => {{
      const response = await fetch('/orchestration/source?q=' + encodeURIComponent(query.value));
      document.querySelector('main').innerHTML = await response.text();
    }})</script>"""


@model_fixture.post("/orchestration/v1/chat/completions")
async def orchestration_provider(request: Request):
    body = await request.json()
    raw = body["messages"][-1]["content"]
    payload = json.loads(raw)
    state = payload.get("session_memory", {})
    page = payload.get("current_page", {})
    evidence = payload.get("evidence", state.get("evidence", []))
    ids = [row["id"] for row in evidence if PASSAGE in row["quote"]]
    claims = [{"text": PASSAGE, "evidence_ids": ids[:1]}] if ids else []
    purpose = payload["purpose"]
    if purpose == "synthesize":
        response = {"claims": claims}
    elif purpose == "verify":
        response = {"complete": bool(ids), "explanation": "Fixture checked indexed source",
                    "checks": [{"criterion": criterion, "met": bool(ids), "evidence_ids": ids}
                               for criterion in payload["success_criteria"]]}
    else:
        response = {"observation": "Observed source or search field", "reason": "Find the product description",
                    "confidence": 1, "expected_result": "Exact source evidence"}
        search = next((item for item in page.get("elements", []) if item.get("role") == "searchbox"), None)
        if claims:
            response.update(decision="COMPLETE", claims=claims)
        elif PASSAGE in page.get("text", ""):
            response.update(decision="EXTRACT", text=PASSAGE, source_quote=PASSAGE)
        elif search and not state.get("failures"):
            response.update(decision="SEARCH", text="Amber Relay", target={"element_id": search["element_id"]})
        else:
            url = next(item["href"] for item in page.get("elements", []) if item.get("href"))
            response.update(decision="NAVIGATE", url=url)
    content = json.dumps(response)
    return {"choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": len(json.dumps(body)) // 4, "completion_tokens": len(content) // 4}}


@pytest.mark.browser
@pytest.mark.parametrize("variant", ["native", "scripted", "alternate"])
async def test_informational_browser_benchmark(client, target, agent_config, agent_servers, variant):  # noqa: F811
    agent_config.ai_base_url = "http://127.0.0.1:8766/orchestration/v1"
    set_url(client, target, "/orchestration/" + variant)
    task = new_task(client, target, objective=OBJECTIVE, mode="autonomous", allow_search_input=True, allow_form_input=False)
    started = time.monotonic()
    await execute(*claim())
    elapsed = time.monotonic() - started
    saved = client.get("/api/agent/tasks/" + task["id"]).json()
    steps = client.get("/api/agent/tasks/" + task["id"] + "/steps").json()["items"]
    tokens = saved["prompt_tokens"] + saved["completion_tokens"]
    failed_completions = [step for step in steps if step["status"] == "failed"
                          and step["decision"].get("decision") == "COMPLETE"]
    print(f"orchestration {variant}: status={saved['status']} calls={saved['model_calls']} "
          f"tokens={tokens} steps={len(steps)} seconds={elapsed:.2f} failed_completions={len(failed_completions)}")
    if os.getenv("ADBOT_TEST_ORCHESTRATION_BASELINE"):
        return
    assert saved["status"] == "completed", saved.get("error_message")
    assert saved["result"]["claims"][0]["text"] == PASSAGE
    assert any(step["decision"].get("decision") == "SEARCH" for step in steps), steps
    if variant == "alternate":
        assert any(step["decision"].get("decision") == "NAVIGATE" and step["status"] == "succeeded" for step in steps)
    else:
        assert any(step["decision"].get("decision") == "SEARCH" and step["status"] == "succeeded" for step in steps)
    assert not failed_completions
