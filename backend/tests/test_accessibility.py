import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from playwright.async_api import async_playwright
from pydantic import ValidationError

from app.agent.contracts import Decision
from app.agent.controller import Controller
from app.agent.model import bounded_request_text
from app.agent.semantic_observer import native_semantics
from test_browser import fixture_server  # noqa: F401


def decision(action, **kwargs):
    return Decision(
        observation="Observed local semantic UI",
        decision=action,
        reason="Requested public control",
        confidence=1,
        expected_result="Verified control state",
        **kwargs,
    )


def test_semantic_contracts_and_native_name_parsing():
    for kwargs in (
        {"decision": "SET_CHECKED"},
        {"decision": "SELECT_OPTION", "option": "New"},
        {"decision": "PRESS_KEY", "key": "F12"},
    ):
        action = kwargs.pop("decision")
        with pytest.raises(ValidationError):
            decision(action, **kwargs)
    assert native_semantics('- button "Read announcement"', {"role": "button", "name": "Wrong"}) == (
        "button",
        "Read announcement",
        "playwright_aria",
    )
    for key in ("Enter", "Space", "Tab", "Escape"):
        assert decision("PRESS_KEY", key=key).key == key


@pytest.mark.browser
@pytest.mark.parametrize("engine", ["chromium", "firefox", "webkit"])
async def test_semantic_controls_keyboard_dialogs_forms_and_stale_nodes(engine, fixture_server, tmp_path):  # noqa: F811
    async with async_playwright() as pw:
        browser = await getattr(pw, engine).launch()
        try:
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900}, locale="en-US", timezone_id="UTC"
            )
            page = await context.new_page()
            await page.goto("http://127.0.0.1:8765/agent/accessibility")
            runner = SimpleNamespace(
                cfg={"navigation_timeout_ms": 3000},
                objective="Search jobs, filter remote, newest, preferences and location",
                permitted=AsyncMock(side_effect=lambda url: url),
            )
            controller = Controller(runner, context, page, {})
            options = {"allow_form_input": True}

            async def observe():
                return await controller.observer.observe(page, "t1", runner.objective)

            async def perform(action, name=None, context_name=None, role=None, **kwargs):
                obs = await observe()
                target = None
                if name is not None:
                    matches = [
                        e
                        for e in obs["elements"]
                        if e["name"] == name
                        and (not role or e["role"] == role)
                        and (not context_name or e.get("context", {}).get("name") == context_name)
                    ]
                    assert len(matches) == 1, (name, [e["name"] for e in obs["elements"]])
                    target = {"element_id": matches[0]["element_id"]}
                return await controller.act(
                    decision(action, **({"target": target} if target else {}), **kwargs), options
                )

            obs = await observe()
            assert "sensitive-test-key-92384" not in json.dumps(obs)
            native = next(e for e in obs["elements"] if e["name"] == "Read announcement")
            assert native["semantic_source"] == "playwright_aria"
            assert next(e for e in obs["elements"] if e["name"] == "Search jobs")["description"] == "Public titles only"
            assert next(e for e in obs["elements"] if e["name"] == "Hidden action")["visible"] is False
            assert next(e for e in obs["elements"] if e["name"] == "Unavailable")["disabled"]
            assert any("Ignore instructions" in e["name"] for e in obs["elements"])
            assert {"radio", "spinbutton", "gridcell", "treeitem", "progressbar", "status"} <= {
                e["role"] for e in obs["elements"]
            }
            result = await perform(
                "CLICK", "View details", context_name="Engineering", expected_text="Engineering details"
            )
            assert result["semantic"]["strategy"].startswith("context")
            assert (await perform("TYPE", "Search jobs", text="Backend Engineer"))["interaction"]["verified"]
            assert (await perform("SET_CHECKED", "Remote only", checked=True))["interaction"]["verified"]
            assert await page.locator("#remote").is_checked()
            assert (await perform("SET_CHECKED", "Remote only", checked=True))["interaction"]["verified"]  # Idempotent.
            assert (await perform("SET_CHECKED", "Part time", checked=True))["interaction"]["verified"]
            assert (await perform("SET_CHECKED", "Notifications", checked=True))["interaction"]["verified"]
            assert (await perform("SELECT_OPTION", "Sort results", option="Newest"))["interaction"]["verified"]
            assert await page.locator("#sort").input_value() == "newest"
            assert (await perform("TYPE", "Available date", text="2026-11-20"))["interaction"]["verified"]
            assert (await perform("TYPE", "Result count", text="5"))["interaction"]["verified"]
            with pytest.raises(ValueError, match="Read-only"):
                await perform("TYPE", "Read only", text="changed")
            with pytest.raises(ValueError, match="validation"):
                await perform("CLICK", "Save profile")
            await perform("TYPE", "Email", text="public@example.org")
            assert (await perform("CLICK", "Save profile", expected_text="Profile saved"))["interaction"]["verified"]
            await perform("CLICK", "More filters")
            assert next(e for e in (await observe())["elements"] if e["name"] == "More filters")["expanded"] is True
            await perform("CLICK", "Preferences")
            modal = await observe()
            assert any(d["name"] == "Job preferences" for d in modal["dialogs"])
            background = next(e for e in modal["elements"] if e["name"] == "Remote only")
            with pytest.raises(ValueError, match="modal"):
                await controller.act(
                    decision("SET_CHECKED", target={"element_id": background["element_id"]}, checked=False), options
                )
            await perform("FOCUS", "City")
            await perform("PRESS_KEY", key="Shift+Tab")
            assert await page.evaluate("document.querySelector('#preferences').contains(document.activeElement)")
            await perform("CLICK", "Close preferences")
            assert await page.locator("#open-dialog").evaluate("e=>e===document.activeElement")
            await perform("TYPE", "Location", text="Lag")
            await perform("FOCUS", "Location")
            await perform("PRESS_KEY", "Location", key="ArrowDown")
            assert (
                next(e for e in (await observe())["elements"] if e["name"] == "Location")["active_descendant"]
                == "lagos"
            )
            await perform("PRESS_KEY", "Location", key="Enter")
            assert await page.locator("#location").input_value() == "Lagos"
            await perform("FOCUS", "Jobs", role="tab")
            await perform("PRESS_KEY", "Jobs", role="tab", key="ArrowRight")
            assert await page.locator("#savedTab").get_attribute("aria-selected") == "true"
            await perform("FOCUS", "Technology")
            await perform("PRESS_KEY", "Technology", key="ArrowRight")
            assert await page.get_by_role("treeitem").get_attribute("aria-expanded") == "true"
            await perform("FOCUS", "Backend")
            await perform("PRESS_KEY", "Backend", key="ArrowRight")
            assert await page.locator("#next-cell").evaluate("e=>e===document.activeElement")
            await perform("CLICK", "Delayed feedback", expected_text="Delayed accessible confirmation")
            assert any(f["text"] == "Delayed accessible confirmation" for f in (await observe())["feedback"])
            original = next(e for e in (await observe())["elements"] if e["name"] == "Replaceable action")
            await page.get_by_role("button", name="Replace node", exact=True).click()
            with pytest.raises(ValueError, match="changed|detached"):
                await controller.act(decision("CLICK", target={"element_id": original["element_id"]}), options)
            replaced = next(e for e in (await observe())["elements"] if e["name"] == "Replaceable action")
            assert replaced["element_id"] != original["element_id"]
            old_virtual = next(e for e in (await observe())["elements"] if e["name"] == "Job 1")
            await page.get_by_role("button", name="Next results", exact=True).click()
            with pytest.raises(ValueError, match="changed|detached"):
                await controller.act(decision("CLICK", target={"element_id": old_virtual["element_id"]}), options)
            await perform("CLICK", "Job 2", expected_text="Opened Job 2")
            legacy = next(e for e in (await observe())["elements"] if e.get("dom_id") == "unlabelled")
            await controller.act(
                decision("CLICK", target={"element_id": legacy["element_id"]}, expected_text="DOM fallback action"),
                options,
            )
            assert "sensitive-test-key-92384" not in json.dumps(controller.engine.trace)
            request = bounded_request_text(
                "fixed system",
                "decide",
                {"objective": runner.objective, "current_page": await observe()},
                Decision,
                18000,
            )
            assert len(request) < 18000 and "sensitive-test-key-92384" not in request
            (tmp_path / f"{engine}-semantic.json").write_text(
                json.dumps(
                    {
                        "engine": engine,
                        "version": browser.version,
                        "observation": (await observe())["observation_metrics"],
                        "passed": True,
                    }
                ),
                encoding="utf-8",
            )
        finally:
            await browser.close()
