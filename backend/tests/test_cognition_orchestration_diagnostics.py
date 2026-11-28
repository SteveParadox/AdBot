import pytest

from app.cognition.orchestration.contracts import AgentRole, CollaborationPlan, WorkItem
from app.cognition.orchestration.diagnostics import Outcome, report_coverage


def test_dependency_coverage_propagates_missing_and_failed_results():
    plan = CollaborationPlan("workspace", "public report", (
        WorkItem("report", AgentRole.WRITER, "write", ("analysis",)),
        WorkItem("analysis", AgentRole.ANALYST, "analyze", ("sources",)),
        WorkItem("sources", AgentRole.RESEARCHER, "review evidence"),
    ))
    result = report_coverage(plan, {"sources": Outcome.FAILED})
    assert [row.outcome for row in result] == [Outcome.FAILED, Outcome.BLOCKED, Outcome.BLOCKED]
    with pytest.raises(ValueError):
        report_coverage(plan, {"report": Outcome.COMPLETE})
    with pytest.raises(ValueError):
        report_coverage(plan, {"unknown": Outcome.COMPLETE})
    complete = report_coverage(plan, {item.item_id: Outcome.COMPLETE for item in plan.items})
    assert all(row.outcome == Outcome.COMPLETE for row in complete)
