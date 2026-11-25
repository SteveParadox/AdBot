"""Research fixtures. All model, provider and public source responses are simulated."""

import asyncio
import gzip
import json
import socket
import time
from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select, update

from app.agent.model import ModelClient
from app.config import settings
from app.db import Job, ResearchTask, Session, transaction
from app.jobs import claim, recover_expired
from app.research.contracts import Mode, Question, route
from app.research.evidence import country_from, product_evidence, rank_products, verified_claims
from app.research.policy import PublicPolicy
from app.research.retrieval import Fetcher, Response, extract
from app.research.search import HEALTH, QUERIES, Hit, ProviderHealth, bounded_bytes, normalize_hits, rank_hits
from app.research.retrieval import DOCUMENTS, ROBOTS
from app.worker import execute
from conftest import OTHER_AUTH

API = "/api/research/v1"
TEXT_A = ("A silicon quantum processor uses superconducting circuits for error correction. "
          "The laboratory recorded a 12 percent error reduction in a controlled test. "
          "Quantum researchers published a detailed report about the processor and the observed error rates. ")
TEXT_B = ("A university team independently studied quantum error correction on a silicon processor. "
          "The researchers reported different error rates under a different protocol. "
          "The quantum processor study explains its uncertainty and the limitations of the measurements. ")
SOURCE_A = "https://science.example.org/study"
SOURCE_B = "https://research.example.com/analysis"


@pytest.fixture
def research(monkeypatch):
    cfg = settings()
    monkeypatch.setattr(cfg, "research_enabled", True)
    for cache in (QUERIES, DOCUMENTS, ROBOTS):
        cache.items.clear()
    for name in HEALTH:
        monkeypatch.setitem(HEALTH, name, ProviderHealth())
    return cfg


@pytest.mark.parametrize("name,mode,intent", [
    ("What is 2 + 2?", Mode.DIRECT, "general"),
    ("Explain Python tuples", Mode.DIRECT, "general"),
    ("What is quantum computing?", Mode.QUICK, "general"),
    ("Latest quantum developments", Mode.QUICK, "current"),
    ("Find a laptop under ₦1.5 million in Nigeria", Mode.SHOPPING, "product_discovery"),
    ("Compare laptops from Nigerian retailers", Mode.SHOPPING, "product_comparison"),
    ("Verify that this statement is true", Mode.FACT_CHECK, "fact_check"),
    ("PostgreSQL and Cassandra benchmark", Mode.TECHNICAL, "technical"),
    ("Deep research on battery storage", Mode.DEEP, "deep_research"),
])
def test_route_modes(name, mode, intent):
    assert route(Question(question=name), []) == (intent, mode)


def test_route_override_follow_up():
    history = [{"mode": "shopping", "question": "Find laptops in Nigeria"}]
    assert route(Question(question="Which of those is cheapest?"), history) == ("follow_up", Mode.SHOPPING)
    assert route(Question(question="Latest news", mode=Mode.DIRECT), []) == ("news", Mode.DIRECT)
    assert country_from("What about Nigeria?") == "NG"


@pytest.mark.parametrize("url", ["file:///example", "http://localhost/", "http://127.0.0.1/",
                                  "http://10.0.0.1/", "http://169.254.169.254/", "http://[::1]/",
                                  "https://public.example:8443/", "https://account@public.example/",
                                  "http://224.0.0.12/"])
def test_public_policy_rejects_non_public_destinations(research, url):
    with pytest.raises(ValueError):
        PublicPolicy().check(url)


async def test_dns_mixed_public_and_private_is_denied(research, monkeypatch):
    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, 0, 0, "", (ip, 443)) for ip in ("93.184.216.34", "10.0.0.3")]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(ValueError, match="forbidden"):
        await PublicPolicy().resolve(SOURCE_A)


def test_duplicate_tracking_urls_rank_once():
    group = normalize_hits("searxng", {"results": [
        {"url": SOURCE_A + "?utm_source=test", "title": "Quantum study"},
        {"url": SOURCE_A, "title": "Quantum repeats"},
        {"url": SOURCE_B, "title": "Quantum paper"},
    ]}, "quantum")
    results = rank_hits([group], "quantum")
    assert len(results) == 2
    assert results[0].canonical_url == SOURCE_A and results[0].published is None


async def test_compressed_size_bound_uses_stream():
    class Compressed(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield gzip.compress(b"a" * 500_000)
    response = httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=Compressed(),
                              request=httpx.Request("GET", SOURCE_A))
    with pytest.raises(ValueError, match="byte limit"):
        await bounded_bytes(response, 1000)


async def test_redirect_and_robots_fail_closed(research):
    seen = []
    def handle(request):
        seen.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /blocked")
        return httpx.Response(302, headers={"location": "http://127.0.0.1/"})
    fetcher = Fetcher("redirect-fixture", {})
    fetcher.metrics["http_requests"] = 0
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as transport:
        fetcher.client = transport
        with pytest.raises(ValueError, match="Forbidden"):
            await fetcher.fetch(SOURCE_A, {"text/html"})
        with pytest.raises(ValueError, match="robots"):
            await fetcher.fetch("https://science.example.org/blocked", {"text/html"})
    assert seen == ["https://science.example.org/robots.txt", SOURCE_A]


def mock_network(monkeypatch, cfg, *, first_code=429, slow=False, empty=False, malformed=False):
    monkeypatch.setattr(cfg, "ai_provider", "local")
    monkeypatch.setattr(cfg, "ai_base_url", "http://model.example.net/v1")
    monkeypatch.setattr(cfg, "ai_model", "qwen3:4b")
    monkeypatch.setattr(cfg, "ai_ollama_native", True)
    monkeypatch.setattr(cfg, "ai_retries", 0)
    monkeypatch.setattr(cfg, "research_searxng_url", "http://search.example.net")
    monkeypatch.setattr(cfg, "research_brave_key", SecretStr("test-only"))
    requests = []
    max_source_parallel = 0
    source_parallel = 0

    @asynccontextmanager
    async def proxy(*args, **kwargs):
        yield None
    monkeypatch.setattr("app.research.search.egress_proxy", proxy)
    monkeypatch.setattr("app.research.retrieval.egress_proxy", proxy)

    async def respond(request):
        nonlocal max_source_parallel, source_parallel
        host = request.url.host
        requests.append((host, request.url.path))
        if host == "search.example.net":
            return httpx.Response(first_code, headers={"Retry-After": "180"})
        if host == "api.search.brave.com":
            return httpx.Response(200, json={"web": {"results": [] if empty else [
                {"title": "Quantum processor correction", "url": SOURCE_A, "description": "Quantum correction"},
                {"title": "Independent quantum processor analysis", "url": SOURCE_B, "description": "Quantum correction"},
                {"title": "Quantum duplicate", "url": SOURCE_A + "?utm_source=fixture"},
            ]}})
        if host == "model.example.net":
            data = json.loads(request.content)
            content = json.loads(data["messages"][1]["content"])
            kind = content["purpose"]
            assert data["format"] and data["think"] is False
            assert "untrusted data" in data["messages"][0]["content"]
            if kind == "research_direct":
                reply = {"answer": "The answer is **4**."}
            elif malformed:
                reply = {}
            elif kind == "research_synthesis":
                ids = [item["id"] for item in content["evidence"]]
                reply = {"claims": [
                    {"text": "The laboratory recorded a 12 percent error reduction in a controlled test.",
                     "kind": "fact", "evidence": [next(item["id"] for item in content["evidence"] if "12 percent" in item["quote"])]},
                    {"text": "Invented citation", "kind": "fact", "evidence": ["fabricated"]},
                    {"text": "The processor solved all limitations.", "kind": "fact", "evidence": ids[:1]},
                ]}
            elif kind == "research_verify":
                reply = {"checks": [{"claim": i, "status": "supported" if i == 0 else "unsupported", "evidence": c["evidence"]}
                                    for i, c in enumerate(content["candidates"])]}
            else:
                reply = {"queries": [], "gaps": []}
            return httpx.Response(200, json={
                "message": {"content": "invalid JSON" if malformed else json.dumps(reply)},
                "prompt_eval_count": 120, "eval_count": 48,
            })
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        assert request.headers.get("x-subscription-token") is None
        assert request.headers.get("cookie") is None
        source_parallel += 1
        max_source_parallel = max(max_source_parallel, source_parallel)
        try:
            if slow:
                await asyncio.sleep(0.03)
            content = TEXT_A if str(request.url).startswith(SOURCE_A) else TEXT_B
            markup = f'<html><head><title>Quantum research</title></head><body><main><p>{content}</p><p>{content}</p></main></body></html>'
            return httpx.Response(200, text=markup, headers={"Content-Type": "text/html", "Set-Cookie": "test=value", "ETag": '"fixture"'})
        finally:
            source_parallel -= 1

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    return requests, lambda: max_source_parallel


async def run_job(task_id):
    item = claim()
    assert item and item[0] == task_id
    await execute(*item)


async def test_current_web_answer_fallback_replay_and_followup(client, research, monkeypatch):
    requests, parallel = mock_network(monkeypatch, research, slow=True)
    question = {"question": "What are the latest quantum processor developments?"}
    created = client.post(API + "/query", json=question, headers={"Idempotency-Key": "quantum"})
    assert created.status_code == 202, created.text
    assert created.json()["intent"] == "current"
    task = created.json()
    assert client.post(API + "/query", json=question, headers={"Idempotency-Key": "quantum"}).json()["id"] == task["id"]
    assert client.post(API + "/query", json={"question": "Different question"},
                       headers={"Idempotency-Key": "quantum"}).status_code == 409
    assert client.get("/api/websites").json()["total"] == 0
    with Session() as session:
        assert session.get(Job, task["id"]).website_id is None
    await run_job(task["id"])
    path = f'{API}/tasks/{task["id"]}'
    response = client.get(path).json()
    assert response["status"] == "completed", response
    assert response["result"]["quality"] == "partial"
    assert "12 percent" in response["result"]["answer"]
    assert "Invented" not in response["result"]["answer"] and "solved all" not in response["result"]["answer"]
    assert response["result"]["metrics"]["rate_limits"] == 1
    assert len(response["result"]["sources"]) == 2
    assert parallel() >= 2
    evidence = client.get(path + "/evidence").json()["items"]
    claim = response["result"]["claims"][0]
    assert set(claim["evidence"]) <= {row["id"] for row in evidence}
    assert all(v["retrieved_at"] > 0 and v["published_at"] is None for v in evidence)
    streamed = client.get(path + "/events")
    assert streamed.status_code == 200
    assert "answer_chunk" in streamed.text and "verifying" in streamed.text
    cursor = max(int(line.split(": ")[1]) for line in streamed.text.splitlines() if line.startswith("id: "))
    assert "answer_chunk" not in client.get(path + "/events", headers={"Last-Event-ID": str(cursor)}).text
    assert client.get(path, headers=OTHER_AUTH).status_code == 404
    assert client.get(path + "/evidence", headers=OTHER_AUTH).status_code == 404
    assert client.get(path + "/events", headers=OTHER_AUTH).status_code == 404
    follow = client.post(f'{API}/conversations/{task["conversation_id"]}/messages',
                         json={"question": "Explain that claim using more recent sources."})
    assert follow.status_code == 202 and follow.json()["intent"] == "follow_up"
    await run_job(follow.json()["id"])
    assert any(host == "api.search.brave.com" for host, _ in requests)
    assert client.get(f'{API}/conversations/{task["conversation_id"]}').json()["total"] == 2
    assert client.delete(f'{API}/conversations/{task["conversation_id"]}').status_code == 204
    assert client.get(path).status_code == 404


async def test_direct_model_with_no_search_and_explicit_override(client, research, monkeypatch):
    requests, _ = mock_network(monkeypatch, research)
    result = client.post(API + "/query", json={"question": "Tell me the latest numbers", "mode": "direct"}).json()
    await run_job(result["id"])
    record = client.get(f'{API}/tasks/{result["id"]}').json()
    assert record["result"]["answer"] == "The answer is **4**."
    assert {host for host, _ in requests} == {"model.example.net"}
    assert record["result"]["sources"] == []


@pytest.mark.parametrize("malformed", [True, False])
async def test_failure_and_empty_results_are_partial(client, research, monkeypatch, malformed):
    mock_network(monkeypatch, research, first_code=503, empty=not malformed, malformed=malformed)
    record = client.post(API + "/query", json={"question": "What is quantum error correction?", "mode": "quick"}).json()
    await run_job(record["id"])
    result = client.get(f'{API}/tasks/{record["id"]}').json()["result"]
    assert result["quality"] == "partial"
    assert all(claim["kind"] == "excerpt" for claim in result["claims"])
    assert bool(result["sources"]) == malformed


async def test_queued_cancel_and_worker_lease_recovery(client, research):
    task = client.post(API + "/query", json={"question": "Calculate 2 + 2"}).json()
    path = f'{API}/tasks/{task["id"]}'
    assert client.post(path + "/cancel").json()["status"] == "cancelled"
    assert claim() is None
    second = client.post(path + "/retry", headers={"Idempotency-Key": "retry"}).json()
    item = claim()
    assert item[0] == second["id"]
    with transaction() as session:
        session.execute(update(Job).where(Job.id == item[0]).values(lease_until=0))
        session.get(ResearchTask, item[0]).usage = {"model_calls": 2, "tokens_charged": 9000}
    recover_expired()
    assert client.get(f"{API}/tasks/{item[0]}").json()["status"] == "queued"
    with Session() as session:
        assert session.get(ResearchTask, item[0]).usage["tokens_charged"] == 9000


async def test_running_cancellation_propagates(client, research, monkeypatch):
    started = asyncio.Event()
    cancelled = asyncio.Event()
    monkeypatch.setattr(research, "ai_provider", "local")

    async def blocked(*args, **kwargs):
        started.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()
    monkeypatch.setattr(ModelClient, "request", blocked)
    task = client.post(API + "/query", json={"question": "Calculate 2 + 2"}).json()
    item = claim()
    worker = asyncio.create_task(execute(*item))
    async with asyncio.timeout(5):
        await started.wait()
        client.post(f'{API}/tasks/{task["id"]}/cancel')
        await worker
    assert cancelled.is_set()
    with Session() as session:
        assert session.scalar(select(Job.status).where(Job.id == item[0])) == "cancelled"
        assert session.get(ResearchTask, item[0]).result == {}


def product(title, price, country, storage, expires=None):
    return {
        "@type": "Product", "name": title, "model": "X16", "sku": storage,
        "additionalProperty": {"name": "Storage", "value": storage},
        "offers": {"@type": "Offer", "priceCurrency": "NGN", "price": price,
                   "availability": "https://schema.org/InStock", "priceValidUntil": expires,
                   "shippingDetails": {"shippingDestination": {"addressCountry": country}}},
    }


def test_product_discovery_variants_geo_price_and_stale_offer(research):
    data = {"@graph": [product("Engineering laptop", "1200000", "NG", "512 GB"),
                       product("Engineering laptop", "1550000", "NG", "1 TB"),
                       product("Export version", "980000", "ZA", "512 GB"),
                       product("Expired", "990000", "NG", "256 GB", "2023-01-01")]}
    body = f'<script type="application/ld+json">{json.dumps(data)}</script>'.encode()
    doc = extract(Response("https://retailer.example.com.ng/catalog", body, "text/html", "utf-8", {}), True)
    from app.research.evidence import source_record
    products, evidence = product_evidence(doc, source_record(doc, "laptops Nigeria", "searxng"), "NG")
    products = rank_products(products + products, "Laptops under ₦1.5 million in Nigeria")
    assert [item["name"] for item in products] == ["Engineering laptop", "Expired", "Engineering laptop"]
    assert [p["price"] for p in products] == ["1200000", None, "1550000"]
    assert products[0]["within_budget"] is True and products[-1]["within_budget"] is False
    assert products[1]["availability"] is None
    assert {p["evidence_id"] for p in products} <= {e["id"] for e in evidence}


def test_claims_conflicting_supported_numbers_and_fabricated_ids():
    from app.research.contracts import Claim, Verification
    sources = {"a": {"independence_group": "a.example.org"}, "b": {"independence_group": "b.example.net"}}
    evidence = {"one": {"source_id": "a", "quote": "The estimate was 10."},
                "two": {"source_id": "b", "quote": "The estimate was 12."}}
    claims = [
        Claim(text="The estimates range from 10 to 12.", kind="conflict", evidence=["one", "two"]),
        Claim(text="The estimate was 99.", kind="fact", evidence=["one"]),
        Claim(text="The estimate was 10.", kind="fact", evidence=["one"]),
    ]
    checked = Verification(checks=[
        {"claim": 0, "status": "conflicting", "evidence": ["one", "two"]},
        {"claim": 1, "status": "supported", "evidence": ["one"]},
        {"claim": 2, "status": "supported", "evidence": ["invented"]},
    ])
    assert [result["kind"] for result in verified_claims(claims, checked, evidence, sources)] == ["conflict"]


async def test_document_cache_owner_scope_and_conditional_revalidation(research, monkeypatch):
    from app.research.service import new_metrics
    stats = new_metrics()
    requests = []
    def handle(request):
        requests.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if "if-none-match" in request.headers:
            return httpx.Response(304)
        return httpx.Response(200, text=TEXT_A, headers={"ETag": '"test"', "Content-Type": "text/plain"})

    hit = Hit("Study", SOURCE_A, SOURCE_A, "Quantum study", "fixture", "science.example.org", None, time.time(), 1, "web", {}, "quantum")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as transport:
        fetcher = Fetcher("owner-one", stats)
        fetcher.client = transport
        doc = await fetcher.retrieve(hit, False, None)
        assert doc.blocks and await fetcher.retrieve(hit, False, None) == doc
        assert stats["document_cache_hits"] == 1
        key = ("owner-one", SOURCE_A, False)
        DOCUMENTS.items[key] = (time.time() - 360, doc)
        assert (await fetcher.retrieve(hit, False, None)).digest == doc.digest
        assert requests[-1].headers["if-none-match"] == '"test"'
        fetcher.owner = "owner-two"
        assert await fetcher.retrieve(hit, False, None)
        assert "if-none-match" not in requests[-1].headers


@pytest.mark.browser
async def test_http_to_javascript_renderer_reuses_browser_and_blocks_writes(research, monkeypatch):
    from app.research.service import new_metrics
    monkeypatch.setattr(research, "research_browser_enabled", True)
    stats = new_metrics()
    markup = (
        '<html><head><title>Rendered study</title></head><body><main></main><script>'
        f'document.querySelector("main").innerHTML="<p>{TEXT_A * 3}</p>";'
        'fetch("/submit", {method:"POST", body:"data"}).catch(()=>{});'
        'fetch("https://other.example.net/track").catch(()=>{});'
        '</script></body></html>'
    )
    paths = []
    def handle(request):
        paths.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=markup, headers={"Content-Type": "text/html"})

    async with Fetcher("browser-fixture", stats, browsers=2) as fetcher:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as transport:
            fetcher.client = transport
            for url in (SOURCE_A, SOURCE_B):
                hit = normalize_hits("searxng", {"results": [{"url": url}]}, "quantum")[0]
                result = await fetcher.retrieve(hit, False, None)
                assert result and "silicon quantum processor" in result.blocks[0]
    assert stats["browser_launches"] == 1 and stats["browser_render_attempts"] == 2
    assert all("/submit" not in url and "other.example" not in url for url in paths)


async def test_model_budget_accounting_is_bounded(research):
    from app.agent.model import ModelBudgetExceeded
    from app.research.contracts import budget_for
    from app.research.service import Research
    engine = Research("owner", Question(question="Testing"), "quick", "general", budget_for(Mode.QUICK),
                      time.monotonic() + 50, [], None, None)
    reservation = await engine.account(1000, 1000, 0, True, {})
    await engine.account(200, 100, 10, False, reservation)
    assert engine.token_count == 300
    with pytest.raises(ModelBudgetExceeded):
        await engine.account(20000, 10000, 0, True, {})


async def test_quick_cold_warm_fixture_measurement(client, research, monkeypatch, capsys):
    from statistics import median
    mock_network(monkeypatch, research, slow=True)
    measurements = {"cold": [], "warm": []}
    for _ in range(6):
        for cache in (QUERIES, DOCUMENTS, ROBOTS):
            cache.items.clear()
        for label in measurements:
            task = client.post(API + "/query", json={
                "question": "What did the quantum processor experiment find?", "mode": "quick",
            }).json()
            await run_job(task["id"])
            result = client.get(f'{API}/tasks/{task["id"]}').json()["result"]
            assert result["claims"] and result["sources"]
            measurements[label].append(result["metrics"])
    with capsys.disabled():
        for label, values in measurements.items():
            keys = ("total_ms", "first_event_ms", "first_answer_ms", "http_requests", "search_requests",
                    "document_cache_hits", "query_cache_hits", "verification_ms", "completion_tokens")
            print(label, {key: median(sample[key] for sample in values) for key in keys}, flush=True)
    assert sum(row["http_requests"] for row in measurements["warm"]) == 0
    assert sum(row["search_requests"] for row in measurements["warm"]) == 0
