"""Regression coverage for charged orchestration and structured schedules."""
import asyncio
import time
from datetime import datetime, timezone

from lxml import html

from app.research.contracts import AnswerLayout, Mode, Question, SemanticRoute, budget_for
from app.research.evidence import source_record, text_evidence
from app.research.retrieval import Document
from app.research.schedule import event_day, structured_events
from app.research.service import Research
from app.research.synthesis import arranged_report, report_markdown


def engine(question, mode=Mode.QUICK, intent="general", semantic=True):
    gate = asyncio.Event()
    gate.set()

    async def emit(*args, **kwargs):
        pass

    return Research("owner", question, mode, intent, budget_for(mode), time.monotonic() + 40,
                    [], emit, gate, model=object(), semantic_route=semantic)


async def test_semantic_route_preserves_explicit_web_constraint(monkeypatch):
    instance = engine(Question(question="Latest company earnings"), intent="financial")

    async def ask(*args, **kwargs):
        return SemanticRoute(mode="direct", needs_web=False, confidence=.99)

    monkeypatch.setattr(instance, "ask", ask)
    await instance.classify()
    assert instance.mode == Mode.QUICK
    assert instance.route_done


async def test_semantic_route_direct_for_stable_knowledge(monkeypatch):
    instance = engine(Question(question="Explain how a binary search works"))

    async def ask(*args, **kwargs):
        return SemanticRoute(mode="direct", needs_web=False, confidence=.95)

    monkeypatch.setattr(instance, "ask", ask)
    await instance.classify()
    assert instance.mode == Mode.DIRECT


async def test_explicit_mode_is_not_semantically_rerouted(monkeypatch):
    instance = engine(Question(question="Define gravity", mode=Mode.QUICK), semantic=False)

    async def unexpected(*args, **kwargs):
        raise AssertionError("Explicit mode cannot be overridden")

    monkeypatch.setattr(instance, "ask", unexpected)
    await instance.classify()
    assert instance.mode == Mode.QUICK


def test_schedule_records_filter_by_actual_event_day():
    tree = html.fromstring("""<html><script type="application/ld+json">
      {"@graph":[{"@type":"SportsEvent","name":"A vs B","startDate":"2026-11-27T23:30:00Z",
      "homeTeam":{"name":"A"},"awayTeam":{"name":"B"}},{"@type":"SportsEvent",
      "name":"C vs D","startDate":"2026-11-29T12:00:00Z"},{"@type":"Article",
      "name":"News","datePublished":"2026-11-28"}]}</script></html>""")
    events = structured_events(tree)
    assert len(events) == 2
    assert event_day(events[0]["startDate"], 60) == "2026-11-28"
    assert event_day("2026-11-28T12:00:00", 60) is None
    doc = Document("https://league.example.com/fixtures", "https://league.example.com/fixtures",
                   "League fixtures", None, None, time.time(), "digest", [], [],
                   {"schedule_events": events}, None, None, {})
    source = source_record(doc, "league fixtures", "test")
    rows = text_evidence(doc, source, "League fixtures today", target_date="2026-11-28", offset_minutes=60)
    assert len(rows) == 1 and rows[0]["kind"] == "structured"
    assert "A vs B" in rows[0]["quote"] and "C vs D" not in rows[0]["quote"]
    assert "schedule_events" not in source["metadata"]


def test_recovery_respects_remaining_budget():
    instance = engine(Question(question="Research test"), semantic=False)
    assert instance.recovery_needed() and instance.can_recover()
    instance.search_count = instance.budget.requests
    assert not instance.can_recover()


def test_layout_rejects_dropped_duplicate_and_invented_indexes():
    source = {"id": "s", "url": "https://example.com/report", "independence_group": "example.com"}
    evidence = {"e": {"id": "e", "source_id": "s", "quote": "A finding."}}
    claims = [{"text": "First finding.", "kind": "fact", "evidence": ["e"]},
              {"text": "Second finding.", "kind": "fact", "evidence": ["e"]}]
    sources = {"s": source}
    baseline = report_markdown(claims, evidence, sources, Mode.DEEP)
    for indexes in ([0], [0, 0], [0, 2]):
        layout = AnswerLayout(groups=[{"heading": "answer", "claims": indexes}])
        assert arranged_report(claims, evidence, sources, Mode.DEEP, layout.model_dump()) == baseline
    layout = AnswerLayout(groups=[{"heading": "comparison", "claims": [1, 0]}])
    answer = arranged_report(claims, evidence, sources, Mode.DEEP, layout.model_dump())
    assert answer.index("Second finding") < answer.index("First finding")
    assert answer.count("https://example.com/report") == 2



async def test_phase_search_limit_applies_to_provider_fallback():
    instance = engine(Question(question="Research test"), semantic=False)
    instance.phase_search_limit = 1
    assert await instance.reserve_search()
    assert not await instance.reserve_search()
    instance.phase_search_limit = None
    assert await instance.reserve_search()


def test_schedule_date_is_not_publication_freshness():
    instance = engine(Question(question="List league fixtures today"), intent="current")
    assert instance.target_date
    assert instance.freshness is None
    assert engine(Question(question="List league fixtures today", freshness="day"), intent="current").freshness == "day"


def test_short_and_punctuation_bearing_subjects():
    from app.research.objectives import mentions_subject
    assert mentions_subject("R", "R is a programming language.")
    assert not mentions_subject("R", "Redis is a data store.")
    assert mentions_subject("C++", "C++ has value semantics.")


def test_structured_event_includes_derived_local_time():
    from app.research.schedule import local_start
    assert local_start("2026-11-27T23:30:00Z", 60) == "2026-11-28T00:30+01:00"
    assert local_start("2026-11-27", 60) is None


async def test_low_budget_skips_optional_semantic_routing(monkeypatch):
    instance = engine(Question(question="Research test"))
    instance.metrics["model_calls"] = instance.budget.calls - 2

    async def unexpected(*args, **kwargs):
        raise AssertionError("Must reserve synthesis/verification calls")

    monkeypatch.setattr(instance, "ask", unexpected)
    await instance.classify()
    assert instance.route_done
    assert instance.mode == Mode.QUICK



def test_comparison_candidate_diversity_and_criteria():
    from types import SimpleNamespace
    from app.research.objectives import prioritize_comparison_hits, subject_query
    def hit(name, key):
        return SimpleNamespace(title=name, description="", url="https://example.com/" + key, canonical_url=key)
    ranked = [hit("PostgreSQL first", "a"), hit("PostgreSQL second", "b"), hit("Cassandra", "c")]
    assert [h.canonical_url for h in prioritize_comparison_hits(ranked, ["PostgreSQL", "Cassandra"])] == ["a", "c", "b"]
    assert subject_query("Cassandra", "Compare PostgreSQL and Cassandra for high-throughput workloads") == "Cassandra high-throughput workloads"


def test_explicit_schedule_date_grounding():
    from app.research.objectives import relative_date
    assert relative_date("fixtures 2026-11-27", 0, 60) == "2026-11-27"
    assert relative_date("fixtures 2026-11-27 and 2026-11-28", 0, 60) is None
    assert relative_date("fixtures 2026-02-30", 0, 60) is None


def test_schedule_coverage_ignores_duplicate_observations():
    instance = engine(Question(question="League fixtures today"), intent="current")
    instance.evidence = {"a": {"event_observation": {"key": "match1"}},
                         "b": {"event_observation": {"key": "match1"}},
                         "c": {"event_observation": {"key": "match2"}}}
    assert instance.missing_schedule_observations([{"kind": "fact", "evidence": ["a"]}]) == 1
    assert instance.missing_schedule_observations([{"kind": "fact", "evidence": ["a", "c"]}]) == 0
