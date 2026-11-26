import asyncio
import time
from urllib.parse import urlsplit, urljoin
import httpx
from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright.async_api import Error as BrowserError

from ..config import settings
from ..browser import BrowserCrashed
from ..db import uid
from ..security import PolicyError
from .observe import Observer
from .interaction import InteractionEngine, ActionabilityTimeout
from .semantics import METADATA
from .semantic_observer import native_semantics


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
        self.crashed_pages = set()
        context.on("page", self.popup)
        self.watch_page(page)

    def watch_page(self, page):
        page.on("crash", lambda _: self.crashed_pages.add(page))
        page.on("dialog", self.dismiss_dialog)
        page.on("response", self.remember_response)

    async def dismiss_dialog(self, dialog):
        try:
            await dialog.dismiss()
        except BrowserError:
            # The context may have closed before this event could be handled.
            pass

    def check_page(self, page=None):
        page = page if page is not None else self.page
        if page.is_closed() or page in self.crashed_pages or not self.context.browser.is_connected():
            raise BrowserCrashed("Agent browser page closed, crashed or disconnected")

    def prune_tabs(self):
        for key, tab in list(self.tabs.items()):
            if key != self.active and tab["page"].is_closed():
                self.crashed_pages.discard(tab["page"])
                del self.tabs[key]

    def remember_response(self, response):
        if response.request.is_navigation_request():
            for tab in self.tabs.values():
                if response.frame == tab["page"].main_frame:
                    tab["last_response"] = response
                    break

    def popup(self, page):
        if not self.creating:
            asyncio.create_task(page.close())

    async def observe(self, *, directory=False, structure=False, research=False):
        self.check_page()
        self.prune_tabs()
        planning = self.memory.get("planning", {})
        active = next(
            (n for n in planning.get("plan", {}).get("subtasks", []) if n["id"] == planning.get("active_subtask")), {}
        )
        data = await self.observer.observe(
            self.page, self.active, getattr(self.runner, "objective", "") + " " + active.get("description", ""),
            **({"directory": directory} if directory else {}),
            **({"structure": structure} if structure else {}),
            **({"research": True} if research else {}),
        )
        if research or structure == "enumeration":
            response = self.runner.response_for(self.page)
            data["http_status"] = response.status if response and response.url == data["url"] else None
        data["tabs"] = [
            {"tab_id": key, "url": tab["page"].url, "purpose": tab["purpose"]} for key, tab in self.tabs.items()
        ]
        data["screenshot_path"] = (await self.runner.screenshot(self.page)
                                   if not directory or self.runner.options.get("visual_reasoning") else None)
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
        if decision.decision == "CLICK":
            return False
        return mode == "assisted" and decision.decision in {
            "NAVIGATE",
            "TYPE",
            "SEARCH",
            "PRESS_KEY",
            "SET_CHECKED",
            "SELECT_OPTION",
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
                    or (permit["method"] is not None and request.method != permit["method"])
                    or (
                        permit["destination"] is not None
                        and (actual.scheme, actual.netloc, actual.path) != permit["destination"]
                    )
                ):
                    raise PolicyError("This request requires an active click submission")
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

    async def inspect_target(self, locator):
        live = await locator.evaluate(METADATA, timeout=self.engine.timeout_ms)
        _, name, _ = native_semantics(await locator.aria_snapshot(timeout=self.engine.timeout_ms), live)
        return {
            **{k: live[k] for k in ("disabled", "safe", "type", "href")},
            "name": name,
            "form": {k: live["form"][k] for k in ("method", "action")} if live["form"] else None,
        }

    async def act(self, decision, options, approved=False, *, read_only=False, prefer_navigation=False):
        self.check_page()
        self.prune_tabs()
        action = decision.decision
        result = {}
        before_url = self.page.url
        if action == "DOWNLOAD":
            return await self.download(decision, options)
        elif action == "NAVIGATE":
            await self.navigate(decision.url)
        elif (
            action in {"CLICK", "TYPE", "SEARCH", "HOVER", "FOCUS", "SET_CHECKED", "SELECT_OPTION"}
            or action == "PRESS_KEY"
            and decision.target
        ):
            observed = self.observer.registry.get(decision.target.element_id, (None, {}))[1]
            with self.engine.phase(
                "resolution",
                element_id=decision.target.element_id,
                role=observed.get("role"),
                accessible_name=observed.get("name"),
                strategy=observed.get("locator_strategy"),
                actionable=observed.get("actionable"),
            ):
                locator, element, binding = await self.observer.resolve(decision, self.page, self.active)
            live = await self.inspect_target(locator)
            expected_form = element.get("form")
            if (
                live["name"] != element["name"]
                or live["disabled"] != element["disabled"]
                or live["safe"] != element["safe"]
                or live["type"] != element["type"]
                or live["href"] != element.get("href")
                or live["form"] != ({k: expected_form[k] for k in ("method", "action")} if expected_form else None)
            ):
                raise ValueError("Target changed since observation; inspect and replan")
            if element["disabled"]:
                raise ValueError("Element is disabled")
            if (prefer_navigation and read_only and action == "CLICK" and live.get("href")
                    and element.get("role") == "link" and not live.get("form")
                    and decision.input_method == "auto" and not decision.expected_text
                    and not urlsplit(live["href"]).fragment
                    and not self.needs_review(decision, "autonomous")):
                ordinary = await locator.evaluate(
                    "e=>e.matches('a[href]:not([download]):not([onclick]):not([role=button])') "
                    "&& (!e.target || e.target==='_self') && !e.closest('form,dialog,[role=dialog]')",
                    timeout=self.engine.timeout_ms,
                )
                if ordinary:
                    # Recheck the live binding after the extra DOM inspection.
                    if await self.inspect_target(locator) != live:
                        raise ValueError("Target changed before direct navigation; reobserve")
                    await self.navigate(live["href"])
                    return {"navigation_direct": True, "interaction": {
                        "changed": self.page.url != before_url, "verified": self.page.url != before_url,
                        "verification": "Authorized ordinary hyperlink navigated directly",
                    }}
            if action == "CLICK" and element["role"] in {"checkbox", "radio", "switch", "option"}:
                if not options.get("allow_form_input", False):
                    raise ValueError("Enable form input before changing a selection control")
                if element["readonly"]:
                    raise ValueError("Read-only selection controls cannot be changed")
            if action in {"TYPE", "SEARCH", "SET_CHECKED", "SELECT_OPTION"}:
                if not options["allow_form_input"]:
                    from .discovery import search_control, search_query_allowed

                    if not (read_only and action == "SEARCH" and options.get("allow_read_search")
                            and search_control(element) and search_query_allowed(self.runner.objective, decision.text)):
                        raise ValueError("Enable form input when creating the task")
                    live_metadata = await locator.evaluate(METADATA, timeout=self.engine.timeout_ms)
                    if not search_control(live_metadata):
                        raise ValueError("Search form changed before input; reobserve")
                if element["type"] in {"password", "file"} or any(
                    x in element["name"].lower() for x in ("password", "credit card", "api key", "secret")
                ):
                    raise ValueError("Secret, payment and file fields are unavailable")
                if element["readonly"]:
                    raise ValueError("Read-only controls cannot be edited")
                if action in {"TYPE", "SEARCH"} and (
                    (
                        element["role"] not in {"textbox", "searchbox", "combobox", "spinbutton"}
                        and not (
                            element["tag"] == "input"
                            and element["type"] in {"date", "time", "month", "week", "datetime-local"}
                        )
                    )
                    or element["tag"] == "select"
                ):
                    raise ValueError("TYPE/SEARCH requires an observed editable text or numeric input")
                if action == "SELECT_OPTION" and element["tag"] != "select":
                    raise ValueError(
                        "Custom selection requires observed options and native keyboard or click interaction"
                    )
                if action == "SELECT_OPTION" and not any(
                    not o["disabled"] and decision.option in {o["label"], o["value"]} for o in element["options"]
                ):
                    raise ValueError("Requested option is not an available observed choice")
                if action == "SET_CHECKED" and element["role"] not in {"checkbox", "radio", "switch"}:
                    raise ValueError("SET_CHECKED requires a checkbox, radio or switch")
                if action == "SET_CHECKED" and element["role"] == "radio" and not decision.checked:
                    raise ValueError("Select another observed radio instead of unchecking a radio")
                if action == "SEARCH":
                    form = element.get("form")
                    if not form or not form["search"] or form["method"] != "GET":
                        raise ValueError("SEARCH requires an observed GET search form")
                    await self.runner.permitted(form["action"])
            if action == "PRESS_KEY":
                if not element["focused"]:
                    raise ValueError("Focus the observed control before sending a targeted key")
                await self.keyboard_policy(decision, options, element)
            activation = action == "CLICK" or action == "PRESS_KEY" and decision.key in {"Enter", "Space"}
            if activation:
                if element.get("href"):
                    await self.runner.permitted(element["href"])
                form = element.get("form")
                if (
                    form
                    and (element["type"] == "submit" or action == "PRESS_KEY" and decision.key == "Enter")
                    and form["invalid_count"]
                ):
                    raise ValueError(
                        "Form validation is unresolved; inspect required fields and validation feedback before submission"
                    )
                if read_only:
                    if form:
                        raise PermissionError("Directory pagination cannot submit forms")
                elif form and form["method"] != "GET":
                    destination = urlsplit(await self.runner.permitted(form["action"]))
                    self.mutation = {
                        "method": form["method"],
                        "destination": (destination.scheme, destination.netloc, destination.path),
                        "until": time.monotonic() + 5,
                    }
                else:
                    # A JS button can submit without a form. Permit one policy-checked
                    # write during this click; revoke it as soon as the action ends.
                    self.mutation = {"method": None, "destination": None, "until": time.monotonic() + 5}
            try:
                result = await self.engine.perform(
                    self.page, decision, locator, self.active, binding=binding,
                    require_content=read_only and action == "CLICK",
                )
                result["semantic"] = {
                    "role": element["role"],
                    "name": element["name"],
                    "strategy": element["locator_strategy"],
                    "element_id": element["element_id"],
                    "context": element["context"],
                    "actionable": element["actionable"],
                }
            except ActionabilityTimeout:
                # The trial dispatched no click. Only an unchanged ordinary link
                # can recover through the normal authorized navigation path.
                if (
                    action != "CLICK"
                    or not live.get("href")
                    or live.get("form")
                    or self.needs_review(decision, "autonomous")
                ):
                    raise
                try:
                    current = await self.inspect_target(locator)
                except PlaywrightTimeout as exc:
                    raise ValueError("Target changed after the failed click trial; reobserve") from exc
                if current != live:
                    raise ValueError("Target changed after the failed click trial; reobserve") from None
                await self.navigate(live["href"])
                return {
                    "navigation_recovery": True,
                    "interaction": {
                        "changed": self.page.url != before_url,
                        "verified": self.page.url != before_url,
                        "verification": "Observed link navigated after a failed pointer trial",
                    },
                }
            finally:
                self.mutation = None
                self.egress_grant = None
            if self.page.url != before_url:
                self.runner.policy.check(self.page.url)
                await self.runner.visit(self.page, self.page.url, navigate=False)
                self.tabs[self.active]["history"].append(self.page.url)
        elif action in {"SCROLL", "SCROLL_BACK", "PRESS_KEY", "WAIT"}:
            binding = None
            if action == "PRESS_KEY":
                if decision.key in {"Enter", "Space"}:
                    raise ValueError("Keyboard activation requires an observed focused target")
                await self.keyboard_policy(
                    decision, options, await self.page.evaluate("() => (" + METADATA + ")(document.activeElement)")
                )
            if decision.target:
                locator, _, binding = await self.observer.resolve(decision, self.page, self.active)
            else:
                locator = None
            result = await self.engine.perform(self.page, decision, locator, self.active, binding=binding)
        elif action == "OPEN_TAB":
            if len(self.tabs) >= settings().agent_max_tabs:
                raise ValueError("Tab budget exhausted; close a tab first")
            await self.runner.permitted(decision.url)
            previous_id, previous_page = self.active, self.page
            self.creating = True
            try:
                self.page = await self.context.new_page()
            finally:
                self.creating = False
            self.active = uid()[:8]
            self.tabs[self.active] = {"page": self.page, "purpose": decision.reason, "history": []}
            self.watch_page(self.page)
            try:
                await self.navigate(decision.url)
            except BaseException:
                failed_page = self.page
                del self.tabs[self.active]
                self.active, self.page = previous_id, previous_page
                try:
                    await failed_page.close()
                except Exception:
                    pass  # Preserve the navigation/cancellation error.
                raise
        elif action == "SWITCH_TAB":
            if decision.tab_id not in self.tabs:
                raise ValueError("Unknown tab")
            self.check_page(self.tabs[decision.tab_id]["page"])
            self.active = decision.tab_id
            self.page = self.tabs[self.active]["page"]
            await self.page.bring_to_front()
        elif action == "CLOSE_TAB":
            if decision.tab_id not in self.tabs or len(self.tabs) == 1:
                raise ValueError("Cannot close the last or an unknown tab")
            await self.tabs[decision.tab_id]["page"].close()
            del self.tabs[decision.tab_id]
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

    async def keyboard_policy(self, decision, options, element):
        if element["sensitive"] and decision.key not in {"Tab", "Shift+Tab", "Escape"}:
            raise ValueError("Secret, payment and file fields are unavailable")
        if element["blocked_by_modal"] and decision.key not in {"Tab", "Shift+Tab", "Escape"}:
            raise ValueError("Focus must remain inside the active modal")
        editing = element["role"] in {
            "textbox",
            "searchbox",
            "combobox",
            "listbox",
            "slider",
            "spinbutton",
            "radio",
            "checkbox",
            "switch",
            "option",
        }
        if editing and decision.key not in {"Tab", "Shift+Tab", "Escape"}:
            if not options.get("allow_form_input", False):
                raise ValueError("Enable form input before sending keys to an editable control")
            if element["readonly"]:
                raise ValueError("Read-only controls cannot be edited with keyboard actions")

    async def download(self, decision, options):
        if not options["allow_downloads"]:
            raise ValueError("Downloads are disabled for this task")
        _, element, _ = await self.observer.resolve(decision, self.page, self.active)
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
                headers={
                    "User-Agent": self.runner.user_agent,
                    "X-AdBot-Automation": "true",
                    "X-AdBot-Session": self.runner.id,
                },
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
