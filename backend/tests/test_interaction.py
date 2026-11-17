"""Real Chromium input and UI outcomes against the local interaction laboratory."""

import time

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

from app.agent.contracts import Decision
from app.agent.interaction import InteractionEngine
from app.agent.observe import Observer
from test_browser import fixture_server  # noqa: F401, F811

pytestmark = pytest.mark.browser


def decision(action, **kwargs):
    return Decision(
        observation="Observed laboratory",
        decision=action,
        reason="Exercise relevant UI",
        confidence=1,
        expected_result="Confirmed UI outcome",
        **kwargs,
    )


@pytest_asyncio.fixture
async def lab(fixture_server):  # noqa: F811
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context(
            viewport={"width": 1000, "height": 700}, extra_http_headers={"X-AdBot-Automation": "true"}
        )
        page = await context.new_page()
        await page.goto("http://127.0.0.1:8765/agent/interactions")
        yield page, InteractionEngine(700), Observer()
        await browser.close()


async def target(observer, page, name):
    observation = await observer.observe(page, "t1")
    item = next(e for e in observation["elements"] if e["name"] == name)
    return {"element_id": item["element_id"]}


async def perform(lab, action, name=None, **kwargs):
    page, engine, observer = lab
    t = await target(observer, page, name) if name else None
    d = decision(action, **({"target": t} if t else {}), **kwargs)
    return await engine.perform(page, d, observer.target(d)[0] if t else None)


async def test_hover_pointer_click_navigation_and_trace(lab):
    page, engine, observer = lab
    assert "Automation marker: true" in await page.inner_text("body")
    assert not await page.get_by_text("Hover release notes", exact=True).is_visible()
    result = await perform(lab, "HOVER", "Resources", expected_text="Hover release notes")
    assert result["interaction"]["verified"]
    result = await perform(lab, "CLICK", "Hover release notes", expected_text="Orion AI will launch in November 2026.")
    assert result["interaction"]["verified"]
    assert page.url.endswith("/agent/article/orion")
    assert {t["phase"] for t in engine.trace} == {"action", "waiting", "inspection"}
    assert all(t["ended_at"] >= t["started_at"] and t["duration_ms"] >= 0 for t in engine.trace)


async def test_focus_keyboard_input_and_tab_navigation(lab):
    page, _, _ = lab
    assert (await perform(lab, "FOCUS", "Keyboard widget"))["interaction"]["verified"]
    result = await perform(
        lab, "TYPE", "Keyboard widget", text="Orion", input_method="keyboard", expected_text="Key: n"
    )
    assert result["interaction"]["verified"]
    assert await page.locator("#widget").input_value() == "Orion"
    await perform(lab, "PRESS_KEY", key="Tab")
    assert await page.get_by_role("button", name="Delayed action").evaluate("e=>e===document.activeElement")
    await perform(lab, "PRESS_KEY", key="Shift+Tab")
    assert await page.locator("#widget").evaluate("e=>e===document.activeElement")


async def test_sticky_target_scroll_back_lazy_and_infinite_scroll(lab):
    page, engine, observer = lab
    await perform(lab, "SCROLL", "Lower release notes")
    box = await page.locator("#section").bounding_box()
    assert box["y"] > 70
    await perform(lab, "SCROLL_BACK")
    assert await page.evaluate("scrollY") == 0
    # Deliberately advance by content-sized increments, inspecting each reveal.
    for batch in (1, 2):
        for _ in range(4):
            await perform(lab, "SCROLL")
            observation = await observer.observe(page, "t1")
            if observation["scroll"]["at_end"]:
                break
        result = await perform(lab, "WAIT", expected_text=f"Loaded batch {batch}")
        assert result["interaction"]["verified"]
    assert "New relevant evidence 2" in await page.inner_text("body")
    assert len(engine.scroll_history["t1"]) <= 20


async def test_disabled_covered_stalled_wait_and_loop_breaker(lab):
    page, engine, _ = lab
    with pytest.raises(ValueError, match="disabled"):
        await perform(lab, "CLICK", "Disabled action")
    with pytest.raises(PlaywrightTimeout):
        await perform(lab, "CLICK", "Covered action")
    # Focus first so no-op clicks cannot count focus movement as progress.
    await page.get_by_role("button", name="No effect", exact=True).focus()
    started = time.monotonic()
    for _ in range(2):
        result = await perform(lab, "CLICK", "No effect")
        assert not result["interaction"]["verified"]
    with pytest.raises(ValueError, match="Repeated interaction"):
        await perform(lab, "CLICK", "No effect")
    assert time.monotonic() - started < 5
    with pytest.raises(ValueError, match="Expected UI text"):
        await perform(lab, "WAIT", expected_text="Never appears")
    assert any(t["status"] == "failed" for t in engine.trace)


async def test_meaningful_wait_delayed_confirmation(lab):
    page, engine, _ = lab
    result = await perform(lab, "CLICK", "Delayed action", expected_text="Delayed confirmation")
    assert result["interaction"]["verified"]
    assert await page.locator("#result").inner_text() == "Delayed confirmation"
    assert any(t.get("condition") == "expected text" for t in engine.trace)


async def test_controller_rejects_changed_link_before_navigation(lab):
    from types import SimpleNamespace
    from app.agent.controller import Controller

    page, _, _ = lab
    runner = SimpleNamespace(cfg={"navigation_timeout_ms": 700})
    controller = Controller(runner, page.context, page, {})
    t = await target(controller.observer, page, "Lower release notes")
    await page.locator("#section").evaluate("e => e.href='/unexpected-destination'")
    with pytest.raises(ValueError, match="Target changed"):
        await controller.act(decision("CLICK", target=t), {})
    assert page.url.endswith("/agent/interactions")


async def test_keyboard_navigation_cannot_bypass_form_input_permission(lab):
    from types import SimpleNamespace
    from app.agent.controller import Controller

    page, _, _ = lab
    controller = Controller(SimpleNamespace(cfg={"navigation_timeout_ms": 700}), page.context, page, {})
    await page.locator("#widget").focus()
    with pytest.raises(ValueError, match="Enable form input"):
        await controller.act(decision("PRESS_KEY", key="ArrowUp"), {"allow_form_input": False})
    await controller.act(decision("PRESS_KEY", key="Tab"), {"allow_form_input": False})
    assert await page.get_by_role("button", name="Delayed action").evaluate("e=>e===document.activeElement")


@pytest.mark.parametrize("link,ambiguous", [(True, False), (False, False), (True, True), (True, "changed")])
async def test_controller_recovers_only_ordinary_link_before_click_dispatch(lab, link, ambiguous):
    from types import SimpleNamespace
    from app.agent.controller import Controller
    from app.agent.interaction import ActionabilityTimeout

    page, _, _ = lab
    destination = "http://127.0.0.1:8765/agent/article/orion"
    tag = (
        f'<a href="{destination}">Rankings</a>'
        if link
        else '<button data-adbot-safe="true" onclick="window.clicked=true">Rankings</button>'
    )
    await page.set_content(tag + '<div style="position:fixed;inset:0;background:white;z-index:99">Overlay</div>')
    visits = []

    async def permitted(url):
        assert url == destination
        return url

    async def visit(current, url):
        visits.append(url)
        await current.goto(url)
        return None, None, None

    runner = SimpleNamespace(
        cfg={"navigation_timeout_ms": 200},
        permitted=permitted,
        visit=visit,
        policy=SimpleNamespace(check=lambda url: url),
    )
    controller = Controller(runner, page.context, page, {})
    observation = await controller.observer.observe(page, "t1")
    item = next(e for e in observation["elements"] if e["name"] == "Rankings")
    choice = decision("CLICK", target={"element_id": item["element_id"]})
    if ambiguous == "changed":

        async def changed(*args, **kwargs):
            await page.locator("a").evaluate("e => e.textContent='Delete account'")
            raise ActionabilityTimeout("Trial failed before dispatch")

        controller.engine.perform = changed
        with pytest.raises(ValueError, match="Target changed"):
            await controller.act(choice, {"allow_form_input": False})
        assert not visits
    elif ambiguous:

        async def dispatched(*args, **kwargs):
            raise PlaywrightTimeout("Actual click outcome is unknown")

        controller.engine.perform = dispatched
        with pytest.raises(PlaywrightTimeout):
            await controller.act(choice, {"allow_form_input": False})
        assert not visits
    elif link:
        outcome = await controller.act(choice, {"allow_form_input": False})
        assert outcome["navigation_recovery"] and page.url == destination
        assert visits == [destination]
    else:
        with pytest.raises(ActionabilityTimeout):
            await controller.act(choice, {"allow_form_input": False})
        assert not visits and not await page.evaluate("Boolean(window.clicked)")
