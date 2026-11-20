import pytest

from app.agent.model import ModelClient
from app.db import ExtractedRecord, transaction
from app.jobs import claim
from app.worker import execute
from conftest import OTHER_AUTH
from test_agent import agent_config, agent_servers, new_task, set_url  # noqa: F401
from test_extraction import setup_dataset

pytestmark = pytest.mark.browser


@pytest.mark.parametrize("engine", ["firefox", "webkit"])
async def test_agent_through_policy_proxy_on_other_engines(client, target, agent_config, agent_servers, engine):  # noqa: F811
    set_url(client, target, "/agent/news")
    body = client.get("/api/websites/" + target["id"]).json()
    patch = {key: body[key] for key in ("name", "base_url", "allowed_domains", "configuration")}
    patch["authorized"] = True
    patch["configuration"].update(browser=engine, max_duration_seconds=120)
    assert client.patch("/api/websites/" + target["id"], json=patch).status_code == 200
    task = new_task(client, target, memory_enabled=False)
    await execute(*claim())
    result = client.get("/api/agent/tasks/" + task["id"]).json()
    assert result["status"] == "completed", result.get("error_message")
    assert result["result"]["verification"]["complete"]


async def test_complex_plan_real_export_and_owned_download(client, target, agent_config, agent_servers, monkeypatch):  # noqa: F811
    from sqlalchemy import update

    original_request = ModelClient.request

    async def concurrent_read(self, *args, **kwargs):
        if args[0] == "verify":
            assert args[1]["artifact"]["rows"] == 1
            assert "November 2026" in str(args[1]["artifact"]["records"])
        result = await original_request(self, *args, **kwargs)
        if getattr(result, "decision", None) == "EXPORT_DATASET":
            # Another run reobserving unchanged content may replace last_job_id.
            # It must neither remove this task's records nor add unrelated rows.
            with transaction() as session:
                session.execute(update(ExtractedRecord).values(last_job_id=None))
        return result

    monkeypatch.setattr(ModelClient, "request", concurrent_read)
    set_url(client, target, "/agent/news")
    schema = {
        "name": "Release notes",
        "record_selector": "article",
        "identity_fields": ["url"],
        "fields": {
            "title": {"type": "string", "method": "css", "selector": "h1", "required": True},
            "quote": {"type": "string", "method": "css", "selector": "p", "required": True},
            "url": {"type": "url", "method": "source_url", "required": True},
        },
    }
    _, dataset = setup_dataset(client, target, definition_value=schema)
    # An unrelated preexisting record must never enter this task's artifact.
    with transaction() as session:
        session.add(
            ExtractedRecord(
                dataset_id=dataset["id"],
                identity="old",
                content_hash="old",
                data={"title": "Unrelated old record"},
                original={},
                provenance={},
                validation_status="valid",
            )
        )
    task = new_task(
        client,
        target,
        objective="Find the launch month for Orion AI then export JSON with the source.",
        dataset_id=dataset["id"],
        output_format="json",
        memory_enabled=False,
    )
    await execute(*claim())
    result = client.get("/api/agent/tasks/" + task["id"]).json()
    assert result["status"] == "completed", {
        "error": result.get("error_message"),
        "failures": result.get("memory", {}).get("failures"),
        "replans": result.get("planning", {}).get("replans"),
    }
    plan = result["planning"]
    assert all(node["status"] == "completed" for node in plan["plan"]["subtasks"])
    assert plan["initialized"] and result["model_calls"] >= 5
    assert "agent_record_scope" not in result["execution_state"]
    url = result["result"]["artifact"]["download_url"]
    artifact = client.get(url)
    assert artifact.status_code == 200, artifact.text
    assert len(artifact.json()["records"]) == 1
    assert "November 2026" in artifact.text and "Unrelated old record" not in artifact.text
    assert client.get(url, headers=OTHER_AUTH).status_code == 404


async def test_ambiguous_dispatched_write_never_replayed(client, target, agent_config, agent_servers, monkeypatch):  # noqa: F811
    from testsupport.model_fixture import decide

    dispatched = 0

    async def responses(self, kind, payload, schema, account, image_path=None, timeout_cap_seconds=None):
        nonlocal dispatched
        result = decide({"purpose": kind, **payload})
        if kind == "decide" and result.get("decision") == "CLICK":
            dispatched += 1
            result["expected_text"] = "A confirmation that never exists"
        return schema.model_validate(result)

    monkeypatch.setattr(ModelClient, "request", responses)
    set_url(client, target, "/agent/form")
    task = new_task(
        client,
        target,
        objective="Complete the demo registration for Ada and verify confirmation.",
        allow_form_input=True,
    )
    await execute(*claim())
    result = client.get("/api/agent/tasks/" + task["id"]).json()
    assert result["status"] == "failed"
    assert "may have modified external state" in result["error_message"]
    assert dispatched == 1
    assert not result["result"].get("verification")
