"""Search adapters, tenant-scoped caching, provider health and result fusion."""

import asyncio
import time
import zlib
from collections import Counter, OrderedDict
from contextlib import AsyncExitStack
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from ..concurrency import database_call
from ..config import settings
from ..egress import egress_proxy
from ..outbound import ProviderPolicy, manager
from ..provider_quota import QuotaBlocked, cooldown, identity, release, reserve
from ..retry import retry_delay
from .policy import PublicPolicy, canonical_key
from .ranking import domain_group, lexical_scores, source_signals


class Cache:
    def __init__(self, capacity):
        self.capacity = capacity
        self.items = OrderedDict()

    def get(self, key, max_age):
        record = self.items.get(key)
        if record and time.time() - record[0] < max_age:
            self.items.move_to_end(key)
            return record[1]
        return None

    def discard(self, key):
        self.items.pop(key, None)

    def put(self, key, value):
        self.items[key] = (time.time(), value)
        self.items.move_to_end(key)
        if len(self.items) > self.capacity:
            self.items.popitem(last=False)


@dataclass(frozen=True)
class Hit:
    title: str
    url: str
    canonical_url: str
    description: str
    provider: str
    domain: str
    published: str | None
    retrieved_at: float
    rank: int
    content_type: str
    source_metadata: dict
    query: str


@dataclass
class ProviderHealth:
    cooldown: float = 0
    failures: int = 0
    status: str = "unknown"

    def fail(self, retry_after=None):
        self.failures += 1
        self.status = "rate_limited" if retry_after is not None else "degraded"
        if retry_after is not None or self.failures >= 3:
            self.cooldown = time.monotonic() + (
                retry_delay(retry_after, min(self.failures, 7)) if retry_after is not None else 25
            )

    def healthy(self):
        if self.cooldown <= time.monotonic():
            self.status, self.failures = "healthy", 0


ENDPOINTS = {
    "brave": "https://api.search.brave.com/res/v1/web/search",
    "tavily": "https://api.tavily.com/search",
    "exa": "https://api.exa.ai/search",
    "serper": "https://google.serper.dev/search",
}
HEALTH = {name: ProviderHealth() for name in ("searxng", *ENDPOINTS)}
QUERIES = Cache(512)


def configured_providers():
    cfg = settings()
    return [
        name for name in cfg.research_provider_order.split(",")
        if (cfg.research_searxng_url if name == "searxng" else getattr(cfg, f"research_{name}_key").get_secret_value())
    ]


def provider_request(name, query, country, freshness):
    cfg = settings()
    if name == "searxng":
        params = {"q": query, "format": "json"}
        if freshness:
            params["time_range"] = freshness
        return "GET", cfg.research_searxng_url.rstrip("/") + "/search", {"params": params}
    key = getattr(cfg, f"research_{name}_key").get_secret_value()
    endpoint = ENDPOINTS[name]
    if name == "brave":
        params = {"q": query, "count": 10}
        if country:
            params["country"] = country
        if freshness:
            params["freshness"] = {"day": "pd", "week": "pw", "month": "pm", "year": "py"}[freshness]
        return "GET", endpoint, {"headers": {"X-Subscription-Token": key}, "params": params}
    if name == "tavily":
        body = {"query": query, "max_results": 10, "search_depth": "basic"}
        if freshness:
            body["time_range"] = freshness
        return "POST", endpoint, {"headers": {"Authorization": f"Bearer {key}"}, "json": body}
    if name == "exa":
        return "POST", endpoint, {"headers": {"x-api-key": key}, "json": {"query": query, "numResults": 10}}
    body = {"q": query, "num": 10}
    if country:
        body["gl"] = country.lower()
    if freshness:
        body["tbs"] = "qdr:" + freshness[0]
    return "POST", endpoint, {"headers": {"X-API-KEY": key}, "json": body}


async def bounded_bytes(response, limit):
    if int(response.headers.get("content-length", "0")) > limit:
        raise ValueError("Response exceeded byte limit")
    if response.is_stream_consumed:
        if len(response.content) > limit:
            raise ValueError("Response exceeded byte limit")
        return response.content
    codec = response.headers.get("content-encoding", "").strip().lower()
    if codec not in {"identity", "", "gzip", "deflate"}:
        raise ValueError("Unsupported response encoding")
    decoder = zlib.decompressobj(31 if codec == "gzip" else 15) if codec in {"gzip", "deflate"} else None
    data = bytearray()
    raw_size = 0
    try:
        async for chunk in response.aiter_raw(16384):
            raw_size += len(chunk)
            if raw_size > limit:
                raise ValueError("Response exceeded encoded byte limit")
            data.extend(decoder.decompress(chunk, limit - len(data) + 1) if decoder else chunk)
            if len(data) > limit or (decoder and (decoder.unused_data or decoder.unconsumed_tail)):
                raise ValueError("Response exceeded byte limit or has invalid encoding")
    except zlib.error as exc:
        raise ValueError("Invalid response encoding") from exc
    if decoder and not decoder.eof:
        raise ValueError("Truncated response encoding")
    return bytes(data)


def normalize_hits(name, data, query):
    if not isinstance(data, dict):
        raise ValueError("Invalid search response")
    if name == "brave":
        web = data.get("web", {})
        if not isinstance(web, dict):
            raise ValueError("Invalid Brave response")
        raw = web.get("results", [])
    elif name == "serper":
        raw = data.get("organic", [])
    else:
        raw = data.get("results", [])
    if not isinstance(raw, list):
        raise ValueError("Invalid result list")
    hits = []
    for rank, item in enumerate(raw[:20], 1):
        if not isinstance(item, dict):
            continue
        try:
            url = PublicPolicy().check(item.get("url", item.get("link", "")))
        except (ValueError, TypeError, AttributeError):
            continue
        date = item.get("publishedDate") or item.get("published_date") or item.get("page_age") or item.get("date")
        hits.append(Hit(
            str(item.get("title") or urlsplit(url).hostname)[:200], url, canonical_key(url),
            str(item.get("content") or item.get("description") or item.get("snippet") or "")[:450],
            name, urlsplit(url).hostname, date[:80] if isinstance(date, str) else None, time.time(), rank,
            str(item.get("category") or item.get("type") or "web")[:60],
            {k: item[k][:80] for k in ("engine", "category", "language") if isinstance(item.get(k), str)}, query,
        ))
    return hits


class ProviderPool:
    def __init__(self, owner, metrics, reserve):
        self.owner, self.metrics, self.reserve = owner, metrics, reserve
        self.names = configured_providers()
        self.stack = AsyncExitStack()
        self.clients = {}
        self.proxies = {}
        self.client_lock = asyncio.Lock()
        self.probe_locks = {name: asyncio.Lock() for name in self.names}

    async def __aenter__(self):
        await self.stack.__aenter__()
        return self

    async def __aexit__(self, *exc):
        return await self.stack.__aexit__(*exc)

    async def client(self, name, url):
        async with self.client_lock:
            return await self.open_client(name, url)

    async def open_client(self, name, url):
        if name in self.clients:
            return self.clients[name]
        local = name == "searxng"
        service = "research_local" if local else "research"
        if service not in self.proxies:
            if local and manager().policy(service).mode != "direct":
                raise ValueError("SearXNG requires a direct operator route")
            self.proxies[service] = await self.stack.enter_async_context(
                egress_proxy(ProviderPolicy(url, True) if local else PublicPolicy(),
                             allow_method=lambda method, _url: method == "POST" and not local, service=service)
            )
        client = self.clients[name] = await self.stack.enter_async_context(httpx.AsyncClient(
            proxy=self.proxies[service], timeout=settings().research_provider_timeout,
            follow_redirects=False, trust_env=False, headers={"User-Agent": settings().user_agent_default, "Accept-Encoding": "gzip, deflate"},
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        ))
        return client

    async def search(self, query, country, freshness, diversify=False):
        names = self.names[1:2] + self.names[:1] + self.names[2:] if diversify else self.names
        for name in names:
            health = HEALTH[name]
            if health.status == "healthy":
                hits = await self.attempt(name, query, country, freshness, health)
            else:
                # One cold or recovering probe per task avoids a burst to an
                # unavailable provider. Healthy providers can fan out.
                async with self.probe_locks[name]:
                    hits = await self.attempt(name, query, country, freshness, health)
            if hits:
                return hits
        return []

    async def attempt(self, name, query, country, freshness, health):
        from json import loads

        key = (self.owner, name, query, country, freshness)
        cached = QUERIES.get(key, settings().research_cache_seconds)
        if cached is not None:
            self.metrics["query_cache_hits"] += 1
            return cached
        if health.cooldown > time.monotonic():
            return []
        cfg = settings()
        method, url, args = provider_request(name, query, country, freshness)
        secret = "" if name == "searxng" else getattr(cfg, f"research_{name}_key").get_secret_value()
        quota = identity("research:" + url, secret)
        try:
            receipt = await database_call(reserve, quota, 0, cfg.research_provider_rpm, 0)
        except QuotaBlocked:
            self.metrics["quota_skips"] += 1
            return []
        if not await self.reserve():
            await database_call(release, quota, receipt)
            return []
        self.metrics["provider_requests"][name] += 1
        started = time.monotonic()
        try:
            client = await self.client(name, url)
            async with client.stream(method, url, **args) as response:
                if response.status_code == 429:
                    health.fail(response.headers.get("retry-after", "30"))
                    self.metrics["rate_limits"] += 1
                    self.metrics["provider_rate_limits"][name] += 1
                    await database_call(cooldown, quota, health.cooldown - time.monotonic())
                    return []
                response.raise_for_status()
                data = loads(await bounded_bytes(response, 512_000))
            hits = normalize_hits(name, data, query)
        except (httpx.HTTPError, RuntimeError, ValueError, OSError, TimeoutError):
            health.fail()
            if health.cooldown > time.monotonic():
                await database_call(cooldown, quota, health.cooldown - time.monotonic())
            self.metrics["provider_failures"][name] += 1
            return []
        else:
            health.healthy()
            QUERIES.put(key, hits)
            return hits
        finally:
            self.metrics["provider_ms"][name] += round((time.monotonic() - started) * 1000)


STOP_WORDS = set("what which where about latest for from with this that those more have find will when were would your best".split())


def terms(text):
    import re
    return set(re.findall(r"[^\W_]{3,}", text.casefold())) - STOP_WORDS


def rank_hits(groups, objective, technical=False, semantic=None):
    by_url = {}
    scores = Counter()
    for group in groups:
        seen = set()
        for hit in group:
            url = hit.canonical_url
            if url in seen:
                continue
            seen.add(url)
            by_url.setdefault(url, hit)
            scores[url] += 1 / (15 + max(1, hit.rank))
    candidates = list(by_url.values())
    relevance = lexical_scores(objective, [
        f"{hit.title} {hit.title} {hit.description} {urlsplit(hit.url).path}"
        for hit in candidates
    ])
    peak = max(scores.values(), default=1)
    semantic = semantic or {}
    ranked = []
    for hit, rel in zip(candidates, relevance):
        authority = source_signals(hit.url, technical=technical)["ranking_adjustment"]
        # Authority can break relevant ties; it cannot turn an unrelated
        # result into a good match. Model scores have a bounded influence.
        score = .55 * rel + .35 * scores[hit.canonical_url] / peak
        score += authority * rel
        score += .18 * semantic.get(hit.canonical_url, 0)
        ranked.append((score, hit))
    order = sorted(ranked, key=lambda pair: (-pair[0], pair[1].canonical_url))
    counts = Counter()
    diversified = []
    for score, hit in order:
        domain = domain_group(hit.url)
        counts[domain] += 1
        diversified.append((score - .09 * (counts[domain] - 1), hit))
    return [hit for _, hit in sorted(diversified, key=lambda pair: (-pair[0], pair[1].canonical_url))]
