"""Declarative research skill contracts; no executable skill engine."""
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class SkillOperation(str, Enum):
    EXTRACT_FIELDS = "extract_fields"
    NORMALIZE_RECORDS = "normalize_records"
    DEDUPLICATE = "deduplicate"
    VERIFY_CITATIONS = "verify_citations"
    COMPOSE_REPORT = "compose_report"


@dataclass(frozen=True)
class SkillCandidate:
    skill_id: str
    version: int
    workspace_id: str
    objective: str
    source_task_id: str
    evidence_ids: tuple[str, ...]
    operations: tuple[SkillOperation, ...]

    def __post_init__(self):
        fields = (self.skill_id, self.workspace_id, self.objective, self.source_task_id)
        if any(not value.strip() for value in fields) or self.version < 1:
            raise ValueError("Invalid skill identity or provenance")
        if not self.evidence_ids or any(not item.strip() for item in self.evidence_ids):
            raise ValueError("Skill requires verified source references")
        if not 1 <= len(self.operations) <= 20:
            raise ValueError("Invalid operation count")
        if any(not isinstance(operation, SkillOperation) for operation in self.operations):
            raise ValueError("Unsupported operation")


@dataclass(frozen=True)
class SkillValidation:
    skill_id: str
    version: int
    fixture_count: int
    failed_fixtures: int
    evidence_verified: bool

    def __post_init__(self):
        if not self.skill_id.strip() or self.version < 1:
            raise ValueError("Invalid validation identity")
        if self.fixture_count < 1 or not 0 <= self.failed_fixtures <= self.fixture_count:
            raise ValueError("Invalid fixture counts")


class CandidateRegistry(Protocol):
    async def submit(self, candidate: SkillCandidate) -> None: ...
    async def candidates(self, workspace_id: str) -> tuple[SkillCandidate, ...]: ...


def eligible_for_review(candidate: SkillCandidate, validation: SkillValidation) -> bool:
    """Review eligibility only, not authorization or production promotion."""
    return (
        candidate.skill_id == validation.skill_id
        and candidate.version == validation.version
        and validation.fixture_count >= 3
        and validation.failed_fixtures == 0
        and validation.evidence_verified
    )
