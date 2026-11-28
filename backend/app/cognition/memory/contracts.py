"""Storage and retrieval contracts; no runtime persistence or inference."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol


class MemoryKind(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    SPATIAL = "spatial"
    TEMPORAL = "temporal"
    REFLECTIVE = "reflective"


@dataclass(frozen=True)
class MemoryScope:
    workspace_id: str
    website_id: str

    def __post_init__(self):
        if any(not isinstance(value, str) or not value.strip() or value != value.strip()
               for value in (self.workspace_id, self.website_id)):
            raise ValueError("Memory requires an explicit workspace and website")


@dataclass(frozen=True)
class MemoryRecord:
    record_id: str
    scope: MemoryScope
    kind: MemoryKind
    summary: str
    source_task_id: str
    evidence_ids: tuple[str, ...]
    expires_at: datetime

    def __post_init__(self):
        if not isinstance(self.scope, MemoryScope) or not isinstance(self.kind, MemoryKind):
            raise ValueError("Invalid memory scope or kind")
        if any(not isinstance(value, str) or not value.strip()
               for value in (self.record_id, self.source_task_id, self.summary)):
            raise ValueError("Memory requires identity, provenance and summary")
        if (not isinstance(self.evidence_ids, tuple) or not self.evidence_ids
                or any(not isinstance(item, str) or not item.strip() for item in self.evidence_ids)
                or len(set(self.evidence_ids)) != len(self.evidence_ids)):
            raise ValueError("Memory requires evidence")
        if not isinstance(self.expires_at, datetime) or self.expires_at.utcoffset() is None:
            raise ValueError("Expiration must be timezone-aware")


@dataclass(frozen=True)
class RetrievalQuery:
    scope: MemoryScope
    objective: str
    limit: int = 3

    def __post_init__(self):
        if (not isinstance(self.scope, MemoryScope) or not isinstance(self.objective, str)
                or not self.objective.strip() or type(self.limit) is not int
                or not 1 <= self.limit <= 20):
            raise ValueError("Invalid retrieval query")


class MemoryStore(Protocol):
    async def save(self, record: MemoryRecord) -> None: ...
    async def candidates(self, query: RetrievalQuery) -> tuple[MemoryRecord, ...]: ...
    async def delete(self, scope: MemoryScope, record_id: str) -> None: ...


class EmbeddingProvider(Protocol):
    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]: ...


def eligible_records(query: RetrievalQuery, records: tuple[MemoryRecord, ...],
                     now: datetime) -> tuple[MemoryRecord, ...]:
    """Filter ranked candidates defensively; historical hints are not current evidence."""
    if now.utcoffset() is None:
        raise ValueError("Current time must be timezone-aware")
    seen: set[str] = set()
    eligible = []
    for record in records:
        if (not isinstance(record, MemoryRecord) or record.scope != query.scope
                or record.expires_at <= now or record.record_id in seen):
            continue
        seen.add(record.record_id)
        eligible.append(record)
        if len(eligible) == query.limit:
            break
    return tuple(eligible)
