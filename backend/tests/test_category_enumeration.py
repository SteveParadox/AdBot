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
    assert map_group({"records": group["records"][:1]}, capture) == {"Harbor": {"Label": "Harbor"}}
    with pytest.raises(ValueError, match="selected field was clipped"):
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


def test_relevant_detail_is_captured_with_its_description_before_navigation():
    runner = AgentRunner.__new__(AgentRunner)
    runner.objective = "List comparison tools"
    runner.memory = {}
    decision = runner.enumeration_decision({
        "url": "https://example.test/record",
        "record_groups": [{"id": 1, "kind": "detail", "label": "Compare tools side by side"}],
    })
    assert decision.decision == "CAPTURE_RECORDS"
    assert [field.position for field in decision.capture.fields] == [1, 2]


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
                    evidence = next((i for i, excerpt in enumerate(excerpts, 1)
                                     if "purchase supplier" in excerpt), 1)
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
        if (payload["rejected_collection_sources"] or payload.get("rejected_collection_scopes")) and page["url"].endswith("/related" + suffix):
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



def test_progressive_scroll_not_blocked_by_unchanged_record_groups():
    from app.agent.structure import scroll_blocked
    from app.agent.memory import semantic_action_key

    page = {"url": "https://example.test/catalog", "scroll": {"y": 486, "height": 8336, "at_end": False}}
    prior = {"action": "SCROLL", "outcome": {"after_url": page["url"], "scroll_direction": "down",
             "scroll_before": {"y": 0, "height": 8336}, "scroll_after": {"y": 486, "height": 8336},
             "record_groups_changed": False}}
    assert not scroll_blocked("SCROLL", "down", page, [prior])
    action = {"decision": "SCROLL", "direction": "down"}
    key = semantic_action_key(action, page)
    page["scroll"]["y"] = 972
    assert semantic_action_key(action, page) != key
    page["scroll"]["at_end"] = True
    assert scroll_blocked("SCROLL", "down", page, [prior])


def test_incomplete_enumeration_releases_scope_and_keeps_verified_records():
    runner = AgentRunner.__new__(AgentRunner)
    url = "https://example.test/catalog"
    verified = {"identity": "Atlas", "source_url": url, "classification": "match", "step_id": 1}
    collection = {"source_url": url, "scope": ["https", "example.test", "Intro", ["Name"]], "records": {}}
    runner.memory = {"structured_capture": collection, "enumeration_verified_capture": "capture-2",
                     "evidence": [{"id": "capture-1"}, {"id": "capture-2"}],
                     "research_partial": {"structured_records": [verified], "evidence": [{"id": "capture-1"}]}}
    runner.reject_enumeration_source(collection, reject_url=False)
    assert "structured_capture" not in runner.memory
    assert "enumeration_verified_capture" not in runner.memory
    assert runner.memory["evidence"] == [{"id": "capture-1"}]
    assert runner.memory["rejected_collection_scopes"] == [[url, "Intro"]]
    assert url not in runner.memory.get("rejected_collection_sources", [])
    other = {"identity": "Beacon", "source_url": url, "classification": "match", "step_id": 3}
    assert set(runner.enumeration_records({"records": {"Beacon": other}})) == {"Atlas", "Beacon"}


def test_listing_prefers_record_groups_to_generic_detail_heading():
    runner = AgentRunner.__new__(AgentRunner)
    runner.objective = "List comparison tools"
    runner.memory = {}
    result = runner.enumeration_decision({"url": "https://example.test/", "elements": [],
        "record_groups": [{"id": 1, "kind": "detail", "label": "Compare tools side by side"},
                          {"id": 2, "kind": "repeated", "label": "Tools", "observed_count": 4}]})
    assert result is None



def test_rejected_group_identity_does_not_hide_other_groups_with_same_heading():
    from app.agent.structure import group_signature, rejected_group

    url = "https://example.test/catalog"
    first = {"kind": "repeated", "label": "Tools", "examples": [[{"label": "Name", "value": "Atlas"}]]}
    second = {"kind": "repeated", "label": "Tools", "examples": [[{"label": "Name", "value": "Beacon"}]]}
    scopes = [[url, "Tools", group_signature(first)]]
    assert rejected_group(url, first, scopes)
    assert not rejected_group(url, second, scopes)


@fixture.app.get("/extraction-first-fixture", response_class=HTMLResponse)
def extraction_first_fixture():
    return ("<main><h1>Buyer tools catalog</h1><div>"
            "<article><h2>Atlas</h2><p>Compare software licensing costs before buying supplier products.</p></article>"
            "<article><h2>Beacon</h2><p>Compare software purchase options and vendor contracts before buying.</p></article>"
            "</div></main>")


@pytest.mark.browser
async def test_extraction_first_listing_uses_capture_and_verification_without_navigation_model(client, target, fixture_server, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings(), "ai_provider", "local")
    registration = {key: target[key] for key in ("name", "allowed_domains", "configuration")}
    registration.update(base_url="http://127.0.0.1:8765/extraction-first-fixture", authorized=True)
    registration["configuration"].update(screenshots=False, max_duration_seconds=120)
    assert client.patch("/api/websites/" + target["id"], json=registration).status_code == 200
    job = client.post("/api/agent/tasks", json={"website_id": target["id"],
                      "objective": "List software buying and comparison tools", "max_steps": 5}).json()["id"]
    purposes = []

    async def respond(self, kind, payload, schema, *_args, **_kwargs):
        purposes.append(kind)
        if kind == "classify":
            return AssessmentBatch(records=[
                {"id": row["id"], "classification": "match",
                 "evidence": next(i for i, quote in enumerate(row["excerpts"], 1)
                                  if "before buying" in quote)}
                for row in payload["records"]
            ])
        assert kind == "verify"
        assert set(payload["captured_records"]["records"]) == {"Atlas", "Beacon"}
        cited = [row["id"] for row in payload["evidence"] if row["id"].startswith("capture-")]
        return Verification(complete=True, explanation="Both records support software purchasing decisions",
                            checks=[{"criterion": criterion, "met": True, "evidence_ids": cited}
                                    for criterion in payload["success_criteria"]])

    monkeypatch.setattr(ModelClient, "request", respond)
    await execute(*claim())
    result = client.get("/api/agent/tasks/" + job).json()
    assert result["status"] == "completed", result.get("error_message")
    assert {row["fields"]["Name"] for row in result["result"]["structured_records"]} == {"Atlas", "Beacon"}
    assert "decide" not in purposes
    assert purposes.count("verify") == 1


@fixture.app.get("/autonomous-search-fixture", response_class=HTMLResponse)
def autonomous_search_fixture():
    return ('<main><h1>Software discovery</h1><form role="search" method="get" action="/autonomous-search-results">'
            '<label for="lookup">Search software</label><input id="lookup" type="search" name="q" required>'
            '<button type="submit">Search</button></form></main>')


@fixture.app.get("/autonomous-search-results", response_class=HTMLResponse)
def autonomous_search_results(q: str = ""):
    if q.casefold() != "software buying and comparison tools":
        return "<main><h1>No results</h1></main>"
    return extraction_first_fixture()


@pytest.mark.browser
async def test_autonomous_native_search_then_capture_without_general_form_permission(client, target, fixture_server, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings(), "ai_provider", "local")
    registration = {key: target[key] for key in ("name", "allowed_domains", "configuration")}
    registration.update(base_url="http://127.0.0.1:8765/autonomous-search-fixture", authorized=True)
    registration["configuration"].update(screenshots=False, max_duration_seconds=120)
    assert client.patch("/api/websites/" + target["id"], json=registration).status_code == 200
    job = client.post("/api/agent/tasks", json={
        "website_id": target["id"], "objective": "List software buying and comparison tools",
        "mode": "autonomous", "allow_form_input": False, "max_steps": 8,
    }).json()["id"]
    purposes = []

    async def respond(self, kind, payload, schema, *_args, **_kwargs):
        purposes.append(kind)
        if kind == "classify":
            return AssessmentBatch(records=[
                {"id": row["id"], "classification": "match",
                 "evidence": next(i for i, quote in enumerate(row["excerpts"], 1) if "before buying" in quote)}
                for row in payload["records"]
            ])
        assert kind == "verify"
        assert set(payload["captured_records"]["records"]) == {"Atlas", "Beacon"}
        cited = [row["id"] for row in payload["evidence"] if row["id"].startswith("capture-")]
        return Verification(complete=True, explanation="Both products meet the purchasing objective",
                            checks=[{"criterion": criterion, "met": True, "evidence_ids": cited}
                                    for criterion in payload["success_criteria"]])

    monkeypatch.setattr(ModelClient, "request", respond)
    await execute(*claim())
    result = client.get("/api/agent/tasks/" + job).json()
    assert result["status"] == "completed", result.get("error_message")
    assert result["planning"]["specification"]["permissions"]["read_search"] is True
    assert result["planning"]["specification"]["permissions"]["form_input"] is False
    records = result["result"]["structured_records"]
    assert {row["fields"]["Name"] for row in records} == {"Atlas", "Beacon"}
    assert all("/autonomous-search-results?" in row["source_url"] for row in records)
    assert "decide" not in purposes


@fixture.app.get("/dynamic-search-fixture/{mode}", response_class=HTMLResponse)
def dynamic_search_fixture(mode: str):
    # No native form: actual browser input events drive delayed suggestions,
    # AJAX results or an explicitly attested POST query.
    if mode == "suggestion":
        return """<main><h1>Find software</h1><section role="search">
        <div contenteditable="true" role="searchbox" aria-label="Search software" aria-controls="suggestions" style="min-height:24px;width:300px"></div>
        <div id="suggestions" role="listbox"></div></section><div id="results"></div>
        <script>
        const input=document.querySelector('[role=searchbox]');
        input.addEventListener('input',()=>setTimeout(()=>{
          const option=document.createElement('div'); option.setAttribute('role','option');
          option.tabIndex=0; option.textContent=input.textContent;
          option.onclick=()=>{document.getElementById('suggestions').replaceChildren(); load(input.textContent)};
          document.getElementById('suggestions').replaceChildren(option);
        },250));
        async function load(q){const r=await fetch('/dynamic-search-data?q='+encodeURIComponent(q));document.getElementById('results').innerHTML=await r.text()}
        </script></main>"""
    method = "POST" if mode == "post" else "GET"
    if mode == "live_nested":
        return """<main><h1>Find software</h1><section role="search">
        <input type="search" aria-label="Search software"><div id="results" aria-busy="false"></div>
        <script>
        const input=document.querySelector('input'),results=document.getElementById('results');
        let timer;
        input.addEventListener('input',()=>{
          clearTimeout(timer);results.setAttribute('aria-busy','true');
          timer=setTimeout(async()=>{
            const r=await fetch('/dynamic-search-data?q='+encodeURIComponent(input.value));
            results.innerHTML=await r.text();results.setAttribute('aria-busy','false');
          },2100);
        });
        input.addEventListener('keydown',e=>{if(e.key==='Enter') results.innerHTML='<p>Unexpected duplicate submission</p>'});
        </script></section></main>"""
    return """<main><h1>Find software</h1><section role="search">
    <input type="text" aria-label="Search software"><button type="button">Search</button></section>
    <div id="results" aria-busy="false"></div>
    <script>
    const input=document.querySelector('input');const results=document.getElementById('results');
    async function load(){
      results.setAttribute('aria-busy','true');
      await new Promise(r=>setTimeout(r,350));
      const method=METHOD;
      const response=await fetch('/dynamic-search-data'+(method==='GET'?'?q='+encodeURIComponent(input.value):''),
        method==='POST'?{method,headers:{'Content-Type':'application/json'},body:JSON.stringify({q:input.value})}:{});
      results.innerHTML=await response.text();results.setAttribute('aria-busy','false');
    }
    document.querySelector('button').onclick=load;
    </script></main>""".replace("METHOD", repr(method))


@fixture.app.get("/dynamic-search-data", response_class=HTMLResponse)
def dynamic_search_data(q: str = ""):
    return extraction_first_fixture() if q.casefold() == "software buying and comparison tools" else "<p>No results</p>"


@fixture.app.post("/dynamic-search-data", response_class=HTMLResponse)
def dynamic_search_post(data: dict):
    return dynamic_search_data(data.get("q", ""))


@pytest.mark.browser
@pytest.mark.parametrize("mode", ["suggestion", "ajax", "post", "live_nested"])
async def test_dynamic_search_variants_capture_rendered_results(client, target, fixture_server, monkeypatch, mode):  # noqa: F811
    monkeypatch.setattr(settings(), "ai_provider", "local")
    registration = {key: target[key] for key in ("name", "allowed_domains", "configuration")}
    registration.update(base_url=f"http://127.0.0.1:8765/dynamic-search-fixture/{mode}", authorized=True)
    registration["configuration"].update(screenshots=False, max_duration_seconds=120)
    assert client.patch("/api/websites/" + target["id"], json=registration).status_code == 200
    options = {"approved_post_search": [{"url": "http://127.0.0.1:8765/dynamic-search-data", "query_field": "q",
                                       "verified_read_only": True}]} if mode == "post" else {}
    job = client.post("/api/agent/tasks", json={
        "website_id": target["id"], "objective": "List software buying and comparison tools",
        "mode": "autonomous", "allow_form_input": False, "max_steps": 8, **options,
    }).json()["id"]
    purposes = []

    async def respond(self, kind, payload, schema, *_args, **_kwargs):
        purposes.append(kind)
        if kind == "classify":
            return AssessmentBatch(records=[
                {"id": row["id"], "classification": "match",
                 "evidence": next(i for i, quote in enumerate(row["excerpts"], 1) if "before buying" in quote)}
                for row in payload["records"]
            ])
        assert kind == "verify"
        assert set(payload["captured_records"]["records"]) == {"Atlas", "Beacon"}
        cited = [row["id"] for row in payload["evidence"] if row["id"].startswith("capture-")]
        return Verification(complete=True, explanation="The rendered products qualify",
                            checks=[{"criterion": criterion, "met": True, "evidence_ids": cited}
                                    for criterion in payload["success_criteria"]])

    monkeypatch.setattr(ModelClient, "request", respond)
    await execute(*claim())
    result = client.get("/api/agent/tasks/" + job).json()
    assert result["status"] == "completed", result.get("error_message")
    assert {row["fields"]["Name"] for row in result["result"]["structured_records"]} == {"Atlas", "Beacon"}
    assert "decide" not in purposes
