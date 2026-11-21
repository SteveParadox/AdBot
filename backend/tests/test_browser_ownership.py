import asyncio

import pytest

from app.agent.runner import AgentRunner
from app.browser import Runner
from app.browser_ownership import exclusive_owner


def test_shared_browser_rejected_without_releasing_original_owner():
    browser, first, second = object(), object(), object()
    with exclusive_owner(browser, first, "Browser"):
        for owner in (first, second):
            with pytest.raises(RuntimeError, match="Browser is already in use"):
                with exclusive_owner(browser, owner, "Browser"):
                    pytest.fail("Shared browser acquired")
    with exclusive_owner(browser, second, "Browser"):
        pass


@pytest.mark.parametrize("runner_class", [Runner, AgentRunner])
@pytest.mark.parametrize("outcome", ["complete", "error", "cancel"])
async def test_runner_overlap_rejected_and_ownership_released(monkeypatch, outcome, runner_class):
    runner = object.__new__(runner_class)
    started, finish = asyncio.Event(), asyncio.Event()

    async def activity(self):
        started.set()
        await finish.wait()
        if outcome == "error":
            raise ValueError("simulated failure")

    monkeypatch.setattr(Runner, "_run_isolated", activity)
    running = asyncio.create_task(runner.run())
    await started.wait()
    with pytest.raises(RuntimeError, match="Runner is already in use"):
        await runner.run()
    assert not running.done()
    if outcome == "cancel":
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
    else:
        finish.set()
        if outcome == "error":
            with pytest.raises(ValueError):
                await running
        else:
            await running
    # A completed, failed, or cancelled run never leaves an ownership claim.
    async def recovered(self):
        pass
    monkeypatch.setattr(Runner, "_run_isolated", recovered)
    await runner.run()
