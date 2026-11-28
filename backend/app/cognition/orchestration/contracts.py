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
        if (not isinstance(self.role, AgentRole)
                or any(not isinstance(value, str) or not value.strip()
                       for value in (self.item_id, self.objective))):
            raise ValueError("Work item requires an ID and objective")
        if (not isinstance(self.dependencies, tuple) or len(self.dependencies) > 20
                or any(not isinstance(value, str) or not value.strip() for value in self.dependencies)):
            raise ValueError("Invalid dependencies")
        if len(set(self.dependencies)) != len(self.dependencies):
            raise ValueError("Duplicate dependencies")


@dataclass(frozen=True)
class CollaborationPlan:
    workspace_id: str
    objective: str
    items: tuple[WorkItem, ...]

    def __post_init__(self):
        if any(not isinstance(value, str) or not value.strip()
               for value in (self.workspace_id, self.objective)):
            raise ValueError("Plan requires workspace and objective")
        if not isinstance(self.items, tuple) or not 1 <= len(self.items) <= 20:
            raise ValueError("Invalid number of work items")
        dependency_order(self.items)


def dependency_order(items: tuple[WorkItem, ...]) -> tuple[str, ...]:
    """Validate a DAG and return a deterministic topological order."""
    if (not isinstance(items, tuple) or not 1 <= len(items) <= 20
            or any(not isinstance(item, WorkItem) for item in items)):
        raise ValueError("Invalid work items")
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

    def __post_init__(self):
        if any(not isinstance(value, str) or not value.strip()
               for value in (self.item_id, self.summary)):
            raise ValueError("Invalid work result")
        if (not isinstance(self.evidence_ids, tuple) or not self.evidence_ids
                or any(not isinstance(value, str) or not value.strip() for value in self.evidence_ids)
                or len(set(self.evidence_ids)) != len(self.evidence_ids)):
            raise ValueError("Work results require unique evidence references")


class EvidenceWorkspace(Protocol):
    async def results(self, workspace_id: str, plan_id: str) -> tuple[WorkResult, ...]: ...
