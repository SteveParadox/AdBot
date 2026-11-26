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
