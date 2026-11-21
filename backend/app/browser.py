import asyncio
import hashlib
import random
import time
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from playwright.async_api import async_playwright
from playwright.async_api import Error as BrowserError
from playwright.async_api import TimeoutError as NavigationTimeout
from sqlalchemy import select

from .config import settings
from .db import Frontier, PageVisit, emit, transaction, uid
from .egress import egress_proxy
from .jobs import owned_job
from .security import Policy, PolicyError
from . import polymorph
from .browser_ownership import exclusive_owner


USER_AGENT = "Adbot/1.0.0"  # Legacy import compatibility; live requests use the session identity.


class BrowserCrashed(RuntimeError):
    pass


def retry_delay(value, attempt):
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError, OverflowError):
            seconds = polymorph.calculate_retry_delay(attempt)
    # Never retry sooner than Retry-After. A delay exceeding the job budget
    # causes the outer session deadline to terminate the job instead.
    return max(0.1, seconds)


class Runner:
    def __init__(self, job_id, token):
        self.id, self.token = job_id, token
        self.user_agent = settings().user_agent_default
        with transaction() as session:
            job = owned_job(session, job_id, token)
            self.job_type = job.job_type
            self.snapshot = job.snapshot
            self.action_index = job.action_index
            self.history = job.execution_state.get("history", [job.snapshot["base_url"]])
        self.cfg = self.snapshot["configuration"]
        self.policy = Policy(self.snapshot["allowed_domains"], self.cfg)
        self.robots = {}
        self.gate = asyncio.Event()
        self.gate.set()

    def log(self, kind, message, **details):
        with transaction() as session:
            owned_job(session, self.id, self.token)
            emit(session, self.id, kind, message, **details)

    async def permitted(self, url):
        url = self.policy.check(url)
        if self.cfg["respect_robots"]:
            p = urlsplit(url)
            origin = f"{p.scheme}://{p.netloc}"
            if origin not in self.robots:
                target = origin + "/robots.txt"
                async with httpx.AsyncClient(proxy=self.proxy, trust_env=False, timeout=15) as client:
                    for _ in range(6):
                        self.policy.check(target, navigation=False)
                        async with client.stream("GET", target, headers={"User-Agent": self.user_agent}) as response:
                            if response.is_redirect:
                                target = urljoin(target, response.headers.get("location", ""))
                                continue
                            if response.status_code in {404, 410}:
                                text = "User-agent: *\nAllow: /"
                            elif response.status_code >= 400:
                                raise PolicyError("robots.txt unavailable; crawl denied")
                            else:
                                data = bytearray()
                                async for chunk in response.aiter_bytes():
                                    data.extend(chunk)
                                    if len(data) > 512000:
                                        raise PolicyError("robots.txt exceeds size limit")
                                text = data.decode("utf-8", errors="replace")
                            robot = RobotFileParser()
                            robot.parse(text.splitlines())
                            self.robots[origin] = robot
                            break
                    else:
                        raise PolicyError("robots.txt redirect limit exceeded")
            robot = self.robots[origin]
            if not robot.can_fetch(self.user_agent, url):
                raise PolicyError("robots.txt disallows this URL")
            delay = robot.crawl_delay(self.user_agent) or robot.crawl_delay("*") or 0
            self.crawl_delay = max(self.crawl_delay, delay)
        return url

    async def route(self, route):
        request = route.request
        try:
            if request.method not in {"GET", "HEAD"}:
                raise PolicyError("Mutating HTTP requests are not permitted")
            self.policy.check(request.url, navigation=request.is_navigation_request())
            if request.is_navigation_request():
                await self.permitted(request.url)
            await route.continue_()
        except Exception:
            await route.abort("blockedbyclient")

    async def screenshot(self, page):
        root = settings().artifact_dir
        root.mkdir(parents=True, exist_ok=True)
        name = f"{self.id}-{uid()}.png"
        # Bounded viewport captures avoid huge images on infinite-scroll pages.
        await page.screenshot(
            path=str(root / name),
            full_page=False,
            mask=[page.locator("input,textarea,select,[contenteditable=true]")],
            timeout=self.cfg["navigation_timeout_ms"],
        )
        return name

    async def visit(self, page, url, frontier_id=None, navigate=True):
        await self.gate.wait()
        url = await self.permitted(url)
        with transaction() as session:
            if owned_job(session, self.id, self.token).pages_visited >= self.cfg["max_pages"]:
                raise ValueError("Session page limit reached")
        self.log("navigation_started", "Opening permitted page", url=url)
        start, response, error, screenshot, title, content_hash = time.monotonic(), None, None, None, "", ""
        links = []
        try:
            if navigate:
                for attempt in range(self.cfg["retries"] + 1):
                    try:
                        response = await page.goto(
                            url, wait_until=self.cfg["wait_until"], timeout=self.cfg["navigation_timeout_ms"]
                        )
                        break
                    except NavigationTimeout:
                        if attempt >= self.cfg["retries"]:
                            raise
                        delay = 2**attempt
                        self.log("retry_scheduled", "Navigation timed out; retry scheduled", seconds=delay)
                        await asyncio.sleep(delay * random.uniform(0.9, 1.1))
            else:
                response = self.response_for(page)
            self.policy.check(page.url)
            if response and response.status in {429, 503}:
                raise RateLimited(response.headers.get("retry-after"))
            if self.cfg["wait_selector"]:
                await page.locator(self.cfg["wait_selector"]).first.wait_for(timeout=self.cfg["navigation_timeout_ms"])
            if self.cfg["scroll"]:
                for _ in range(random.randint(3, 6)):
                    await page.mouse.wheel(0, polymorph.get_random_scroll_amount())
                    await asyncio.sleep(polymorph.get_random_wait_time(0.05, 0.15))
            title = (await page.title())[:2000]
            if self.snapshot.get("extraction"):
                if response is None or response.status < 400:
                    from .extraction.service import extract_page

                    await extract_page(self, page, required=self.job_type == 'crawl')
                else:
                    from .extraction.persistence import issue

                    issue(self.id, self.token, url, "navigation", {"http_status": response.status})
            content_hash = hashlib.sha256((await page.content()).encode()).hexdigest()
            if self.cfg["screenshots"]:
                screenshot = await self.screenshot(page)
            links = await page.locator("a[href]").evaluate_all("els => els.slice(0, 5000).map(e => e.href)")
        except RateLimited:
            raise
        except Exception as exc:
            if page.is_closed() or not page.context.browser.is_connected():
                raise BrowserCrashed("Browser disconnected unexpectedly") from exc
            error = type(exc).__name__
        final = page.url if page.url.startswith(("http://", "https://")) else url
        with transaction() as session:
            job = owned_job(session, self.id, self.token)
            visit = PageVisit(
                job_id=self.id,
                frontier_id=frontier_id,
                requested_url=url,
                final_url=final,
                page_title=title,
                http_status=response.status if response else None,
                navigation_duration_ms=(time.monotonic() - start) * 1000,
                content_hash=content_hash,
                screenshot_path=screenshot,
                error=error,
            )
            session.add(visit)
            session.flush()
            job.pages_visited += 1
            if frontier_id:
                session.get(Frontier, frontier_id).crawl_status = "failed" if error else "visited"
            emit(
                session,
                self.id,
                "navigation_failure" if error else "navigation_completed",
                "Navigation failed" if error else "Page recorded",
                url=url,
                http_status=visit.http_status,
                error=error,
            )
            visit_id = visit.id
        return links, visit_id, error

    async def crawl(self, page):
        while True:
            await self.gate.wait()
            with transaction() as session:
                job = owned_job(session, self.id, self.token)
                if job.pages_visited >= self.cfg["max_pages"]:
                    return
                item = session.scalar(
                    select(Frontier)
                    .where(Frontier.job_id == self.id, Frontier.crawl_status == "pending")
                    .order_by(Frontier.depth, Frontier.id)
                    .limit(1)
                )
                if not item:
                    return
                item.crawl_status = "visiting"
                url, depth, frontier_id, retries = item.normalized_url, item.depth, item.id, item.retry_count
            try:
                links, visit_id, error = await self.visit(page, url, frontier_id)
                if error:
                    # Navigation failures are persisted, allowing diagnosis; each
                    # URL consumes a page slot even on failure.
                    self.log("page_failed", "Page failed without stopping crawl", url=url)
                if self.snapshot.get("extraction") and self.cfg["discover_links"] and depth >= self.cfg["max_depth"]:
                    from .db import ExtractionRun

                    with transaction() as session:
                        owned_job(session, self.id, self.token)
                        seen = set(session.scalars(select(Frontier.normalized_url).where(Frontier.job_id == self.id)))
                        for raw in links:
                            try:
                                candidate = self.policy.check(urljoin(url, raw))
                            except ValueError:
                                continue
                            if candidate not in seen:
                                session.get(ExtractionRun, self.id).truncated = True
                                break
                if self.cfg["discover_links"] and depth < self.cfg["max_depth"]:
                    with transaction() as session:
                        owned_job(session, self.id, self.token)
                        seen = set(session.scalars(select(Frontier.normalized_url).where(Frontier.job_id == self.id)))
                        discovered = 0
                        for raw in links:
                            if len(seen) >= self.cfg["max_pages"] * 10:
                                if self.snapshot.get("extraction"):
                                    from .db import ExtractionRun

                                    session.get(ExtractionRun, self.id).truncated = True
                                break
                            try:
                                link = self.policy.check(urljoin(url, raw))
                            except ValueError:
                                continue
                            if link in seen:
                                continue
                            seen.add(link)
                            session.add(
                                Frontier(
                                    job_id=self.id,
                                    source_page_id=visit_id,
                                    discovered_url=raw,
                                    normalized_url=link,
                                    depth=depth + 1,
                                )
                            )
                            discovered += 1
                        emit(session, self.id, "links_discovered", "Internal links added to frontier", count=discovered)
            except RateLimited as exc:
                with transaction() as session:
                    owned_job(session, self.id, self.token)
                    item = session.get(Frontier, frontier_id)
                    item.retry_count += 1
                    item.crawl_status = "pending" if retries < self.cfg["retries"] else "failed"
                if retries >= self.cfg["retries"]:
                    raise RuntimeError("Rate-limit retry budget exhausted") from exc
                delay = retry_delay(exc.retry_after, retries + 1)
                self.log("retry_scheduled", "Server requested backoff", seconds=delay)
                await asyncio.sleep(delay)
            except PolicyError:
                with transaction() as session:
                    owned_job(session, self.id, self.token)
                    session.get(Frontier, frontier_id).crawl_status = "blocked"
                    emit(session, self.id, "policy_block", "Page denied by navigation or robots policy", url=url)
            await asyncio.sleep(max(self.cfg["delay_seconds"], self.crawl_delay) * random.uniform(0.8, 1.3))

    async def workflow(self, page):
        # Rebuild read-only page state on resume; CLICK workflows never auto-recover.
        _, _, error = await self.visit(page, self.history[-1])
        if error:
            raise RuntimeError("Workflow initial navigation failed")
        for index, step in enumerate(self.snapshot["workflow"]["steps"]):
            if index < self.action_index:
                continue
            await self.gate.wait()
            action = step["action"]
            locator = page.locator(step["selector"]).first if step.get("selector") else None
            async with asyncio.timeout(step["timeout_ms"] / 1000):
                details = {}
                if action == "OPEN_URL":
                    with transaction() as session:
                        job = owned_job(session, self.id, self.token)
                        if job.pages_visited >= self.cfg["max_pages"]:
                            raise ValueError("Workflow page limit reached")
                    _, _, error = await self.visit(page, step["url"])
                    if error:
                        raise RuntimeError("Workflow navigation failed")
                    self.history.append(page.url)
                elif action == "WAIT":
                    await asyncio.sleep(step["seconds"])
                elif action == "WAIT_FOR_SELECTOR":
                    await locator.wait_for()
                elif action == "CLICK":
                    info = await locator.evaluate(
                        "e => ({tag:e.tagName, form:!!e.closest('form'), href:e.closest('a')?.href, safe:e.dataset.adbotSafe === 'true'})"
                    )
                    if info["form"]:
                        raise PolicyError("Form interactions are disabled")
                    if info.get("href"):
                        await self.permitted(info["href"])
                    elif not info["safe"]:
                        raise PolicyError("Non-link clicks require data-adbot-safe='true' on the element")
                    await locator.click(no_wait_after=False)
                    if page.url != self.history[-1]:
                        self.policy.check(page.url)
                        _, _, error = await self.visit(page, page.url, navigate=False)
                        if error:
                            raise RuntimeError("Click navigation failed")
                        self.history.append(page.url)
                elif action == "SCROLL":
                    if locator:
                        await locator.scroll_into_view_if_needed()
                    else:
                        await page.mouse.wheel(0, step["pixels"])
                elif action == "EXTRACT_TEXT":
                    details["text"] = (await locator.inner_text())[:10000]
                elif action == "EXTRACT_LINKS":
                    raw = await page.locator("a[href]").evaluate_all("els => els.slice(0, 500).map(e => e.href)")
                    details["links"] = []
                    for url in raw:
                        try:
                            details["links"].append(self.policy.check(url))
                        except ValueError:
                            pass
                elif action == "SCREENSHOT":
                    details["screenshot_path"] = await self.screenshot(page)
                elif action == "ASSERT_VISIBLE":
                    if not await locator.is_visible():
                        raise AssertionError("Element is not visible")
                elif action == "ASSERT_TEXT":
                    if step["text"] not in await locator.inner_text():
                        raise AssertionError("Expected text was absent")
                elif action == "NAVIGATE_BACK":
                    if len(self.history) < 2:
                        raise ValueError("No previous workflow URL")
                    self.history.pop()
                    with transaction() as session:
                        if owned_job(session, self.id, self.token).pages_visited >= self.cfg["max_pages"]:
                            raise ValueError("Workflow page limit reached")
                    _, _, error = await self.visit(page, self.history[-1])
                    if error:
                        raise RuntimeError("Back navigation failed")
                elif action == "STOP":
                    return
                if self.snapshot.get("extraction") and action in {
                    "WAIT_FOR_SELECTOR",
                    "SCROLL",
                    "EXTRACT_TEXT",
                    "EXTRACT_LINKS",
                }:
                    from .extraction.service import extract_page

                    await extract_page(self, page, required=False)
                with transaction() as session:
                    job = owned_job(session, self.id, self.token)
                    job.action_index = index + 1
                    job.execution_state = {**job.execution_state, "history": self.history}
                    emit(session, self.id, "action_completed", f"{action} completed", index=index, **details)
            await asyncio.sleep(self.cfg["delay_seconds"] * random.uniform(0.7, 1.4))

    def context_options(self):
        return {
            "accept_downloads": False,
            "extra_http_headers": {"X-AdBot-Automation": "true", "X-AdBot-Session": self.id},
        }

    def proxy_method_allowed(self, method, url):
        return False

    def handle_popup(self, popup, initial):
        if popup != initial:
            asyncio.create_task(popup.close())

    def response_for(self, page):
        response = self.last_response
        return response if response is not None and response.frame == page.main_frame else None

    async def handle_dialog(self, dialog):
        try:
            await dialog.dismiss()
        except BrowserError:
            # A page/context can close while its dialog event is queued.
            pass

    async def execute_page(self, page, context):
        if "workflow" in self.snapshot:
            await self.workflow(page)
        else:
            await self.crawl(page)

    async def run(self):
        # Claim before the first await: a rejected run must not mutate runner state.
        with exclusive_owner(self, self, "Runner"):
            await self._run_isolated()

    async def _run_isolated(self):
        self.crawl_delay = 0
        async with (
            egress_proxy(self.policy, self.proxy_method_allowed, session=self.id) as proxy,
            async_playwright() as playwright,
        ):
            from .outbound import manager
            from .coordination import assign

            self.user_agent = assign(self, manager())
            self.proxy = proxy
            engine = getattr(playwright, self.cfg["browser"])
            options = {"headless": self.cfg["headless"], "proxy": {"server": proxy}}
            if self.cfg["browser"] == "chromium":
                options["args"] = [
                    "--proxy-bypass-list=<-loopback>",
                    "--disable-quic",
                    "--disable-background-networking",
                    "--disable-features=WebRtcHideLocalIpsWithMdns",
                    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                    f"--window-size={polymorph.get_random_viewport()['width']},{polymorph.get_random_viewport()['height']}",
                ]
            if self.cfg["browser"] == "firefox":
                options["firefox_user_prefs"] = {
                    "network.proxy.allow_hijacking_localhost": True,
                    "media.peerconnection.enabled": False,
                }
            browser = await engine.launch(**options)
            with exclusive_owner(browser, self, "Browser"):
                await self._execute_browser(browser)

    async def _execute_browser(self, browser):
        try:
            mobile = self.cfg["viewport"] == "mobile"
            vp = polymorph.get_random_viewport() if not mobile else {"width": 390, "height": 844}
            context = await browser.new_context(
                viewport={"width": vp["width"] if not mobile else 390, "height": vp["height"] if not mobile else 844},
                user_agent=self.user_agent,
                service_workers="block",
                **self.context_options(),
            )
            await context.route("**/*", self.route)
            await context.route_web_socket("**/*", lambda ws: ws.close())
            page = await context.new_page()
            self.last_response = None

            def remember_response(response):
                if response.request.is_navigation_request() and response.frame == page.main_frame:
                    self.last_response = response

            page.on("response", remember_response)
            page.set_default_timeout(self.cfg["navigation_timeout_ms"])
            context.on("page", lambda popup: self.handle_popup(popup, page))
            page.on("dialog", self.handle_dialog)
            self.log("browser_launched", "Isolated browser context launched", engine=self.cfg["browser"])
            await self.execute_page(page, context)
        finally:
            await asyncio.wait_for(browser.close(), 10)


class RateLimited(Exception):
    def __init__(self, retry_after):
        self.retry_after = retry_after
