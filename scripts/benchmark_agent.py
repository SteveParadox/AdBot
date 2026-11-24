"""Repeatable real-browser agent benchmark against local semantic model fixtures."""

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time


def main():
    with tempfile.TemporaryDirectory(prefix="adbot-planner-benchmark-") as directory:
        root = Path(directory)
        os.environ.update(
            ADBOT_DATABASE_URL="sqlite:///" + str(root / "test.db"),
            ADBOT_API_KEYS="benchmark-agent-key-000000000000000000",
            ADBOT_AI_PROVIDER="local",
            ADBOT_AI_PROVIDER_ORDER=" ",
            ADBOT_AI_API_KEY="benchmark-fixture-not-a-live-provider-key",
            ADBOT_AI_MODEL="semantic-fixture",
            ADBOT_AI_BASE_URL="http://127.0.0.1:8766/v1",
            ADBOT_AI_OLLAMA_NATIVE="false",
            ADBOT_AI_FALLBACK_PROVIDER="disabled",
            ADBOT_BROWSER_SESSION_PERSISTENCE="false",
            ADBOT_FIXTURE_MODE="true",
            ADBOT_REDIS_URL="",
            ADBOT_ARTIFACT_DIR=str(root / "artifacts"),
            ADBOT_AUTHORIZED_DOMAINS="",
        )
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
        import uvicorn
        from fastapi.testclient import TestClient
        from app.db import Base, engine, Session, AgentStep, AgentTask
        from app.main import app
        from app.jobs import claim
        from app.worker import execute
        from sqlalchemy import select

        servers = []
        threads = []
        try:
            for module, port in [
                ("app.fixture:app", 8765),
                ("testsupport.model_fixture:app", 8766),
            ]:
                server = uvicorn.Server(
                    uvicorn.Config(
                        module, host="127.0.0.1", port=port, log_level="error"
                    )
                )
                thread = threading.Thread(target=server.run, daemon=True)
                thread.start()
                servers.append(server)
                threads.append(thread)
                deadline = time.monotonic() + 15
                while not server.started:
                    if time.monotonic() > deadline:
                        raise RuntimeError("Fixture startup failed")
                    time.sleep(0.02)
            Base.metadata.create_all(engine)
            with TestClient(app) as client:
                client.headers.update(
                    {"Authorization": "Bearer benchmark-agent-key-000000000000000000"}
                )
                site = client.post(
                    "/api/websites",
                    json={
                        "name": "Benchmark",
                        "base_url": "http://127.0.0.1:8765/agent/news",
                        "allowed_domains": ["127.0.0.1"],
                        "authorized": True,
                        "configuration": {
                            "max_pages": 10,
                            "max_duration_seconds": 90,
                            "delay_seconds": 0.1,
                            "screenshots": True,
                        },
                    },
                )
                assert site.status_code == 201, site.text
                task = client.post(
                    "/api/agent/tasks",
                    json={
                        "website_id": site.json()["id"],
                        "objective": "Find the launch month for Orion AI and cite the source.",
                        "max_steps": 15,
                        "max_tokens": 100000,
                        "memory_enabled": False,
                    },
                )
                assert task.status_code == 201, task.text
                started = time.perf_counter()
                asyncio.run(execute(*claim()))
                elapsed = time.perf_counter() - started
                result = client.get("/api/agent/tasks/" + task.json()["id"]).json()
                with Session() as session:
                    state = session.get(AgentTask, task.json()["id"])
                    steps = session.scalars(
                        select(AgentStep)
                        .where(AgentStep.job_id == state.job_id)
                        .order_by(AgentStep.number)
                    ).all()
                    action_latencies = [
                        phase["duration_ms"]
                        for step in steps
                        for phase in step.outcome.get("trace", [])
                        if phase.get("phase") in {"action", "loading"}
                        and phase.get("status") == "completed"
                    ]
                    measured = {
                        "scenario": "Local Orion launch-month goal; Chromium; deterministic semantic fixture, not live LLM",
                        "status": result["status"],
                        "elapsed_seconds": elapsed,
                        "steps": len(steps),
                        "model_calls": state.model_calls,
                        "tokens": state.prompt_tokens + state.completion_tokens,
                        "failed_actions": sum(s.status == "failed" for s in steps),
                        "browser_action_count": len(action_latencies),
                        "mean_browser_operation_ms": sum(action_latencies)
                        / len(action_latencies)
                        if action_latencies
                        else None,
                        "verified": bool(
                            result.get("result", {})
                            .get("verification", {})
                            .get("complete")
                        ),
                        "planning_present": bool(state.memory.get("planning")),
                        "error": result.get("error_message"),
                    }
            print(json.dumps(measured, indent=2))
        finally:
            for server in servers:
                server.should_exit = True
            for thread in threads:
                thread.join(5)
            engine.dispose()
        if measured["status"] != "completed" or not measured["verified"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
