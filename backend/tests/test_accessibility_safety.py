import json
from types import SimpleNamespace

import pytest
from playwright.async_api import async_playwright

from app.agent.controller import Controller
from test_accessibility import decision


@pytest.mark.browser
async def test_semantic_failures_permissions_and_bounded_keyboard():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page()
            controller = Controller(SimpleNamespace(cfg={"navigation_timeout_ms": 3000}), page.context, page, {})
            await page.set_content("""<main><button>Delete</button><button>Delete</button>
<input type="hidden" value="1"><p>Public release 1</p><label><input id="filter" type="checkbox">Remote only</label><label><input id="private" value="known-protected-7792" aria-label="API key"></label>
<label>Read only<input id="readonly" readonly value="fixed"></label>
<button aria-expanded="false" aria-controls="content" onclick="this.setAttribute('aria-expanded','true')">Broken expansion</button><div id="content" hidden>Must remain unverified</div>
<div id="legacy" role="not-a-real-role" tabindex="0" onclick="document.querySelector('#feedback').textContent='Legacy click confirmed'">Legacy action</div>
<dialog open aria-label="Nonmodal information">Nonmodal dialog</dialog><output id="feedback">Ready</output></main>""")

            async def choice(action, name, **kw):
                obs = await controller.observer.observe(page, "t1")
                item = next(e for e in obs["elements"] if e["name"] == name)
                return decision(action, target={"element_id": item["element_id"]}, **kw)

            obs = await controller.observer.observe(page, "t1")
            assert "Public release 1" in obs["text"]
            duplicates = [e for e in obs["elements"] if e["name"] == "Delete"]
            assert len(duplicates) == 2 and all(e["ambiguous"] for e in duplicates)
            with pytest.raises(ValueError, match="Ambiguous"):
                await controller.act(decision("CLICK", target={"element_id": duplicates[0]["element_id"]}), {})
            assert not next(e for e in obs["elements"] if e["name"] == "Remote only")["blocked_by_modal"]
            for action, kw in [("CLICK", {}), ("SET_CHECKED", {"checked": True})]:
                with pytest.raises(ValueError, match="Enable form input"):
                    await controller.act(await choice(action, "Remote only", **kw), {"allow_form_input": False})
            await controller.act(await choice("FOCUS", "Remote only"), {})
            await controller.act(await choice("PRESS_KEY", "Remote only", key="Space"), {"allow_form_input": True})
            assert await page.locator("#filter").is_checked()
            with pytest.raises(ValueError, match="Enable form input"):
                await controller.act(await choice("PRESS_KEY", "Remote only", key="Space"), {"allow_form_input": False})
            await page.locator("#private").focus()
            with pytest.raises(ValueError, match="Secret"):
                await controller.act(decision("PRESS_KEY", key="ArrowLeft"), {"allow_form_input": True})
            assert "known-protected-7792" not in json.dumps(await controller.observer.observe(page, "t1"))
            assert "known-protected-7792" not in controller.observer.safe_text("error: known-protected-7792")
            with pytest.raises(ValueError, match="Read-only"):
                await controller.act(await choice("TYPE", "Read only", text="changed"), {"allow_form_input": True})
            with pytest.raises(ValueError, match="semantic control"):
                await controller.act(await choice("CLICK", "Broken expansion"), {})
            assert await page.locator("#content").is_hidden()
            result = await controller.act(
                await choice("CLICK", "Legacy action", expected_text="Legacy click confirmed"), {}
            )
            assert result["semantic"]["strategy"] == "unique DOM identifier"
            assert result["interaction"]["verified"]
            controller.engine.keyboard_hops["t1"] = 32
            with pytest.raises(ValueError, match="traversal budget"):
                await controller.act(decision("PRESS_KEY", key="Tab"), {})
            assert not controller.engine.dispatch_started
            with pytest.raises(ValueError, match="observed focused target"):
                await controller.act(decision("PRESS_KEY", key="Enter"), {})
            await page.route(
                "http://semantics.test/**",
                lambda route: route.fulfill(
                    content_type="text/html",
                    body="<main><h1>New document only</h1><button>Current control</button></main>",
                ),
            )
            original_locate = controller.observer.locate
            navigated = False

            async def navigate_during_inspection(current, fallback, handle, element):
                nonlocal navigated
                if not navigated:
                    navigated = True
                    await page.goto("http://semantics.test/new")
                return await original_locate(current, fallback, handle, element)

            controller.observer.locate = navigate_during_inspection
            coherent = await controller.observer.observe(page, "t1")
            assert coherent["url"] == "http://semantics.test/new"
            assert "New document only" in coherent["text"] and "Broken expansion" not in coherent["text"]
            await page.set_content(
                """<div role="menu" aria-label="Actions"><div role="menuitem" tabindex="0" onkeydown="if(event.key==='ArrowDown')this.nextElementSibling.focus()">First action</div><div role="menuitem" tabindex="-1">Second action</div></div>"""
            )
            await controller.act(await choice("FOCUS", "First action"), {})
            moved = await controller.act(await choice("PRESS_KEY", "First action", key="ArrowDown"), {})
            assert moved["interaction"]["verified"]
            assert await page.get_by_role("menuitem", name="Second action", exact=True).evaluate(
                "e=>e===document.activeElement"
            )
        finally:
            await browser.close()
