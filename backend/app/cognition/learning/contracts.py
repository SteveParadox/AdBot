"""Offline evaluation contracts; no autonomous policy or model updates."""
from dataclasses import dataclass
from math import isfinite
from typing import Protocol


@dataclass(frozen=True)
class FeedbackRecord:
    workspace_id: str
    task_id: str
    rubric_version: str
    evidence_ids: tuple[str, ...]
    verified_success: bool
    lesson: str

    def __post_init__(self):
        fields = (self.workspace_id, self.task_id, self.rubric_version, self.lesson)
        if (any(not isinstance(value, str) or not value.strip() for value in fields)
                or type(self.verified_success) is not bool
                or not isinstance(self.evidence_ids, tuple) or not self.evidence_ids):
            raise ValueError("Feedback requires provenance, evidence and a lesson")
        if (any(not isinstance(item, str) or not item.strip() for item in self.evidence_ids)
                or len(set(self.evidence_ids)) != len(self.evidence_ids)):
            raise ValueError("Invalid evidence ID")


@dataclass(frozen=True)
class EvaluationReport:
    suite_id: str
    baseline_success: float
    candidate_success: float
    cases: int
    regressions: int
    held_out: bool

    def __post_init__(self):
        rates = (self.baseline_success, self.candidate_success)
        if any(type(rate) not in (int, float) or not isfinite(rate)
               or not 0 <= rate <= 1 for rate in rates):
            raise ValueError("Success rates must be finite probabilities")
        if (not isinstance(self.suite_id, str) or not self.suite_id.strip()
                or type(self.cases) is not int or type(self.regressions) is not int
                or type(self.held_out) is not bool or self.cases < 1
                or not 0 <= self.regressions <= self.cases):
            raise ValueError("Invalid evaluation report")


class OfflineEvaluator(Protocol):
    async def compare(self, candidate_id: str, suite_id: str) -> EvaluationReport: ...


def eligible_for_review(report: EvaluationReport, minimum_cases: int = 20) -> bool:
    """Only nominates a candidate for human review; never deploys it."""
    if type(minimum_cases) is not int or minimum_cases < 1:
        raise ValueError("Invalid minimum case count")
    return (
        report.held_out
        and report.cases >= minimum_cases
        and report.regressions == 0
        and report.candidate_success > report.baseline_success
    )
