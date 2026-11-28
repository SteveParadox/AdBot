"""Bounded reference store for explicitly supplied, redacted research records.

Inspired by LangGraph's namespace and TTL contracts. Not wired to agents;
callers must authenticate scope and verify provenance before submission.
"""
from datetime import datetime
from threading import RLock
import re

from .contracts import MemoryRecord, MemoryScope, RetrievalQuery, eligible_records


def _terms(text: str) -> set[str]:
    return set(re.findall(r"[^\W_]+", text.casefold(), re.UNICODE))


class ResearchMemoryStore:
    """Process-local reference adapter; no durable storage or network access."""

    def __init__(self, clock, capacity: int = 1000):
        if type(capacity) is not int or not 1 <= capacity <= 10000:
            raise ValueError("Invalid memory capacity")
        self._clock = clock
        self._capacity = capacity
        self._records: dict[tuple[MemoryScope, str], MemoryRecord] = {}
        self._lock = RLock()

    def _now(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime) or now.utcoffset() is None:
            raise ValueError("Clock must be timezone-aware")
        return now

    def _purge(self, now: datetime) -> int:
        expired = [key for key, record in self._records.items() if record.expires_at <= now]
        for key in expired:
            del self._records[key]
        return len(expired)

    async def save(self, record: MemoryRecord) -> None:
        if not isinstance(record, MemoryRecord) or len(record.summary) > 4000:
            raise ValueError("Invalid research record")
        with self._lock:
            now = self._now()
            self._purge(now)
            if record.expires_at <= now:
                raise ValueError("Expired research record")
            key = (record.scope, record.record_id)
            previous = self._records.get(key)
            if previous is not None and previous != record:
                raise ValueError("Conflicting record identity")
            if previous is None and len(self._records) >= self._capacity:
                raise OverflowError("Research memory capacity exhausted")
            self._records[key] = record

    async def candidates(self, query: RetrievalQuery) -> tuple[MemoryRecord, ...]:
        if not isinstance(query, RetrievalQuery) or len(query.objective) > 4000:
            raise ValueError("Invalid research query")
        with self._lock:
            now = self._now()
            self._purge(now)
            terms = _terms(query.objective)
            ranked = []
            for (scope, _), record in self._records.items():
                if scope != query.scope:
                    continue
                score = len(terms & _terms(record.summary))
                if score:
                    ranked.append((score, record))
            ranked.sort(key=lambda pair: (-pair[0], pair[1].record_id))
            return eligible_records(query, tuple(record for _, record in ranked), now)

    async def delete(self, scope: MemoryScope, record_id: str) -> None:
        with self._lock:
            self._records.pop((scope, record_id), None)

    async def purge_expired(self) -> int:
        with self._lock:
            return self._purge(self._now())
