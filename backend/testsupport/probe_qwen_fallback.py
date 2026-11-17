"""Local-only integration probe: simulated Groq 429, real Ollama, no browser actions."""

import asyncio
import json
import time
import httpx
from app.agent.contracts import Decision, Verification
from app.agent.model import ModelClient, warm_local_fallback
from app.config import settings


async def main():
    cfg = settings()
    assert cfg.ai_provider == "groq" and cfg.ai_fallback_provider == "local"
    assert cfg.ai_fallback_base_url.rstrip("/") == "http://127.0.0.1:11434/v1"
    assert cfg.ai_fallback_model == "qwen3:4b"
    original = httpx.AsyncClient
    calls = []

    async def handle(request):
        if request.url.host == "api.groq.com":
            calls.append("simulated-groq-429")
            return httpx.Response(429, headers={"retry-after": "60"})
        assert request.url.host == "127.0.0.1" and request.url.port == 11434
        calls.append("real-local-qwen")
        async with original(timeout=cfg.ai_fallback_timeout_seconds, trust_env=False) as local:
            return await local.send(request)

    httpx.AsyncClient = lambda **kw: original(transport=httpx.MockTransport(handle), **kw)
    started = time.monotonic()
    try:
        assert await warm_local_fallback() is True
        calls.clear()
        client = ModelClient()
        payload = {
            "objective": "Extract the release month from the provided page.",
            "success_criteria": ["Quote the visible release statement"],
            "current_page": {
                "url": "https://fixture.invalid/news",
                "text": "Orion AI will launch in November 2026.",
                "elements": [],
            },
            "session_memory": {"evidence": [], "recent_actions": []},
        }
        for _ in range(1):
            result = await client.request("decide", payload, Decision, lambda *args: (1, 1), timeout_cap_seconds=120)
            assert result.decision == "EXTRACT", result.decision
            assert result.text in payload["current_page"]["text"]
        unsupported = await client.request(
            "verify",
            {
                "objective": "Verify a 2030 launch claim",
                "success_criteria": ["Orion AI launches in 2030."],
                "claims": [{"text": "Orion AI launches in 2030.", "evidence_ids": ["evidence-9"]}],
                "evidence": [
                    {
                        "id": "evidence-9",
                        "url": "https://fixture.invalid/news",
                        "quote": "Orion AI will launch in November 2026.",
                    }
                ],
            },
            Verification,
            lambda *args: (1, 1),
            timeout_cap_seconds=120,
        )
        assert unsupported.complete is False and all(not check.met for check in unsupported.checks)
        assert calls == ["simulated-groq-429", "real-local-qwen", "real-local-qwen"]
        print(
            json.dumps(
                {
                    "valid_decisions": 1,
                    "unsupported_claim_rejected": True,
                    "calls": calls,
                    "seconds": round(time.monotonic() - started, 2),
                    "models_used": sorted(client.models_used),
                }
            )
        )
    finally:
        httpx.AsyncClient = original


if __name__ == "__main__":
    asyncio.run(main())
