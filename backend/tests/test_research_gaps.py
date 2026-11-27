"""Regression tests for bounded, evidence-driven deep research planning."""

import asyncio
import time

from app.research.contracts import Mode, Plan, Question, budget_for
from app.research.gaps import Coverage, GapPlan
from app.research.service import Research


def records():
    sources = {
        "s1": {"independence_group": "one.example", "url": "https://one.example/a"},
        "s2": {"independence_group": "two.example", "url": "https://two.example/b"},
    }
    evidence = {
        "a": {"id": "a", "source_id": "s1", "quote": "Battery costs have declined in recent years.",
              "published_at": None, "kind": "quote"},
        "b": {"id": "b", "source_id": "s2", "quote": "Battery recycling remains a technical challenge.",
              "published_at": None, "kind": "quote"},
    }
    return sources, evidence


def assessment(*checks):
    return Coverage.model_validate({"checks": [
        {"question_id": q, "status": status, "evidence": ids} for q, status, ids in checks
    ]})


def test_gap_plan_deduplicates_and_bounds_subquestions():
    plan = GapPlan("Battery research", [" battery  research ", "", "Costs", "Recycling", "Supply", "Policy", "Extra"])
    assert [q.question for q in plan.questions] == ["Battery research", "Costs", "Recycling", "Supply", "Policy"]
    assert len(plan.pending()) == 5
    assert not plan.complete()


def test_coverage_rejects_unknown_unoffered_and_duplicate_evidence():
    sources, evidence = records()
    plan = GapPlan("Battery research", ["Costs", "Recycling"])
    plan.apply(assessment(("q1", "covered", ["invented"]), ("q2", "covered", ["b"]),
                          ("q3", "covered", ["a", "a"])), {"a"}, sources, evidence)
    assert all(q.status == "missing" for q in plan.questions)
    plan.apply(assessment(("q1", "covered", ["a"]), ("q1", "covered", ["b"])),
               set(evidence), sources, evidence)
    assert plan.questions[0].status == "missing"


def test_conflicting_requires_independent_sources_and_never_completes():
    sources, evidence = records()
    plan = GapPlan("Battery research")
    plan.apply(assessment(("q1", "conflicting", ["a"])), set(evidence), sources, evidence)
    assert plan.questions[0].status == "missing"
    plan.apply(assessment(("q1", "conflicting", ["a", "b"])), set(evidence), sources, evidence)
    assert plan.questions[0].status == "conflicting"
    assert not plan.complete()


def test_answer_coverage_excludes_excerpts_and_unused_evidence():
    sources, evidence = records()
    plan = GapPlan("Battery costs", ["Battery recycling"])
    plan.apply(assessment(("q1", "covered", ["a"]), ("q2", "covered", ["b"])),
               set(evidence), sources, evidence)
    assert plan.complete()
    assert [q.id for q in plan.unanswered([
        {"kind": "fact", "evidence": ["a"]}, {"kind": "excerpt", "evidence": ["b"]},
    ])] == ["q2"]


def engine(mode=Mode.DEEP):
    gate = asyncio.Event()
    gate.set()
    events = []

    async def emit(name, message, **details):
        events.append((name, details))

    question = Question(question="Research battery costs and recycling", mode=mode)
    instance = Research("test-owner", question, mode, "deep_research", budget_for(mode),
                        time.monotonic() + 60, [], emit, gate, model=object())
    return instance, events


async def test_deep_followup_targets_unresolved_and_does_not_stop_on_source_count(monkeypatch):
    instance, events = engine()

    async def ask(kind, prompt, schema, data, **kwargs):
        if kind == "research_plan":
            return Plan(queries=[], gaps=["Battery costs", "Battery recycling"])
        assert kind == "research_coverage"
        assert {q["id"] for q in data["subquestions"]} == {"q1", "q2", "q3"}
        return assessment(("q1", "covered", ["a"]), ("q2", "covered", ["a"]), ("q3", "missing", []))

    monkeypatch.setattr(instance, "ask", ask)
    first = await instance.plan(0)
    instance.queries.extend(first)
    instance.sources, instance.evidence = records()
    await instance.assess_coverage()
    # Even many independent sources cannot replace an answer to q3.
    for i in range(30):
        instance.sources[f"s{i + 3}"] = {"independence_group": f"domain-{i}"}
        instance.evidence[f"extra-{i}"] = {"source_id": f"s{i + 3}"}
    assert not instance.sufficient()
    next_queries = await instance.plan(1)
    assert next_queries and all("recycling" in q.lower() and "costs" not in q.lower() for q in next_queries)
    assert not set(first) & set(next_queries)
    assert events[-2][0] == "coverage"


async def test_deep_stops_only_after_evidence_coverage_and_two_domains(monkeypatch):
    instance, _ = engine()
    instance.gap_plan = GapPlan("Battery costs", ["Battery recycling"])
    instance.sources, instance.evidence = records()

    async def ask(*args, **kwargs):
        return assessment(("q1", "covered", ["a"]), ("q2", "covered", ["b"]))

    monkeypatch.setattr(instance, "ask", ask)
    await instance.assess_coverage()
    assert instance.sufficient()
    instance.sources["s2"]["independence_group"] = "one.example"
    assert not instance.sufficient()
    assert await instance.plan(1)


async def test_quick_search_does_not_use_deep_planner(monkeypatch):
    instance, _ = engine(Mode.QUICK)

    async def unexpected(*args, **kwargs):
        raise AssertionError("Quick Search must not call the model for planning")

    monkeypatch.setattr(instance, "ask", unexpected)
    assert len(await instance.plan(0)) == 2
    assert instance.gap_plan is None
