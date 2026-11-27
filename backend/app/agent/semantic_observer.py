"""Native ARIA semantics and identity-bound, observation-scoped targets."""

import asyncio
import hashlib
import json
import re
import time

from playwright.async_api import Error as BrowserError

from .memory import fingerprint
from .semantics import CONTROL_SELECTOR, DOM, METADATA

ARIA_ROLES = set(
    "alert alertdialog application article banner blockquote button caption cell checkbox code columnheader combobox complementary contentinfo definition deletion dialog directory document emphasis feed figure form generic grid gridcell group heading img insertion link list listbox listitem log main marquee math menu menubar menuitem menuitemcheckbox menuitemradio meter navigation none note option paragraph presentation progressbar radio radiogroup region row rowgroup rowheader scrollbar search searchbox separator slider spinbutton status strong subscript superscript switch tab table tablist tabpanel term textbox time timer toolbar tooltip tree treegrid treeitem".split()
)


def redact(text):
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~-]{12,}", r"\1[redacted]", text)
    return re.sub(r"(?i)((?:api[_-]?key|password|access[_-]?token|secret)\s*[:=]\s*)[^\s,;]+", r"\1[redacted]", text)


def native_semantics(snapshot, fallback):
    first = snapshot.splitlines()[0].strip() if snapshot else ""
    match = re.match(r'^- ([a-z][a-z0-9-]*)(?: ("(?:[^"\\]|\\.)*"))?', first)
    if not match or match[1] in {"text", "generic"}:
        return fallback["role"] if fallback["role"] in ARIA_ROLES else "generic", fallback["name"], "dom_fallback"
    try:
        name = json.loads(match[2]) if match[2] else ""
    except (ValueError, TypeError):
        return fallback["role"] if fallback["role"] in ARIA_ROLES else "generic", fallback["name"], "dom_fallback"
    return match[1], name, "playwright_aria"


class Observer:
    def __init__(self):
        self.registry, self.bindings, self.previous = {}, {}, {}
        self.private_targets = {}
        self.document = self.page = self.tab_id = None
        self.generation = 0
        self.secrets = []
        self.directory_cache = None
        self.structural_groups = {}

    def safe_text(self, text):
        for secret in self.secrets:
            text = text.replace(secret, "[redacted]")
        return redact(text)

    def sanitize(self, value):
        if isinstance(value, str):
            return self.safe_text(value)
        if isinstance(value, list):
            return [self.sanitize(v) for v in value]
        if isinstance(value, dict):
            return {k: self.sanitize(v) for k, v in value.items()}
        return value

    async def observe(self, page, tab_id, goal="", _retry=0, *, directory=False, structure=False, research=False):
        start = time.perf_counter()
        await asyncio.gather(*(h.dispose() for h in self.bindings.values()), return_exceptions=True)
        self.bindings, self.registry, self.private_targets = {}, {}, {}
        same_document = False
        if self.document is not None and self.page == page:
            try:
                same_document = await self.document.evaluate("s=>s.document===document")
            except BrowserError:
                pass
        if not same_document:
            if self.document is not None:
                if self.directory_cache is not None and self.page is not None and not self.page.is_closed():
                    try:
                        await self.document.evaluate("s=>{s.watch?.disconnect();s.events?.abort()}")
                    except BrowserError:
                        pass
                await self.document.dispose()
            self.directory_cache = None
            self.document = await page.evaluate_handle("({document,nodes:new WeakMap(),next:0})")
            self.generation += 1
        self.page, self.tab_id = page, tab_id
        data = await page.evaluate(DOM)
        if research:
            from .research import READ_RESEARCH, terms

            data["research_chunks"] = await page.evaluate(READ_RESEARCH, sorted(terms(goal))[:100])
        if structure:
            from ..config import settings
            from .structure import READ_STRUCTURE

            structural_groups = await page.evaluate(READ_STRUCTURE, {
                "rows": min(250, settings().agent_collection_batch_rows), "nodes": 1000,
                "individual": structure == "enumeration",
            })
        directory_cache_hit = False
        if directory:
            from ..config import settings
            from .directory import READ_DIRECTORY, directory_link, pagination_element
            limit = settings().agent_collection_batch_rows
            arguments = {"limit": limit, "table": directory in {"table", "table rows"}}
            stamp = await self.document.evaluate(r"""s=>{
                if(!s.watch) {
                    s.revision=0;
                    s.watch=new MutationObserver(()=>s.revision++);
                    s.watch.observe(document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true});
                    s.events=new AbortController();
                    for(const event of ['input','change','scroll','resize','load'])
                        addEventListener(event,()=>s.revision++,{capture:true,signal:s.events.signal});
                }
                if(s.watch.takeRecords().length)s.revision++;
                return [location.href,document.readyState,s.revision,scrollX,scrollY,innerWidth,innerHeight];
            }""")
            key = (tab_id, stamp, limit, arguments["table"])
            cached = self.directory_cache
            if cached is not None and cached[0] == key and time.monotonic() - cached[1] < 0.75:
                data["directory"] = cached[2]
                directory_cache_hit = True
            else:
                data["directory"] = await page.evaluate(READ_DIRECTORY, arguments)
                self.directory_cache = (key, time.monotonic(), data["directory"])
        secrets = data.pop("sensitive_values")
        self.secrets = secrets

        def clean(value):
            if isinstance(value, str):
                for secret in secrets:
                    value = value.replace(secret, "[redacted]")
                return redact(value)
            if isinstance(value, list):
                return [clean(item) for item in value]
            if isinstance(value, dict):
                return {key: clean(item) for key, item in value.items()}
            return value

        all_elements = data.pop("elements")
        words = set(re.findall(r"\w{3,}", goal.lower()))

        def priority(e):
            relevance = len(words & set(re.findall(r"\w{3,}", (e["name"] + " " + str(e["context"])).lower())))
            return (
                e["blocked_by_modal"],
                not e["visible"],
                e["role"] not in {"dialog", "alertdialog"},
                not e["focused"],
                not e["actionable"],
                bool(directory) and not pagination_element(e),
                not (bool(research or structure or directory) and e.get("role") in {"searchbox", "textbox", "combobox"}
                     and (e.get("search_interface", {}).get("search_semantics")
                          or e.get("form", {}) and e["form"].get("search"))),
                -relevance,
                not e["in_view"],
                e["role"] == "link",
                e["index"],
            )

        # A directory-only observation deliberately binds few controls. When
        # the scan found no batch, retain ordinary discovery controls instead.
        compact_directory = bool(directory and data.get("directory"))
        limit = 12 if compact_directory else 80
        eligible = [element for element in all_elements if not element["sensitive"]]
        if compact_directory:
            # Bind forward controls and directory routes. Record extraction reads
            # the visible cards directly, so their individual links need no handles.
            entity = directory if isinstance(directory, str) else None
            eligible = [element for element in eligible if element["role"] in {"dialog", "alertdialog"} or (
                element["visible"] and (pagination_element(element) or directory_link(element, entity))
            )]
        candidates = sorted(eligible, key=priority)[:limit]
        semaphore = asyncio.Semaphore(8)

        async def inspect(element):
            async with semaphore:
                locator = page.locator(CONTROL_SELECTOR).nth(element["index"])
                try:
                    handle = await locator.element_handle(timeout=1500)
                except BrowserError:
                    if page.is_closed():
                        raise
                    return None
                if handle is None:
                    return None
                try:
                    current = await handle.evaluate(METADATA)
                    if current != {k: v for k, v in element.items() if k != "index"}:
                        await handle.dispose()
                        return None
                    token = await handle.evaluate(
                        "(e,s)=>{if(!s.nodes.has(e))s.nodes.set(e,++s.next);return s.nodes.get(e)}", self.document
                    )
                    snapshot = await locator.aria_snapshot(timeout=1500) if element["visible"] else ""
                    role, name, source = native_semantics(snapshot, element)
                    element = {
                        **element,
                        "role": role,
                        "name": name,
                        "accessible_name": name,
                        "semantic_source": source,
                        "node_token": f"{self.generation}:{token}",
                    }
                    resolved, strategy, ambiguous = await self.locate(page, locator, handle, element)
                    element["locator_strategy"], element["ambiguous"] = strategy, ambiguous
                    element["actionable"] = element["actionable"] and not ambiguous
                    return element, resolved, handle
                except BrowserError:
                    await handle.dispose()
                    if page.is_closed():
                        raise
                    return None
                except BaseException:
                    await handle.dispose()
                    raise

        inspected = [item for item in await asyncio.gather(*(inspect(e) for e in candidates)) if item]
        source_url = data.pop("source_url")
        try:
            coherent = await self.document.evaluate("s=>s.document===document") and page.url == source_url
        except BrowserError:
            coherent = False
        if not coherent:
            await asyncio.gather(*(item[2].dispose() for item in inspected), return_exceptions=True)
            if _retry < 1:
                return await self.observe(page, tab_id, goal, _retry=1, directory=directory, structure=structure, research=research)
            raise ValueError("Page changed repeatedly during semantic observation; no coherent evidence available")
        if len(inspected) < len(candidates) and _retry < 1:
            await asyncio.gather(*(item[2].dispose() for item in inspected), return_exceptions=True)
            retried = await self.observe(page, tab_id, goal, _retry=1, directory=directory, structure=structure, research=research)
            retried["observation_metrics"]["read_attempts"] = 2
            retried["observation_metrics"]["duration_ms"] = round((time.perf_counter() - start) * 1000, 2)
            return retried
        data["elements"] = [item[0] for item in inspected]
        data["url"], data["tab_id"] = source_url, tab_id
        data["form_state"] = hashlib.sha256(
            json.dumps(
                [
                    {k: e[k] for k in ("node_token", "value", "checked", "selected", "invalid")}
                    for e in data["elements"]
                ],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        data = clean(data)
        self.structural_groups = {}
        if structure and not any(dialog.get("visible") for dialog in data.get("dialogs", [])):
            from .structure import summarize_structure

            groups = clean(structural_groups)
            self.structural_groups = {group["id"]: group for group in groups}
            data["record_groups"] = summarize_structure(groups, goal if structure == "enumeration" else None)
        data["accessibility"] = "\n".join(
            f"- {e['role']} {json.dumps(e['name'])}" for e in data["elements"] if e["visible"]
        )[:6000]
        snapshot_key = fingerprint(data)[:10]
        for i, (private, locator, handle) in enumerate(inspected):
            public = data["elements"][i]
            public["element_id"] = f"e{snapshot_key}_{i}"
            self.registry[public["element_id"]] = (locator, public)
            self.bindings[public["element_id"]] = handle
            # Redaction is a presentation boundary, not target identity. Raw
            # metadata stays in this bounded, observation-scoped private map.
            self.private_targets[public["element_id"]] = {**private, "element_id": public["element_id"]}
        data["fingerprint"] = fingerprint(data)
        states = {
            e["node_token"]: {
                k: e[k] for k in ("role", "name", "focused", "expanded", "pressed", "checked", "selected", "invalid", "value")
            }
            for e in data["elements"]
        }
        previous = self.previous if same_document else {}
        data["semantic_changes"] = [v for k, v in states.items() if previous.get(k) != v][:12]
        data["removed_controls"] = [
            {"role": value["role"], "name": value["name"]} for key, value in previous.items() if key not in states
        ][:8]
        self.previous = states
        data["focus"] = next((e["element_id"] for e in data["elements"] if e["focused"]), None)
        data["dialogs"] = [
            {k: e[k] for k in ("element_id", "role", "name", "focused", "visible")}
            for e in data["elements"]
            if e["role"] in {"dialog", "alertdialog"} and e["visible"]
        ]
        data["feedback"] = [
            {"role": e["role"], "name": e["name"], "text": e["text"], "busy": e["busy"]}
            for e in data["elements"]
            if e["live"]
        ][:10]
        data["observation_metrics"] = {
            "candidates": len(all_elements),
            "included": len(data["elements"]),
            "truncated": data.pop("candidate_limit") or sum(not e["sensitive"] for e in all_elements) > limit,
            "withheld_sensitive": sum(e["sensitive"] for e in all_elements),
            "changed_during_inspection": len(candidates) - len(data["elements"]),
            "read_attempts": _retry + 1,
            "collection_cache_hit": directory_cache_hit,
            "native_semantics": sum(e["semantic_source"] == "playwright_aria" for e in data["elements"]),
            "duration_ms": round((time.perf_counter() - start) * 1000, 2),
        }
        data["observation_metrics"]["characters"] = len(json.dumps(data, ensure_ascii=False))
        return data

    async def locate(self, page, fallback, handle, element):
        name, role = element["name"], element["role"]
        scopes = [(page, "")]
        context = element.get("context")
        if context and context["name"] and context["role"] in ARIA_ROLES - {"generic"}:
            scopes.insert(0, (page.get_by_role(context["role"], name=context["name"], exact=True), "context + "))
        if context and context["heading"]:
            scopes.insert(
                0,
                (
                    page.locator(context["tag"]).filter(
                        has=page.get_by_role("heading", name=context["heading"], exact=True)
                    ),
                    "context heading + ",
                ),
            )
        attempts = []
        for scope, prefix in scopes:
            if name and role != "generic":
                attempts.append((scope.get_by_role(role, name=name, exact=True), prefix + "role + accessible name"))
            for label in element["labels"][:2]:
                attempts.append((scope.get_by_label(label, exact=True), prefix + "associated label"))
            if element["placeholder"]:
                attempts.append((scope.get_by_placeholder(element["placeholder"], exact=True), prefix + "placeholder"))
        if element["test_id"]:
            attempts.append((page.get_by_test_id(element["test_id"]), "test identifier"))
        if element["dom_id"]:
            attempts.append((page.locator("[id=" + json.dumps(element["dom_id"]) + "]"), "unique DOM identifier"))
        if element["href"] and name:
            attempts.append(
                (
                    page.get_by_role(role, name=name, exact=True).and_(
                        page.locator("a[href=" + json.dumps(element["href"]) + "]")
                    ),
                    "role + name + destination",
                )
            )
        for locator, strategy in attempts:
            if await locator.count() == 1 and await locator.evaluate("(e,original)=>e===original", handle):
                return locator, strategy, False
        count = await page.get_by_role(role, name=name, exact=True).count() if role != "generic" else 0
        return fallback, "bound DOM fallback", count > 1

    def target(self, decision):
        if not decision.target or decision.target.element_id not in self.registry:
            raise ValueError("Action must reference an element from the latest observation")
        return self.registry[decision.target.element_id]

    async def resolve(self, decision, page, tab_id):
        locator, _ = self.target(decision)
        element = self.private_targets[decision.target.element_id]
        handle = self.bindings[decision.target.element_id]
        if element["ambiguous"]:
            raise ValueError("Ambiguous semantic target; inspect context or request clarification")
        if self.page != page or self.tab_id != tab_id or not await handle.evaluate("e=>e.isConnected"):
            raise ValueError("Target changed or detached since observation; reobserve")
        if not await locator.evaluate("(e,original)=>e===original", handle):
            raise ValueError("Target changed: locator resolved to a replaced control")
        current = await handle.evaluate(METADATA)
        role, name, _ = native_semantics(await locator.aria_snapshot(timeout=1500), current)
        keys = ("disabled", "readonly", "href", "form", "expanded", "checked", "selected", "value", "blocked_by_modal")
        if decision.decision == "SEARCH":
            keys = (*keys, "search_interface", "controls", "active_descendant")
        if role != element["role"] or name != element["name"] or any(current[k] != element[k] for k in keys):
            raise ValueError("Target changed since observation; reobserve")
        if not current["actionable"]:
            raise ValueError("Target is hidden, disabled, sensitive, or outside the active modal")
        return locator, element, handle
