import asyncio
import threading
import time

import pytest
import uvicorn
from sqlalchemy import select

from app.db import Frontier, Session
from app.jobs import claim
from app.worker import execute

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def fixture_server():
    server = uvicorn.Server(uvicorn.Config("app.fixture:app", host="127.0.0.1", port=8765, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("Fixture server failed to start")
        time.sleep(0.02)
    yield
    server.should_exit = True
    thread.join(timeout=5)


async def test_real_crawl_persists_pages_screenshots_and_robots(client, target, fixture_server):
    identifier = client.post("/api/jobs", json={"website_id": target["id"]}).json()["id"]
    await execute(*claim())
    job = client.get(f"/api/jobs/{identifier}").json()
    assert job["status"] == "completed", job
    visits = client.get(f"/api/jobs/{identifier}/pages").json()["items"]
    assert any(p["http_status"] == 404 for p in visits)
    assert any(p["page_title"] == "About fixture" for p in visits)
    assert not any("/private" in p["requested_url"] or "169.254" in p["requested_url"] for p in visits)
    assert all(p["screenshot_path"] for p in visits)
    capture = client.get("/api/artifacts/" + visits[0]["screenshot_path"])
    assert capture.status_code == 200 and capture.content.startswith(b"\x89PNG")
    with Session() as session:
        assert (
            session.scalar(
                select(Frontier.crawl_status).where(
                    Frontier.job_id == identifier, Frontier.normalized_url.endswith("/private")
                )
            )
            == "blocked"
        )
    analytics = client.get("/api/analytics/overview").json()
    assert analytics["pages"] == len(visits) and analytics["daily_pages"]


async def test_page_limit_and_depth(client, target, fixture_server):
    data = {k: v for k, v in target.items() if k in {"name", "base_url", "allowed_domains", "configuration"}}
    data["authorized"] = True
    data["configuration"] |= {"max_pages": 1, "max_depth": 0}
    client.patch("/api/websites/" + target["id"], json=data)
    identifier = client.post("/api/jobs", json={"website_id": target["id"]}).json()["id"]
    await execute(*claim())
    assert client.get(f"/api/jobs/{identifier}").json()["pages_visited"] == 1
    with Session() as session:
        assert len(session.scalars(select(Frontier).where(Frontier.job_id == identifier)).all()) == 1


async def test_real_workflow_click_scroll_extract_back(client, target, fixture_server):
    response = client.post(
        "/api/workflows",
        json={
            "name": "Fixture workflow",
            "website_id": target["id"],
            "definition": {
                "steps": [
                    {"action": "ASSERT_VISIBLE", "selector": "h1"},
                    {"action": "CLICK", "selector": "#toggle", "authorized": True},
                    {"action": "ASSERT_TEXT", "selector": "#result", "text": "Clicked"},
                    {"action": "SCROLL", "pixels": 600},
                    {"action": "EXTRACT_TEXT", "selector": "h1"},
                    {"action": "OPEN_URL", "url": "http://127.0.0.1:8765/about"},
                    {"action": "NAVIGATE_BACK"},
                    {"action": "SCREENSHOT"},
                    {"action": "STOP"},
                ]
            },
        },
    )
    assert response.status_code == 201, response.text
    identifier = client.post(
        "/api/jobs", json={"website_id": target["id"], "workflow_id": response.json()["id"]}
    ).json()["id"]
    await execute(*claim())
    job = client.get(f"/api/jobs/{identifier}").json()
    assert job["status"] == "completed", job
    logs = client.get(f"/api/jobs/{identifier}/logs").json()["items"]
    assert any(e["details"].get("text") == "Monitoring fixture" for e in logs)
    assert any(e["details"].get("screenshot_path") for e in logs)


async def test_cancel_browser_session(client, target, fixture_server):
    workflow = client.post(
        "/api/workflows",
        json={
            "name": "Wait",
            "website_id": target["id"],
            "definition": {"steps": [{"action": "WAIT", "seconds": 10, "timeout_ms": 20000}]},
        },
    ).json()
    identifier = client.post("/api/jobs", json={"website_id": target["id"], "workflow_id": workflow["id"]}).json()["id"]
    task = asyncio.create_task(execute(*claim()))
    await asyncio.sleep(0.5)
    client.post(f"/api/jobs/{identifier}/cancel")
    await asyncio.wait_for(task, 5)
    assert client.get(f"/api/jobs/{identifier}").json()["status"] == "cancelled"


@pytest.mark.parametrize("path", ["unsafe-redirect", "slow"])
async def test_redirect_and_timeout_fail_closed(client, target, fixture_server, path):
    data = {k: v for k, v in target.items() if k in {"name", "base_url", "allowed_domains", "configuration"}}
    data["base_url"] = "http://127.0.0.1:8765/" + path
    data["authorized"] = True
    data["configuration"] |= {"navigation_timeout_ms": 200, "max_pages": 1, "retries": 0}
    assert client.patch("/api/websites/" + target["id"], json=data).status_code == 200
    identifier = client.post("/api/jobs", json={"website_id": target["id"]}).json()["id"]
    await execute(*claim())
    visits = client.get(f"/api/jobs/{identifier}/pages").json()["items"]
    assert len(visits) == 1 and visits[0]["error"]


async def test_rate_limit_exhaustion_is_bounded(client, target, fixture_server):
    data = {k: v for k, v in target.items() if k in {"name", "base_url", "allowed_domains", "configuration"}}
    data["base_url"] = "http://127.0.0.1:8765/rate-limited"
    data["authorized"] = True
    data["configuration"]["retries"] = 1
    client.patch("/api/websites/" + target["id"], json=data)
    identifier = client.post("/api/jobs", json={"website_id": target["id"]}).json()["id"]
    await execute(*claim())
    assert client.get(f"/api/jobs/{identifier}").json()["status"] == "failed"


async def test_browser_crash_retry_budget(client, target, monkeypatch):
    from app.browser import BrowserCrashed, Runner

    async def crashed(self):
        raise BrowserCrashed("simulated browser process loss")

    monkeypatch.setattr(Runner, "run", crashed)
    identifier = client.post("/api/jobs", json={"website_id": target["id"]}).json()["id"]
    for expected in ["queued", "queued", "failed"]:
        await execute(*claim())
        assert client.get(f"/api/jobs/{identifier}").json()["status"] == expected


async def test_concurrent_workers_keep_navigation_and_session_private(client, target, fixture_server, monkeypatch):
    from app.browser import Runner

    identifiers = [client.post("/api/jobs", json={"website_id": target["id"]}).json()["id"] for _ in range(2)]
    # Production domain leases serialize same-origin jobs. Seed a second valid
    # execution lease to stress browser isolation independently of scheduling.
    from app.db import Job, transaction, uid
    claims = [claim()]
    token = uid()
    with transaction() as session:
        job = session.get(Job, identifiers[1])
        job.status, job.lease_token = "running", token
        job.started_at, job.lease_until = time.time(), time.time() + 120
    claims.append((identifiers[1], token))
    ready = {identifier: asyncio.Event() for identifier in identifiers}
    release = asyncio.Event()
    resources = {}

    async def isolated_activity(self, page, context):
        await page.goto(target["base_url"])
        # Both jobs write the same origin/key with different values.
        await context.add_cookies([{"name": "owner", "value": self.id, "url": target["base_url"]}])
        await page.evaluate("value => localStorage.setItem('owner', value)", self.id)
        if self.id == identifiers[0]:
            await page.goto(target["base_url"] + "about")
        resources[self.id] = (context.browser, context, page)
        ready[self.id].set()
        await release.wait()
        assert (await context.cookies())[0]["value"] == self.id
        assert await page.evaluate("localStorage.getItem('owner')") == self.id
        assert page.url == target["base_url"]

    monkeypatch.setattr(Runner, "execute_page", isolated_activity)
    tasks = [asyncio.create_task(execute(*item)) for item in claims]
    try:
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in ready.values())), 20)
        first, second = (resources[identifier] for identifier in identifiers)
        assert all(a is not b for a, b in zip(first, second))
        assert first[2].url.endswith("/about")
        assert second[2].url == target["base_url"]
        tasks[0].cancel()
        await asyncio.wait_for(tasks[0], 10)
        assert not first[0].is_connected()
        assert second[0].is_connected()
        release.set()
        await asyncio.wait_for(tasks[1], 10)
        assert not second[0].is_connected()
        assert client.get(f"/api/jobs/{identifiers[0]}").json()["status"] == "cancelled"
        assert client.get(f"/api/jobs/{identifiers[1]}").json()["status"] == "completed"
    finally:
        release.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
