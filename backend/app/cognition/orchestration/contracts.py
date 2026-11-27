"""Read-only research collaboration contracts, without dispatch or execution."""
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class AgentRole(str, Enum):
    RESEARCHER = "researcher"
    EXTRACTOR = "extractor"
    ANALYST = "analyst"
    VERIFIER = "verifier"
    WRITER = "writer"


@dataclass(frozen=True)
class WorkItem:
    item_id: str
    role: AgentRole
    objective: str
    dependencies: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.item_id.strip() or not self.objective.strip():
            raise ValueError("Work item requires an ID and objective")
        if len(set(self.dependencies)) != len(self.dependencies):
            raise ValueError("Duplicate dependencies")


@dataclass(frozen=True)
class CollaborationPlan:
    workspace_id: str
    objective: str
    items: tuple[WorkItem, ...]

    def __post_init__(self):
        if not self.workspace_id.strip() or not self.objective.strip():
            raise ValueError("Plan requires workspace and objective")
        if not 1 <= len(self.items) <= 20:
            raise ValueError("Invalid number of work items")
        dependency_order(self.items)


def dependency_order(items: tuple[WorkItem, ...]) -> tuple[str, ...]:
    """Validate a DAG and return a deterministic topological order."""
    by_id = {item.item_id: item for item in items}
    if len(by_id) != len(items):
        raise ValueError("Duplicate work item")
    visiting: set[str] = set()
    visited: set[str] = set()
    order: list[str] = []

    def visit(item_id: str) -> None:
        if item_id not in by_id:
            raise ValueError("Unknown dependency")
        if item_id in visiting:
            raise ValueError("Cyclic dependency")
        if item_id in visited:
            return
        visiting.add(item_id)
        for parent in by_id[item_id].dependencies:
            visit(parent)
        visiting.remove(item_id)
        visited.add(item_id)
        order.append(item_id)

    for item in items:
        visit(item.item_id)
    return tuple(order)


@dataclass(frozen=True)
class WorkResult:
    item_id: str
    evidence_ids: tuple[str, ...]
    summary: str


class EvidenceWorkspace(Protocol):
    async def results(self, workspace_id: str, plan_id: str) -> tuple[WorkResult, ...]: ...
