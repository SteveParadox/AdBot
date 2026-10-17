import asyncio
import threading
import time

import pytest
import uvicorn
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.agent.contracts import Decision
from app.agent.model import ModelClient
from app.agent.model import ModelError
import httpx
from app.agent.memory import decrypt_session, encrypt_session
from app.config import settings
from app.db import AgentMemory, AgentStep, Job, transaction
from app.db import AgentTask, Session
from app.jobs import claim, recover_expired
from app.worker import execute
from conftest import OTHER_AUTH


@pytest.fixture
def agent_config(monkeypatch):
    cfg = settings()
    monkeypatch.setattr(cfg, "ai_provider", "local")
    monkeypatch.setattr(cfg, "ai_model", "fixture-model-not-live-llm")
    monkeypatch.setattr(cfg, "ai_base_url", "http://127.0.0.1:8766/v1")
    monkeypatch.setattr(cfg, "agent_max_steps", 15)
    monkeypatch.setattr(cfg, "ai_retries", 0)
    return cfg


@pytest.fixture(scope="module")
def agent_servers():
    from testsupport.model_fixture import app as model_app
    from app.fixture import app as fixture_app

    servers, threads = [], []
    for app, port in [(fixture_app, 8765), (model_app, 8766)]:
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        servers.append(server)
        threads.append(thread)
        deadline = time.monotonic() + 10
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("Agent fixture failed to start")
            time.sleep(0.02)
    yield
    for server in servers:
        server.should_exit = True
    for thread in threads:
        thread.join(timeout=5)


def new_task(client, target, objective="Find the launch month for Orion AI and cite the source.", **options):
    result = client.post(
        "/api/agent/tasks",
        json={"website_id": target["id"], "objective": objective, "max_steps": 12, "max_tokens": 100000, **options},
    )
    assert result.status_code == 201, result.text
    return result.json()


def set_url(client, target, path):
    body = {k: v for k, v in target.items() if k in {"name", "base_url", "allowed_domains", "configuration"}}
    body["base_url"] = "http://127.0.0.1:8765" + path
    body["configuration"]["max_duration_seconds"] = 90
    body["authorized"] = True
    result = client.patch("/api/websites/" + target["id"], json=body)
    assert result.status_code == 200, result.text


def test_decision_schema_rejects_code_and_missing_parameters():
    base = dict(
        observation="A page", reason="A visible link is relevant", confidence=0.9, expected_result="Relevant page"
    )
    for body in [
        {"decision": "EVALUATE", "code": "print(1)"},
        {"decision": "CLICK"},
        {"decision": "COMPLETE"},
        {"decision": "TYPE", "target": {"element_id": "e1"}},
    ]:
        with pytest.raises(ValidationError):
            Decision(**base, **body)
    assert Decision(**base, decision="CLICK", target={"element_id": "e1"}).decision == "CLICK"


def test_task_api_provider_gating_and_ownership(client, target, agent_config):
    task = new_task(client, target)
    assert client.get(f"/api/agent/tasks/{task['id']}", headers=OTHER_AUTH).status_code == 404
    assert client.get("/api/agent/tasks", headers=OTHER_AUTH).json()["items"] == []
    assert "encrypted_session" not in task
    assert "api_key" not in client.get("/api/agent/config").text
    headers = {"Idempotency-Key": "agent-stable"}
    body = {"website_id": target["id"], "objective": "Find current AI documentation."}
    a, b = (
        client.post("/api/agent/tasks", json=body, headers=headers),
        client.post("/api/agent/tasks", json=body, headers=headers),
    )
    assert a.json()["id"] == b.json()["id"]
    body["objective"] = "Find different documentation."
    assert client.post("/api/agent/tasks", json=body, headers=headers).status_code == 409
    agent_config.ai_provider = "disabled"
    assert client.post("/api/agent/tasks", json=body).status_code == 503


def test_encrypted_sessions_and_memory_isolation(client, target, agent_config, monkeypatch):
    from pydantic import SecretStr

    monkeypatch.setattr(agent_config, "session_encryption_key", SecretStr(Fernet.generate_key().decode()))
    state = {"cookies": [{"name": "session", "value": "private-cookie-value"}], "origins": []}
    cipher = encrypt_session(state)
    assert "private-cookie-value" not in cipher and decrypt_session(cipher) == state
    task = new_task(client, target)
    with transaction() as session:
        job = session.get(Job, task["id"])
        session.add(
            AgentMemory(
                owner=job.owner,
                website_id=job.website_id,
                objective="Orion AI research",
                content={"claims": []},
                expires_at=time.time() + 60,
            )
        )
    assert client.get("/api/agent/memories").json()["total"] == 1
    assert client.get("/api/agent/memories", headers=OTHER_AUTH).json()["items"] == []


@pytest.mark.browser
@pytest.mark.parametrize(
    "path,objective,allow_input",
    [
        ("/agent/news?layout=0", "Find the launch month for Orion AI and cite the source.", False),
        ("/agent/news?layout=1", "Find the launch month for Orion AI and cite the source.", False),
        ("/agent/dynamic", "Find the launch month for Orion AI and cite the source.", False),
        ("/agent/search", "Search this portal for Orion AI and find its launch month.", True),
        ("/agent/catalog", "Find the price of the Orion AI workstation with source evidence.", False),
    ],
)
async def test_goal_driven_real_browser(client, target, agent_config, agent_servers, path, objective, allow_input):
    set_url(client, target, path)
    task = new_task(client, target, objective, allow_form_input=allow_input)
    await execute(*claim())
    result = client.get("/api/agent/tasks/" + task["id"]).json()
    assert result["status"] == "completed", result
    assert result["result"]["verification"]["complete"] is True
    assert result["result"]["evidence"]
    assert result["model_calls"] >= 4 and result["prompt_tokens"] > 0
    steps = client.get(f"/api/agent/tasks/{task['id']}/steps").json()["items"]
    assert any(s["decision"].get("decision") == "CLICK" for s in steps)
    assert all(s["observation"]["screenshot_path"] for s in steps)
    assert client.get("/api/agent/memories").json()["total"] == 1


@pytest.mark.browser
async def test_assisted_review_and_stale_review(client, target, agent_config, agent_servers):
    set_url(client, target, "/agent/news")
    task = new_task(client, target, mode="assisted")
    execution = asyncio.create_task(execute(*claim()))
    deadline = time.monotonic() + 20
    pending = None
    while time.monotonic() < deadline:
        await asyncio.sleep(0.1)
        current = client.get("/api/agent/tasks/" + task["id"]).json()
        if current["pending_step_id"]:
            pending = current["pending_step_id"]
            break
    assert pending
    assert (
        client.post(
            f"/api/agent/tasks/{task['id']}/review", headers=OTHER_AUTH, json={"step_id": pending, "approved": True}
        ).status_code
        == 404
    )
    assert (
        client.post(f"/api/agent/tasks/{task['id']}/review", json={"step_id": pending, "approved": True}).status_code
        == 200
    )
    assert (
        client.post(f"/api/agent/tasks/{task['id']}/review", json={"step_id": pending, "approved": True}).status_code
        == 409
    )
    await asyncio.wait_for(execution, 30)
    assert client.get("/api/agent/tasks/" + task["id"]).json()["status"] == "completed"


@pytest.mark.browser
async def test_step_budget_does_not_mark_incomplete_success(client, target, agent_config, agent_servers):
    set_url(client, target, "/agent/news")
    task = new_task(client, target, max_steps=1)
    await execute(*claim())
    result = client.get("/api/agent/tasks/" + task["id"]).json()
    assert result["status"] == "failed" and not result["result"]


def test_interrupted_mutation_requires_review(client, target, agent_config):
    task = new_task(client, target)
    identifier, token = claim()
    with transaction() as session:
        session.add(
            AgentStep(job_id=identifier, number=1, observation={}, decision={"decision": "CLICK"}, status="executing")
        )
        session.get(Job, identifier).lease_until = time.time() - 1
    recover_expired()
    assert client.get("/api/agent/tasks/" + task["id"]).json()["status"] == "failed"


@pytest.mark.browser
async def test_reviewed_multistep_form_with_real_post(client, target, agent_config, agent_servers):
    set_url(client, target, "/agent/form")
    task = new_task(
        client,
        target,
        "Complete demo registration using Ada in the Name field and verify confirmation.",
        allow_form_input=True,
    )
    execution = asyncio.create_task(execute(*claim()))
    reviewed = set()
    deadline = time.monotonic() + 30
    while not execution.done() and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
        current = client.get("/api/agent/tasks/" + task["id"]).json()
        pending = current["pending_step_id"]
        if pending and pending not in reviewed:
            result = client.post(f"/api/agent/tasks/{task['id']}/review", json={"step_id": pending, "approved": True})
            assert result.status_code == 200
            reviewed.add(pending)
    await asyncio.wait_for(execution, 5)
    result = client.get("/api/agent/tasks/" + task["id"]).json()
    assert result["status"] == "completed", result
    assert len(reviewed) == 2
    assert "Registration received for Ada." in result["result"]["evidence"][0]["quote"]


@pytest.mark.browser
async def test_tab_manager_and_bounded_download(client, target, agent_config, agent_servers, monkeypatch):
    from testsupport.model_fixture import decide

    set_url(client, target, "/agent/news")

    async def planned(self, kind, payload, schema, account, image_path=None):
        data = {"purpose": kind, **payload}
        state = payload.get("current_page", {})
        memory = payload.get("session_memory", {})
        result = decide(data)
        if kind == "decide":
            links = state.get("elements", [])
            if result["decision"] == "CLICK":
                element = next(e for e in links if e["element_id"] == result["target"]["element_id"])
                result = dict(result, decision="OPEN_TAB", url=element["href"], target=None)
            elif not any(a["action"] == "DOWNLOAD" for a in memory.get("recent_actions", [])):
                link = next((e for e in links if "Download" in e["name"]), None)
                if link:
                    result = dict(result, decision="DOWNLOAD", target={"element_id": link["element_id"]}, text=None)
        return schema.model_validate(result)

    monkeypatch.setattr(ModelClient, "request", planned)
    task = new_task(client, target, allow_downloads=True)
    await execute(*claim())
    result = client.get("/api/agent/tasks/" + task["id"]).json()
    assert result["status"] == "completed", result
    assert len(result["memory"]["tabs"]) == 2
    steps = client.get(f"/api/agent/tasks/{task['id']}/steps").json()["items"]
    download = next(s["outcome"]["download_path"] for s in steps if "download_path" in s["outcome"])
    assert client.get("/api/artifacts/" + download).content == b"Orion AI will launch in November 2026."


@pytest.mark.browser
async def test_unobserved_completion_is_rejected(client, target, agent_config, agent_servers, monkeypatch):
    async def invented(self, *args, **kwargs):
        return Decision(
            observation="Unsupported conclusion",
            decision="COMPLETE",
            reason="No evidence",
            confidence=0.8,
            expected_result="Finish",
            claims=[{"text": "Invented result", "evidence_ids": ["missing"]}],
        )

    monkeypatch.setattr(ModelClient, "request", invented)
    set_url(client, target, "/agent/news")
    task = new_task(client, target, max_steps=1)
    await execute(*claim())
    result = client.get("/api/agent/tasks/" + task["id"]).json()
    assert result["status"] == "failed" and not result["result"]


async def test_model_malformed_json_is_rejected_and_accounted(agent_config, monkeypatch):
    original = httpx.AsyncClient

    async def response(request):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "```python\nprint(1)\n```"}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 20},
            },
        )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(response), **kw))
    charges = []

    def account(prompt, completion, latency, reserve, reservation=None):
        charges.append((prompt, completion, reserve))
        return (prompt, completion)

    with pytest.raises(ModelError, match="JSON schema"):
        await ModelClient().request("decide", {"objective": "Read docs"}, Decision, account)
    assert len(charges) == 2 and charges[-1] == (50, 20, False)


def test_token_budget_prevents_request(client, target, agent_config):
    from app.agent.runner import AgentRunner

    new_task(client, target)
    runner = AgentRunner(*claim())
    runner.account(runner.options["max_tokens"] - 100, 100, 0, True)
    with pytest.raises(RuntimeError, match="token budget"):
        runner.account(1, 1, 0, True)


@pytest.mark.browser
async def test_real_session_state_is_encrypted(client, target, agent_config, agent_servers, monkeypatch):
    from pydantic import SecretStr

    monkeypatch.setattr(agent_config, "browser_session_persistence", True)
    monkeypatch.setattr(agent_config, "session_encryption_key", SecretStr(Fernet.generate_key().decode()))
    set_url(client, target, "/agent/news")
    task = new_task(client, target, session_persistence=True)
    await execute(*claim())
    result = client.get("/api/agent/tasks/" + task["id"]).json()
    assert result["status"] == "completed", result
    with Session() as session:
        encrypted = session.get(AgentTask, task["id"]).encrypted_session
    assert "demo-cookie" not in encrypted
    assert any(c["name"] == "fixture_session" for c in decrypt_session(encrypted)["cookies"])
    assert "demo-cookie" not in str(result)


@pytest.mark.browser
async def test_failed_action_replans_from_fresh_observation(client, target, agent_config, agent_servers, monkeypatch):
    from testsupport.model_fixture import decide

    count = 0

    async def responses(self, kind, payload, schema, account, image_path=None):
        nonlocal count
        result = decide({"purpose": kind, **payload})
        if kind == "decide" and count == 0:
            result.update(decision="CLICK", target={"element_id": "missing"})
        count += 1
        return schema.model_validate(result)

    monkeypatch.setattr(ModelClient, "request", responses)
    set_url(client, target, "/agent/news")
    task = new_task(client, target)
    await execute(*claim())
    result = client.get("/api/agent/tasks/" + task["id"]).json()
    assert result["status"] == "completed", result
    steps = client.get(f"/api/agent/tasks/{task['id']}/steps").json()["items"]
    assert steps[0]["status"] == "failed" and steps[0]["outcome"]["replanning"]
    assert steps[1]["status"] == "succeeded"


@pytest.mark.browser
async def test_natural_interactions_persist_traces_and_automation_identity(
    client, target, agent_config, agent_servers, monkeypatch
):
    from testsupport.model_fixture import decide

    actions = iter(
        [
            ("FOCUS", "Keyboard widget", {}),
            ("TYPE", "Keyboard widget", {"text": "Orion", "input_method": "keyboard", "expected_text": "Key: n"}),
            ("PRESS_KEY", None, {"key": "Tab"}),
            ("HOVER", "Resources", {"expected_text": "Hover release notes"}),
            ("CLICK", "Hover release notes", {"expected_text": "Orion AI will launch in November 2026."}),
        ]
    )

    async def responses(self, kind, payload, schema, account, image_path=None):
        action = next(actions, None) if kind == "decide" else None
        if action:
            name, label, extras = action
            body = dict(
                observation="Observed fixture controls",
                decision=name,
                reason="Verify native input",
                confidence=1,
                expected_result="Expected UI transition",
                **extras,
            )
            if label:
                item = next(e for e in payload["current_page"]["elements"] if e["name"] == label)
                body["target"] = {"element_id": item["element_id"]}
            return schema.model_validate(body)
        return schema.model_validate(decide({"purpose": kind, **payload}))

    monkeypatch.setattr(ModelClient, "request", responses)
    set_url(client, target, "/agent/interactions")
    task = new_task(client, target, allow_form_input=True)
    await execute(*claim())
    result = client.get("/api/agent/tasks/" + task["id"]).json()
    assert result["status"] == "completed", result
    assert result["traffic_kind"] == "automated" and result["automation_session_id"] == task["id"]
    steps = client.get(f"/api/agent/tasks/{task['id']}/steps").json()["items"]
    assert "Automation marker: true" in steps[0]["observation"]["text"]
    assert [s["decision"]["decision"] for s in steps[:5]] == ["FOCUS", "TYPE", "PRESS_KEY", "HOVER", "CLICK"]
    for step in steps[:5]:
        assert step["outcome"]["interaction"]["verified"], step
        trace = step["outcome"]["trace"]
        assert {"decision", "inspection", "action", "waiting"} <= {span["phase"] for span in trace}
        assert all(span["ended_at"] >= span["started_at"] for span in trace)
    assert client.get("/api/agent/metrics").json()["traffic_kind"] == "automated"
