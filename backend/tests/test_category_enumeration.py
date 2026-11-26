import time

import pytest
from fastapi.responses import HTMLResponse

from app import fixture
from app.agent.classification import AssessmentBatch
from app.agent.contracts import Decision, Verification
from app.agent.model import ModelClient
from app.agent.planning import execution_intent
from app.agent.routing import select_route
from app.agent.runner import AgentRunner
from app.agent.structure import RecordCapture, map_group
from app.config import settings
from app.jobs import claim
from app.security import Policy
from app.worker import execute
from test_browser import fixture_server  # noqa: F401


@pytest.mark.parametrize("objective,route,intent", [
    ("List invoice calculation and comparison appliances", "enumeration", "structured_extraction"),
    ("Could you list workflow templates", "enumeration", "structured_extraction"),
    ("Give me a list of kayak rental guides", "enumeration", "structured_extraction"),
    ("Comparison utilities for marine suppliers", "general", "general"),
    ("Compare Cedar and Juniper on availability", "comparison", "comparison"),
    ("Rank options by total cost", "research", "research"),
    ("Recommend an option for a small team", "research", "research"),
    ("Research the origin of this instrument", "research", "research"),
])
def test_operation_is_separate_from_subject(objective, route, intent):
    assert select_route(objective, {}).name == route
    assert execution_intent(objective)["category"] == intent


def test_non_exhaustive_mapping_keeps_independently_valid_rows():
    group = {"records": [
        {"truncated": True, "segments": [{"label": "Record", "value": "Harbor"},
                                         {"label": "", "value": "Clipped ancillary content", "truncated": True},
                                         {"label": "", "value": "Compares supplier license terms."}]},
        {"truncated": True, "segments": [{"label": "Record", "value": "Incomplete", "truncated": True}]},
    ]}
    capture = RecordCapture(group=1, identity=1, fields=[{"name": "Label", "position": 1}])
    assert map_group(group, capture, preserve_context=True) == {
        "Harbor": ({"Label": "Harbor"}, ["Harbor", "Compares supplier license terms."]),
    }
    with pytest.raises(ValueError, match="Required fields"):
        map_group(group, capture)


def test_direct_relevance_prefers_an_observed_utility_to_an_editorial_link():
    runner = AgentRunner.__new__(AgentRunner)
    runner.objective = "List buying and comparison suppliers"
    runner.policy = Policy(["example.test"])
    runner.memory = {"visited_urls": ["https://example.test/"]}
    decision = runner.enumeration_decision({"elements": [
        {"name": "Rankings of comparison suppliers", "href": "https://example.test/reviews", "actionable": True},
        {"name": "Compare suppliers", "href": "https://example.test/options", "actionable": True},
        {"name": "Compare suppliers", "href": "https://outside.test/options", "actionable": True},
    ]})
    assert decision.url == "https://example.test/options"


@fixture.app.get("/category-probe/{source}", response_class=HTMLResponse)
def category_source(source: str):
    if source.startswith("related"):
        target = "catalog-single" if source == "related-single" else "catalog"
        return ('<main><h1>Publishing comparisons</h1><p>Shop software and compare the best tools.</p>'
                '<div><article><h2>SideNote</h2><p>Build comparison pages and publish product reviews.</p></article>'
                '<article><h2>PrintKit</h2><p>Generate layouts for editorial comparison articles.</p></article></div>'
                f'<a href="/category-probe/{target}">Buyer utilities catalog</a></main>')
    if source == "catalog-single":
        return "<main><h1>CompareCart</h1><p>Helps buyers compare software prices and purchase supplier licenses.</p></main>"
    return ('<main><h1>Buyer utilities catalog</h1><div>'
            '<article><h2>CompareCart</h2><p>Helps buyers compare software prices and purchase supplier licenses.</p></article>'
            '<article><h2>PhotoBox</h2><p>Organizes photographs and edits images for publication.</p></article></div></main>')


@pytest.mark.browser
@pytest.mark.parametrize("singleton", [False, True])
async def test_listing_rejects_a_misleading_source_and_publishes_qualified_records(client, target, fixture_server, monkeypatch, singleton):  # noqa: F811
    monkeypatch.setattr(settings(), "ai_provider", "local")
    registration = {key: target[key] for key in ("name", "allowed_domains", "configuration")}
    suffix = "-single" if singleton else ""
    registration.update(base_url=f"http://127.0.0.1:8765/category-probe/related{suffix}", authorized=True)
    registration["configuration"].update(screenshots=False, max_duration_seconds=120)
    assert client.patch(f"/api/websites/{target['id']}", json=registration).status_code == 200
    objective = "List software shopping and comparison utilities"
    task = client.post("/api/agent/tasks", json={"website_id": target["id"], "objective": objective, "max_steps": 10}).json()["id"]

    async def respond(self, kind, payload, schema, *_args, **_kwargs):
        if kind == "classify":
            records = []
            for row in payload["records"]:
                excerpts = row["excerpts"]
                if "SideNote" in excerpts:
                    # A valid response index pointing to just a name is inadequate.
                    classification, evidence = "match", excerpts.index("SideNote") + 1
                else:
                    classification = "match" if any("purchase supplier" in excerpt for excerpt in excerpts) else "excluded"
                    evidence = 1
                records.append({"id": row["id"], "classification": classification, "evidence": evidence})
            return AssessmentBatch(records=records)
        if kind == "verify":
            records = payload["captured_records"]["records"]
            assert list(records) == ["CompareCart"]
            assert "purchase supplier" in records["CompareCart"]["classification_evidence"]
            return Verification(complete=True, explanation="The listed tool serves buyers", checks=[
                {"criterion": criterion, "met": True, "evidence_ids": [payload["evidence"][0]["id"]]}
                for criterion in payload["success_criteria"]
            ])
        assert kind == "decide"
        current = client.get(f"/api/agent/tasks/{task}").json()
        assert current["planning"]["plan"]["subtasks"][0]["status"] != "completed"
        page = payload["current_page"]
        defaults = {"observation": "Observed candidate group", "reason": "Inspect the record descriptions",
                    "confidence": 1, "expected_result": "Sources for category qualification"}
        if payload["rejected_collection_sources"] and page["url"].endswith("/related" + suffix):
            return Decision(decision="NAVIGATE", url=next(e["href"] for e in page["elements"]
                            if (e.get("href") or "").endswith("/catalog" + suffix)), **defaults)
        group = next(group for group in page["record_groups"]
                     if group["examples"][0][0]["value"] in {"SideNote", "CompareCart"})
        return Decision(decision="CAPTURE_RECORDS", capture={"group": group["id"], "identity": 1, "exhaustive": True,
                        "fields": [{"name": "Name", "position": 1}]}, **defaults)

    monkeypatch.setattr(ModelClient, "request", respond)
    started = time.monotonic()
    await execute(*claim())
    result = client.get(f"/api/agent/tasks/{task}").json()
    assert result["status"] == "completed", result.get("error_message")
    assert result["planning"]["specification"]["execution_intent"]["category"] == "structured_extraction"
    assert result["result"]["verification"]["complete"]
    records = result["result"]["structured_records"]
    assert [row["fields"]["Name"] for row in records] == ["CompareCart"]
    assert records[0]["source_url"].endswith("/catalog" + suffix)
    print(f"category fixture singleton={singleton} elapsed={time.monotonic() - started:.2f}s")


@pytest.mark.browser
@pytest.mark.parametrize("objective,expected", [
    ("Rank CompareCart and PhotoBox by fit for supplier licenses", "CompareCart ranks ahead for supplier licenses."),
    ("Recommend a utility that can purchase supplier licenses", "CompareCart serves software buyers."),
    ("Research which tool edits images for publication", "PhotoBox edits images for publication."),
])
async def test_other_read_side_tasks_retain_evidence_verification(client, target, fixture_server, monkeypatch, objective, expected):  # noqa: F811
    monkeypatch.setattr(settings(), "ai_provider", "local")
    registration = {key: target[key] for key in ("name", "allowed_domains", "configuration")}
    registration.update(base_url="http://127.0.0.1:8765/category-probe/catalog", authorized=True)
    registration["configuration"].update(screenshots=False, max_duration_seconds=120)
    assert client.patch(f"/api/websites/{target['id']}", json=registration).status_code == 200
    task = client.post("/api/agent/tasks", json={"website_id": target["id"], "objective": objective, "max_steps": 5}).json()["id"]

    async def respond(self, kind, payload, schema, *_args, **_kwargs):
        if kind == "plan":
            return schema.model_validate(payload["seed_plan"])
        if kind == "verify":
            assert expected == payload["claims"][0]["text"]
            return Verification(complete=True, explanation="Observed source evidence supports the result", checks=[
                {"criterion": criterion, "met": True, "evidence_ids": payload["claims"][0]["evidence_ids"]}
                for criterion in payload["success_criteria"]
            ])
        assert kind == "decide"
        evidence = payload["session_memory"]["evidence"]
        assert evidence and all(item["id"].startswith("dom-") for item in evidence)
        return Decision(decision="COMPLETE", observation="Observed product purposes", reason="Relevant evidence found",
                        confidence=1, expected_result="Verified answer",
                        claims=[{"text": expected, "evidence_ids": [item["id"] for item in evidence]}])

    monkeypatch.setattr(ModelClient, "request", respond)
    await execute(*claim())
    result = client.get(f"/api/agent/tasks/{task}").json()
    assert result["status"] == "completed", result.get("error_message")
    assert result["result"]["claims"][0]["text"] == expected
