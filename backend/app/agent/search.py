"""Scoped search eligibility and explicit query-only POST authorization.

A site owner's attestation is required for POST; HTTP method, names and page
markup cannot establish absence of side effects. Never infer a POST permit.
"""
import json
from urllib.parse import parse_qsl, urlsplit
from typing import Literal

from pydantic import Field, model_validator

from ..schemas import Strict
from ..security import normalize


class ApprovedPostSearch(Strict):
    url: str = Field(min_length=8, max_length=1800)
    query_field: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    verified_read_only: Literal[True]

    @model_validator(mode="after")
    def validate_endpoint(self):
        parsed = urlsplit(self.url)
        if parsed.query or parsed.fragment or "*" in self.url:
            raise ValueError("Use an exact POST search endpoint without query, fragment or wildcard")
        self.url = normalize(self.url)
        return self


def matching_post_endpoint(url, endpoints):
    try:
        if urlsplit(url).fragment or urlsplit(url).query:
            return None
        canonical = normalize(url)
    except (ValueError, TypeError, AttributeError):
        return None
    return next((item for item in endpoints if item.get("verified_read_only") is True
                 and item.get("url") == canonical), None)


def validate_post_endpoints(endpoints, policy):
    seen = set()
    for item in endpoints:
        validated = ApprovedPostSearch.model_validate(item).model_dump()
        url = policy.check(validated["url"])
        if url in seen:
            raise ValueError("Duplicate approved POST search endpoint")
        seen.add(url)


def approved_post_payload(url, content_type, body, query, endpoints):
    endpoint = matching_post_endpoint(url, endpoints)
    if not endpoint or not isinstance(body, str) or len(body.encode()) > 4096:
        return False
    field = endpoint["query_field"]
    mime = content_type.split(";", 1)[0].strip().lower()
    try:
        if mime == "application/json":
            # Keep duplicate keys visible, and distinguish objects from arrays.
            class ObjectPairs(list):
                pass
            pairs = json.loads(body, object_pairs_hook=ObjectPairs)
            if not isinstance(pairs, ObjectPairs):
                return False
        elif mime == "application/x-www-form-urlencoded":
            pairs = parse_qsl(body, keep_blank_values=True, strict_parsing=True, max_num_fields=2)
        else:
            return False
    except (ValueError, TypeError, UnicodeError):
        return False
    return pairs == [(field, query)]


def search_interface(element, endpoints=()):
    """Return a candidate kind, never permission to send arbitrary requests."""
    if (not element.get("actionable") or element.get("visible") is False
            or any(element.get(key) for key in ("disabled", "readonly", "sensitive", "blocked_by_modal"))):
        return None
    tag, role, kind = element.get("tag"), element.get("role"), element.get("type")
    hints = element.get("search_interface") or {}
    native = tag == "input" and kind in {"search", "text", ""}
    custom = (tag == "textarea" or hints.get("editable") is True) and role in {"searchbox", "textbox", "combobox"}
    if not (native or custom) or role not in {"searchbox", "textbox", "combobox"}:
        return None
    if not (role == "searchbox" or kind == "search" or hints.get("search_semantics") is True
            or (element.get("form") or {}).get("search")):
        return None
    form = element.get("form")
    if form:
        try:
            url = form.get("action") or ""
            if urlsplit(url).fragment:
                return None
            normalize(url)
        except ValueError:
            return None
        if form.get("method") == "POST":
            return "approved_post" if matching_post_endpoint(url, endpoints) else None
        if form.get("method") != "GET":
            return None
        return "native_get" if native else "scripted_get"
    return "scripted"


SUGGESTIONS = r"""e => {
 const norm=s=>String(s||'').trim().replace(/\s+/g,' ');
 const visible=n=>!!n.getClientRects().length&&getComputedStyle(n).visibility==='visible'&&!n.closest('[hidden],[inert],[aria-hidden=true],[aria-disabled=true]');
 const roots=[...(e.getAttribute('aria-controls')||'').split(/\s+/),...(e.getAttribute('aria-owns')||'').split(/\s+/)]
   .filter(Boolean).map(id=>document.getElementById(id)).filter(Boolean);
 const scope=e.closest('[role=search],search,form');
 if(scope) roots.push(...scope.querySelectorAll('[role=listbox],[role=menu]'));
 const options=[...new Set(roots.flatMap(r=>[...r.querySelectorAll('[role=option],[role=menuitem],a[href]')]))]
   .filter(n=>visible(n)&&!n.matches(':disabled')).slice(0,24);
 return options.map(n=>({label:norm(n.getAttribute('aria-label')||n.innerText).slice(0,180),role:n.getAttribute('role')||n.tagName.toLowerCase()})).filter(n=>n.label);
}"""


SUGGESTION_TARGET = r"""(e,query) => {
 const norm=s=>String(s||'').trim().replace(/\s+/g,' ').toLowerCase();
 const roots=[...(e.getAttribute('aria-controls')||'').split(/\s+/),...(e.getAttribute('aria-owns')||'').split(/\s+/)]
   .filter(Boolean).map(id=>document.getElementById(id)).filter(Boolean);
 const scope=e.closest('[role=search],search,form');
 if(scope) roots.push(...scope.querySelectorAll('[role=listbox],[role=menu]'));
 const found=[...new Set(roots.flatMap(r=>[...r.querySelectorAll('[role=option],[role=menuitem],a[href]')]))]
   .filter(n=>!!n.getClientRects().length&&getComputedStyle(n).visibility==='visible'&&!n.closest('[hidden],[inert],[aria-hidden=true],[aria-disabled=true]')&&!n.matches(':disabled')&&norm(n.getAttribute('aria-label')||n.innerText)===norm(query));
 return found.length===1?found[0]:null;
}"""


SEARCH_BUTTON = r"""e => {
 const scope=e.closest('[role=search],search,form');
 if(!scope) return null;
 const found=[...scope.querySelectorAll('button,[role=button],input[type=submit]')]
   .filter(n=>!!n.getClientRects().length&&getComputedStyle(n).visibility==='visible'&&!n.matches(':disabled')&&!n.closest('[hidden],[inert],[aria-hidden=true],[aria-disabled=true]')&&/^(search|find|go|submit search)$/i.test((n.getAttribute('aria-label')||n.innerText||n.value||'').trim())&&!['formaction','formmethod','formtarget','formenctype','formnovalidate'].some(a=>n.hasAttribute(a)));
 return found.length===1?found[0]:null;
}"""


SAFE_FORM = r"""e => {
 const form=e.form||e.closest('form');
 if(!form) return true;
 if(form.target&&form.target!=='_self') return false;
 if(e.matches('input,textarea')&&!e.name) return false;
 return [...form.elements].every(x=>x===e||x.disabled||
   (['submit','image'].includes(x.type)?
     !x.name&&x.type!=='image'&&!['formaction','formmethod','formtarget','formenctype','formnovalidate'].some(a=>x.hasAttribute(a)):
     !x.name&&!x.required&&!['password','file'].includes(x.type)));
}"""

SEARCH_STATE = r"""() => {
 const scope=document.querySelector('main,[role=main]')||document.body;
 const parts=[];
 const walker=document.createTreeWalker(scope,NodeFilter.SHOW_TEXT);
 let n,count=0,length=0;
 while((n=walker.nextNode())&&count++<2500&&length<18000){
   const e=n.parentElement;
   if(!e||!e.getClientRects().length||getComputedStyle(e).visibility!=='visible'||
      e.closest('script,style,template,[hidden],[aria-hidden=true],form,search,[role=search],[role=listbox],[role=menu],[role=status],[role=progressbar],[contenteditable=true]')) continue;
   const text=n.textContent.trim();
   if(text){parts.push(text);length+=text.length;}
 }
 return {url:location.href,text:parts.join(' ').slice(0,18000),busy:!!document.querySelector('[aria-busy=true]')};
}"""


async def execute_scoped_search(controller, decision, locator, element, binding, options):
    """Type, inspect suggestions, optionally submit, then observe settled results."""
    import asyncio
    import time

    from playwright.async_api import Error as BrowserError
    from .discovery import search_query_allowed
    from .semantics import METADATA

    page, engine = controller.page, controller.engine
    endpoints = options.get("approved_post_search", [])
    query = decision.text
    kind = search_interface(element, endpoints)
    if not kind or not search_query_allowed(controller.runner.objective, query):
        raise ValueError("Search requires an eligible observed search control and objective-derived query")
    target = binding if binding is not None else locator
    live = await target.evaluate(METADATA)
    if search_interface(live, endpoints) != kind or live.get("form") != element.get("form"):
        raise ValueError("Search control changed since observation")
    if not await target.evaluate(SAFE_FORM):
        raise ValueError("Search form contains unrelated fields or ambiguous submission controls")
    if live.get("form"):
        await controller.runner.permitted(live["form"]["action"])
        if kind == "approved_post":
            endpoint = matching_post_endpoint(live["form"]["action"], endpoints)
            if await target.evaluate("e=>e.name||''") != endpoint["query_field"]:
                raise ValueError("Native POST search field does not match its approved query parameter")
    if controller.search_scope is not None or controller.mutation or controller.egress_grant:
        raise ValueError("Another browser request authorization is still active")
    budget = min(8.0, max(0.0, controller.runner.deadline - time.time() - 1))
    if budget <= 0:
        raise ValueError("Insufficient remaining time for search")
    scope = {"page": page, "query": query, "endpoints": endpoints, "until": time.monotonic() + budget,
             "remaining": 2, "approved": 0, "blocked": 0}
    pending = set()
    network = {"requests": 0, "finished": 0}

    def on_request(request):
        if request.resource_type in {"xhr", "fetch", "document"}:
            pending.add(request)
            network["requests"] += 1

    def on_done(request):
        if request in pending:
            pending.discard(request)
            network["finished"] += 1

    async def read_state():
        try:
            return await page.evaluate(SEARCH_STATE)
        except BrowserError:
            if page.is_closed():
                raise
            return None

    async def suggestions():
        try:
            if await target.evaluate("e=>e.isConnected"):
                return await target.evaluate(SUGGESTIONS)
        except BrowserError:
            if page.is_closed():
                raise
        return []

    async def settle(before, seconds, *, inspect_suggestions=False):
        end = min(scope["until"], time.monotonic() + seconds)
        latest, previous, stable_since = None, None, time.monotonic()
        choices = []
        while time.monotonic() < end:
            await asyncio.sleep(0.1)
            latest = await read_state()
            if latest is None:
                continue
            choices = await suggestions() if inspect_suggestions else []
            signature = (latest["url"], latest["text"], latest["busy"], json.dumps(choices))
            if signature != previous:
                previous, stable_since = signature, time.monotonic()
            changed = latest["url"] != before["url"] or latest["text"] != before["text"]
            if (changed or choices) and not latest["busy"] and not pending and time.monotonic() - stable_since >= 0.35:
                break
        return latest or before, choices

    async def click_scoped(script, arg=None):
        if not await target.evaluate("e=>e.isConnected"):
            return False
        handle = await target.evaluate_handle(script, arg) if arg is not None else await target.evaluate_handle(script)
        try:
            control = handle.as_element()
            if control is None:
                return False
            metadata = await control.evaluate(METADATA)
            if (not metadata["actionable"] or metadata["sensitive"] or metadata["blocked_by_modal"]
                    or metadata["role"] not in {"option", "menuitem", "link", "button"}):
                return False
            if metadata.get("href"):
                await controller.runner.permitted(metadata["href"])
            form = metadata.get("form")
            if form and (not live.get("form") or any(form[k] != live["form"][k] for k in ("action", "method"))):
                return False
            if not await target.evaluate(SAFE_FORM):
                return False
            await control.click(timeout=engine.timeout_ms)
            return True
        finally:
            await handle.dispose()

    before = await read_state()
    if before is None:
        raise ValueError("Search page changed before input")
    controller.search_scope = scope
    page.on("request", on_request)
    page.on("requestfinished", on_done)
    page.on("requestfailed", on_done)
    strategy, choices = "typed", []
    try:
        with engine.phase("search", interface=kind):
            await engine.actionable(locator)
            engine.dispatch_started = True
            if decision.input_method == "keyboard":
                await target.fill("")
                if binding is not None:
                    await binding.type(query, timeout=engine.timeout_ms)
                else:
                    await locator.press_sequentially(query, timeout=engine.timeout_ms)
            else:
                await target.fill(query, timeout=engine.timeout_ms)
            after, choices = await settle(before, 1.8, inspect_suggestions=True)
            changed = after["url"] != before["url"] or after["text"] != before["text"]
            if after["url"] != before["url"]:
                strategy = "live_navigation"
            elif choices:
                if await click_scoped(SUGGESTION_TARGET, query):
                    strategy = "exact_suggestion"
                    after, _ = await settle(before, 3.0)
                else:
                    strategy = "suggestions_observed"
            elif changed and (kind.startswith("scripted") or network["finished"]):
                strategy = "live_results"
            elif pending:
                strategy = "pending_results"
                after, choices = await settle(before, 3.0, inspect_suggestions=True)
            elif time.monotonic() < scope["until"] and await target.evaluate("e=>e.isConnected"):
                current = await target.evaluate(METADATA)
                if search_interface(current, endpoints) != kind or not await target.evaluate(SAFE_FORM):
                    raise ValueError("Search control changed before submission")
                if current.get("form"):
                    if current["form"]["action"] != live["form"]["action"] or current["form"]["method"] != live["form"]["method"]:
                        raise ValueError("Search form destination changed before submission")
                    await controller.runner.permitted(current["form"]["action"])
                if kind.startswith("scripted") and await click_scoped(SEARCH_BUTTON):
                    strategy = "search_button"
                else:
                    await target.press("Enter", timeout=engine.timeout_ms)
                    strategy = "enter"
                after, choices = await settle(before, 3.0, inspect_suggestions=True)
            final = await read_state() or after
            content_changed = final["url"] != before["url"] or final["text"] != before["text"]
            return {"interaction": {"changed": content_changed or bool(choices),
                                    "content_changed": content_changed,
                                    "verified": content_changed,
                                    "verification": "Observed search content change, not evidence of task completion",
                                    "search": {"interface": kind, "strategy": strategy,
                                               "suggestions": choices[:12], "requests": network["requests"],
                                               "responses": network["finished"], "pending": len(pending),
                                               "approved_posts": scope["approved"], "blocked_posts": scope["blocked"]}}}
    finally:
        page.remove_listener("request", on_request)
        page.remove_listener("requestfinished", on_done)
        page.remove_listener("requestfailed", on_done)
        controller.search_scope = None
        controller.egress_grant = None
        controller.mutation = None
