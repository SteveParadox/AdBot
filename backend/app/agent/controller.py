import asyncio
import time
import re
from urllib.parse import urlsplit, urljoin
import httpx

from ..config import settings
from ..browser import USER_AGENT
from ..db import uid
from ..security import PolicyError
from .observe import Observer
from .interaction import InteractionEngine


class Controller:
    def __init__(self, runner, context, page, memory):
        self.runner, self.context, self.page = runner, context, page
        self.observer = Observer()
        self.engine = InteractionEngine(min(runner.cfg["navigation_timeout_ms"], 3000))
        self.tabs = {"t1": {"page": page, "purpose": "Initial task page", "history": []}}
        self.active = "t1"
        self.memory = memory
        self.mutation = None
        self.egress_grant = None
        self.creating = False
        context.on("page", self.popup)
        page.on("dialog", lambda dialog: asyncio.create_task(dialog.dismiss()))
        page.on("response", self.remember_response)

    def remember_response(self, response):
        if response.request.is_navigation_request() and response.frame == self.page.main_frame:
            self.runner.last_response = response

    def popup(self, page):
        if not self.creating:
            asyncio.create_task(page.close())

    async def observe(self):
        data = await self.observer.observe(self.page, self.active)
        data["tabs"] = [
            {"tab_id": key, "url": tab["page"].url, "purpose": tab["purpose"]} for key, tab in self.tabs.items()
        ]
        data["screenshot_path"] = await self.runner.screenshot(self.page)
        return data

    async def navigate(self, url):
        if url.startswith(("http://", "https://")):
            await self.runner.permitted(url)
        else:
            raise PolicyError("Navigation requires an absolute HTTP(S) URL")
        with self.engine.phase("loading", url=url):
            _, _, error = await self.runner.visit(self.page, url)
        if error:
            raise RuntimeError("Navigation failed: " + error)
        self.tabs[self.active]["history"].append(self.page.url)

    def needs_review(self, decision, mode):
        if decision.decision == "ASK_USER":
            return True
        if decision.decision in {"CLICK", "TYPE", "SEARCH"}:
            _, element = self.observer.target(decision)
            if decision.decision == "CLICK" and re.search(
                r"\b(delete|remove|send|publish|purchase|checkout|buy|pay|unsubscribe|logout|sign out)\b",
                element.get("name", "") + " " + (element.get("href") or ""),
                re.IGNORECASE,
            ):
                return True
            form = element.get("form")
            if decision.decision == "CLICK" and not element.get("href") and not element.get("safe"):
                if not (form and form["search"] and form["method"] == "GET"):
                    return True
            if form and form["method"] != "GET" and decision.decision == "CLICK":
                return True
        return mode == "assisted" and decision.decision in {
            "NAVIGATE",
            "CLICK",
            "TYPE",
            "SEARCH",
            "PRESS_KEY",
            "OPEN_TAB",
            "GO_BACK",
            "CLOSE_TAB",
        }

    async def route(self, route):
        request = route.request
        try:
            self.runner.policy.check(request.url, navigation=request.is_navigation_request())
            if request.method not in {"GET", "HEAD"}:
                permit = self.mutation
                actual = urlsplit(request.url)
                if (
                    not permit
                    or time.monotonic() > permit["until"]
                    or request.method != permit["method"]
                    or (actual.scheme, actual.netloc, actual.path) != permit["destination"]
                ):
                    raise PolicyError("This request requires a reviewed form submission")
                self.egress_grant = (request.method, request.url, time.monotonic() + 5)
                self.mutation = None
            if request.is_navigation_request():
                await self.runner.permitted(request.url)
            await route.continue_()
        except Exception:
            await route.abort("blockedbyclient")

    def allow_proxy_method(self, method, url):
        grant = self.egress_grant
        if grant and grant[0] == method and grant[1] == url and grant[2] > time.monotonic():
            self.egress_grant = None
            return True
        return False

    async def act(self, decision, options, approved=False):
        action = decision.decision
        result = {}
        before_url = self.page.url
        if action == "DOWNLOAD":
            return await self.download(decision, options)
        elif action == "NAVIGATE":
            await self.navigate(decision.url)
        elif action in {"CLICK", "TYPE", "SEARCH", "HOVER", "FOCUS"}:
            locator, element = self.observer.target(decision)
            live = await locator.evaluate(
                """e => {
                const labelled=(e.getAttribute('aria-labelledby')||'').split(' ').map(id=>document.getElementById(id)?.textContent||'').join(' ').trim();
                const type=(e.type||'').toLowerCase();
                const name=(e.getAttribute('aria-label')||labelled||[...(e.labels||[])].map(l=>l.textContent).join(' ')||e.innerText||e.getAttribute('alt')||e.getAttribute('placeholder')||(type==='submit'?e.value:'')||'').trim().replace(/\\s+/g,' ').slice(0,160);
                return {name,safe:e.dataset.adbotSafe==='true',type:(e.type||'').toLowerCase(),href:e.tagName==='A'?e.href:null,
                form:e.closest('form')?{method:e.closest('form').method.toUpperCase(),action:e.closest('form').action}:null}}""",
                timeout=self.engine.timeout_ms,
            )
            expected_form = element.get("form")
            if (
                live["name"] != element["name"]
                or live["safe"] != element["safe"]
                or live["type"] != element["type"]
                or live["href"] != element.get("href")
                or live["form"] != ({k: expected_form[k] for k in ("method", "action")} if expected_form else None)
            ):
                raise ValueError("Target changed since observation; inspect and replan")
            if element["disabled"]:
                raise ValueError("Element is disabled")
            if action in {"TYPE", "SEARCH"}:
                if not options["allow_form_input"]:
                    raise ValueError("Enable form input when creating the task")
                if element["type"] in {"password", "file"} or any(
                    x in element["name"].lower() for x in ("password", "credit card", "api key", "secret")
                ):
                    raise ValueError("Secret, payment and file fields are unavailable")
                if element["role"] not in {"textbox", "searchbox"}:
                    raise ValueError("TYPE/SEARCH requires an observed text input")
                if action == "SEARCH":
                    form = element.get("form")
                    if not form or not form["search"] or form["method"] != "GET":
                        raise ValueError("SEARCH requires an observed GET search form")
                    await self.runner.permitted(form["action"])
            elif action == "CLICK":
                if self.needs_review(decision, "autonomous") and not approved:
                    raise ValueError("This interaction requires approval")
                if element.get("href"):
                    await self.runner.permitted(element["href"])
                form = element.get("form")
                if form and form["method"] != "GET":
                    if not approved:
                        raise ValueError("Form submission requires approval")
                    destination = urlsplit(await self.runner.permitted(form["action"]))
                    self.mutation = {
                        "method": form["method"],
                        "destination": (destination.scheme, destination.netloc, destination.path),
                        "until": time.monotonic() + 5,
                    }
            try:
                result = await self.engine.perform(self.page, decision, locator, self.active)
            finally:
                self.mutation = None
            if self.page.url != before_url:
                self.runner.policy.check(self.page.url)
                await self.runner.visit(self.page, self.page.url, navigate=False)
                self.tabs[self.active]["history"].append(self.page.url)
        elif action in {"SCROLL", "SCROLL_BACK", "PRESS_KEY", "WAIT"}:
            if action == "PRESS_KEY" and not options.get("allow_form_input", False):
                edits_field = await self.page.evaluate("""() => !!document.activeElement?.matches(
                    'input,textarea,select,[contenteditable=true],[role=combobox],[role=slider],[role=spinbutton],[role=radio]')""")
                if edits_field and decision.key not in {"Tab", "Shift+Tab", "Escape"}:
                    raise ValueError("Enable form input before sending keys to an editable control")
            locator = self.observer.target(decision)[0] if decision.target else None
            result = await self.engine.perform(self.page, decision, locator, self.active)
        elif action == "OPEN_TAB":
            if len(self.tabs) >= settings().agent_max_tabs:
                raise ValueError("Tab budget exhausted; close a tab first")
            await self.runner.permitted(decision.url)
            self.creating = True
            try:
                self.page = await self.context.new_page()
            finally:
                self.creating = False
            self.active = uid()[:8]
            self.tabs[self.active] = {"page": self.page, "purpose": decision.reason, "history": []}
            self.page.on("dialog", lambda dialog: asyncio.create_task(dialog.dismiss()))
            self.page.on("response", self.remember_response)
            await self.navigate(decision.url)
        elif action == "SWITCH_TAB":
            if decision.tab_id not in self.tabs:
                raise ValueError("Unknown tab")
            self.active = decision.tab_id
            self.page = self.tabs[self.active]["page"]
            await self.page.bring_to_front()
        elif action == "CLOSE_TAB":
            if decision.tab_id not in self.tabs or len(self.tabs) == 1:
                raise ValueError("Cannot close the last or an unknown tab")
            await self.tabs.pop(decision.tab_id)["page"].close()
            if self.active == decision.tab_id:
                self.active = next(iter(self.tabs))
                self.page = self.tabs[self.active]["page"]
        elif action == "GO_BACK":
            history = self.tabs[self.active]["history"]
            if len(history) < 2:
                raise ValueError("No prior URL in this tab")
            previous = history[-2]
            await self.navigate(previous)
            self.tabs[self.active]["history"] = history[:-2] + [previous]
        elif action not in {"OBSERVE", "SUMMARIZE", "EXTRACT", "ASK_USER", "COMPLETE", "FAIL"}:
            raise ValueError("Unsupported action")
        self.mutation = None
        return result

    async def download(self, decision, options):
        if not options["allow_downloads"]:
            raise ValueError("Downloads are disabled for this task")
        _, element = self.observer.target(decision)
        if not element.get("href"):
            raise ValueError("DOWNLOAD requires an observed link")
        url = element["href"]
        name = f"{self.runner.id}-{uid()}.bin"
        root = settings().artifact_dir
        root.mkdir(parents=True, exist_ok=True)
        path = root / name
        try:
            async with httpx.AsyncClient(
                proxy=self.runner.proxy,
                trust_env=False,
                timeout=20,
                headers={"User-Agent": USER_AGENT, "X-AdBot-Automation": "true", "X-AdBot-Session": self.runner.id},
            ) as client:
                for _ in range(6):
                    await self.runner.permitted(url)
                    async with client.stream("GET", url) as response:
                        if response.is_redirect:
                            url = urljoin(url, response.headers.get("location", ""))
                            continue
                        if response.status_code != 200:
                            raise ValueError("Download returned an unsuccessful response")
                        size = 0
                        with path.open("xb") as file:
                            async for chunk in response.aiter_bytes():
                                size += len(chunk)
                                if size > 10 * 1024 * 1024:
                                    raise ValueError("Download exceeds 10 MiB limit")
                                file.write(chunk)
                        return {"download_path": name, "bytes": size, "source_url": url}
                raise ValueError("Download redirect limit reached")
        except BaseException:
            path.unlink(missing_ok=True)
            raise
