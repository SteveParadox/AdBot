"""Deterministic Playwright input, bounded state waits and auditable outcomes."""

import asyncio
import hashlib
import json
import random
import time
from contextlib import contextmanager

from playwright.async_api import TimeoutError as PlaywrightTimeout
from .. import polymorph
from .semantics import METADATA

VISIBLE_TEXT = "document.body.innerText.slice(0,18000)"

# Values participate in change detection but never appear in persisted traces.
STATE = """() => JSON.stringify({url:location.href,ready:document.readyState,
 text:VISIBLE_TEXT,y:Math.round(scrollY),height:document.documentElement.scrollHeight,
 focus:[document.activeElement?.tagName,document.activeElement?.id,document.activeElement?.getAttribute('aria-label')],
 controls:[...document.querySelectorAll('input,textarea,select,button,[role],[aria-expanded],[aria-busy]')].slice(0,250).map(e=>
 [e.tagName,e.type==='password'||e.type==='file'?'':e.value,e.checked,e.disabled,e===document.activeElement,e.getAttribute('aria-expanded'),e.getAttribute('aria-checked'),e.getAttribute('aria-selected'),e.getAttribute('aria-activedescendant'),e.getAttribute('aria-busy'),!!e.getClientRects().length])})""".replace("VISIBLE_TEXT", VISIBLE_TEXT)


class ActionabilityTimeout(PlaywrightTimeout):
    """The trial timed out before a real input action was dispatched."""


class InteractionEngine:
    def __init__(self, timeout_ms=2000):
        self.timeout_ms = min(max(timeout_ms, 100), 5000)
        self.trace = []
        self.scroll_history = {}
        self.repeats = {}
        self.dispatch_started = False
        self.keyboard_hops = {}
        self.dialog_openers = {}

    @contextmanager
    def phase(self, name, **details):
        start, clock = time.time(), time.monotonic()
        item = {"phase": name, "started_at": start, **details}
        self.trace.append(item)
        try:
            yield
            item["status"] = "completed"
        except BaseException:
            item["status"] = "failed"
            raise
        finally:
            item["ended_at"] = time.time()
            item["duration_ms"] = round((time.monotonic() - clock) * 1000, 2)

    async def state(self, page):
        return await page.evaluate(STATE)

    async def changed(self, page, before, *, require_content=False):
        predicate = f"before => ({STATE})() !== before"
        argument = before
        if require_content:
            predicate = f"before => location.href !== before.url || {VISIBLE_TEXT} !== before.text"
            state = json.loads(before)
            argument = {key: state[key] for key in ("url", "text")}
        condition = "URL or visible text change" if require_content else "observable UI change"
        with self.phase("waiting", condition=condition, timeout_ms=self.timeout_ms):
            try:
                await page.wait_for_function(predicate, arg=argument, timeout=self.timeout_ms)
                return True
            except PlaywrightTimeout:
                return False

    async def actionable(self, locator, pointer=False):
        await locator.wait_for(state="visible", timeout=self.timeout_ms)
        if not await locator.is_enabled():
            raise ValueError("Target is disabled")
        if pointer:
            # Playwright checks visibility, stability, enabled state and hit testing.
            try:
                await locator.click(trial=True, timeout=self.timeout_ms)
            except PlaywrightTimeout as exc:
                raise ActionabilityTimeout("Target could not receive pointer input before the action deadline") from exc

    async def perform(self, page, decision, locator=None, tab_id="t1", binding=None, *, require_content=False):
        self.dispatch_started = False
        action = decision.decision
        idempotent = False
        target = binding if binding is not None else locator
        expected_control = None
        if action == "CLICK" and target is not None:
            control = await target.evaluate(METADATA)
            if control["role"] in {"checkbox", "radio", "switch"} and control["checked"] in {
                True,
                False,
                "true",
                "false",
            }:
                expected_control = {
                    "state": "checked",
                    "value": True if control["role"] == "radio" else control["checked"] not in {True, "true"},
                }
            elif control["role"] in {"tab", "option"} and control["selected"] is not None:
                expected_control = {"state": "selected", "value": True}
            elif control["expanded"] is not None:
                expected_control = {"state": "expanded", "value": not control["expanded"]}
        before = await self.state(page)
        if action == "PRESS_KEY" and decision.key in {"Tab", "Shift+Tab"}:
            self.keyboard_hops[tab_id] = self.keyboard_hops.get(tab_id, 0) + 1
            if self.keyboard_hops[tab_id] > 32:
                raise ValueError("Keyboard traversal budget reached; focus a relevant observed control")
        else:
            self.keyboard_hops[tab_id] = 0
        dialogs_before = await self.dialogs(page)
        focus_before = await page.evaluate(
            "() => ({tag:document.activeElement?.tagName,id:document.activeElement?.id,role:document.activeElement?.getAttribute('role')})"
        )
        # Use semantic action parameters, excluding the model's varying explanations.
        key = hashlib.sha256(
            (
                before
                + json.dumps(
                    {
                        k: decision.model_dump()[k]
                        for k in ("decision", "target", "direction", "key", "text", "input_method", "checked", "option")
                    },
                    sort_keys=True,
                )
            ).encode()
        ).hexdigest()
        if self.repeats.get(key, 0) >= 2:
            raise ValueError("Repeated interaction on unchanged UI; inspect and replan")
        self.repeats[key] = self.repeats.get(key, 0) + 1
        if len(self.repeats) > 100:
            self.repeats = {key: self.repeats[key]}
        with self.phase("action", action=action, input_method=decision.input_method):
            if locator is not None:
                await self.actionable(locator, action in {"CLICK", "HOVER"})
            if binding is not None and not await binding.evaluate("e=>e.isConnected"):
                raise ValueError("Target detached before input dispatch; reobserve")
            # Trial checks above dispatch no input. From this point a failed write
            # may have reached the page even if its confirmation was not observed.
            self.dispatch_started = False
            if action == "HOVER":
                await asyncio.sleep(polymorph.get_random_wait_time(0.01, 0.05))
                await target.hover(timeout=self.timeout_ms)
            elif action == "FOCUS":
                idempotent = await target.evaluate("e=>e===document.activeElement")
                if binding is not None:
                    await asyncio.wait_for(binding.focus(), self.timeout_ms / 1000)
                else:
                    await target.focus(timeout=self.timeout_ms)
            elif action == "CLICK":
                await asyncio.sleep(polymorph.get_random_wait_time(0.01, 0.03))
                self.dispatch_started = True
                await target.click(timeout=self.timeout_ms)
            elif action in {"TYPE", "SEARCH"}:
                self.dispatch_started = True
                if decision.input_method == "keyboard":
                    await target.fill("")
                    await asyncio.sleep(polymorph.get_random_wait_time(0.05, 0.15))
                    if binding is not None:
                        await binding.type(decision.text, timeout=self.timeout_ms)
                    else:
                        await target.press_sequentially(decision.text, timeout=self.timeout_ms)
                else:
                    await asyncio.sleep(polymorph.get_random_wait_time(0.05, 0.1))
                    await target.fill(decision.text, timeout=self.timeout_ms)
                if action == "SEARCH":
                    await asyncio.sleep(polymorph.get_random_wait_time(0.1, 0.2))
                    await target.press("Enter", timeout=self.timeout_ms)
            elif action == "SELECT_OPTION":
                options = await target.evaluate(
                    "e=>[...e.options].map(o=>({label:o.label,value:o.value,disabled:o.disabled||!!o.closest('optgroup[disabled]')}))"
                )
                matches = [o for o in options if not o["disabled"] and decision.option in {o["label"], o["value"]}]
                if len(matches) != 1:
                    raise ValueError("Native option is unavailable or ambiguous")
                idempotent = await target.evaluate("(e,value)=>e.value===value", matches[0]["value"])
                if not idempotent:
                    self.dispatch_started = True
                    await target.select_option(value=matches[0]["value"], timeout=self.timeout_ms)
            elif action == "SET_CHECKED":
                native = await target.evaluate("e=>e.matches('input[type=checkbox],input[type=radio]')")
                if native:
                    idempotent = await target.evaluate("(e,value)=>e.checked===value", decision.checked)
                    if not idempotent:
                        self.dispatch_started = True
                        await target.set_checked(decision.checked, timeout=self.timeout_ms)
                else:
                    current = await target.get_attribute("aria-checked")
                    if current not in {"true", "false"}:
                        raise ValueError("Custom boolean control has no supported checked state")
                    if (current == "true") != decision.checked:
                        self.dispatch_started = True
                        await target.click(timeout=self.timeout_ms)
                    else:
                        idempotent = True
            elif action == "PRESS_KEY":
                key_name = " " if decision.key == "Space" else decision.key
                self.dispatch_started = True
                if target is not None:
                    await target.press(key_name, timeout=self.timeout_ms)
                else:
                    await page.keyboard.press(key_name)
            elif action in {"SCROLL", "SCROLL_BACK"}:
                history = self.scroll_history.setdefault(tab_id, [])
                current = await page.evaluate("() => ({x:scrollX,y:scrollY})")
                if action == "SCROLL_BACK":
                    if not history:
                        raise ValueError("No previously viewed section in this tab")
                    await page.evaluate("p => scrollTo(p.x,p.y)", history.pop())
                else:
                    history.append(current)
                    del history[:-20]
                    if locator is not None:
                        await locator.scroll_into_view_if_needed(timeout=self.timeout_ms)
                        # Keep content clear of sticky navigation.
                        await locator.evaluate("e => e.scrollIntoView({block:'center',behavior:'instant'})")
                    else:
                        await page.mouse.wheel(
                            0,
                            int(page.viewport_size["height"] * random.uniform(0.5, 0.9))
                            * (1 if decision.direction == "down" else -1),
                        )
            elif action != "WAIT":
                raise ValueError("Unsupported interaction")
        changed = False if idempotent else await self.changed(page, before, require_content=require_content)
        focus_recovery = None
        if action == "PRESS_KEY" and decision.key in {"Tab", "Shift+Tab"}:
            dialogs = await self.dialogs(page)
            if dialogs and not dialogs[-1]["focus_contained"]:
                # Some native engines traverse browser chrome at a dialog edge.
                # Restore within the observed modal using real focus, once only.
                modals = page.locator(
                    "dialog[open]:modal:visible,dialog[open][aria-modal=true]:visible,[role=dialog][aria-modal=true]:visible,[role=alertdialog][aria-modal=true]:visible"
                )
                # After focus is lost, DOM order cannot establish top-layer
                # authority. Recover only a single unambiguous modal.
                if await modals.count() != 1:
                    raise ValueError("Modal focus authority is ambiguous; inspect and replan")
                modal = modals.first
                controls = await modal.locator(
                    "button,input,select,textarea,a[href],[tabindex],[contenteditable=true]"
                ).all()
                if decision.key == "Shift+Tab":
                    controls.reverse()
                for control in controls:
                    if (
                        await control.is_visible()
                        and await control.is_enabled()
                        and await control.evaluate("e=>e.tabIndex>=0&&!e.closest('[inert]')")
                    ):
                        await control.focus(timeout=self.timeout_ms)
                        focus_recovery = "Native focus restored within active modal after traversal left its scope"
                        break
                if not all(d["focus_contained"] for d in (await self.dialogs(page))[-1:]):
                    raise ValueError("Modal focus containment could not be restored")
        if action in {"SCROLL", "SCROLL_BACK"}:
            # Give the wheel/scroll event a render opportunity before inspecting lazy content.
            await page.evaluate(
                "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
            )
        if await page.locator('[aria-busy="true"]').count():
            with self.phase("loading", condition="aria-busy cleared", timeout_ms=self.timeout_ms):
                try:
                    await page.wait_for_function(
                        "() => !document.querySelector('[aria-busy=true]')", timeout=self.timeout_ms
                    )
                except PlaywrightTimeout:
                    pass
        if decision.expected_text:
            with self.phase("waiting", condition="expected text", timeout_ms=self.timeout_ms):
                try:
                    await page.wait_for_function(
                        "text => document.body.innerText.includes(text)",
                        arg=decision.expected_text,
                        timeout=self.timeout_ms,
                    )
                except PlaywrightTimeout:
                    pass
        with self.phase("inspection"):
            after = await self.state(page)
            data = json.loads(after)
            verified = changed
            if action == "FOCUS":
                verified = await target.evaluate("e => document.activeElement===e")
            elif action == "TYPE":
                verified = await target.evaluate(
                    "(e,value)=>(e.isContentEditable?e.textContent:e.value)===value", decision.text
                )
            elif action == "SET_CHECKED":
                verified = await target.evaluate(
                    "(e,value)=>e.matches('input[type=checkbox],input[type=radio]')?e.checked===value:e.getAttribute('aria-checked')===String(value)",
                    decision.checked,
                )
            elif action == "SELECT_OPTION":
                verified = await target.evaluate(
                    "(e,value)=>[...e.selectedOptions].some(o=>o.value===value||o.label===value)", decision.option
                )
            if expected_control:
                end = time.monotonic() + self.timeout_ms / 1000
                while True:
                    verified = await target.evaluate(
                        r"""(e,expect) => {
                        const value=expect.state==='checked'&&e.matches('input[type=checkbox],input[type=radio]')?e.checked:expect.state==='expanded'&&e.tagName==='SUMMARY'?e.parentElement.open:e.getAttribute('aria-'+expect.state)==='true';
                        const controlled=(e.getAttribute('aria-controls')||'').split(/\s+/).filter(Boolean).map(id=>document.getElementById(id));
                        return value===expect.value&&controlled.every(node=>node&&(['selected','expanded'].includes(expect.state)?!!node.getClientRects().length===expect.value:true));
                    }""",
                        expected_control,
                    )
                    if verified or time.monotonic() >= end:
                        break
                    await asyncio.sleep(0.05)
                after = await self.state(page)
                data = json.loads(after)
            if decision.expected_text:
                verified = decision.expected_text in data["text"] and (
                    verified
                    if action in {"TYPE", "FOCUS", "SET_CHECKED", "SELECT_OPTION"} or expected_control
                    else True
                )
            if action == "SCROLL" and not changed:
                history.pop()
            outcome = {
                "changed": changed,
                "content_changed": data["text"] != json.loads(before)["text"],
                "verified": verified,
                "verification": "expected text"
                if decision.expected_text
                else "input value"
                if action == "TYPE"
                else "focus"
                if action == "FOCUS"
                else "checked state"
                if action == "SET_CHECKED"
                else "selected option"
                if action == "SELECT_OPTION"
                else "URL or visible text change"
                if require_content
                else "observable UI change",
                "state_digest": hashlib.sha256(after.encode()).hexdigest(),
                "scroll": {"y": data["y"], "height": data["height"]},
                "key": decision.key if action == "PRESS_KEY" else None,
                "focus_recovery": focus_recovery,
                "expected_control": expected_control,
                "focus_before": focus_before,
                "focus_after": await page.evaluate(
                    "() => ({tag:document.activeElement?.tagName,id:document.activeElement?.id,role:document.activeElement?.getAttribute('role')})"
                ),
            }
            dialogs_after = await self.dialogs(page)
            opened = [d for d in dialogs_after if d["id"] not in {x["id"] for x in dialogs_before}]
            closed = [d for d in dialogs_before if d["id"] not in {x["id"] for x in dialogs_after}]
            for dialog in opened:
                self.dialog_openers[(tab_id, dialog["id"])] = (
                    await target.evaluate("e=>e.id||null") if target is not None else None
                )
            restored = []
            for dialog in closed:
                opener = self.dialog_openers.pop((tab_id, dialog["id"]), None)
                restored.append(outcome["focus_after"]["id"] == opener if opener else None)
            outcome["dialogs"] = {
                "opened": opened,
                "closed": closed,
                "focus_contained": not dialogs_after or dialogs_after[-1]["focus_contained"],
                "focus_restored": restored,
            }
        if decision.expected_text and not verified:
            raise ValueError("Expected UI text did not appear; inspect and replan")
        if action in {"SET_CHECKED", "SELECT_OPTION", "TYPE", "FOCUS"} and not verified:
            raise ValueError("Control state did not match the intended outcome; inspect and replan")
        if expected_control and not verified:
            raise ValueError("Expected semantic control state or controlled content did not appear")
        return {"interaction": outcome}

    async def dialogs(self, page):
        return await page.evaluate(
            """() => {
 const modals=[...document.querySelectorAll('dialog[open],[role=dialog][aria-modal=true],[role=alertdialog][aria-modal=true]')].filter(e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden'&&(e.tagName!=='DIALOG'||e.matches(':modal')||e.getAttribute('aria-modal')==='true'));
 const active=[...modals].reverse().find(e=>e.contains(document.activeElement));
 return [...modals.filter(e=>e!==active),...(active?[active]:[])].slice(-10).map((e,i)=>({id:e.id||'unidentified-modal-'+i,focus_contained:e.contains(document.activeElement)}));
 }"""
        )
