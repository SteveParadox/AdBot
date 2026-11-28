"""Pure diagnostics for research report dependencies, not a worker dispatcher."""
from dataclasses import dataclass
from enum import Enum

from .contracts import CollaborationPlan, dependency_order


class Outcome(str, Enum):
    COMPLETE = "complete"
    FAILED = "failed"
    MISSING = "missing"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class Coverage:
    item_id: str
    outcome: Outcome
    unresolved_dependencies: tuple[str, ...]


def report_coverage(plan: CollaborationPlan, outcomes: dict[str, Outcome]) -> tuple[Coverage, ...]:
    """Inspect submitted report results without scheduling or executing any work."""
    if not isinstance(plan, CollaborationPlan) or not isinstance(outcomes, dict):
        raise ValueError("Invalid coverage inputs")
    by_id = {item.item_id: item for item in plan.items}
    if any(key not in by_id or value not in (Outcome.COMPLETE, Outcome.FAILED, Outcome.MISSING)
           or not isinstance(value, Outcome) for key, value in outcomes.items()):
        raise ValueError("Unexpected report outcome")
    resolved: dict[str, Coverage] = {}
    for item_id in dependency_order(plan.items):
        unresolved = tuple(parent for parent in by_id[item_id].dependencies
                           if resolved[parent].outcome != Outcome.COMPLETE)
        observed = outcomes.get(item_id, Outcome.MISSING)
        if unresolved and observed == Outcome.COMPLETE:
            raise ValueError("Completed report has unresolved dependencies")
        state = Outcome.BLOCKED if unresolved and observed == Outcome.MISSING else observed
        resolved[item_id] = Coverage(item_id, state, unresolved)
    return tuple(resolved.values())
