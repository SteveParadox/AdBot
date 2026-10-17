"""Deterministic Playwright input, bounded state waits and auditable outcomes."""

import hashlib
import json
import time
from contextlib import contextmanager

from playwright.async_api import TimeoutError as PlaywrightTimeout

# Values participate in change detection but never appear in persisted traces.
STATE = """() => JSON.stringify({url:location.href,ready:document.readyState,
 text:document.body.innerText.slice(0,18000),y:Math.round(scrollY),height:document.documentElement.scrollHeight,
 focus:[document.activeElement?.tagName,document.activeElement?.id,document.activeElement?.getAttribute('aria-label')],
 controls:[...document.querySelectorAll('input,textarea,select,button,[aria-expanded],[aria-busy]')].slice(0,160).map(e=>
 [e.tagName,e.type==='password'||e.type==='file'?'':e.value,e.checked,e.disabled,e.getAttribute('aria-expanded'),e.getAttribute('aria-busy'),!!e.getClientRects().length])})"""


class InteractionEngine:
    def __init__(self, timeout_ms=2000):
        self.timeout_ms = min(max(timeout_ms, 100), 5000)
        self.trace = []
        self.scroll_history = {}
        self.repeats = {}

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

    async def changed(self, page, before):
        with self.phase("waiting", condition="observable UI change", timeout_ms=self.timeout_ms):
            try:
                await page.wait_for_function(f"before => ({STATE})() !== before", arg=before, timeout=self.timeout_ms)
                return True
            except PlaywrightTimeout:
                return False

    async def actionable(self, locator, pointer=False):
        await locator.wait_for(state="visible", timeout=self.timeout_ms)
        if not await locator.is_enabled():
            raise ValueError("Target is disabled")
        if pointer:
            # Playwright checks visibility, stability, enabled state and hit testing.
            await locator.click(trial=True, timeout=self.timeout_ms)

    async def perform(self, page, decision, locator=None, tab_id="t1"):
        action = decision.decision
        before = await self.state(page)
        # Use semantic action parameters, excluding the model's varying explanations.
        key = hashlib.sha256(
            (
                before
                + json.dumps(
                    {
                        k: decision.model_dump()[k]
                        for k in ("decision", "target", "direction", "key", "text", "input_method")
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
            if action == "HOVER":
                await locator.hover(timeout=self.timeout_ms)
            elif action == "FOCUS":
                await locator.focus(timeout=self.timeout_ms)
            elif action == "CLICK":
                await locator.click(timeout=self.timeout_ms)
            elif action in {"TYPE", "SEARCH"}:
                if decision.input_method == "keyboard":
                    await locator.fill("")
                    await locator.press_sequentially(decision.text, timeout=self.timeout_ms)
                else:
                    await locator.fill(decision.text, timeout=self.timeout_ms)
                if action == "SEARCH":
                    await locator.press("Enter", timeout=self.timeout_ms)
            elif action == "PRESS_KEY":
                await page.keyboard.press(decision.key)
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
                            0, int(page.viewport_size["height"] * 0.7) * (1 if decision.direction == "down" else -1)
                        )
            elif action != "WAIT":
                raise ValueError("Unsupported interaction")
        changed = await self.changed(page, before)
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
                verified = await locator.evaluate("e => document.activeElement===e")
            elif action == "TYPE":
                verified = await locator.input_value() == decision.text
            if decision.expected_text:
                verified = decision.expected_text in data["text"]
            if action == "SCROLL" and not changed:
                history.pop()
            outcome = {
                "changed": changed,
                "verified": verified,
                "verification": "expected text"
                if decision.expected_text
                else "input value"
                if action == "TYPE"
                else "focus"
                if action == "FOCUS"
                else "observable UI change",
                "state_digest": hashlib.sha256(after.encode()).hexdigest(),
                "scroll": {"y": data["y"], "height": data["height"]},
            }
        if decision.expected_text and not verified:
            raise ValueError("Expected UI text did not appear; inspect and replan")
        return {"interaction": outcome}
