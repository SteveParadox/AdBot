import pytest

from app.agent.directory import DirectoryCollection, directory_intent, directory_result
from app.agent.memory import semantic_action_key
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
    assert directory_intent("List all AI chatbots except paid products", {}) is None
    assert directory_intent("List all AI chatbots", {"success_criteria": ["Sort by rating"]}) is None
    assert directory_intent("List all AI chatbots", {}, True) is None


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
