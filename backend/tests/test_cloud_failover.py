"""Cloud failover regressions; every credential and transport is a test double."""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel, SecretStr, ValidationError
from PIL import Image

from app.agent.model import ModelClient, ModelError, ModelProvidersUnavailable
from app.config import Settings, settings
from test_browser import fixture_server  # noqa: F401


class Reply(BaseModel):
    status: str


async def test_provider_context_rejection_rebuilds_before_retry(cloud, monkeypatch):
    original = httpx.AsyncClient
    requests, reservations = [], []
    objective = "Compare two observed services"

    async def respond(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(400, json={"error": {"code": "context_length_exceeded"}})
        return success()

    def account(prompt, completion, latency, reserve, receipt=None):
        if reserve:
            reservations.append((prompt, completion))
            return (prompt, completion)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    page = {"text": "Distracting text " * 400, "research_chunks": [{"quote": "Evidence " * 35}] * 12,
            "elements": [{"element_id": "observed1", "visible": True, "actionable": True, "name": "Related source"}]}
    result = await ModelClient().request("decide", {"objective": objective, "current_page": page}, Reply, account)
    assert result.status == "ok"
    assert len(requests) == 2 and requests[0]["model"] == requests[1]["model"]
    assert reservations[1][0] < reservations[0][0]
    retry = json.loads(requests[1]["messages"][1]["content"])
    assert retry["objective"] == objective and "schema" in retry
    assert retry["current_page"]["elements"][0]["element_id"] == "observed1"
    print(f"context recovery input estimates {reservations[0][0]} -> {reservations[1][0]} with {reservations[1][1]} output reserved")


@pytest.fixture
def cloud(monkeypatch):
    cfg = settings()
    values = dict(
        ai_provider="groq", ai_model="primary", ai_provider_order="groq,openrouter,google,nvidia,groq_secondary",
        ai_fallback_provider="disabled", ai_ollama_native=True, ai_retries=4,
        groq_base_url="https://groq.test/v1", groq_api_key=SecretStr("primary-key"),
        groq_secondary_api_key=SecretStr("secondary-key"), groq_secondary_model="secondary",
        openrouter_base_url="https://openrouter.test/v1", openrouter_api_key=SecretStr("router-key"),
        openrouter_model="router", google_base_url="https://google.test/v1", google_api_key=SecretStr("google-key"),
        google_model="google", nvidia_base_url="https://nvidia.test/v1", nvidia_api_key=SecretStr("nvidia-key"),
        nvidia_model="nvidia", ai_provider_rpm=0, ai_provider_tpm=0,
    )
    for name, value in values.items():
        monkeypatch.setattr(cfg, name, value)
    return cfg


def success(content='{"status":"ok"}'):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}],
                                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}})


@pytest.mark.parametrize("failed", [1, 2, 3, 4])
@pytest.mark.parametrize("failure", [401, 402, 429, 503, "timeout", "protocol", "schema", "envelope", "array", "usage"])
async def test_chain_hands_off_each_failure_once_and_preserves_request(cloud, monkeypatch, failed, failure):
    calls, requests, reservations, settlements = [], [], [], []
    original = httpx.AsyncClient

    async def respond(request):
        body = json.loads(request.content)
        calls.append(body["model"])
        requests.append(body)
        assert request.url.path == "/v1/chat/completions"  # Never Ollama for remote fallbacks.
        if len(calls) <= failed:
            assert request.extensions["timeout"]["read"] == cloud.ai_primary_fallback_timeout_seconds
            assert request.extensions["timeout"]["connect"] == 3
            if isinstance(failure, int):
                return httpx.Response(failure, headers={"retry-after": "3600"})
            if failure == "timeout":
                raise httpx.ReadTimeout("fixture")
            if failure == "protocol":
                raise httpx.RemoteProtocolError("fixture")
            if failure == "schema":
                return success('{}')
            if failure == "array":
                return httpx.Response(200, json=[])
            if failure == "envelope":
                return httpx.Response(200, json={"choices": []})
            return httpx.Response(200, json={"usage": {"prompt_tokens": -1, "completion_tokens": 5}})
        return success()

    def account(prompt, completion, latency, reserve, receipt=None):
        (reservations if reserve else settlements).append(receipt)
        return (prompt, completion) if reserve else None

    async def no_backoff(*args):
        pytest.fail("Failover must not sleep for provider retries")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    monkeypatch.setattr("app.agent.model.asyncio.sleep", no_backoff)
    client = ModelClient()
    for _ in range(2):
        assert (await client.request("decide", {"objective": "keep this objective"}, Reply, account)).status == "ok"
    models = [entry[2] for entry in cloud.model_providers()]
    assert calls == models[:failed] + [models[failed], models[failed]]
    assert len(reservations) == len(settlements) == failed + 2
    assert all(body["messages"] == requests[0]["messages"] for body in requests)
    assert client.active_provider_index == failed


async def test_shared_cooldowns_skip_every_failed_provider_in_new_task(cloud, monkeypatch):
    original, calls = httpx.AsyncClient, []

    async def respond(request):
        model = json.loads(request.content)["model"]
        calls.append(model)
        return success() if model == "secondary" else httpx.Response(503)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    for _ in range(2):
        await ModelClient().request("decide", {}, Reply, lambda *args: (1, 1))
    assert calls == ["primary", "router", "google", "nvidia", "secondary", "secondary"]


async def test_all_failed_providers_exhaust_chain_without_retries(cloud, monkeypatch):
    original, calls = httpx.AsyncClient, []

    async def respond(request):
        calls.append(json.loads(request.content)["model"])
        return httpx.Response(401)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    with pytest.raises(ModelError, match="HTTP 401"):
        await ModelClient().request("decide", {}, Reply, lambda *args: (1, 1))
    assert calls == [entry[2] for entry in cloud.model_providers()]


async def test_cancelled_task_does_not_start_another_model(cloud, monkeypatch):
    original, calls = httpx.AsyncClient, []

    async def respond(request):
        calls.append(request.url.host)
        raise asyncio.CancelledError()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    with pytest.raises(asyncio.CancelledError):
        await ModelClient().request("decide", {}, Reply, lambda *args: (1, 1))
    assert calls == ["groq.test"]


async def test_remote_fallbacks_keep_remote_egress_policy(cloud, monkeypatch):
    from app import egress, outbound, user_agents
    observed, agents = [], []

    @asynccontextmanager
    async def proxy(policy, methods, service, token):
        observed.append((policy.local, service))
        yield "http://127.0.0.1:12345"

    monkeypatch.setattr(outbound, "manager", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(egress, "egress_proxy", proxy)
    monkeypatch.setattr(user_agents, "resolve", lambda service, **kw: agents.append(service) or "Fixture/1")
    async with outbound.model_clients(cloud.model_providers(), trust_env=False) as clients:
        assert len(clients) == 5
    assert observed == [(False, "ai")] * 5
    assert agents == ["ai"] * 5


def test_new_provider_keys_are_redacted(cloud):
    from app.privacy import Redact
    secrets = [key.get_secret_value() for _, key, _ in cloud.model_providers()]
    record = logging.LogRecord("fixture", 30, "", 0, " ".join(secrets), (), None)
    Redact().filter(record)
    assert all(secret not in record.getMessage() for secret in secrets)


@pytest.mark.parametrize("change", [
    {"ai_provider_order": "openrouter,groq"},
    {"ai_provider_order": "groq,unknown"},
    {"ai_provider_order": "groq,groq"},
    {"ai_provider_order": "groq,openrouter", "openrouter_api_key": ""},
    {"ai_provider_order": "groq,openrouter", "openrouter_base_url": "http://remote.test/v1"},
    {"ai_provider_order": "groq,openrouter", "openrouter_base_url": "https://remote.test/v1#fragment"},
])
def test_invalid_cloud_chain_rejected(cloud, change):
    values = cloud.model_dump()
    values.update(change)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_disabled_provider_retains_configuration_without_enabling_requests(cloud):
    cfg = Settings(_env_file=None, **{**cloud.model_dump(), "ai_provider": "disabled"})
    assert cfg.model_providers() == []


async def test_stalled_stream_is_bounded_and_closed_before_handoff(cloud, monkeypatch):
    original, calls, closed = httpx.AsyncClient, [], []
    monkeypatch.setattr(cloud, "ai_primary_fallback_timeout_seconds", 0.01)

    class StalledStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"choices":['
            await asyncio.Event().wait()

        async def aclose(self):
            closed.append(True)

    async def respond(request):
        calls.append(json.loads(request.content)["model"])
        if len(calls) == 1:
            return httpx.Response(200, stream=StalledStream())
        assert closed
        return success()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    result = await ModelClient().request("decide", {}, Reply, lambda *args: (1, 1))
    assert result.status == "ok"
    assert calls == ["primary", "router"]


@pytest.mark.parametrize("primary", ["groq", "openrouter", "google", "nvidia", "groq_secondary"])
def test_any_named_provider_can_be_primary(cloud, primary):
    names = cloud.ai_provider_order.split(",")
    order = ",".join([primary] + [name for name in names if name != primary])
    cfg = Settings(_env_file=None, **{**cloud.model_dump(), "ai_provider": primary, "ai_provider_order": order})
    assert cfg.model_providers()[0][2] == cfg.ai_model
    for name, (_, _, model) in zip(order.split(","), cfg.model_providers()):
        if name != primary:
            assert model == getattr(cfg, name + "_model")


@pytest.mark.browser
async def test_existing_browser_task_completes_through_cloud_chain(client, target, cloud, fixture_server, monkeypatch):  # noqa: F811
    from app.jobs import claim
    from app.worker import execute
    from testsupport.model_fixture import app as fixture_model

    original, calls = httpx.AsyncClient, []
    fixture_transport = httpx.ASGITransport(app=fixture_model)

    async def respond(request):
        if request.url.host not in {"groq.test", "openrouter.test", "google.test", "nvidia.test"}:
            async with original(trust_env=False) as local:
                return await local.send(request)
        model = json.loads(request.content)["model"]
        calls.append(model)
        if model == "primary" and calls.count(model) > 1:
            return httpx.Response(429, headers={"retry-after": "3600"})
        if model == "router":
            return httpx.Response(503)
        if model == "google":
            return success('{}')
        return await fixture_transport.handle_async_request(request)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    data = {key: target[key] for key in ("name", "base_url", "allowed_domains", "configuration")}
    data.update(base_url="http://127.0.0.1:8765/agent/article/orion", authorized=True)
    data["configuration"] = {**data["configuration"], "max_duration_seconds": 120, "screenshots": False}
    assert client.patch("/api/websites/" + target["id"], json=data).status_code == 200
    response = client.post("/api/agent/tasks", json={
        "website_id": target["id"], "objective": "Find the launch month for Orion AI and cite the source.",
        "max_steps": 6, "max_tokens": 100000, "memory_enabled": False,
    })
    assert response.status_code == 201, response.text
    identifier = response.json()["id"]
    item = claim()
    assert item[0] == identifier
    await execute(*item)
    task = client.get("/api/agent/tasks/" + identifier).json()
    assert task["status"] == "completed", task
    assert task["result"]["verification"]["complete"] is True
    assert task["result"]["evidence"]
    assert task["result"]["models_used"] == ["nvidia", "primary"]
    assert calls[:4] == ["primary", "primary", "router", "google"]
    assert all(model == "nvidia" for model in calls[4:])


async def test_last_provider_failure_revisits_recovered_primary(cloud, monkeypatch):
    from app import provider_quota
    clock, calls = [1000.0], []
    monkeypatch.setattr(provider_quota, "time", SimpleNamespace(time=lambda: clock[0]))
    monkeypatch.setattr("app.agent.model.time", SimpleNamespace(monotonic=lambda: clock[0]))
    original = httpx.AsyncClient

    async def respond(request):
        model = json.loads(request.content)["model"]
        calls.append(model)
        if clock[0] == 1000 and model != "secondary":
            return httpx.Response(503)
        if clock[0] > 1000 and model == "secondary":
            raise httpx.ReadTimeout("last provider failed")
        return success()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    client = ModelClient()
    await client.request("decide", {}, Reply, lambda *args: (1, 1))
    assert client.active_provider_index == 4
    clock[0] += 31
    for _ in range(2):
        await client.request("decide", {}, Reply, lambda *args: (1, 1))
    assert calls == ["primary", "router", "google", "nvidia", "secondary", "secondary", "primary", "primary"]
    assert client.active_provider_index == 0


async def test_all_cooling_providers_report_earliest_retry_without_dispatch(cloud, monkeypatch):
    from app import provider_quota
    from app.agent import model as agent_model
    from app.provider_quota import cooldown, identity

    # This checks ordering and remaining cooldown, independent of SQLite I/O latency.
    monkeypatch.setattr(provider_quota, "time", SimpleNamespace(time=lambda: 1000))
    monkeypatch.setattr(agent_model, "time", SimpleNamespace(monotonic=lambda: 1000))
    for index, (base, key, _) in enumerate(cloud.model_providers()):
        cooldown(identity(base, key.get_secret_value()), 10 + index * 10)

    def no_charge(*args):
        pytest.fail("Cooldown skips must not reserve the task budget")

    with pytest.raises(ModelProvidersUnavailable) as captured:
        await ModelClient().request("decide", {}, Reply, no_charge)
    assert captured.value.retry_after == 10
    assert [item["provider"] for item in captured.value.failures] == cloud.ai_provider_order.split(",")


async def test_provider_events_identify_failures_without_credentials(cloud, monkeypatch):
    original, events = httpx.AsyncClient, []
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(lambda request: httpx.Response(401)), **kw))
    client = ModelClient()
    client.on_provider_event = events.append
    with pytest.raises(ModelProvidersUnavailable) as captured:
        await client.request("decide", {}, Reply, lambda *args: (1, 1))
    assert captured.value.retry_after is None  # Invalid credentials are terminal, not a temporary outage.
    assert [item["provider"] for item in events] == cloud.ai_provider_order.split(",")
    assert all("HTTP 401" in item["reason"] for item in events)
    assert not any(key.get_secret_value() in json.dumps(events) for _, key, _ in cloud.model_providers())


def inference_runner(request):
    import time
    from app.agent.runner import AgentRunner
    runner = AgentRunner.__new__(AgentRunner)
    runner.deadline = time.time() + 60
    runner.model = SimpleNamespace(request=request)
    runner.gate = asyncio.Event()
    runner.gate.set()
    runner.memory = {"failures": [], "planning": {"replans": [], "retry_counts": {}}}
    return runner


async def test_provider_cooldown_wait_preserves_inference_and_action_budget(monkeypatch):
    calls, notices = [], []
    payload = {"objective": "original objective", "current_page": {"url": "https://fixture.test"}}

    async def request(kind, data, schema, account, image, **kwargs):
        calls.append((kind, data, schema, kwargs["timeout_cap_seconds"]))
        if len(calls) < 3:
            raise ModelProvidersUnavailable([{"provider": "groq", "reason": "ReadTimeout"}], retry_after=0.001)
        return Reply(status="ok")

    runner = inference_runner(request)
    async def notice(kind, message, **details):
        notices.append(kind)
    monkeypatch.setattr(runner, "provider_notice", notice)
    assert (await runner.ask_model("decide", payload, Reply)).status == "ok"
    assert len(calls) == 3 and all(item[1] is payload and item[2] is Reply for item in calls)
    assert calls[0][3] >= calls[1][3] >= calls[2][3]
    assert notices == ["model_waiting", "model_waiting"]
    assert runner.memory == {"failures": [], "planning": {"replans": [], "retry_counts": {}}}


async def test_provider_wait_cannot_exceed_remaining_task_deadline():
    from app.agent.model import ModelDeadlineExceeded
    calls = []
    async def request(*args, **kwargs):
        calls.append(True)
        raise ModelProvidersUnavailable([{"provider": "groq", "reason": "cooling down"}], retry_after=3600)
    with pytest.raises(ModelDeadlineExceeded, match="cannot recover"):
        await inference_runner(request).ask_model("decide", {}, Reply)
    assert calls == [True]


async def test_provider_wait_remains_cancellable(monkeypatch):
    waiting, calls = asyncio.Event(), []
    async def request(*args, **kwargs):
        calls.append(True)
        raise ModelProvidersUnavailable([{"provider": "groq", "reason": "cooling down"}], retry_after=20)
    runner = inference_runner(request)
    async def notice(*args, **kwargs):
        waiting.set()
    monkeypatch.setattr(runner, "provider_notice", notice)
    task = asyncio.create_task(runner.ask_model("decide", {}, Reply))
    await asyncio.wait_for(waiting.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == [True]


@pytest.mark.parametrize("provider,reasoning_field", [("groq", "reasoning_effort"), ("openrouter", "reasoning")])
@pytest.mark.parametrize("configured,purpose,effort", [
    ("auto", "decide", "medium"), ("auto", "verify", "high"), ("low", "verify", "low"),
])
async def test_gpt_oss_uses_configured_reasoning_budget(cloud, monkeypatch, provider, reasoning_field,
                                                       configured, purpose, effort):
    monkeypatch.setattr(cloud, "ai_provider", provider)
    monkeypatch.setattr(cloud, "ai_provider_order", provider)
    monkeypatch.setattr(cloud, "ai_model", "openai/gpt-oss-120b")
    monkeypatch.setattr(cloud, "ai_reasoning_effort", configured)
    original = httpx.AsyncClient
    async def respond(request):
        body = json.loads(request.content)
        expected = {"effort": effort} if provider == "openrouter" else effort
        assert body[reasoning_field] == expected
        return success()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    await ModelClient().request(purpose, {}, Reply, lambda *args: (1, 1))


@pytest.mark.parametrize("screenshot_exists", [True, False])
async def test_vision_fallback_only_sends_screenshot_to_compatible_model(cloud, monkeypatch, tmp_path, screenshot_exists):
    monkeypatch.setattr(cloud, "ai_model", "vision-fixture")
    monkeypatch.setattr(cloud, "ai_vision_models", "groq:vision-fixture")
    screenshot = tmp_path / "observation.png"
    if screenshot_exists:
        with Image.new("RGB", (24, 24)) as picture:
            picture.save(screenshot)
    contents = []
    original = httpx.AsyncClient

    async def respond(request):
        contents.append(json.loads(request.content)["messages"][1]["content"])
        return httpx.Response(503) if len(contents) == 1 else success()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    await ModelClient().request("decide", {}, Reply, lambda *args: (1, 1), image_path=screenshot)
    assert len(contents) == 2 and isinstance(contents[1], str)
    if screenshot_exists:
        assert contents[0][0]["text"] == contents[1]
        assert contents[0][1]["type"] == "image_url"
    else:
        assert contents[0] == contents[1]


@pytest.mark.browser
async def test_browser_task_waits_for_provider_recovery_without_replanning(client, target, cloud, fixture_server, monkeypatch):  # noqa: F811
    from app.agent import runner as runner_module
    from app.db import ProviderQuota, transaction
    from app.jobs import claim
    from app.worker import execute
    from sqlalchemy import update
    from testsupport.model_fixture import app as fixture_model

    original, failures, decide_payloads, waits = httpx.AsyncClient, [], [], []
    fixture_transport = httpx.ASGITransport(app=fixture_model)
    recovered = False

    async def expire_cooldowns(delay):
        nonlocal recovered
        waits.append(delay)
        with transaction() as session:
            session.execute(update(ProviderQuota).values(cooldown_until=0))
        recovered = True

    # Advance only this runner's inference wait; browser and worker clocks remain real.
    monkeypatch.setattr(runner_module, "asyncio", SimpleNamespace(sleep=expire_cooldowns, timeout=asyncio.timeout))

    async def respond(request):
        if request.url.host not in {"groq.test", "openrouter.test", "google.test", "nvidia.test"}:
            async with original(trust_env=False) as local:
                return await local.send(request)
        body = json.loads(request.content)
        payload = json.loads(body["messages"][1]["content"])
        if payload["purpose"] == "decide":
            decide_payloads.append(payload)
            if not recovered:
                failures.append(body["model"])
                return httpx.Response(503)
        return await fixture_transport.handle_async_request(request)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    data = {key: target[key] for key in ("name", "base_url", "allowed_domains", "configuration")}
    data.update(base_url="http://127.0.0.1:8765/agent/article/orion", authorized=True)
    data["configuration"] = {**data["configuration"], "max_duration_seconds": 120, "screenshots": False}
    assert client.patch("/api/websites/" + target["id"], json=data).status_code == 200
    response = client.post("/api/agent/tasks", json={
        "website_id": target["id"], "objective": "Find the launch month for Orion AI and cite the source.",
        "max_steps": 6, "max_tokens": 100000, "memory_enabled": False,
    })
    assert response.status_code == 201, response.text
    identifier = response.json()["id"]
    item = claim()
    assert item[0] == identifier
    await execute(*item)
    task = client.get("/api/agent/tasks/" + identifier).json()
    assert task["status"] == "completed", task
    assert task["result"]["verification"]["complete"] is True
    assert failures == ["primary", "router", "google", "nvidia", "secondary"]
    assert len(waits) == 1
    assert all(payload == decide_payloads[0] for payload in decide_payloads[:6])
    assert task["memory"]["planning"]["replans"] == []
    assert task["memory"]["planning"].get("retry_counts", {}) == {}
    steps = client.get("/api/agent/tasks/" + identifier + "/steps").json()["items"]
    assert all(step["status"] == "succeeded" for step in steps)


async def test_retry_after_on_server_errors_is_preserved(cloud, monkeypatch):
    # Verify the provider's delay independently of host/SQLite scheduling time.
    monkeypatch.setattr("app.agent.model.time", SimpleNamespace(monotonic=lambda: 1000.0))
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(
        lambda request: httpx.Response(503, headers={"retry-after": "120"})), **kw))
    with pytest.raises(ModelProvidersUnavailable) as captured:
        await ModelClient().request("decide", {}, Reply, lambda *args: (1, 1))
    assert 120 <= captured.value.retry_after <= 120.25


async def test_paused_model_request_keeps_original_deadline():
    import time
    from app.agent.model import ModelDeadlineExceeded
    async def request(*args, **kwargs):
        pytest.fail("A paused task must not send model requests")
    runner = inference_runner(request)
    runner.gate.clear()
    runner.deadline = time.time() + 5.01
    with pytest.raises(ModelDeadlineExceeded, match="while paused"):
        await runner.ask_model("decide", {}, Reply)


async def test_context_window_skips_incompatible_provider_without_spending_budget(cloud, monkeypatch):
    monkeypatch.setattr(cloud, "ai_context_windows", {"groq": 256})
    calls, reservations = [], []
    original = httpx.AsyncClient

    async def respond(request):
        calls.append(request.url.host)
        return success()

    def account(prompt, completion, latency, reserve, receipt=None):
        if reserve:
            reservations.append(receipt["provider_index"])
            return (prompt, completion)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    model = ModelClient()
    await model.request("decide", {}, Reply, account)
    assert calls == ["openrouter.test"]
    assert reservations == [1]
