import asyncio
import json
import threading
import time

import pytest
import uvicorn
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.agent.contracts import Decision, TaskInput
from app.agent.controller import Controller
from app.agent.model import ModelBudgetExceeded, ModelClient
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
    monkeypatch.setattr(cfg, "ai_fallback_provider", "disabled")
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
    set_url(client, target, "/agent/form")
    task = new_task(client, target, "Complete demo registration using Ada in the Name field and verify confirmation.",
                    mode="assisted", allow_form_input=True)
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
async def test_autonomous_multistep_form_with_real_post(client, target, agent_config, agent_servers):
    set_url(client, target, "/agent/form")
    task = new_task(
        client,
        target,
        "Complete demo registration using Ada in the Name field and verify confirmation.",
        allow_form_input=True,
    )
    await asyncio.wait_for(execute(*claim()), 30)
    result = client.get("/api/agent/tasks/" + task["id"]).json()
    assert result["status"] == "completed", result
    assert result["pending_step_id"] is None
    with transaction() as session:
        assert all(step.approved is None for step in session.query(AgentStep).filter_by(job_id=task["id"]))
    assert "Registration received for Ada." in result["result"]["evidence"][0]["quote"]


@pytest.mark.browser
async def test_tab_manager_and_bounded_download(client, target, agent_config, agent_servers, monkeypatch):
    from testsupport.model_fixture import decide

    set_url(client, target, "/agent/news")

    async def planned(self, kind, payload, schema, account, image_path=None, timeout_cap_seconds=None):
        assert timeout_cap_seconds is not None and timeout_cap_seconds > 0
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
    assert result["status"] == "completed", (result.get("error_message"), result)
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


async def test_model_falls_back_to_local_after_groq_network_failure(agent_config, monkeypatch):
    from pydantic import BaseModel, SecretStr

    class Reply(BaseModel):
        status: str

    agent_config.ai_provider = "groq"
    agent_config.ai_model = "primary-fixture"
    agent_config.groq_api_key = SecretStr("test-key")
    agent_config.ai_fallback_provider = "local"
    agent_config.ai_fallback_model = "dolphin3:8b"
    agent_config.ai_fallback_base_url = "http://127.0.0.1:11434/v1"
    agent_config.ai_retries = 0
    original = httpx.AsyncClient
    requests = []

    async def response(request):
        requests.append(request)
        if "groq.test" in request.url.host:
            raise httpx.ConnectError("provider unavailable", request=request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"status":"ok"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
            request=request,
        )

    agent_config.groq_base_url = "https://groq.test/v1"
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(response), **kw))
    result = await ModelClient().request("decide", {"objective": "test"}, Reply, lambda *args: (1, 1))
    assert result.status == "ok"
    assert [request.url.host for request in requests] == ["groq.test", "127.0.0.1"]
    assert b'"model":"dolphin3:8b"' in requests[1].content


async def test_model_immediately_falls_back_after_any_primary_http_error(agent_config, monkeypatch):
    from pydantic import BaseModel, SecretStr

    class Reply(BaseModel):
        status: str

    agent_config.ai_provider = "groq"
    agent_config.ai_model = "primary-fixture"
    agent_config.groq_api_key = SecretStr("test-key")
    agent_config.groq_base_url = "https://groq.test/v1"
    agent_config.ai_fallback_provider = "local"
    agent_config.ai_fallback_model = "dolphin3:8b"
    agent_config.ai_fallback_base_url = "http://127.0.0.1:11434/v1"
    agent_config.ai_retries = 2
    original = httpx.AsyncClient
    requests = []

    async def response(request):
        requests.append(request)
        if request.url.host == "groq.test":
            return httpx.Response(400, request=request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"status":"ok"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
            request=request,
        )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(response), **kw))
    result = await ModelClient().request("decide", {"objective": "test"}, Reply, lambda *args: (1, 1))
    assert result.status == "ok"
    assert [request.url.host for request in requests] == ["groq.test", "127.0.0.1"]


async def test_fallback_retries_invalid_schema_without_spending_an_agent_step(agent_config, monkeypatch):
    from pydantic import BaseModel, SecretStr

    class Reply(BaseModel):
        status: str

    agent_config.ai_provider = "groq"
    agent_config.ai_model = "primary-fixture"
    agent_config.groq_api_key = SecretStr("test-key")
    agent_config.groq_base_url = "https://groq.test/v1"
    agent_config.ai_fallback_provider = "local"
    agent_config.ai_fallback_model = "dolphin3:8b"
    agent_config.ai_fallback_base_url = "http://127.0.0.1:11434/v1"
    agent_config.ai_retries = 1
    original = httpx.AsyncClient
    requests = []

    async def response(request):
        requests.append(request)
        if request.url.host == "groq.test":
            return httpx.Response(429, request=request)
        if len(requests) == 2:
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "not valid JSON"}}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 3},
                },
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"status":"ok"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
            request=request,
        )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(response), **kw))
    result = await ModelClient().request("decide", {"objective": "test"}, Reply, lambda *args: (1, 1))
    assert result.status == "ok"
    assert [request.url.host for request in requests] == ["groq.test", "127.0.0.1", "127.0.0.1"]


async def test_model_compacts_oversized_observation_before_request(agent_config, monkeypatch):
    from pydantic import BaseModel

    class Reply(BaseModel):
        status: str

    agent_config.ai_max_request_chars = 8000
    original = httpx.AsyncClient
    requests = []

    async def response(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"status":"ok"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
            request=request,
        )

    observation = {
        "url": "https://example.test/",
        "text": "a" * 100_000,
        "viewport_text": "b" * 100_000,
        "accessibility": "c" * 100_000,
        "headings": ["d" * 1000] * 100,
        "elements": [
            {"element_id": f"e{i}", "name": "e" * 1000, "href": "https://example.test/" + "f" * 1000}
            for i in range(100)
        ],
    }
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(response), **kw))
    result = await ModelClient().request(
        "decide", {"objective": "test", "current_page": observation}, Reply, lambda *args: (1, 1)
    )
    content = json.loads(requests[0].content)["messages"][1]["content"]
    assert result.status == "ok"
    assert len(content) < agent_config.ai_max_request_chars
    assert '"url":"https://example.test/"' in content


async def test_model_request_timeout_is_capped_by_remaining_session(agent_config, monkeypatch):
    from pydantic import BaseModel

    class Reply(BaseModel):
        status: str

    agent_config.ai_timeout_seconds = 90
    original = httpx.AsyncClient
    observed = []

    async def response(request):
        observed.append(request.extensions["timeout"]["read"])
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"status":"ok"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
            request=request,
        )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(response), **kw))
    result = await ModelClient().request(
        "decide", {"objective": "test"}, Reply, lambda *args: (1, 1), timeout_cap_seconds=7
    )
    assert result.status == "ok"
    assert observed == [7]


async def test_model_falls_back_after_413_without_spending_rejected_reservation(agent_config, monkeypatch):
    from pydantic import BaseModel, SecretStr

    class Reply(BaseModel):
        status: str

    agent_config.ai_provider = "groq"
    agent_config.ai_model = "primary-fixture"
    agent_config.groq_api_key = SecretStr("test-key")
    agent_config.ai_fallback_provider = "local"
    agent_config.ai_fallback_model = "dolphin3:8b"
    agent_config.ai_fallback_base_url = "http://127.0.0.1:11434/v1"
    agent_config.ai_retries = 0
    original = httpx.AsyncClient
    requests = []
    balance = [0, 0]

    async def response(request):
        requests.append(request)
        if request.url.host == "groq.test":
            return httpx.Response(413, request=request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"status":"ok"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
            request=request,
        )

    def account(prompt, completion, latency, reserve, reservation=None):
        if reserve:
            balance[0] += prompt
            balance[1] += completion
            return (prompt, completion)
        balance[0] += prompt - reservation[0]
        balance[1] += completion - reservation[1]

    agent_config.groq_base_url = "https://groq.test/v1"
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(response), **kw))
    result = await ModelClient().request("decide", {"objective": "test"}, Reply, account)
    assert result.status == "ok"
    assert [request.url.host for request in requests] == ["groq.test", "127.0.0.1"]
    assert balance == [12, 3]


async def test_model_falls_back_when_primary_task_budget_is_reserved(agent_config, monkeypatch):
    from pydantic import BaseModel, SecretStr

    class Reply(BaseModel):
        status: str

    agent_config.ai_provider = "groq"
    agent_config.ai_model = "primary-fixture"
    agent_config.groq_api_key = SecretStr("test-key")
    agent_config.ai_fallback_provider = "local"
    agent_config.ai_fallback_model = "dolphin3:8b"
    agent_config.ai_fallback_base_url = "http://127.0.0.1:11434/v1"
    requests = []
    original = httpx.AsyncClient

    async def response(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"status":"ok"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
            request=request,
        )

    def account(prompt, completion, latency, reserve, reservation=None):
        if reserve and reservation["provider_index"] == 0:
            raise ModelBudgetExceeded("primary token reserve exhausted")
        if reserve:
            return (prompt, completion)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(response), **kw))
    result = await ModelClient().request("decide", {"objective": "test"}, Reply, account)
    assert result.status == "ok"
    assert len(requests) == 1
    assert requests[0].url.host == "127.0.0.1"
    assert b'"model":"dolphin3:8b"' in requests[0].content


def test_token_budget_prevents_request(client, target, agent_config):
    from app.agent.runner import AgentRunner

    new_task(client, target)
    runner = AgentRunner(*claim())
    runner.account(runner.options["max_tokens"] - 100, 100, 0, True)
    with pytest.raises(RuntimeError, match="token budget"):
        runner.account(1, 1, 0, True)


def test_fallback_budget_is_reserved_from_primary(client, target, agent_config):
    from app.agent.runner import AgentRunner

    agent_config.ai_fallback_provider = "local"
    new_task(client, target)
    runner = AgentRunner(*claim())
    fallback_reserve = agent_config.agent_fallback_tokens
    primary_budget = runner.options["max_tokens"] - fallback_reserve

    runner.account(primary_budget - 100, 100, 0, True, {"provider_index": 0})
    with pytest.raises(RuntimeError, match="token budget"):
        runner.account(1, 1, 0, True, {"provider_index": 0})
    runner.account(1, 1, 0, True, {"provider_index": 1})


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

    async def responses(self, kind, payload, schema, account, image_path=None, timeout_cap_seconds=None):
        nonlocal count
        assert timeout_cap_seconds is not None and timeout_cap_seconds > 0
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
    assert result["status"] == "completed", (result.get("error_message"), result)
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

    async def responses(self, kind, payload, schema, account, image_path=None, timeout_cap_seconds=None):
        assert timeout_cap_seconds is not None and timeout_cap_seconds > 0
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


@pytest.mark.browser
@pytest.mark.parametrize("deadline", [False, True])
async def test_unchanged_observe_and_deadline_do_not_loop(
    client, target, agent_config, agent_servers, monkeypatch, deadline
):
    from app.agent.model import ModelDeadlineExceeded

    calls = []

    async def response(self, kind, payload, schema, account, image_path=None, **kwargs):
        calls.append(kind)
        if deadline:
            raise ModelDeadlineExceeded("Task time budget exhausted before model request")
        return Decision(
            observation="The same readable page",
            decision="OBSERVE",
            reason="Inspect again",
            confidence=1,
            expected_result="Same page",
        )

    monkeypatch.setattr(ModelClient, "request", response)
    set_url(client, target, "/agent/news")
    task = new_task(client, target)
    await execute(*claim())
    result = client.get("/api/agent/tasks/" + task["id"]).json()
    assert result["status"] == "failed"
    steps = client.get("/api/agent/tasks/" + task["id"] + "/steps").json()["items"]
    logs = client.get("/api/jobs/" + task["id"] + "/logs").json()["items"]
    if deadline:
        assert len(calls) == 1
        assert not any(e["event_type"] == "agent_replanning" for e in logs)
    else:
        assert len(calls) == 1 + agent_config.agent_max_retries
        assert sum(s["status"] == "succeeded" for s in steps) == 1
        assert "recovery budget" in result["error_message"]


@pytest.mark.parametrize("mode", ["assisted", "autonomous", "supervised"])
def test_all_clicks_skip_review(mode):
    controller = Controller.__new__(Controller)
    decision = Decision(observation="A purchase button", decision="CLICK", target={"element_id": "e1"},
                        reason="Complete the task", confidence=1, expected_result="Submitted")
    assert controller.needs_review(decision, mode) is False
    question = decision.model_copy(update={"decision": "ASK_USER", "text": "Which item?"})
    assert controller.needs_review(question, mode) is True


def test_step_limit_defaults_and_validation(client, target, agent_config, monkeypatch):
    from app.config import Settings

    assert Settings(_env_file=None).agent_max_steps == 500
    body = {"website_id": target["id"], "objective": "Inspect this website."}
    assert TaskInput(**body).max_steps == 500
    monkeypatch.setattr(agent_config, "agent_max_steps", 500)
    assert client.get("/api/agent/config").json()["max_steps"] == 500
    for limit in [100, 101, 500]:
        response = client.post("/api/agent/tasks", json={**body, "max_steps": limit})
        assert response.status_code == 201, response.text
        assert response.json()["options"]["max_steps"] == limit
    for limit in [0, 501]:
        assert client.post("/api/agent/tasks", json={**body, "max_steps": limit}).status_code == 422
        with pytest.raises(ValidationError):
            Settings(_env_file=None, agent_max_steps=limit)
    monkeypatch.setattr(agent_config, "agent_max_steps", 100)
    assert client.post("/api/agent/tasks", json={**body, "max_steps": 500}).json()["options"]["max_steps"] == 100
