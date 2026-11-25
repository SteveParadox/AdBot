"""Source ranking and independence regression cases; no external traffic."""

import asyncio
import time

from app.config import settings
from app.research.contracts import Mode, Question, RelevanceRatings, Summary, Verification, budget_for
from app.research.evidence import verified_claims
from app.research.ranking import Independence, domain_group, lexical_scores, source_signals, supporting_groups
from app.research.search import Hit, rank_hits
from app.research.service import Research


def hit(url, title, snippet="", rank=1):
    from urllib.parse import urlsplit

    return Hit(title, url, url, snippet, "fixture", urlsplit(url).hostname, None, time.time(), rank, "web", {}, "battery")


def test_lexical_scoring_distinguishes_relevant_phrase_from_repeated_generic_words():
    scores = lexical_scores("battery thermal runaway mitigation", [
        "battery thermal runaway mitigation experiment",
        "battery battery battery battery battery battery",
        "unrelated financial market report",
    ])
    assert scores[0] > scores[1] > scores[2]


def test_namespace_is_not_a_verified_identity_or_relevance_guarantee():
    assert source_signals("https://energy.gov/report")["role_hint"] == "government_namespace"
    assert source_signals("https://energy.gov.example.com/report")["role_hint"] == "unclassified"
    assert source_signals("https://docs.example.com/")["assessment"] == "heuristic_not_verified"
    assert source_signals("https://example.com/", {"sponsored_marker": True})["ranking_adjustment"] < 0
    irrelevant = hit("https://energy.gov/food", "Unrelated agriculture figures")
    relevant = hit("https://example.org/report", "Battery thermal runaway mitigation", rank=2)
    assert rank_hits([[irrelevant, relevant]], "battery thermal runaway mitigation")[0] == relevant


def test_duplicate_domains_do_not_receive_unlimited_top_positions():
    first = hit("https://www.example.com/a", "Battery report")
    same = hit("https://news.example.com/b", "Battery report")
    other = hit("https://example.org/c", "Battery report")
    assert domain_group(first.url) == domain_group(same.url)
    assert {domain_group(h.url) for h in rank_hits([[first, same, other]], "battery report")[:2]} == {
        domain_group(first.url), domain_group(other.url),
    }


def test_near_copies_cluster_transitively_without_deleting_original_source():
    article = " ".join(f"Experiment {n} measured battery performance under controlled temperature conditions."
                       for n in range(30))
    a = {"id": "a", "url": "https://example.com/report"}
    b = {"id": "b", "url": "https://example.org/report"}
    c = {"id": "c", "url": "https://news.example.org/report"}
    d = {"id": "d", "url": "https://example.net/report"}
    sources = {r["id"]: r for r in (a, b, c, d)}
    index = Independence()
    index.add(a, [article])
    index.add(b, [article + " Published with additional editorial commentary."])
    index.add(c, ["An unrelated article."])
    index.add(d, ["Independent experimental findings with distinct methods and results."])
    index.apply(sources)
    assert len(sources) == 4
    assert a["independence_group"] == b["independence_group"] == c["independence_group"]
    assert a["independence_group"] != d["independence_group"]
    assert a["independence_assessment"]["possible_shared_origin"] is True


def test_short_shared_phrase_does_not_cluster_documents():
    index = Independence()
    sources = {k: {"id": k, "url": f"https://example.{suffix}/report"}
               for k, suffix in (("a", "com"), ("b", "org"))}
    for source in sources.values():
        index.add(source, ["A short shared phrase about battery research."])
    index.apply(sources)
    assert sources["a"]["independence_group"] != sources["b"]["independence_group"]


def test_structured_retailer_data_does_not_collapse_independent_offers():
    sources = {k: {"id": k, "independence_group": k} for k in ("a", "b")}
    evidence = {k: {"source_id": k, "kind": "structured", "quote": "Battery laptop RAM storage warranty shipping "
                "model name currency price condition availability manufacturer identifier"}
                for k in sources}
    assert supporting_groups(evidence.keys(), evidence, sources) == {"a", "b"}


def test_shared_excerpt_cannot_be_verified_as_independent_conflict():
    quote = "The experiment measured the battery performance at the same temperature during the controlled laboratory trial."
    sources = {k: {"id": k, "independence_group": k} for k in ("a", "b")}
    evidence = {k: {"source_id": k, "kind": "quote", "quote": quote} for k in sources}
    proposals = Summary(claims=[{"text": "Sources disagree about the trial.", "kind": "conflict",
                                 "evidence": ["a", "b"]}]).claims
    checked = Verification(checks=[{"claim": 0, "status": "conflicting", "evidence": ["a", "b"]}])
    assert len(supporting_groups(evidence.keys(), evidence, sources)) == 1
    assert verified_claims(proposals, checked, evidence, sources) == []


async def test_optional_semantic_ranking_validates_ids_and_reserves_calls(monkeypatch):
    cfg = settings()
    monkeypatch.setattr(cfg, "research_semantic_ranking_enabled", True)
    monkeypatch.setattr(cfg, "ai_provider", "local")
    gate = asyncio.Event()
    gate.set()

    async def emit(*args, **kwargs):
        pass

    engine = Research("owner", Question(question="Research battery thermal runaway", mode=Mode.DEEP),
                      Mode.DEEP, "deep_research", budget_for(Mode.DEEP), time.monotonic() + 60,
                      [], emit, gate, model=object())
    candidates = [hit("https://example.com/report", "Battery research"),
                  hit("https://example.org/report", "Thermal runaway mitigation")]

    async def invalid(kind, prompt, schema, data, **kwargs):
        assert kind == "research_rank"
        return RelevanceRatings(ratings=[{"candidate": 0, "relevance": 4}, {"candidate": 0, "relevance": 3}])

    monkeypatch.setattr(engine, "ask", invalid)
    assert await engine.semantic_ranking(candidates) == {}
    assert engine.metrics["semantic_rank_attempts"] == 1
    assert engine.metrics["semantic_rank_successes"] == 0
    engine.metrics["semantic_rank_attempts"] = 0

    async def valid(*args, **kwargs):
        return RelevanceRatings(ratings=[{"candidate": 0, "relevance": 0}, {"candidate": 1, "relevance": 4}])

    monkeypatch.setattr(engine, "ask", valid)
    assert await engine.semantic_ranking(candidates) == {candidates[0].url: 0, candidates[1].url: 1}
    engine.metrics["semantic_rank_attempts"] = 0
    engine.metrics["model_calls"] = engine.budget.calls - 6
    assert await engine.semantic_ranking(candidates) == {}
