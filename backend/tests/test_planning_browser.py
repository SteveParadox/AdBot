import pytest

from app.agent.model import ModelClient
from app.db import ExtractedRecord, transaction
from app.jobs import claim
from app.worker import execute
from conftest import OTHER_AUTH
from test_agent import agent_config, agent_servers, new_task, set_url  # noqa: F401
from test_extraction import setup_dataset

pytestmark = pytest.mark.browser


@pytest.mark.usefixtures("agent_config", "agent_servers")
async def test_general_discovery_rejects_premature_terminal_failure(client, target, monkeypatch):
    from testsupport.model_fixture import decide

    homepage_evidence = []

    async def responses(self, kind, payload, schema, account, image_path=None, timeout_cap_seconds=None):
        if kind == "route":
            return schema(informational=False, subject="")
        if kind == "decide" and payload["current_page"]["url"].endswith("/agent/news"):
            homepage_evidence.extend(payload["session_memory"]["evidence"])
            assert payload["task_plan"]["active_subtask"] == "research"
            return schema(decision="FAIL", observation="News homepage", reason="The homepage lacks the weather outlook.",
                          confidence=0.99, expected_result="Stop", text="Unrelated homepage copy")
        if kind == "decide" and not payload["session_memory"]["evidence"]:
            return schema(decision="EXTRACT", observation="Weather article", reason="Capture the observed forecast.",
                          confidence=1, expected_result="Forecast evidence", text="Clear skies are expected on Sunday.")
        return schema.model_validate(decide({"purpose": kind, **payload}))

    monkeypatch.setattr(ModelClient, "request", responses)
    set_url(client, target, "/agent/news")
    task = new_task(client, target, objective="Sunday weather outlook", mode="autonomous", allow_search_input=False)
    await execute(*claim())
    result = client.get("/api/agent/tasks/" + task["id"]).json()
    assert result["planning"]["route"] == "general"
    assert not homepage_evidence
    assert result["planning"]["replans"]
    assert result["status"] == "completed", result.get("error_message")
    assert any(url.endswith("/agent/article/weather") for url in result["memory"]["visited_urls"])


@pytest.mark.usefixtures("agent_config", "agent_servers")
async def test_terminal_failure_is_reassessed_and_reports_the_blocker(client, target, monkeypatch):
    decisions = []

    async def responses(self, kind, payload, schema, account, image_path=None, timeout_cap_seconds=None):
        if kind == "route":
            return schema(informational=False, subject="")
        assert kind == "decide"
        decisions.append(payload["current_page"]["url"])
        return schema(decision="FAIL", observation="Weather article", reason="The authorized page has no tide forecast.",
                      confidence=1, expected_result="Stop", text="Clear skies are expected on Sunday.")

    monkeypatch.setattr(ModelClient, "request", responses)
    set_url(client, target, "/agent/article/weather")
    task = new_task(client, target, objective="tide forecast", allow_search_input=False)
    await execute(*claim())
    result = client.get("/api/agent/tasks/" + task["id"]).json()
    assert result["status"] == "failed"
    assert len(decisions) == 2
    assert "The authorized page has no tide forecast." in result["error_message"]
    assert "Clear skies" not in result["error_message"]


@pytest.mark.parametrize("opener", ["link", "dialog"])
@pytest.mark.usefixtures("agent_config", "agent_servers")
async def test_title_lookup_opens_search_and_verifies_source(client, target, monkeypatch, opener):
    from fastapi.responses import HTMLResponse
    from app.fixture import app as fixture
    from testsupport.model_fixture import decide

    objective = "Google Sheets Data Cleaning and Formulas"
    title = "Google Sheets Data Cleaning Checklist and Formulas"
    search_form = """<form method="get" action="/agent/title-search" role="search">
        <label>Search documentation<input type="search" name="q"></label><button>Search</button></form>"""
    queries = []

    def home():
        control = '<a href="/agent/title-search">Search ⌘K</a>' if opener == "link" else (
            '<button onclick="document.querySelector(\'dialog\').showModal()">Open search</button>'
            f'<dialog aria-label="Search documentation">{search_form}</dialog>'
        )
        return f"<title>Documentation</title><main><h1>Documentation</h1>{control}</main>"

    def search(q: str = ""):
        queries.append(q)
        result = f'<a href="/agent/title-source">{title}</a>' if q == "Google Sheets Data Cleaning" else ""
        return f"<title>Search</title><main><h1>Search</h1>{search_form}{result}</main>"

    def source():
        return (f"<title>{title}</title><main><article><h1>{title}</h1>"
                "<p>In Google Sheets, preserve the original data and validate row counts after cleaning with formulas.</p>"
                "</article></main>")

    monkeypatch.setattr(fixture.router, "routes", list(fixture.router.routes))
    for path, handler in (("home", home), ("search", search), ("source", source)):
        fixture.get(f"/agent/title-{path}", response_class=HTMLResponse)(handler)

    async def responses(self, kind, payload, schema, account, image_path=None, timeout_cap_seconds=None):
        if kind == "synthesize":
            assert all(row["url"].endswith("/agent/title-source") for row in payload["evidence"])
            return schema(claims=[{"text": row["quote"], "evidence_ids": [row["id"]]} for row in payload["evidence"]])
        return schema.model_validate(decide({"purpose": kind, **payload}))

    monkeypatch.setattr(ModelClient, "request", responses)
    set_url(client, target, "/agent/title-home")
    task = new_task(client, target, objective=objective, mode="autonomous", allow_search_input=True, allow_form_input=False)
    await execute(*claim())
    result = client.get("/api/agent/tasks/" + task["id"]).json()
    assert result["status"] == "completed", result.get("error_message")
    assert result["planning"]["route"] == "informational"
    assert result["result"]["verification"]["complete"]
    assert [query for query in queries if query] == [objective, "Google Sheets Data Cleaning"]


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
