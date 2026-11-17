"""Real browser rotation against a loopback-only recording destination."""

import json
import threading
import time
import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse
from app.browser import Runner
from app.config import settings
from app.db import NetworkAssignment, Session
from app.jobs import claim
from app.outbound import Manager
from app.worker import execute
from conftest import KEY

pytestmark = pytest.mark.browser


@pytest.fixture
def recording_destination():
    destination = FastAPI()
    records = []

    @destination.get("/robots.txt", response_class=PlainTextResponse)
    def robots():
        return "User-agent: *\nAllow: /\n"

    @destination.get("/rotation", response_class=HTMLResponse)
    def first():
        return '<title>Rotation first page</title><h1>Local rotation fixture</h1><a href="/rotation/next">Next page</a>'

    @destination.get("/rotation/next", response_class=HTMLResponse)
    def second():
        return "<title>Rotation second page</title><h1>Second page</h1>"

    async def capture(scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            records.append(
                {
                    "path": scope["path"],
                    "user_agent": headers.get(b"user-agent", b"").decode(),
                    "automation": headers.get(b"x-adbot-automation", b"").decode(),
                    "session": headers.get(b"x-adbot-session", b"").decode(),
                }
            )
        await destination(scope, receive, send)

    server = uvicorn.Server(uvicorn.Config(capture, host="127.0.0.1", port=8765, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Controlled rotation destination failed to start")
            time.sleep(0.02)
        yield records
    finally:
        server.should_exit = True
        thread.join(timeout=5)


async def test_rotation_reaches_destination_and_preserves_active_session(
    client, target, recording_destination, monkeypatch
):
    monkeypatch.setattr(settings(), "content_admin_keys", KEY)
    monkeypatch.setattr(settings(), "user_agent_rotatable_services", "browser")
    monkeypatch.setattr(settings(), "user_agent_fixed_identities", {})
    routing = Manager(enabled=False)
    monkeypatch.setattr("app.outbound.manager", lambda: routing)
    monkeypatch.setattr("app.egress.manager", lambda: routing)
    config = {
        "revision": 0,
        "profiles": [
            {"id": "rotation-a", "name": "Rotation A", "value": "Adbot-Rotation-A/1", "clients": ["chromium"]},
            {"id": "rotation-b", "name": "Rotation B", "value": "Adbot-Rotation-B/1", "clients": ["chromium"]},
            {"id": "rotation-disabled", "name": "Disabled", "value": "Adbot-Disabled/1", "enabled": False},
        ],
        "services": {
            "browser": {
                "rotation": "round_robin",
                "profiles": ["rotation-a", "rotation-b", "rotation-disabled"],
                "fallback": "fail",
            }
        },
    }
    response = client.post("/api/admin/user-agents", json=config)
    assert response.status_code == 200, response.text
    config["revision"] = response.json()["revision"]
    site = {k: target[k] for k in ("name", "base_url", "allowed_domains", "configuration")}
    site["authorized"] = True
    site["base_url"] = "http://127.0.0.1:8765/rotation"
    site["configuration"] = {
        **site["configuration"],
        "max_pages": 2,
        "max_depth": 1,
        "screenshots": False,
        "max_duration_seconds": 60,
    }
    assert client.patch("/api/websites/" + target["id"], json=site).status_code == 200
    original_visit = Runner.visit
    switch_job = [None]
    edited = [False]

    async def visit(self, *args, **kwargs):
        result = await original_visit(self, *args, **kwargs)
        if self.id == switch_job[0] and not edited[0]:
            config["profiles"][0]["value"] = "Adbot-Rotation-A/2"
            config["profiles"][1]["enabled"] = False
            changed = client.post("/api/admin/user-agents", json=config)
            assert changed.status_code == 200, changed.text
            config["revision"] = changed.json()["revision"]
            edited[0] = True
        return result

    monkeypatch.setattr(Runner, "visit", visit)
    outcomes = []
    try:
        expected = [
            "Adbot-Rotation-A/1",
            "Adbot-Rotation-B/1",
            "Adbot-Rotation-A/1",
            "Adbot-Rotation-B/1",
            "Adbot-Rotation-A/2",
        ]
        for index, identity in enumerate(expected):
            start = len(recording_destination)
            response = client.post("/api/jobs", json={"website_id": target["id"]})
            assert response.status_code == 201, response.text
            identifier = response.json()["id"]
            if index == 3:
                switch_job[0] = identifier
            acquired = claim()
            assert acquired[0] == identifier
            await execute(*acquired)
            job = client.get("/api/jobs/" + identifier).json()
            assert job["status"] == "completed", (job["error_message"], index)
            assert job["pages_visited"] == 2
            received = recording_destination[start:]
            pages = [r for r in received if r["path"].startswith("/rotation")]
            assert {r["path"] for r in pages} == {"/rotation", "/rotation/next"}
            assert {r["user_agent"] for r in received} == {identity}
            assert all(r["automation"] == "true" and r["session"] == identifier for r in pages)
            assert any(r["path"] == "/robots.txt" for r in received)
            with Session() as session:
                assignment = session.get(NetworkAssignment, identifier)
                assert assignment.user_agent == identity and not assignment.active
            outcomes.append(
                {"session": index + 1, "observed_user_agent": identity, "pages": 2, "disclosure_headers": True}
            )
        assert edited[0]
        print("ROTATION_SIMULATION " + json.dumps(outcomes))
    finally:
        await routing.close()
