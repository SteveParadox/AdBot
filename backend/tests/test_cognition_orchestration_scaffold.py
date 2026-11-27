import pytest

from app.cognition.orchestration.contracts import (
    AgentRole, CollaborationPlan, WorkItem, dependency_order,
)


def item(identity, *dependencies):
    return WorkItem(identity, AgentRole.RESEARCHER, "Collect approved public facts", dependencies)


def test_dependency_order():
    items = (item("report", "a", "b"), item("b"), item("a"))
    plan = CollaborationPlan("workspace", "Compare facts", items)
    assert dependency_order(plan.items) == ("a", "b", "report")


@pytest.mark.parametrize("items", [
    (item("a", "b"), item("b", "a")),
    (item("a", "missing"),),
    (item("a"), item("a")),
])
def test_invalid_graph(items):
    with pytest.raises(ValueError):
        CollaborationPlan("workspace", "Compare facts", items)
