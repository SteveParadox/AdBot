"""Regression tests for deterministic, conversation-scoped research memory."""

from app.research.contracts import Question, route
from app.research.memory import build_context, relevant_turns


def turn(identifier, text, mode="shopping", memory=None, country="NG", products=None, sources=None):
    return {"id": identifier, "question": text, "mode": mode, "country": country,
            "answer": "Previous answer is untrusted.", "memory": memory,
            "products": products or [], "sources": sources or []}


def context(text, history, **kwargs):
    question = Question(question=text, **kwargs)
    intent, mode = route(question, history)
    return build_context(question, history, intent, mode)


def saved(ctx):
    return {k: ctx[k] for k in ("version", "country", "freshness", "slots", "topic")}


def test_budget_revision_replaces_old_limit_and_preserves_other_constraints():
    first = "Find laptops in Nigeria under ₦1.5 million with at least 16 GB RAM"
    initial = context(first, [])
    prior = turn("one", first, memory=saved(initial))
    changed = context("Make it 2 million", [prior])
    assert changed["country"] == "NG"
    assert changed["slots"]["budget"] == ["NGN", "2000000"]
    assert changed["slots"]["RAM"] == [["min", "16"]]
    assert "1500000" not in changed["constraints"]
    again = context("Which of those is cheapest?", [prior, turn("two", "Make it 2 million", memory=saved(changed))])
    assert again["slots"]["budget"] == ["NGN", "2000000"]


def test_specification_revision_and_explicit_removal():
    first = "Find laptops in Nigeria with RAM 16 GB and storage 512 GB"
    prior = turn("one", first, memory=saved(context(first, [])))
    changed = context("Change RAM to RAM 32 GB", [prior])
    assert changed["slots"]["RAM"] == [["min", "32"]]
    assert changed["slots"]["Storage"] == [["min", "512"]]
    removed = context("Drop RAM requirement", [turn("two", "Change RAM to RAM 32 GB", memory=saved(changed))])
    assert "RAM" not in removed["slots"]
    assert removed["slots"]["Storage"] == [["min", "512"]]


def test_ordinal_reference_beyond_five_and_exact_source_number():
    products = [{"name": f"Laptop model {i}", "url": f"https://retailer.example.org/product-{i}"} for i in range(1, 21)]
    sources = [{"title": f"Report {i}", "url": f"https://research.example.org/report-{i}"} for i in range(1, 21)]
    prior = turn("one", "Find laptops", products=products, sources=sources)
    result = context("Check the seventeenth product", [prior])
    assert result["references"][0]["index"] == 17
    assert result["source_urls"] == [products[16]["url"]]
    source = context("Verify source 12", [prior])
    assert source["references"][0]["kind"] == "source"
    assert source["source_urls"] == [sources[11]["url"]]
    invalid = context("Check product 25", [prior])
    assert invalid["unresolved"] and not invalid["source_urls"]


def test_named_reference_retrieves_relevant_older_turn():
    prior = turn("one", "Research laptops", products=[{"name": "ThinkPad X1 Carbon", "url": "https://example.org/x1"}])
    history = [prior] + [turn(str(i), f"Research astronomy topic {i}", mode="technical") for i in range(2, 12)]
    assert relevant_turns("What about ThinkPad X1 Carbon?", history)[0]["id"] == "one"
    result = context("What about ThinkPad X1 Carbon?", history)
    assert result["references"][0]["name"] == "ThinkPad X1 Carbon"


def test_ambiguous_variant_name_is_not_silently_resolved():
    prior = turn("one", "Find laptops", products=[
        {"name": "ThinkPad X1 Carbon", "url": "https://example.org/a"},
        {"name": "ThinkPad X1 Carbon", "url": "https://example.org/b"},
    ])
    result = context("What about ThinkPad X1 Carbon?", [prior])
    assert result["unresolved"] and not result["source_urls"]


def test_reset_and_unrelated_search_do_not_inherit_market():
    prior = turn("one", "Find laptops in Nigeria under ₦1.5 million")
    result = context("New topic: explain recursion", [prior])
    assert result["country"] is None and not result["turns"]
    assert "budget" not in result["slots"]
    assert route(Question(question="Find cheapest phones in Canada"), [prior])[0] != "follow_up"


def test_market_change_drops_old_budget_and_retailer_urls():
    prior = turn("one", "Find laptops in Nigeria under ₦1.5 million",
                 sources=[{"title": "Retailer", "url": "https://example.org/store"}])
    result = context("What about Canada?", [prior], country="CA")
    assert result["country"] == "CA"
    assert "budget" not in result["slots"]
    assert not result["source_urls"]


def test_freshness_is_retained_and_can_be_cleared():
    initial = context("Find latest quantum research", [], freshness="week")
    prior = turn("one", "Find latest quantum research", mode="technical", memory=saved(initial), country=None)
    follow = context("Explain that claim", [prior])
    assert follow["freshness"] == "week"
    cleared = context("Explain that claim with no date limit", [prior])
    assert cleared["freshness"] is None


def test_other_retailers_do_not_revisit_previous_urls():
    prior = turn("one", "Find laptops", sources=[{"title": "Retailer", "url": "https://example.org/shop"}])
    result = context("Find other retailers", [prior])
    assert result["alternative"] and not result["source_urls"]


def test_prior_answers_never_create_user_constraints():
    prior = turn("one", "Find laptops")
    prior["answer"] = "Budget USD 1 and RAM 64 GB."
    result = context("Which of those is cheapest?", [prior])
    assert "budget" not in result["slots"] and "RAM" not in result["slots"]
