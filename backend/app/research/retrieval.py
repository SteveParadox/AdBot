"""Bounded, credential-free HTTP plus an isolated browser rendering tier."""

import asyncio
import hashlib
import json
import re
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura
from lxml import html
from playwright.async_api import Error as PlaywrightError, async_playwright

from ..concurrency import database_call
from ..config import settings
from ..egress import egress_proxy
from ..security import PolicyError
from .policy import PublicPolicy
from .search import Cache, bounded_bytes

ROBOTS = Cache(512)
DOCUMENTS = Cache(96)
MAX_HTML_BYTES = 1_200_000
REDIRECTS = {301, 302, 303, 307, 308}
DOCUMENT_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}
BROWSER_TYPES = DOCUMENT_TYPES | {"application/javascript", "text/javascript", "application/json"}
BLOCKED_PATH = re.compile(r"/(log[io]n|log[io]ut|sign[io]n|signout|account|admin|cart|checkout|payment|track|pixel|ads?)(/|$)", re.I)


def clean(value, limit):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def normalized_date(value):
    value = clean(value, 80)
    if not re.match(r"^\d{4}-\d{2}-\d{2}(?:$|T| )", value):
        return None
    try:
        date = datetime.fromisoformat(value)
        date = date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date
        return (value if len(value) == 10 else date.isoformat()) if date.timestamp() <= time.time() + 86400 else None
    except ValueError:
        return None


def structured_products(tree):
    stack = []
    for node in tree.xpath('//script[@type="application/ld+json"]')[:24]:
        try:
            stack.append(json.loads((node.text or "")[:100_000]))
        except (ValueError, RecursionError):
            continue
    records = []
    for _ in range(300):
        if not stack:
            break
        value = stack.pop()
        if isinstance(value, list):
            stack.extend(value[:50])
        elif isinstance(value, dict):
            kind = value.get("@type", [])
            kinds = [kind] if isinstance(kind, str) else kind if isinstance(kind, list) else []
            if any(item in kinds for item in ("Product", "https://schema.org/Product")):
                records.append(value)
                if len(records) >= 16:
                    break
            for key in ("@graph", "mainEntity", "itemListElement", "item", "hasVariant"):
                if key in value:
                    stack.append(value[key])
    return records


@dataclass(frozen=True)
class Response:
    url: str
    body: bytes
    mime: str
    encoding: str
    headers: dict


@dataclass(frozen=True)
class Document:
    url: str
    canonical: str
    title: str
    published: str | None
    modified: str | None
    retrieved: float
    digest: str
    blocks: list[str]
    products: list[dict]
    metadata: dict
    etag: str | None
    last_modified: str | None


def robots_directives(content):
    content = re.sub(r":\s+", ":", content.casefold()[:1000])
    return set(re.split(r"[,\s]+", content))


def extract(response, shopping):
    text = response.body.decode(response.encoding, "replace")
    metadata, products = {}, []
    directives = robots_directives(response.headers.get("x-robots-tag", ""))
    canonical = response.url
    if response.mime != "text/plain":
        tree = html.fromstring(text or "<html></html>")
        for field in tree.xpath("//meta[@content]")[:100]:
            key = (field.get("property") or field.get("name") or "").lower()
            if key in {"robots", settings().user_agent_default.split("/", 1)[0].casefold()}:
                directives.update(robots_directives(field.get("content", "")))
            if key in {"og:title", "og:site_name", "og:description", "og:type", "article:published_time",
                       "article:modified_time", "date", "datepublished", "datemodified", "description"}:
                metadata.setdefault(key, clean(field.get("content"), 350))
        metadata.setdefault("title", clean(tree.findtext(".//title"), 200))
        if re.search(r"^(access denied|just a moment|verify (?:that )?you are human|security check|sign in|log in)\b",
                     metadata.get("title", ""), re.I):
            raise PolicyError("Source requires authentication or verification")
        for link in tree.xpath("//link[@rel='canonical']/@href")[:1]:
            try:
                candidate = PublicPolicy().check(urljoin(response.url, link))
                if urlsplit(candidate).hostname == urlsplit(response.url).hostname:
                    canonical = candidate
            except ValueError:
                pass
        if shopping:
            products = structured_products(tree)
            # Persist only supported product fields, with a strict bound on nested input.
            products = [product_fields(product) for product in products]
        text = trafilatura.extract(tree, include_comments=False, include_tables=True, favor_precision=True) or ""
    if directives & {"none", "noindex", "nosnippet", "max-snippet:0"}:
        raise PolicyError("Source excludes indexing or quotations")
    if "noarchive" in directives:
        metadata["robots_noarchive"] = True
    blocks = [clean(line, 1800) for line in text.splitlines()[:300] if len(line.strip()) >= 25]
    title = metadata.get("og:title") or metadata.get("title") or urlsplit(response.url).hostname
    return Document(
        response.url, canonical, title[:200],
        normalized_date(metadata.get("article:published_time") or metadata.get("datepublished") or metadata.get("date")),
        normalized_date(metadata.get("article:modified_time") or metadata.get("datemodified")),
        time.time(), hashlib.sha256(response.body).hexdigest(), blocks, products, metadata,
        response.headers.get("etag"), response.headers.get("last-modified"),
    )


def product_fields(product):
    result = {key: clean(product.get(key), 250) for key in
              ("name", "model", "sku", "mpn", "gtin", "gtin13", "gtin14", "color", "size", "description")}
    brand = product.get("brand")
    result["brand"] = clean(brand.get("name") if isinstance(brand, dict) else brand, 100)
    result["rating"] = {}
    if isinstance(rating := product.get("aggregateRating"), dict):
        result["rating"] = {key: clean(rating.get(key), 30) for key in ("ratingValue", "reviewCount", "ratingCount")}
    specs = product.get("additionalProperty", [])
    if isinstance(specs, dict):
        specs = [specs]
    result["specs"] = {
        clean(spec.get("name"), 80): clean(spec.get("value"), 160)
        for spec in (specs[:16] if isinstance(specs, list) else []) if isinstance(spec, dict) and clean(spec.get("name"), 80)
    }
    offers = product.get("offers") or []
    if isinstance(offers, dict):
        offers = offers.get("offers", []) if offers.get("@type") == "AggregateOffer" else [offers]
    result["offers"] = []
    if not isinstance(offers, list):
        return result
    for offer in offers[:8]:
        if not isinstance(offer, dict):
            continue
        item = {key: clean(offer.get(key), 350) for key in
                ("price", "priceCurrency", "availability", "url", "priceValidUntil", "itemCondition")}
        if isinstance(seller := offer.get("seller"), dict):
            item["seller"] = clean(seller.get("name"), 100)
        if isinstance(warranty := offer.get("warranty"), dict):
            item["warranty"] = clean(warranty.get("name") or warranty.get("description"), 160)
        if isinstance(shipping := offer.get("shippingDetails"), dict):
            item["shipping"] = clean(shipping.get("name") or shipping.get("description"), 160)
            region = shipping.get("shippingDestination")
            item["country"] = clean(region.get("addressCountry"), 2).upper() if isinstance(region, dict) else ""
        result["offers"].append(item)
    return result


class Fetcher:
    def __init__(self, owner, metrics, browsers=0, reserve_browser=None):
        self.owner, self.metrics, self.browsers = owner, metrics, browsers
        self.reserve_browser = reserve_browser
        self.policy = PublicPolicy()
        self.stack = AsyncExitStack()
        self.client = None
        self.browser = None
        self.browser_lock = asyncio.Lock()
        self.robots_lock = asyncio.Lock()

    async def __aenter__(self):
        await self.stack.__aenter__()
        try:
            proxy = await self.stack.enter_async_context(egress_proxy(self.policy, service="research"))
            self.client = await self.stack.enter_async_context(httpx.AsyncClient(
                proxy=proxy, trust_env=False, follow_redirects=False, timeout=settings().research_fetch_timeout,
                limits=httpx.Limits(max_connections=12, max_keepalive_connections=8),
            ))
        except BaseException:
            await self.stack.aclose()
            raise
        return self

    async def __aexit__(self, *exc):
        return await self.stack.__aexit__(*exc)

    async def fetch(self, url, types, *, robots=True, headers=None, max_bytes=MAX_HTML_BYTES,
                    origin=None, allowed_redirects=4):
        url = self.policy.check(url)
        for hop in range(allowed_redirects + 1):
            await self.gate(url, robots, origin)
            # A fresh request deliberately excludes the shared client's cookie jar,
            # ambient auth, referral headers and any browser-provided headers.
            request = httpx.Request("GET", url, headers={
                "User-Agent": settings().user_agent_default, "Accept": ", ".join(sorted(types)),
                "Accept-Encoding": "gzip, deflate", **(headers if hop == 0 and headers else {}),
            })
            self.metrics["http_requests"] += 1
            response = await self.client.send(request, stream=True)
            try:
                if response.status_code == 304 and hop == 0 and headers:
                    return None
                if response.status_code in REDIRECTS:
                    location = response.headers.get("location")
                    if not location:
                        raise PolicyError("Redirect missing a destination")
                    redirected = self.policy.check(urljoin(url, location))
                    if urlsplit(url).scheme == "https" and urlsplit(redirected).scheme != "https":
                        raise PolicyError("HTTPS downgrade blocked")
                    url = redirected
                    continue
                response.raise_for_status()
                mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if mime not in types:
                    raise ValueError("Unsupported response type")
                body = await bounded_bytes(response, max_bytes)
                kept = {k: v[:1000] for k, v in response.headers.items()
                        if k in {"etag", "last-modified", "content-security-policy", "x-robots-tag"}}
                return Response(url, body, mime, response.encoding or "utf-8", kept)
            finally:
                await response.aclose()
        raise PolicyError("Redirect limit reached")

    async def gate(self, url, robots, origin):
        parsed = urlsplit(url)
        if origin and (parsed.scheme, parsed.netloc) != origin:
            raise PolicyError("Browser subresource is outside its origin")
        if robots and BLOCKED_PATH.search(unquote(parsed.path)):
            raise PolicyError("Research excludes interactive paths")
        if robots and not await self.robots_allowed(url):
            raise PolicyError("Destination blocked by robots policy")

    async def robots_allowed(self, url):
        parsed = urlsplit(url)
        origin = (parsed.scheme, parsed.netloc)
        cache_key = (self.owner, *origin)
        record = ROBOTS.get(cache_key, 600)
        if record is None:
            async with self.robots_lock:
                record = ROBOTS.get(cache_key, 600)
                if record is None:
                    record = RobotFileParser()
                    robots_url = urlunsplit((*origin, "/robots.txt", "", ""))
                    try:
                        response = await self.fetch(robots_url, {"text/plain"}, robots=False, max_bytes=300_000,
                                                    origin=origin, allowed_redirects=2)
                        record.parse(response.body.decode(response.encoding, "replace").splitlines())
                    except httpx.HTTPStatusError as exc:
                        record.allow_all = exc.response.status_code in {404, 410}
                        record.disallow_all = not record.allow_all
                    except (ValueError, httpx.HTTPError, OSError, TimeoutError):
                        record.disallow_all = True
                    ROBOTS.put(cache_key, record)
        return record.can_fetch(settings().user_agent_default, url)

    async def retrieve(self, hit, shopping, freshness):
        cfg = settings()
        try:
            self.policy.check(hit.url)
        except ValueError:
            return None
        cache_key = (self.owner, hit.url, shopping)
        max_age = min(cfg.research_cache_seconds, 60) if shopping or freshness else cfg.research_cache_seconds
        cached = DOCUMENTS.get(cache_key, max_age)
        if cached:
            self.metrics["document_cache_hits"] += 1
            return cached
        prior = DOCUMENTS.get(cache_key, 3600) if cfg.research_cache_seconds else None
        headers = {}
        if prior and prior.url == hit.url:
            if prior.etag:
                headers["If-None-Match"] = prior.etag
            if prior.last_modified:
                headers["If-Modified-Since"] = prior.last_modified
        started = time.monotonic()
        try:
            async with asyncio.timeout(cfg.research_fetch_timeout + 3):
                response = await self.fetch(hit.url, DOCUMENT_TYPES, headers=headers)
                if response is None:
                    from dataclasses import replace
                    doc = replace(prior, retrieved=time.time())
                else:
                    doc = await database_call(extract, response, shopping)
            if response and response.mime == "text/html" and not doc.products and sum(map(len, doc.blocks)) < 200:
                doc = await self.render(response, doc, shopping)
            if not doc.blocks and not doc.products:
                return None
            if cfg.research_cache_seconds and not doc.metadata.get("robots_noarchive"):
                DOCUMENTS.put(cache_key, doc)
            return doc
        except (httpx.HTTPError, PlaywrightError, TimeoutError, ValueError, OSError, LookupError):
            self.metrics["retrieval_failures"] += 1
            return None
        finally:
            self.metrics["retrieval_ms"] += round((time.monotonic() - started) * 1000)

    async def render(self, response, doc, shopping):
        if not self.browsers or not settings().research_browser_enabled:
            return doc
        async with self.browser_lock:
            if not self.browsers or (self.reserve_browser and not await self.reserve_browser()):
                return doc
            self.browsers -= 1
            self.metrics["browser_render_attempts"] += 1
            try:
                async with asyncio.timeout(settings().research_fetch_timeout + 5):
                    if self.browser is None:
                        playwright = await self.stack.enter_async_context(async_playwright())
                        self.browser = await playwright.chromium.launch(
                            headless=True, proxy={"server": "http://127.0.0.1:1", "bypass": "<-loopback>"},
                            args=["--disable-quic", "--disable-background-networking",
                                  "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"],
                        )
                        self.stack.push_async_callback(self.browser.close)
                        self.metrics["browser_launches"] += 1
                    rendered = await self.render_in_context(response)
                    document = await database_call(extract, rendered, shopping)
                    return document if document.blocks or document.products else doc
            except (PlaywrightError, TimeoutError, ValueError):
                self.metrics["browser_failures"] += 1
                return doc

    async def render_in_context(self, response):
        parsed = urlsplit(response.url)
        origin = (parsed.scheme, parsed.netloc)
        context = await self.browser.new_context(
            service_workers="block", accept_downloads=False, user_agent=settings().user_agent_default,
        )
        async with AsyncExitStack() as cleanup:
            cleanup.push_async_callback(context.close)
            await context.route_web_socket("**/*", lambda socket: socket.close())
            page = await context.new_page()
            budget = 10
            served_main = False

            async def route_request(route):
                nonlocal budget, served_main
                request = route.request
                if request.method != "GET":
                    await route.abort()
                    return
                if request.is_navigation_request():
                    if served_main or request.url != response.url or request.frame != page.main_frame:
                        await route.abort()
                        return
                    served_main = True
                    fetched = response
                elif budget and request.resource_type in {"script", "xhr", "fetch"}:
                    budget -= 1
                    try:
                        fetched = await self.fetch(request.url, BROWSER_TYPES, origin=origin, max_bytes=200_000)
                    except (httpx.HTTPError, ValueError, OSError, TimeoutError):
                        await route.abort()
                        return
                else:
                    await route.abort()
                    return
                headers = {"Content-Type": f"{fetched.mime}; charset={fetched.encoding}", "X-Content-Type-Options": "nosniff"}
                if "content-security-policy" in fetched.headers:
                    headers["Content-Security-Policy"] = fetched.headers["content-security-policy"]
                await route.fulfill(status=200, headers=headers, body=fetched.body)

            await context.route("**/*", route_request)
            # To avoid closing the first page, install the popup handler only after creation.
            context.on("page", lambda popup: popup.close())
            await page.goto(response.url, wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("networkidle", timeout=1200)
            except PlaywrightError:
                pass
            content = (await page.content()).encode()
            if len(content) > MAX_HTML_BYTES:
                raise ValueError("Rendered content exceeded byte limit")
            return Response(response.url, content, "text/html", "utf-8", response.headers)
