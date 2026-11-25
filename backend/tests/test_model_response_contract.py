"""Model response compatibility must preserve browser action and evidence checks."""
import json

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.agent.classification import AssessmentBatch
from app.agent.contracts import Decision
from app.agent.model import ModelClient, structured_response_format, validate_response
from app.agent.planning import TaskPlan
from app.config import settings
from test_browser import fixture_server  # noqa: F401


def decision(**values):
    return {"observation": "Visible reference link", "decision": "SCROLL", "reason": "Read more controls",
            "confidence": 0.9, "expected_result": "More visible content", **values}


def test_null_unused_claims_keeps_default_empty_collection():
    result = validate_response(json.dumps(decision(claims=None)), Decision)
    assert result.claims == []
    assert result.decision == "SCROLL"


@pytest.mark.parametrize("values", [
    {"decision": "COMPLETE", "claims": None},
    {"decision": "CLICK", "target": None, "claims": None},
    {"decision": "EXTRACT", "text": None, "claims": None},
    {"observation": None},
    {"confidence": None},
    {"claims": "not an array"},
    {"invented_parameter": "not permitted"},
])
def test_null_compatibility_does_not_relax_required_parameters(values):
    with pytest.raises(ValidationError):
        validate_response(json.dumps(decision(**values)), Decision)


def test_markdown_and_arbitrary_code_are_never_repaired_or_evaluated():
    for response in ["```json\n" + json.dumps(decision()) + "\n```", "__import__('os').getcwd()"]:
        with pytest.raises(ValueError):
            validate_response(response, Decision)


def test_nested_plan_wire_schema_has_closed_required_object_shapes():
    source = TaskPlan.model_json_schema()
    wire = structured_response_format(TaskPlan)["json_schema"]
    assert wire["strict"] is True
    intent = wire["schema"]["$defs"]["Intent"]
    assert "constraints" in intent["required"]
    assert intent["additionalProperties"] is False
    assert "constraints" not in source["$defs"]["Intent"].get("required", [])


@pytest.mark.parametrize("provider,model", [
    ("groq", "openai/gpt-oss-120b"),
    ("openrouter", "openai/gpt-oss-120b"),
    ("nvidia", "nvidia/nemotron-3.5-lightning-30b-a3b"),
])
async def test_configured_cloud_models_use_schema_and_reserved_output_limit(monkeypatch, provider, model):
    cfg = settings()
    for name, value in {"ai_provider": provider, "ai_provider_order": provider, "ai_model": model,
                        "ai_max_output_tokens": 2048, "ai_provider_rpm": 0, "ai_provider_tpm": 0,
                        "nvidia_thinking_enabled": False}.items():
        monkeypatch.setattr(cfg, name, value)
    original, charged = httpx.AsyncClient, []

    async def respond(request):
        body = json.loads(request.content)
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["strict"] is True
        assert body["max_tokens"] == 2048
        if provider == "nvidia":
            assert body["chat_template_kwargs"] == {"enable_thinking": False}
        if provider == "openrouter":
            assert body["provider"]["require_parameters"] is True
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(decision(claims=None))}}]})

    def account(prompt, completion, latency, reserve, receipt=None):
        if reserve:
            charged.append(completion)
            return (prompt, completion)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    assert (await ModelClient().request("decide", {}, Decision, account)).claims == []
    assert charged == [2048]


async def test_diagnostic_reports_schema_path_without_raw_response_or_secret(monkeypatch):
    from app.agent.model import ModelProvidersUnavailable
    cfg = settings()
    for name, value in {"ai_provider": "groq", "ai_provider_order": "groq", "ai_model": "fixture",
                        "groq_base_url": "https://groq.test/v1", "groq_api_key": SecretStr("secret-fixture-key")}.items():
        monkeypatch.setattr(cfg, name, value)
    original, events = httpx.AsyncClient, []
    content = decision(confidence="private-invalid-value")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})), **kw))
    client = ModelClient()
    client.on_provider_event = events.append
    with pytest.raises(ModelProvidersUnavailable):
        await client.request("decide", {}, Decision, lambda *args: (1, 1))
    assert events[0]["validation_errors"] == [{"field": "confidence", "type": "float_parsing"}]
    assert events[0]["purpose"] == "decide"
    assert "confidence" in events[0]["reason"]
    assert "private-invalid-value" not in json.dumps(events)
    assert "secret-fixture-key" not in json.dumps(events)


async def test_classification_response_fails_over_after_invalid_schema(monkeypatch):
    cfg = settings()
    for name, value in {"ai_provider": "groq", "ai_provider_order": "groq,openrouter",
                        "groq_base_url": "https://primary.test/v1", "openrouter_base_url": "https://secondary.test/v1",
                        "ai_provider_rpm": 0, "ai_provider_tpm": 0}.items():
        monkeypatch.setattr(cfg, name, value)
    original = httpx.AsyncClient
    providers = []
    answer = {"records": [{"id": "one", "classification": "match", "quote": "Answers questions in a conversation."}]}

    def respond(request):
        host = request.url.host
        providers.append(host)
        body = json.loads(request.content)
        assert json.loads(body["messages"][-1]["content"])["purpose"] == "classify"
        assert body["response_format"]["json_schema"]["name"] == "AssessmentBatch"
        value = {"records": [{"id": "one", "classification": "invalid"}]} if host == "primary.test" else answer
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    result = await ModelClient().request("classify", {"records": []}, AssessmentBatch, lambda *args: (1, 1))
    assert result.model_dump() == answer
    assert providers == ["primary.test", "secondary.test"]


@pytest.mark.browser
async def test_browser_task_accepts_unused_null_claims_and_still_verifies_completion(client, target, fixture_server, monkeypatch):  # noqa: F811
    from app.jobs import claim
    from app.worker import execute
    from testsupport.model_fixture import app as fixture_model

    cfg = settings()
    for name, value in {"ai_provider": "groq", "ai_provider_order": "groq", "ai_model": "openai/gpt-oss-120b",
                        "groq_base_url": "https://groq.test/v1", "groq_api_key": SecretStr("fixture-key"),
                        "ai_fallback_provider": "disabled", "ai_max_output_tokens": 2048}.items():
        monkeypatch.setattr(cfg, name, value)
    original, null_responses = httpx.AsyncClient, []
    fixture_transport = httpx.ASGITransport(app=fixture_model)

    async def respond(request):
        if request.url.host != "groq.test":
            async with original(trust_env=False) as local:
                return await local.send(request)
        assert json.loads(request.content)["response_format"]["type"] == "json_schema"
        response = await fixture_transport.handle_async_request(request)
        await response.aread()
        body = response.json()
        value = json.loads(body["choices"][0]["message"]["content"])
        if value.get("decision") and value["decision"] != "COMPLETE":
            value["claims"] = None
            null_responses.append(value["decision"])
            body["choices"][0]["message"]["content"] = json.dumps(value)
        return httpx.Response(200, json=body)

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
    assert task["status"] == "completed", {key: task.get(key) for key in ("status", "error_message", "model_calls", "result")}
    assert task["result"]["verification"]["complete"] is True
    assert task["result"]["evidence"]
    assert null_responses
    assert task["memory"]["failures"] == []


def test_extraction_dictionary_keeps_dynamic_keys_and_local_validation():
    from app.extraction.service import AIRecord
    assert structured_response_format(AIRecord) == {"type": "json_object"}
    result = validate_response(json.dumps({"values": {"launch_month": {
        "value": "May", "quote": "Orion launches in May.",
    }}}), AIRecord)
    assert result.values["launch_month"].value == "May"
    with pytest.raises(ValidationError):
        validate_response('{"values":{"launch_month":{"unknown":"unsupported"}}}', AIRecord)
