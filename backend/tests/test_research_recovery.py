"""Distributed cache and checkpoint regression tests, no live websites."""

import asyncio
import time

from redis.exceptions import ConnectionError

from app.config import settings
from app.research.checkpoint import freeze
from app.research.contracts import Mode, Question, budget_for
from app.research.retrieval import cache_max_age
from app.research.search import Hit
from app.research.service import Research
from app.research.shared_cache import SharedCache, slot


class FakeRedis:
    def __init__(self):
        self.rows = {}
        self.fail = False

    async def get(self, key):
        if self.fail:
            raise ConnectionError("unavailable")
        return self.rows.get(key)

    async def set(self, key, value, ex):
        assert 0 < ex <= 3600
        self.rows[key] = value

    async def delete(self, key):
        self.rows.pop(key, None)


async def test_cache_shares_results_across_instances_and_isolates_scope():
    store = FakeRedis()
    one = SharedCache("owner", "thread", {})
    two = SharedCache("owner", "thread", {})
    other = SharedCache("other-owner", "thread", {})
    unrelated = SharedCache("owner", "other-thread", {})
    for cache in (one, two, other, unrelated):
        cache.client = store
    key = ("provider", "battery", "NG", "week")
    await one.put("query", key, [{"title": "Battery study"}], 60)
    assert (await two.get("query", key, 60))[0] == [{"title": "Battery study"}]
    assert await other.get("query", key, 60) is None
    assert await unrelated.get("query", key, 60) is None
    assert await two.get("query", key, 0) is None
    await two.discard("query", key)
    assert await one.get("query", key, 60) is None


async def test_slot_collision_and_redis_outage_are_misses():
    cache = SharedCache("owner", "thread", {})
    cache.client = FakeRedis()
    key = ("original",)
    address, _ = slot("owner", "thread", "query", key)
    collision = next((str(i),) for i in range(10000)
                     if slot("owner", "thread", "query", (str(i),))[0] == address)
    await cache.put("query", key, ["original"], 30)
    await cache.put("query", collision, ["other"], 30)
    assert await cache.get("query", key, 30) is None
    cache.client.fail = True
    assert await cache.get("query", collision, 30) is None
    assert cache.disabled and cache.metrics["shared_cache_errors"] == 1


def test_origin_cache_policy():
    assert cache_max_age({"cache-control": "private"}, 300) is None
    assert cache_max_age({"cache-control": "no-store"}, 300) is None
    assert cache_max_age({"vary": "Cookie"}, 300) is None
    assert cache_max_age({"cache-control": "no-cache"}, 300) == 0
    assert cache_max_age({"cache-control": "max-age=20", "age": "5"}, 300) == 15


def engine(**kwargs):
    gate = asyncio.Event()
    gate.set()

    async def emit(*args, **details):
        pass

    return Research("owner", Question(question="Research battery technology", mode=Mode.DEEP),
                    Mode.DEEP, "deep_research", budget_for(Mode.DEEP),
                    time.monotonic() + 60, [], emit, gate, model=object(), **kwargs)


def seed(instance):
    url = "https://example.org/battery"
    instance.sources = {"s": {"id": "s", "url": url, "independence_group": "example.org"}}
    instance.evidence = {"e": {"id": "e", "source_id": "s", "kind": "quote",
                               "quote": "Battery research finding.", "published_at": None}}
    instance.attempted.add(url)
    instance.search_done = True
    instance.synthesis_state = {
        "accepted": [{"kind": "fact", "text": "Battery research finding.", "evidence": ["e"],
                      "independent_sources": 1}],
        "presented": [{"id": "e", "source": "example.org", "quote": "Battery research finding.",
                       "date": None, "kind": "quote"}],
        "batches": 1, "proposed_total": 1, "rejected": 0, "verified_total": 1,
    }


async def test_recovery_preserves_evidence_and_authoritative_usage():
    before = engine()
    seed(before)
    state = freeze(before)
    after = engine(saved=state, usage={"model_calls": 5, "tokens_charged": 12345,
                                      "pages_attempted": 7, "search_requests": 3})
    assert after.resumed and after.search_done
    assert after.evidence == before.evidence
    assert after.page_count == 7 and after.search_count == 3
    assert after.metrics["model_calls"] == 5 and after.token_count == 12345
    assert after.synthesis_state["accepted"] == before.synthesis_state["accepted"]

    async def forbidden(*args, **kwargs):
        raise AssertionError("Already processed evidence must not be sent again")

    after.ask = forbidden
    await after.synthesize()
    assert after.claims == before.synthesis_state["accepted"]


async def test_policy_change_rejects_checkpoint_without_refunding_usage(monkeypatch):
    before = engine()
    seed(before)
    state = freeze(before)
    monkeypatch.setattr(settings(), "research_excluded_domains", "example.org")
    after = engine(saved=state, usage={"pages_attempted": 3, "model_calls": 2})
    assert not after.resumed and after.result_quality == "partial"
    assert not after.sources and after.page_count == 3 and after.metrics["model_calls"] == 2


async def test_ranked_candidates_resume_without_repeating_provider_search(monkeypatch):
    from dataclasses import asdict

    monkeypatch.setattr(settings(), "research_browser_enabled", False)
    before = engine()
    a = Hit("A", "https://example.org/a", "https://example.org/a", "", "fixture",
            "example.org", None, time.time(), 1, "web", {}, "battery")
    b = Hit("B", "https://example.net/b", "https://example.net/b", "", "fixture",
            "example.net", None, time.time(), 2, "web", {}, "battery")
    before.pending_ranked = [asdict(a), asdict(b)]
    before.round_page_limit = 2
    before.attempted.add(a.canonical_url)
    recovered = engine(saved=freeze(before), usage={"pages_attempted": 1})
    observed = []

    async def retrieve(fetcher, queued):
        observed.extend(queued)
        return []

    class Pool:
        async def search(self, *args, **kwargs):
            raise AssertionError("Provider search already checkpointed")

    recovered.retrieve_batch = retrieve
    await recovered.search_round(Pool(), object(), [], True)
    assert observed == [b]
