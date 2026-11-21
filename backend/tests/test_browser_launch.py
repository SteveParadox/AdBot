"""Exercise launch options through Runner.run without starting a real browser."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.browser import Runner


@pytest.mark.parametrize("first,second", [
    ({"width": 1920, "height": 1080}, {"width": 1280, "height": 720}),
    ({"width": 1280, "height": 720}, {"width": 1920, "height": 1080}),
])
async def test_chromium_window_dimensions_use_one_preset(monkeypatch, first, second):
    browser = object()
    launch = AsyncMock(return_value=browser)
    choose = Mock(side_effect=[first, second])

    @asynccontextmanager
    async def playwright():
        yield SimpleNamespace(chromium=SimpleNamespace(launch=launch))

    @asynccontextmanager
    async def proxy(*args, **kwargs):
        yield "http://127.0.0.1:1234"

    monkeypatch.setattr("app.browser.async_playwright", playwright)
    monkeypatch.setattr("app.browser.egress_proxy", proxy)
    monkeypatch.setattr("app.browser.polymorph.get_random_viewport", choose)
    monkeypatch.setattr("app.coordination.assign", lambda *args: "fixture-session-identity")
    monkeypatch.setattr("app.outbound.manager", lambda: None)
    runner = object.__new__(Runner)
    runner.id, runner.policy = "window-size-test", object()
    runner.cfg = {"browser": "chromium", "headless": True}
    runner._execute_browser = AsyncMock()

    await runner.run()

    choose.assert_called_once_with()
    launch.assert_awaited_once()
    assert f"--window-size={first['width']},{first['height']}" in launch.await_args.kwargs["args"]
    runner._execute_browser.assert_awaited_once_with(browser)
