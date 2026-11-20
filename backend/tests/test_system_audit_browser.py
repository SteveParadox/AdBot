"""Real browser reproductions; website fixtures never contact external services."""

import json
import asyncio
import time
from types import SimpleNamespace

import pytest
from playwright.async_api import async_playwright

from app.agent.observe import Observer
from app.agent.interaction import InteractionEngine
from app.agent.controller import Controller
from app.agent.planning import evaluate, guard, initial_plan, specification, track_progress
from app.db import ExtractionRun, ExtractedRecord, Job, Lease, transaction
from app.extraction.service import extract_page
from app.jobs import claim, recover_expired, tick
from app.worker import execute
from sqlalchemy import select
from conftest import OTHER_AUTH
from test_browser import fixture_server  # noqa: F401
from test_system_audit import extraction_job
from test_extraction import normalized, setup_dataset
from test_planning import decision


@pytest.mark.browser
async def test_redaction_preserves_private_target_identity():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page()
            await page.set_content("""<input type="password" value="2026">
<button id="release-2026" onclick="this.dataset.clicked='yes'">Release 2026</button>""")
            observer = Observer()
            data = await observer.observe(page, "t1")
            assert "2026" not in json.dumps(data)
            button = next(e for e in data["elements"] if e["role"] == "button")
            locator, _, binding = await observer.resolve(
                decision("CLICK", target={"element_id": button["element_id"]}), page, "t1"
            )
            await binding.click()
            assert await locator.get_attribute("data-clicked") == "yes"
        finally:
            await browser.close()


@pytest.mark.browser
async def test_semantic_disclosure_extraction_and_confirmed_empty(client, target):
    dataset, identifier, token = extraction_job(client, target)
    with transaction() as session:
        snapshot = session.get(Job, identifier).snapshot
    runner = SimpleNamespace(
        id=identifier, token=token, snapshot=snapshot, cfg={"navigation_timeout_ms": 10000}, gate=asyncio.Event()
    )
    runner.gate.set()
    runner.snapshot["extraction"]["options"]["ready_selector"] = ".product"
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page()
            html = """<button aria-expanded="false" onclick="document.querySelector('main').innerHTML='<article class=product><span class=name>Revealed product</span><span class=price>$23.00</span><a class=product-url href=/product/1>Details</a></article>';this.setAttribute('aria-expanded','true')">Show catalog</button><main></main>"""
            await page.route("https://example.org/**", lambda route: route.fulfill(body=html, content_type="text/html"))
            await page.goto("https://example.org/catalog")
            assert await page.locator(".product").count() == 0
            await extract_page(runner, page, required=False)
            with transaction() as session:
                assert session.get(ExtractionRun, identifier).invalid_count == 0
                assert session.get(ExtractionRun, identifier).pages == 0
            observer = Observer()
            observed = await observer.observe(page, "t1")
            button = next(e for e in observed["elements"] if e["name"] == "Show catalog")
            action = decision("CLICK", target={"element_id": button["element_id"]})
            locator, _, binding = await observer.resolve(action, page, "t1")
            result = await InteractionEngine(3000).perform(page, action, locator, binding=binding)
            assert result["interaction"]["verified"]
            await extract_page(runner, page)
            with transaction() as session:
                assert session.scalar(select(ExtractedRecord)).data["price"] == "23.00"
            # A configured marker must actually be visible; a hidden marker is
            # not evidence that the site has intentionally returned zero rows.
            runner.snapshot["extraction"]["options"]["empty_state_selector"] = "#empty"
            runner.snapshot["extraction"]["options"]["ready_selector"] = None
            await page.set_content("<p id=empty hidden>No products</p>")
            await extract_page(runner, page)
            with transaction() as session:
                assert session.get(ExtractionRun, identifier).invalid_count == 1
            await page.locator("#empty").evaluate("e=>e.hidden=false")
            runner.snapshot["extraction"]["options"]["ready_selector"] = ".product"
            await extract_page(runner, page)
            with transaction() as session:
                assert session.get(ExtractionRun, identifier).invalid_count == 1
        finally:
            await browser.close()


@pytest.mark.browser
async def test_scheduler_executes_repeat_and_persists_real_change(client, target, fixture_server):  # noqa: F811
    def source(price):
        body = {k: target[k] for k in ("name", "base_url", "allowed_domains", "configuration")}
        body["authorized"] = True
        body["base_url"] = f"http://127.0.0.1:8765/extraction/catalog?page=1&price={price}"
        body["configuration"].update(max_pages=2, discover_links=False, screenshots=False, max_duration_seconds=60)
        assert client.patch("/api/websites/" + target["id"], json=body).status_code == 200

    source("12.30")
    _, dataset = setup_dataset(client, target)
    client.post(f"/api/extraction/datasets/{dataset['id']}/run")
    await execute(*claim())
    source("18.00")
    response = client.post(
        f"/api/extraction/datasets/{dataset['id']}/schedules",
        json={"website_id": target["id"], "cron_expression": "0 */6 * * *"},
    )
    assert response.status_code == 201, response.text
    from app.db import Schedule

    with transaction() as session:
        session.get(Schedule, response.json()["id"]).next_run_at = 100
    assert tick(100) == 1
    await execute(*claim())
    records = client.get(f"/api/extraction/datasets/{dataset['id']}/records").json()
    assert records["total"] == 1 and records["items"][0]["data"]["price"] == "18.00"
    changes = client.get(f"/api/extraction/datasets/{dataset['id']}/changes").json()["items"]
    assert any(c["kind"] == "price_increase" for c in changes)


def test_expired_worker_preserves_extraction_and_fences_old_writer(client, target):
    from app.extraction.persistence import save_page

    dataset, identifier, token = extraction_job(client, target)
    save_page(identifier, token, "https://example.org/catalog", [normalized()])
    with transaction() as session:
        session.get(Job, identifier).lease_until = time.time() - 1
        for lease in session.scalars(select(Lease)):
            lease.expires_at = 0
    recover_expired()
    recovered, new_token = claim()
    assert recovered == identifier and new_token != token
    with pytest.raises(InterruptedError):
        save_page(identifier, token, "https://example.org/catalog", [normalized(price="$99")])
    save_page(identifier, new_token, "https://example.org/catalog", [normalized()])
    with transaction() as session:
        records = session.scalars(select(ExtractedRecord).where(ExtractedRecord.dataset_id == dataset)).all()
        assert len(records) == 1 and records[0].revision == 1


@pytest.mark.browser
async def test_real_concurrent_worker_workspaces_and_cleanup(client, target, fixture_server, monkeypatch):  # noqa: F811
    # Extend the isolated fixture's loopback exception to one exact second
    # origin in this test only. Production SSRF policy is unchanged. Both jobs
    # still use real browser sockets, the egress proxy and durable worker paths.
    from app.security import Policy, normalize
    from urllib.parse import urlsplit

    original_check, original_resolve = Policy.check, Policy.resolve

    def second_origin(url):
        p = urlsplit(url)
        return p.scheme == "http" and p.hostname == "localhost" and p.port == 8765

    def check(self, url, navigation=True):
        if second_origin(url) and "localhost" in self.domains:
            original_check(Policy(["127.0.0.1"], self.config), url.replace("localhost", "127.0.0.1", 1), navigation)
            return normalize(url)
        return original_check(self, url, navigation)

    async def resolve(self, url):
        if second_origin(url) and "localhost" in self.domains:
            self.check(url)
            return ["127.0.0.1"]
        return await original_resolve(self, url)

    monkeypatch.setattr(Policy, "check", check)
    monkeypatch.setattr(Policy, "resolve", resolve)
    jobs = []
    for hostname, auth in [("127.0.0.1", {}), ("localhost", OTHER_AUTH)]:
        response = client.post(
            "/api/websites",
            headers=auth,
            json={
                "name": hostname,
                "base_url": f"http://{hostname}:8765/agent/news",
                "allowed_domains": [hostname],
                "authorized": True,
                "configuration": {"max_pages": 1, "screenshots": False, "max_duration_seconds": 60},
            },
        )
        assert response.status_code == 201, response.text
        response = client.post("/api/jobs", headers=auth, json={"website_id": response.json()["id"]})
        assert response.status_code == 201, response.text
        jobs.append((response.json()["id"], auth))
    claims = [claim(), claim()]
    assert all(claims) and claim() is None
    await asyncio.gather(*(execute(*item) for item in claims))
    for identifier, auth in jobs:
        response = client.get("/api/jobs/" + identifier, headers=auth)
        assert response.json()["status"] == "completed", response.text
        assert response.json()["pages_visited"] == 1
        other = {} if auth else OTHER_AUTH
        assert client.get("/api/jobs/" + identifier, headers=other).status_code == 404
    with transaction() as session:
        assert all(row.expires_at == 0 for row in session.scalars(select(Lease)))


@pytest.mark.browser
async def test_modal_authority_follows_top_layer_not_dom_order():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page()
            await page.set_content("""<dialog id="first"><button>Active choice</button></dialog>
<dialog id="second"><button>Background choice</button></dialog>""")
            await page.evaluate("second.showModal(); first.showModal()")
            observer = Observer()
            data = await observer.observe(page, "t1")
            active = next(e for e in data["elements"] if e["name"] == "Active choice")
            background = next(e for e in data["elements"] if e["name"] == "Background choice")
            assert active["actionable"] and not active["blocked_by_modal"]
            assert not background["actionable"] and background["blocked_by_modal"]
            dialogs = await InteractionEngine().dialogs(page)
            assert dialogs[-1]["id"] == "first" and dialogs[-1]["focus_contained"]
        finally:
            await browser.close()


@pytest.mark.browser
async def test_long_semantic_sequence_preserves_planning_constraints_and_stale_downloads():
    objective = "Read 25 catalog stages. Only public data."
    planning = initial_plan(specification(objective, ["Observe stage 25"], {}, ["example.org"]), 50)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page()
            await page.route(
                "https://example.org/**",
                lambda r: r.fulfill(
                    content_type="text/html",
                    body="""
<main><output>Stage 0</output><button onclick="document.querySelector('output').textContent='Stage '+(++window.stage)">Next stage</button><a href="/old">Download catalog</a></main><script>window.stage=0</script>""",
                ),
            )
            await page.goto("https://example.org/catalog")
            observer = Observer()
            interaction = InteractionEngine(3000)
            for stage in range(25):
                observed = await observer.observe(page, "t1")
                evaluate(planning, observed, [])
                element = next(e for e in observed["elements"] if e["name"] == "Next stage")
                action = decision("CLICK", target={"element_id": element["element_id"]})
                guard(planning, action, observed)
                track_progress(planning, action, observed, 0)
                locator, _, binding = await observer.resolve(action, page, "t1")
                await interaction.perform(page, action, locator, binding=binding)
                assert await page.locator("output").inner_text() == f"Stage {stage + 1}"
                assert planning["specification"]["objective"] == objective
                assert planning["specification"]["constraints"] == ["Only public data"]
                interaction.trace.clear()
            assert not any(n["status"] == "completed" for n in planning["plan"]["subtasks"] if n["kind"] == "verify")
            observed = await observer.observe(page, "t1")
            link = next(e for e in observed["elements"] if e["name"] == "Download catalog")
            await page.get_by_role("link").evaluate("e=>e.href='/changed'")
            controller = Controller.__new__(Controller)
            controller.observer, controller.page, controller.active = observer, page, "t1"
            with pytest.raises(ValueError, match="changed"):
                await controller.download(
                    decision("DOWNLOAD", target={"element_id": link["element_id"]}), {"allow_downloads": True}
                )
        finally:
            await browser.close()
