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


def test_reject_mutable_or_invalid_plan_inputs():
    with pytest.raises(ValueError):
        WorkItem("a", "researcher", "objective")
    with pytest.raises(ValueError):
        WorkItem("a", AgentRole.RESEARCHER, "objective", ["b"])
    with pytest.raises(ValueError):
        CollaborationPlan("workspace", "objective", [item("a")])
    with pytest.raises(ValueError):
        dependency_order(tuple(item(str(i)) for i in range(21)))


def test_result_requires_unique_evidence():
    from app.cognition.orchestration.contracts import WorkResult

    assert WorkResult("a", ("e1",), "summary").evidence_ids == ("e1",)
    for refs in ((), ("e1", "e1"), ["e1"]):
        with pytest.raises(ValueError):
            WorkResult("a", refs, "summary")
