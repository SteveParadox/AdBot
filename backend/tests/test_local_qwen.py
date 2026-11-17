"""Opt-in, real local model + browser test. Never contacts the real Groq service."""

import os
import httpx
import pytest
from pydantic import SecretStr
from app.config import settings
from app.agent.model import warm_local_fallback
from app.jobs import claim
from app.worker import execute
from test_browser import fixture_server  # noqa: F401


@pytest.mark.browser
@pytest.mark.skipif(
    os.environ.get("ADBOT_TEST_LOCAL_QWEN") != "1", reason="Requires explicitly enabled local Ollama qwen3:4b"
)
async def test_real_qwen_finishes_existing_task_after_simulated_groq_limit(client, target, fixture_server, monkeypatch):  # noqa: F811
    cfg = settings()
    for key, value in dict(
        ai_provider="groq",
        ai_model="simulated-groq",
        groq_api_key=SecretStr("fixture-key"),
        groq_base_url="https://groq.test/v1",
        ai_fallback_provider="local",
        ai_fallback_model="qwen3:4b",
        ai_fallback_base_url="http://127.0.0.1:11434/v1",
        ai_ollama_native=True,
        ai_fallback_timeout_seconds=120,
    ).items():
        monkeypatch.setattr(cfg, key, value)
    original = httpx.AsyncClient
    calls = []

    async def handle(request):
        if request.url.host == "groq.test":
            calls.append("groq-429")
            return httpx.Response(429, headers={"retry-after": "3600"})
        assert request.url.host == "127.0.0.1" and request.url.port in (11434, 8765)
        if request.url.path == "/api/chat":
            calls.append("qwen")
        async with original(timeout=120, trust_env=False) as real:
            response = await real.send(request)
            if request.url.path == "/api/chat":
                data = response.json()
                print("QWEN_RESULT", data.get("message", {}).get("content", "")[:700], flush=True)
            return response

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    assert await warm_local_fallback() is True
    data = {k: target[k] for k in ("name", "base_url", "allowed_domains", "configuration")}
    data["base_url"] = "http://127.0.0.1:8765/agent/article/orion"
    data["authorized"] = True
    data["configuration"] = {**data["configuration"], "max_duration_seconds": 300, "screenshots": False}
    assert client.patch("/api/websites/" + target["id"], json=data).status_code == 200
    response = client.post(
        "/api/agent/tasks",
        json={
            "website_id": target["id"],
            "objective": "Find the launch month for Orion AI and cite the source.",
            "max_steps": 6,
            "max_tokens": 100000,
            "memory_enabled": False,
        },
    )
    assert response.status_code == 201, response.text
    identifier = response.json()["id"]
    item = claim()
    assert item[0] == identifier
    await execute(*item)
    result = client.get("/api/agent/tasks/" + identifier).json()
    assert result["status"] == "completed", (result.get("error_message"), result.get("memory"))
    assert result["result"]["verification"]["complete"] is True
    assert result["result"]["models_used"] == ["qwen3:4b"]
    assert calls[0] == "groq-429" and calls.count("groq-429") == 1 and calls.count("qwen") >= 3
