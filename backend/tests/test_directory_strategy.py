import pytest

from app.agent.classification import AssessmentBatch, apply_assessments, assessment_payload
from app.agent.context import retrieve_evidence
from app.agent.directory import DirectoryCollection, directory_intent, directory_result
from app.agent.memory import semantic_action_key
from app.agent.routing import RouteAssessment, assessed_entity, select_route
from app.security import PolicyError


class Policy:
    def check(self, url):
        if not url.startswith("https://example.test/"):
            raise PolicyError("outside authorized scope")
        return url


def row(name, category, url=None):
    return {"name": name, "category": category, "description": "Visible detail", "quote": f"{name} {category}",
            "href": url or f"https://example.test/tool/{name}"}


def observation(rows, *, total=1, forward=0, filtered=False):
    return {"url": "https://example.test/tools", "elements": [], "directory": {"rows": rows, "total": total,
            "kind": "tools", "filtered": filtered, "truncated": False, "busy": False, "forward_enabled": forward}}


@pytest.mark.parametrize("rows,changes,fragment", [
    ([row("Bot", "AI chatbot")], {"total": 2}, "advertised total"),
    ([row("Other", "AI")], {}, "could not be classified"),
    ([row("Bot", "AI chatbot")], {"filtered": True}, "filtered"),
    ([row("Bot", "AI chatbot")], {"forward": 1}, "pagination control"),
    ([row("Bot", "AI chatbot", "https://evil.test/tool")], {}, "only part"),
])
def test_directory_does_not_claim_unsupported_completeness(rows, changes, fragment):
    state = {}
    strategy = DirectoryCollection("ai chatbots", state)
    _, reason = strategy.advance(observation(rows, **changes), 1, Policy())
    assert fragment in reason
    result = directory_result(state, reason)
    assert result["partial"] and not result["verification"]["complete"]
    assert all("evil.test" not in evidence["source_url"] for evidence in result["evidence"])


def test_unrelated_constraints_or_dataset_keep_original_strategy():
    assert directory_intent("List all AI chatbots.", {}) == "ai chatbots"
    assert directory_intent("Give me a comprehensive list of conversational AI platforms.", {}) == "ai chatbots"
    assert directory_intent("List all AI chatbots except paid products", {}) is None
    assert directory_intent("List all AI chatbots", {"success_criteria": ["Sort by rating"]}) is None
    assert directory_intent("List all AI chatbots", {}, True) is None


@pytest.mark.parametrize("objective,options,dataset,expected", [
    ("Extract all rows from the table", {}, False, "table_extraction"),
    ("Compare the plans and cite their features", {}, False, "comparison"),
    ("Retrieve the warranty PDF", {}, False, "document_retrieval"),
    ("Research the origins of the brand", {}, False, "research"),
    ("Open the register and then verify the published data", {}, False, "workflow"),
    ("List all products", {}, True, "configured_extraction"),
    ("Find published prices", {"output_format": "csv"}, False, "configured_extraction"),
])
def test_route_selection(objective, options, dataset, expected):
    assert select_route(objective, options, dataset).name == expected


def test_inferred_inventory_keeps_literal_scope():
    assessment = RouteAssessment(exhaustive_inventory=True, entity_phrase="language tutors")
    assert assessed_entity("Give me a complete list of language tutors", assessment) == "semantic:language tutors"
    assert assessed_entity("Give me a complete list of language tutors under $10", assessment) is None
    assert assessed_entity("Give me a complete list of tutoring tools", assessment) is None


def test_semantic_classification_requires_exact_quotes_and_ids():
    quote = "Answers follow-up questions in a conversation."
    rows = [{"name": "One", "category": "AI", "quote": quote, "classification": "unknown"},
            {"name": "Two", "category": "AI", "quote": "Unknown product type.", "classification": "unknown"}]
    payload = assessment_payload("ai chatbots", rows)
    answer = {"id": 1, "evidence": 1, "classification": "match"}
    invalid = AssessmentBatch(records=[answer, answer])
    with pytest.raises(ValueError, match="record IDs"):
        apply_assessments(rows, payload, invalid)
    invalid = AssessmentBatch(records=[answer, {**answer, "id": 2, "evidence": 3}])
    with pytest.raises(ValueError, match="observed excerpt"):
        apply_assessments(rows, payload, invalid)
    grounded = AssessmentBatch(records=[answer, {"id": 2, "classification": "unknown", "evidence": 0}])
    assert apply_assessments(rows, payload, grounded) == 1
    assert rows[0]["classification_quote"] == quote
    assert rows[1]["classification"] == "unknown"


def test_classification_expands_evidence_without_inventing_text():
    first = "Tool Alpha automates customer interactions."
    last = "Users can ask follow-up questions and receive contextual answers."
    candidate = {**row("Alpha", "AI"), "description": first, "quote": f"{first} {last}"}
    assert assessment_payload("ai chatbots", [candidate])["records"][0]["excerpts"] == [first]
    assert assessment_payload("ai chatbots", [candidate], expanded=True)["records"][0]["excerpts"] == [first, last]


@pytest.mark.parametrize("quote", [
    "Bot is a live streaming platform with overlays, chat tools and alerts.",
    "Bot is a code editor built around AI workflows.",
    "Bot integrates an AI assistant into its analytics dashboard.",
    "Built for research and editing with fewer mistakes.",
])
def test_chatbot_match_requires_more_than_an_exact_quote(quote):
    rows = [{**row("Bot", "AI"), "classification": "unknown", "description": quote, "quote": quote}]
    payload = assessment_payload("ai chatbots", rows)
    result = AssessmentBatch(records=[{"id": 1, "classification": "match", "evidence": 1}])
    assert apply_assessments(rows, payload, result) == 0
    assert rows[0]["classification"] == "unknown"


@pytest.mark.parametrize("description", [
    "Bot is an AI chatbot builder for sales teams.",
    "Unlike Product X, which is an AI chatbot, Bot builds dashboards.",
])
def test_chatbot_mention_cannot_prove_the_product_is_a_chatbot(description):
    state = {}
    strategy = DirectoryCollection("ai chatbots", state)
    candidate = {**row("Bot", "AI"), "description": description, "quote": description}
    _, reason = strategy.advance(observation([candidate]), 1, Policy())
    assert "could not be classified" in reason
    assert not directory_result(state, reason)["claims"]


def test_collection_budgets_return_partial_and_keep_observed_rows():
    state = {}
    strategy = DirectoryCollection("ai chatbots", state, max_rows=1)
    _, reason = strategy.advance(observation([row("One", "AI chatbot"), row("Two", "AI chatbot")], total=2), 1, Policy())
    result = directory_result(state, reason)
    assert result["partial"]
    assert result["directory"]["unique_records"] == 1
    assert "storage budget" in reason


def test_observed_inventory_without_count_returns_partial():
    state = {}
    strategy = DirectoryCollection("ai tools", state)
    _, reason = strategy.advance(observation([row("One", "AI chatbot")], total=None), 1, Policy())
    result = directory_result(state, reason)
    assert result["partial"]
    assert result["directory"]["unique_records"] == 1


def test_relevance_can_retrieve_an_older_evidence_quote():
    original = "Intro " * 110 + "The warranty agreement covers April."
    evidence = [{"id": "old", "url": "/contract", "quote": original}]
    evidence.extend({"id": str(index), "url": "/news", "quote": "Latest news."} for index in range(12))
    first, second = retrieve_evidence(evidence, "Get the warranty agreement", {"url": "/news"}, limit=2)
    assert first["id"] == "old" and first["quote"] in original and "warranty" in first["quote"]
    assert second["id"] == "11"


def test_equivalent_button_survives_scroll_focus_and_regenerated_ids():
    page = {"url": "https://example.test/tools", "tab_id": "t1", "text": "Example", "headings": ["Tools"],
            "scroll": {"y": 0}, "elements": [{"element_id": "first", "role": "button", "name": "All tags",
                                               "expanded": False, "focused": False}]}
    first = semantic_action_key({"decision": "CLICK", "target": {"element_id": "first"}}, page)
    page["scroll"]["y"] = 500
    page["elements"][0].update(element_id="second", focused=True)
    decision = {"decision": "CLICK", "target": {"element_id": "second"}}
    assert first == semantic_action_key(decision, page)
    page["elements"][0]["expanded"] = True
    assert first != semantic_action_key(decision, page)
