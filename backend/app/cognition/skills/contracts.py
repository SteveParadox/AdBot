"""Declarative research skill contracts; no executable skill engine."""
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
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
        if (any(not isinstance(value, str) or not value.strip() for value in fields)
                or type(self.version) is not int or self.version < 1):
            raise ValueError("Invalid skill identity or provenance")
        if (not isinstance(self.evidence_ids, tuple) or not self.evidence_ids
                or any(not isinstance(item, str) or not item.strip() for item in self.evidence_ids)
                or len(set(self.evidence_ids)) != len(self.evidence_ids)):
            raise ValueError("Skill requires verified source references")
        if not isinstance(self.operations, tuple) or not 1 <= len(self.operations) <= 20:
            raise ValueError("Invalid operation count")
        if any(not isinstance(operation, SkillOperation) for operation in self.operations):
            raise ValueError("Unsupported operation")


    def content_digest(self) -> str:
        """Bind offline review evidence to the exact declarative candidate."""
        payload = [self.workspace_id, self.skill_id, self.version, self.objective,
                   self.source_task_id, self.evidence_ids,
                   [operation.value for operation in self.operations]]
        return sha256(json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class SkillValidation:
    skill_id: str
    version: int
    fixture_count: int
    failed_fixtures: int
    evidence_verified: bool
    workspace_id: str = ""
    candidate_digest: str = ""

    def __post_init__(self):
        if (not isinstance(self.skill_id, str) or not self.skill_id.strip()
                or type(self.version) is not int or self.version < 1):
            raise ValueError("Invalid validation identity")
        if (type(self.fixture_count) is not int or type(self.failed_fixtures) is not int
                or type(self.evidence_verified) is not bool or self.fixture_count < 1
                or not 0 <= self.failed_fixtures <= self.fixture_count):
            raise ValueError("Invalid fixture counts")


class CandidateRegistry(Protocol):
    async def submit(self, candidate: SkillCandidate) -> None: ...
    async def candidates(self, workspace_id: str) -> tuple[SkillCandidate, ...]: ...


def eligible_for_review(candidate: SkillCandidate, validation: SkillValidation) -> bool:
    """Review eligibility only, not authorization or production promotion."""
    return (
        candidate.skill_id == validation.skill_id
        and candidate.version == validation.version
        and candidate.workspace_id == validation.workspace_id
        and candidate.content_digest() == validation.candidate_digest
        and validation.fixture_count >= 3
        and validation.failed_fixtures == 0
        and validation.evidence_verified
    )
