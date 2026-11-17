import json
import httpx
import pytest
from pydantic import BaseModel, SecretStr
from app.config import settings
from app.agent.model import ModelClient


class Reply(BaseModel):
    status: str


@pytest.fixture
def providers(monkeypatch):
    cfg = settings()
    for key, value in dict(
        ai_provider="groq",
        groq_base_url="https://groq.test/v1",
        groq_api_key=SecretStr("fixture-key"),
        ai_model="primary",
        ai_fallback_provider="local",
        ai_fallback_base_url="http://127.0.0.1:11434/v1",
        ai_fallback_model="qwen3:4b",
        ai_retries=0,
    ).items():
        monkeypatch.setattr(cfg, key, value)
    return cfg


def successful(headers=None):
    return httpx.Response(
        200,
        headers=headers,
        json={
            "choices": [{"message": {"content": '{"status":"ok"}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


@pytest.mark.parametrize("status", [400, 401, 402, 429, 500, 503])
async def test_failure_hands_off_once_and_stays_local(providers, monkeypatch, status):
    calls = []
    original = httpx.AsyncClient

    async def respond(request):
        calls.append(request.url.host)
        if request.url.host == "groq.test":
            assert request.extensions["timeout"]["read"] == 10
            return httpx.Response(status, headers={"retry-after": "3600"})
        body = json.loads(request.content)
        assert "/no_think" in body["messages"][0]["content"]
        return successful()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    client = ModelClient()
    for _ in range(2):
        assert (
            await client.request("decide", {"objective": "Read fixture"}, Reply, lambda *args: (1, 1))
        ).status == "ok"
    assert calls == ["groq.test", "127.0.0.1", "127.0.0.1"]
    assert client.fallback_active


@pytest.mark.parametrize(
    "header,value,should_switch",
    [
        ("tokens", "0", True),
        ("tokens", "100", True),
        ("requests", "1", True),
        ("requests", "0", True),
        ("tokens", "100000", False),
        ("tokens", "invalid", False),
    ],
)
async def test_quota_headers_switch_next_decision_without_discarding_success(
    providers, monkeypatch, header, value, should_switch
):
    calls = []
    original = httpx.AsyncClient

    async def respond(request):
        calls.append(request.url.host)
        return successful({"x-ratelimit-remaining-" + header: value})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    client = ModelClient()
    for _ in range(2):
        await client.request("decide", {"objective": "Read fixture"}, Reply, lambda *args: (1, 1))
    assert calls == ["groq.test", "127.0.0.1" if should_switch else "groq.test"]


async def test_primary_timeout_falls_back_without_retry(providers, monkeypatch):
    calls = []
    original = httpx.AsyncClient

    async def respond(request):
        calls.append(request.url.host)
        if request.url.host == "groq.test":
            raise httpx.ReadTimeout("fixture timeout")
        return successful()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    await ModelClient().request("decide", {}, Reply, lambda *args: (1, 1))
    assert calls == ["groq.test", "127.0.0.1"]


async def test_native_ollama_json_and_warmup(providers, monkeypatch):
    from app.agent.model import warm_local_fallback

    monkeypatch.setattr(providers, "ai_ollama_native", True)
    original = httpx.AsyncClient
    calls = []

    async def respond(request):
        calls.append(request.url.path)
        body = json.loads(request.content)
        if request.url.path == "/api/generate":
            assert body["keep_alive"] == -1 and body["options"]["num_ctx"] == 8192
            return httpx.Response(200, json={"done": True})
        if request.url.host == "groq.test":
            return httpx.Response(429)
        assert request.url.path == "/api/chat" and body["think"] is False
        assert body["format"]["properties"]["status"]["type"] == "string"
        return httpx.Response(
            200, json={"message": {"content": '{"status":"ok"}'}, "prompt_eval_count": 10, "eval_count": 5}
        )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    assert await warm_local_fallback() is True
    reply = await ModelClient().request("decide", {}, Reply, lambda *args: (1, 1))
    assert reply.status == "ok"
    assert calls == ["/api/generate", "/v1/chat/completions", "/api/chat"]


async def test_handoff_keeps_original_time_budget(providers, monkeypatch):
    from types import SimpleNamespace

    clock = [0]
    monkeypatch.setattr("app.agent.model.time", SimpleNamespace(monotonic=lambda: clock[0]))
    original = httpx.AsyncClient

    async def respond(request):
        if request.url.host == "groq.test":
            clock[0] = 2
            return httpx.Response(429)
        assert request.extensions["timeout"]["read"] == 1
        return successful()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    await ModelClient().request("decide", {}, Reply, lambda *args: (1, 1), timeout_cap_seconds=3)


async def test_failed_warmup_is_reported(providers, monkeypatch):
    from app.agent.model import warm_local_fallback

    monkeypatch.setattr(providers, "ai_ollama_native", True)
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(lambda request: httpx.Response(503)), **kw),
    )
    assert await warm_local_fallback() is False


async def test_native_text_fallback_does_not_send_unsupported_vision_payload(providers, monkeypatch, tmp_path):
    from PIL import Image

    monkeypatch.setattr(providers, "ai_ollama_native", True)
    path = tmp_path / "fixture.png"
    Image.new("RGB", (8, 8)).save(path)
    original = httpx.AsyncClient

    async def respond(request):
        if request.url.host == "groq.test":
            return httpx.Response(429)
        body = json.loads(request.content)
        assert isinstance(body["messages"][1]["content"], str)
        assert "image_url" not in body["messages"][1]
        return httpx.Response(
            200, json={"message": {"content": '{"status":"ok"}'}, "prompt_eval_count": 10, "eval_count": 5}
        )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    result = await ModelClient().request(
        "decide", {"current_page": {"text": "visible fixture text"}}, Reply, lambda *args: (1, 1), image_path=path
    )
    assert result.status == "ok"


async def test_native_validation_retry_gets_feedback(providers, monkeypatch):
    monkeypatch.setattr(providers, "ai_ollama_native", True)
    monkeypatch.setattr(providers, "ai_retries", 1)
    original = httpx.AsyncClient
    local_calls = []

    async def respond(request):
        if request.url.host == "groq.test":
            return httpx.Response(429)
        body = json.loads(request.content)
        local_calls.append(body)
        if len(local_calls) == 1:
            return httpx.Response(200, json={"message": {"content": "{}"}, "prompt_eval_count": 10, "eval_count": 5})
        assert "Validation errors" in body["messages"][-1]["content"]
        assert "status: missing" in body["messages"][-1]["content"]
        return httpx.Response(
            200, json={"message": {"content": '{"status":"ok"}'}, "prompt_eval_count": 10, "eval_count": 5}
        )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    assert (await ModelClient().request("decide", {}, Reply, lambda *args: (1, 1))).status == "ok"
    assert len(local_calls) == 2


@pytest.mark.parametrize("cancel_warmup", [False, True])
async def test_worker_warms_before_pickup_and_cancels_on_shutdown(providers, monkeypatch, cancel_warmup):
    import asyncio
    from types import SimpleNamespace
    from app import worker, automation

    callbacks = []
    events = []
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda sig, callback: callbacks.append(callback))
    monkeypatch.setattr(providers, "redis_url", "")

    class Routing:
        def start(self):
            events.append("routing_start")

        async def close(self):
            events.append("routing_closed")

    monkeypatch.setattr(worker, "manager", lambda: Routing())

    async def warm():
        events.append("warming")
        if cancel_warmup:
            callbacks[0]()
            try:
                await asyncio.Event().wait()
            finally:
                events.append("warmup_cancelled")
        events.append("warm_ready")
        return True

    monkeypatch.setattr("app.agent.model.warm_local_fallback", warm)

    def claim():
        assert "warm_ready" in events
        events.append("claim")
        callbacks[0]()
        return None

    monkeypatch.setattr(worker, "claim", claim)
    monkeypatch.setattr(worker, "recover_expired", lambda: None)
    monkeypatch.setattr(automation, "get_policy", lambda: SimpleNamespace(concurrency=1))
    monkeypatch.setattr(automation, "pulse", lambda *args: None)
    await asyncio.wait_for(worker.main(), 3)
    assert "routing_closed" in events
    assert ("claim" in events) is not cancel_warmup
    if cancel_warmup:
        assert "warmup_cancelled" in events


@pytest.mark.parametrize("network_timeout", [False, True])
async def test_expired_model_deadline_never_attempts_fallback(providers, monkeypatch, network_timeout):
    from types import SimpleNamespace
    from app.agent.model import ModelDeadlineExceeded

    clock = [0]
    monkeypatch.setattr("app.agent.model.time", SimpleNamespace(monotonic=lambda: clock[0]))
    original = httpx.AsyncClient
    calls = []

    async def respond(request):
        calls.append(request.url.host)
        clock[0] = 4
        if network_timeout:
            raise httpx.ReadTimeout("Model request exceeded its deadline", request=request)
        return httpx.Response(429)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    with pytest.raises(ModelDeadlineExceeded):
        await ModelClient().request("decide", {}, Reply, lambda *args: (1, 1), timeout_cap_seconds=3)
    assert calls == ["groq.test"]


async def test_native_search_permission_and_automatic_observation_hint(providers, monkeypatch):
    monkeypatch.setattr(providers, "ai_ollama_native", True)
    original = httpx.AsyncClient

    async def respond(request):
        if request.url.host == "groq.test":
            return httpx.Response(429)
        messages = json.loads(request.content)["messages"]
        assert "runner automatically observes" in messages[0]["content"]
        assert "Form input is disabled" in messages[2]["content"]
        assert "SEARCH requires target=" in messages[2]["content"]
        return httpx.Response(200, json={"message": {"content": '{"status":"ok"}'}})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    assert (await ModelClient().request("decide", {"form_input_enabled": False}, Reply, lambda *args: (1, 1))).status == "ok"


async def test_runner_rejects_expired_budget_before_request():
    import time
    from app.agent.runner import AgentRunner
    from app.agent.model import ModelDeadlineExceeded

    runner = AgentRunner.__new__(AgentRunner)
    runner.deadline = time.time() - 1
    with pytest.raises(ModelDeadlineExceeded, match="before model request"):
        await runner.ask_model("decide", {}, Reply)
