from app.agent.discovery import (
    automatic_capture, compact_page, navigation_candidate, ranked_excerpt, task_token_allowance, unchanged_scrolls,
)
from app.security import Policy


def record(name, description):
    return {"truncated": False, "segments": [
        {"label": "Record heading", "value": name, "truncated": False},
        {"label": "", "value": description, "truncated": False},
    ]}


def test_capture_repeated_records_before_navigation():
    url = "https://example.test/"
    group = {"id": 2, "kind": "repeated", "label": "Buyer utilities",
             "records": [record("Atlas", "Compare software licensing costs and purchase options."),
                         record("Beacon", "Manage software purchases and compare vendors.")]}
    observed = {"url": url, "record_groups": [{"id": 2}], "elements": []}
    decision = automatic_capture(observed, {2: group}, "List software buying and comparison tools")
    assert decision.decision == "CAPTURE_RECORDS"
    assert decision.capture.identity == 1
    assert decision.capture.restrict_to_objective
    assert decision.capture.fields[1].position == 2
    group["kind"] = "detail"
    assert automatic_capture(observed, {2: group}, "List software buying and comparison tools") is None


def test_automatic_capture_does_not_invent_mapping_or_use_hidden_group():
    group = {"id": 2, "kind": "repeated", "label": "Buyer utilities",
             "records": [record("Atlas", "Compare software license offers before buying."),
                         record("Atlas", "Compare software prices from vendors.")]}
    observed = {"url": "https://example.test/", "record_groups": [{"id": 2}]}
    assert automatic_capture(observed, {2: group}, "List buying tools") is None
    group["records"][1] = record("Beacon", "Compare supplier contracts before buying.")
    observed["record_groups"] = []
    assert automatic_capture(observed, {2: group}, "List buying tools") is None


def test_ranked_discovery_links_respect_scope_and_prior_visits():
    observation = {"url": "https://example.test/", "elements": [
        {"role": "link", "actionable": True, "name": "Buying tools catalog", "href": "https://example.test/catalog"},
        {"role": "link", "actionable": True, "name": "Comparison pages for publishers", "href": "https://example.test/blog"},
        {"role": "link", "actionable": True, "name": "Buying tools catalog", "href": "https://outside.test/catalog"},
        {"role": "link", "actionable": True, "name": "Buying tools catalog", "href": "https://example.test/form", "form": {"method": "POST"}},
    ]}
    policy = Policy(["example.test"])
    decision = navigation_candidate(observation, "List buying and comparison tools", policy)
    assert decision.url == "https://example.test/catalog"
    decision = navigation_candidate(observation, "List buying and comparison tools", policy,
                                    excluded={"https://example.test/catalog", "https://example.test/blog"})
    assert decision is None


def test_compact_page_preserves_relevant_text_and_observed_ids():
    source = "Archive announcements.\n" * 250 + "Atlas compares software before buying."
    observed = {"url": "https://example.test/", "text": source, "elements": []}
    elements = [{"element_id": "link1", "role": "link", "name": "Buying tools", "href": "https://example.test/catalog",
                 "actionable": True}, {"element_id": "search1", "role": "searchbox", "actionable": True}]
    page = compact_page(observed, "List buying tools", elements=elements, groups=[])
    assert "Atlas compares software before buying." in page["text"]
    assert len(page["text"]) <= 1400
    assert [item["element_id"] for item in page["elements"]] == ["link1"]
    assert "Atlas" in ranked_excerpt("List buying tools", source, limit=100)


def test_information_progress_is_distinct_from_scroll_position():
    page = {"url": "https://example.test/catalog"}
    action = {"action": "SCROLL", "outcome": {"after_url": page["url"], "page_changed": True,
                                               "content_changed": False, "record_groups_changed": False}}
    assert unchanged_scrolls(page, [action, action]) == 2
    assert unchanged_scrolls(page, [action, {**action, "outcome": {**action["outcome"], "information_progress": True}}]) == 0


def test_budget_reserves_are_bounded_and_finalization_can_use_remaining_tokens():
    allowance, fallback, final = task_token_allowance(60000, 53879, fallback_reserve=20000,
                                                       primary=True, purpose="decide", handoff=True)
    assert allowance + fallback + final == 6121
    assert fallback == 0 and final > 0
    assert task_token_allowance(60000, 53879, fallback_reserve=20000,
                                primary=True, purpose="verify", handoff=True) == (6121, 0, 0)
    assert task_token_allowance(60000, 60001, fallback_reserve=20000,
                                primary=True, purpose="decide") == (0, 0, 0)


def test_compact_page_accepts_controls_without_hrefs():
    page = compact_page({"url": "https://example.test/"}, "List tools",
                        elements=[{"element_id": "button1", "role": "button", "name": "Open menu",
                                   "href": None, "actionable": True}], groups=[])
    assert page["elements"][0]["element_id"] == "button1"


def test_catalog_ranking_prefers_collection_to_keyword_matching_interface():
    observation = {"url": "https://example.test/", "elements": [
        {"role": "link", "actionable": True, "name": "Compare Tools", "href": "https://example.test/compare"},
        {"role": "link", "actionable": True, "name": "Browse software products by use case",
         "href": "https://example.test/products"},
    ]}
    decision = navigation_candidate(observation, "List software buying and comparison tools",
                                    Policy(["example.test"]), catalog_only=True, minimum=8)
    assert decision.url == "https://example.test/products"


def test_automatic_mapping_rejects_duplicate_even_in_large_group():
    rows = [record(f"Tool {i}", "Compare supplier purchase costs before buying.") for i in range(6)]
    rows.append(record("Tool 0", "Different duplicate record for comparing costs."))
    group = {"id": 2, "kind": "repeated", "label": "Buyer catalog", "records": rows}
    observed = {"url": "https://example.test/", "record_groups": [{"id": 2}]}
    assert automatic_capture(observed, {2: group}, "List buying tools") is None


def test_discovery_ignores_malformed_hidden_and_fragment_links():
    elements = [
        {"role": "link", "actionable": True, "name": "Buying catalog", "href": "https://[bad"},
        {"role": "link", "actionable": True, "name": "Buying catalog", "href": "https://example.test/hidden", "visible": False},
        {"role": "link", "actionable": True, "name": "Buying catalog", "href": "https://example.test/#catalog"},
    ]
    page = {"url": "https://example.test/", "elements": elements}
    assert navigation_candidate(page, "List buying tools", Policy(["example.test"])) is None
    compact = compact_page(page, "List buying tools", elements=elements, groups=[])
    assert all(item.get("href") != "https://[bad" for item in compact["elements"])


def test_automatic_mapping_does_not_shift_unlabeled_fields_across_rows():
    first = record("Atlas", "Compare supplier costs before buying software.")
    second = record("Beacon", "Compare vendor purchase costs before buying software.")
    second["segments"][1]["label"] = "Editorial"
    group = {"id": 2, "kind": "repeated", "label": "Buyer catalog", "records": [first, second]}
    page = {"url": "https://example.test/", "record_groups": [{"id": 2}]}
    assert automatic_capture(page, {2: group}, "List buying tools") is None


def test_unrelated_generic_catalog_is_not_automatic_destination():
    from app.agent.discovery import observed_links

    page = {"url": "https://example.test/", "elements": [
        {"role": "link", "actionable": True, "name": "Browse prompt library", "href": "https://example.test/prompts"},
        {"role": "link", "actionable": True, "name": "Browse software products", "href": "https://example.test/products"},
    ]}
    ranked = observed_links(page, "List software buying and comparison tools", Policy(["example.test"]), catalog_only=True)
    assert [url for _, url in ranked] == ["https://example.test/products"]


def test_autonomous_search_is_separate_from_general_form_permission():
    from app.agent.discovery import read_search_permission, search_candidate, search_control, search_attempt_key
    from app.agent.planning import specification

    objective = "List software buying and comparison tools"
    options = {"mode": "autonomous", "allow_search_input": True, "allow_form_input": False}
    assert read_search_permission(objective, options, "structured_extraction")
    assert not read_search_permission("List software tools without searching", options, "structured_extraction")
    assert not read_search_permission(objective, {**options, "mode": "assisted"}, "structured_extraction")
    assert not read_search_permission(objective, {**options, "allow_search_input": False}, "structured_extraction")
    spec = specification(objective, [objective], options, ["example.test"])
    assert spec["permissions"]["read_search"] and not spec["permissions"]["form_input"]
    element = {"element_id": "search1", "tag": "input", "type": "search", "role": "searchbox",
               "actionable": True, "form": {"method": "GET", "search": True, "action": "https://example.test/search"}}
    page = {"url": "https://example.test/", "elements": [element]}
    decision = search_candidate(page, objective, Policy(["example.test"]), [])
    assert decision.decision == "SEARCH" and decision.text == "software buying and comparison tools"
    assert search_candidate(page, objective, Policy(["example.test"]), [search_attempt_key(element, decision.text)]) is None
    assert not search_control({**element, "form": {**element["form"], "method": "POST"}})
    assert not search_control({**element, "type": "password"})
    assert not search_control({**element, "sensitive": True})


def test_frontier_preserves_unexplored_candidates_after_page_transition():
    from app.agent.discovery import update_frontier, frontier_candidate

    objective = "List buying tools"
    root = {"url": "https://example.test/", "elements": [
        {"role": "link", "actionable": True, "name": "Buying tools catalog", "href": "https://example.test/catalog"},
        {"role": "link", "actionable": True, "name": "Buying tools directory", "href": "https://example.test/directory"},
    ]}
    policy = Policy(["example.test"])
    frontier = update_frontier({}, root, objective, policy, {root["url"]})
    page = {"url": "https://example.test/catalog", "elements": []}
    frontier = update_frontier(frontier, page, objective, policy, {root["url"], page["url"]})
    assert frontier_candidate(frontier, page, policy, {root["url"], page["url"]}).url == "https://example.test/directory"


def test_mapping_diagnostics_and_unlabelled_card_fallback():
    first = record("Atlas", "Compare supplier purchase costs before buying.")
    second = record("Beacon", "Compare software vendors before buying.")
    for row in (first, second):
        row["segments"][0]["label"] = ""
    group = {"id": 2, "kind": "repeated", "label": "Buyer catalog", "records": [first, second]}
    observed = {"url": "https://example.test/", "record_groups": [{"id": 2}]}
    diagnostics = {}
    assert automatic_capture(observed, {2: group}, "List buying tools", diagnostics=diagnostics)
    assert diagnostics["strategy"] == "automatic_capture"
    group["records"][1]["segments"][0]["value"] = "Atlas"
    assert automatic_capture(observed, {2: group}, "List buying tools", diagnostics=diagnostics) is None
    assert diagnostics["strategy"] == "model_assisted"
    assert diagnostics["mapping_rejections"]["no_confident_mapping"] == 1


def test_search_opt_out_respects_criteria_and_legacy_permissions():
    from app.agent.planning import specification

    objective = "List software comparison tools"
    options = {"mode": "autonomous", "allow_search_input": True, "allow_form_input": False}
    for constraint in ("Do not use any search bars", "Avoid using the website search", "Never submit forms"):
        assert not specification(objective, [objective, constraint], options, ["example.test"])["permissions"]["read_search"]
    legacy = specification(objective, [objective], {"mode": "autonomous"}, ["example.test"])
    assert legacy["permissions"] == {"form_input": False, "downloads": False}


def test_search_rejects_invalid_endpoints_and_exhausted_attempts():
    from app.agent.discovery import MAX_SEARCH_ATTEMPTS, search_candidate, search_control

    element = {"element_id": "search1", "tag": "input", "type": "search", "role": "searchbox",
               "actionable": True, "form": {"method": "GET", "search": True, "action": "https://example.test/search"}}
    page = {"url": "https://example.test/", "elements": [element]}
    policy = Policy(["example.test"])
    assert search_candidate(page, "List buying tools", policy, [])
    assert search_candidate(page, "List buying tools", policy, list(range(MAX_SEARCH_ATTEMPTS))) is None
    for url in ("https://[invalid", "https://user:pass@example.test/search", "javascript:alert(1)",
                "https://example.test/search#form"):
        candidate = {**element, "form": {**element["form"], "action": url}}
        assert not search_control(candidate)
        assert search_candidate({**page, "elements": [candidate]}, "List buying tools", policy, []) is None
    external = {**element, "form": {**element["form"], "action": "https://outside.test/search"}}
    assert search_candidate({**page, "elements": [external]}, "List buying tools", policy, []) is None


def test_unproductive_content_changes_do_not_reset_information_progress():
    page = {"url": "https://example.test/catalog"}
    action = {"action": "SCROLL", "outcome": {"after_url": page["url"], "page_changed": True,
                "content_changed": True, "record_groups_changed": True, "information_progress": False}}
    assert unchanged_scrolls(page, [action, action]) == 2


def test_automatic_capture_rejects_case_variant_duplicate_names():
    rows = [record("Atlas", "Compare supplier purchase costs before buying."),
            record("ATLAS", "Compare software vendors before buying.")]
    group = {"id": 2, "kind": "repeated", "label": "Buyer catalog", "records": rows}
    observed = {"url": "https://example.test/", "record_groups": [{"id": 2}]}
    diagnostics = {}
    assert automatic_capture(observed, {2: group}, "List buying tools", diagnostics=diagnostics) is None
    assert diagnostics["mapping_rejections"]["duplicate_identity"] == 1


def test_relevant_structure_is_not_hidden_behind_unrelated_groups():
    from app.agent.structure import summarize_structure

    def group(identifier, records):
        return {"id": identifier, "kind": "repeated", "label": "Catalog", "context": [],
                "observed_count": len(records), "truncated": False, "static_table": False, "records": records}

    groups = [group(i, [record("News", "Latest releases from the publishing team.")]) for i in range(1, 9)]
    groups.append(group(9, [record("Atlas", "Compare supplier costs before buying software.")]))
    assert 9 not in {item["id"] for item in summarize_structure(groups)}
    assert summarize_structure(groups, "List buying tools")[0]["id"] == 9


def test_scripted_search_control_recognizes_nonstandard_editable_without_form():
    from app.agent.search import search_interface
    from app.agent.discovery import search_candidate

    element = {"element_id": "custom1", "tag": "div", "type": "", "role": "searchbox",
               "actionable": True, "search_interface": {"search_semantics": True, "editable": True}}
    page = {"url": "https://example.test/", "elements": [element]}
    assert search_interface(element) == "scripted"
    assert search_candidate(page, "List buying tools", Policy(["example.test"]), []).target.element_id == "custom1"
    assert search_interface({**element, "name": "Password search"}) is None
    assert search_interface({**element, "role": "textbox", "search_interface": {"editable": True}}) is None
    assert search_interface({**element, "readonly": True}) is None


def test_approved_post_search_is_exact_and_query_only():
    from app.agent.search import ApprovedPostSearch, approved_post_payload, search_interface

    endpoint = ApprovedPostSearch(url="https://example.test/api/search", query_field="q",
                                  verified_read_only=True).model_dump()
    endpoints = [endpoint]
    url, query = endpoint["url"], "buying tools"
    assert approved_post_payload(url, "application/json", '{"q":"buying tools"}', query, endpoints)
    assert approved_post_payload(url, "application/x-www-form-urlencoded; charset=utf-8", "q=buying+tools", query, endpoints)
    for body in ('{"q":"buying tools","delete":true}', '{"q":"buying tools","q":"different"}',
                 '{"q":{"value":"buying tools"}}', '[["q","buying tools"]]', '{"q":"different"}'):
        assert not approved_post_payload(url, "application/json", body, query, endpoints)
    assert not approved_post_payload(url + "?admin=1", "application/json", '{"q":"buying tools"}', query, endpoints)
    assert not approved_post_payload("https://outside.test/api/search", "application/json", '{"q":"buying tools"}', query, endpoints)
    assert not approved_post_payload(url, "application/json", '{"q":"buying tools"}', query, [])
    element = {"tag": "input", "type": "search", "role": "searchbox", "actionable": True,
               "form": {"method": "POST", "action": url, "search": True}}
    assert search_interface(element, endpoints) == "approved_post"
    assert search_interface(element) is None


def test_post_search_approval_requires_attestation_and_allowed_domain():
    import pytest
    from app.agent.search import ApprovedPostSearch, validate_post_endpoints

    for url in ("https://example.test/*", "https://example.test/api/search?x=1",
                "https://example.test/api/search#fragment", "https://user:pw@example.test/search"):
        with pytest.raises(ValueError):
            ApprovedPostSearch(url=url, query_field="q", verified_read_only=True)
    with pytest.raises(ValueError):
        ApprovedPostSearch(url="https://example.test/search", query_field="q", verified_read_only=False)
    with pytest.raises(ValueError):
        validate_post_endpoints([{"url": "https://outside.test/search", "query_field": "q",
                                  "verified_read_only": True}], Policy(["example.test"]))


def test_formless_search_attempt_keys_are_page_scoped():
    from app.agent.discovery import search_attempt_key

    control = {"role": "searchbox", "name": "Search"}
    assert search_attempt_key(control, "buying tools", "https://example.test/a") != search_attempt_key(
        control, "buying tools", "https://example.test/b")


def test_post_attestation_is_boolean_and_payload_is_strict_utf8():
    import pytest
    from app.agent.search import ApprovedPostSearch, approved_post_payload

    url = "https://example.test/search"
    for value in (1, "true", "yes", None):
        with pytest.raises(ValueError):
            ApprovedPostSearch(url=url, query_field="q", verified_read_only=value)
    approvals = [ApprovedPostSearch(url=url, query_field="q", verified_read_only=True).model_dump()]
    assert not approved_post_payload(url, "application/x-www-form-urlencoded", "q=%FF", "\ufffd", approvals)
    assert not approved_post_payload(url, "application/x-www-form-urlencoded", "q=%", "%", approvals)
    assert not approved_post_payload(url, "application/x-www-form-urlencoded", "q=x&q=x", "x", approvals)
    assert not approved_post_payload(url, "application/json", '{"q":"x"}', "x", [])


def test_ambiguous_custom_search_is_not_selected():
    from app.agent.search import search_interface
    from app.agent.discovery import search_candidate

    element = {"element_id": "custom1", "tag": "div", "type": "", "role": "searchbox",
               "actionable": True, "ambiguous": True,
               "search_interface": {"search_semantics": True, "editable": True}}
    page = {"url": "https://example.test/", "elements": [element]}
    assert search_interface(element) is None
    assert search_candidate(page, "List buying tools", Policy(["example.test"]), []) is None
def test_title_lookup_and_search_controls_inside_dialogs():
    from app.agent.discovery import search_candidate, search_opener
    from app.agent.routing import select_route

    objective = "Google Sheets Data Cleaning and Formulas"
    policy = Policy(["example.test"])
    assert select_route(objective, {}).name == "informational"
    assert select_route("Delete Google Sheets Data", {}).name == "general"
    observed = {
        "url": "https://example.test/",
        "elements": [{"element_id": "open", "role": "button", "name": "Search ⌘K", "actionable": True}],
    }
    decision, key = search_opener(observed, policy, [])
    assert decision.target.element_id == "open"
    assert search_opener(observed, policy, [key]) == (None, None)
    observed.update(dialogs=[{"visible": True}], elements=[
        {"element_id": "outside", "role": "searchbox", "type": "search", "tag": "input",
         "actionable": True, "blocked_by_modal": True},
        {"element_id": "inside", "role": "searchbox", "type": "search", "tag": "input", "actionable": True},
    ])
    search = search_candidate(observed, objective, policy, [], short_title=True)
    assert search.target.element_id == "inside"
    assert search.text == objective
