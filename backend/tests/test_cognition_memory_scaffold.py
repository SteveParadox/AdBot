from datetime import datetime, timedelta, timezone

import pytest

from app.cognition.memory.contracts import (
    MemoryKind, MemoryRecord, MemoryScope, RetrievalQuery, eligible_records,
)


def test_scope_expiration_and_deduplication():
    now = datetime.now(timezone.utc)
    scope = MemoryScope("workspace", "website")

    def record(identity, owner, expires):
        return MemoryRecord(identity, owner, MemoryKind.EPISODIC, "summary",
                            "task", ("evidence",), expires)

    good = record("good", scope, now + timedelta(days=1))
    foreign = record("foreign", MemoryScope("other", "website"), now + timedelta(days=1))
    expired = record("expired", scope, now)
    assert eligible_records(RetrievalQuery(scope, "question"), (foreign, expired, good, good), now) == (good,)


def test_query_validation():
    with pytest.raises(ValueError):
        RetrievalQuery(MemoryScope("workspace", "website"), "question", 21)
    with pytest.raises(ValueError):
        MemoryScope("", "website")


def test_malformed_memory_inputs_fail_closed():
    scope = MemoryScope("workspace", "website")
    now = datetime.now(timezone.utc)
    for evidence in (["evidence"], ("evidence", "evidence"), ("",)):
        with pytest.raises(ValueError):
            MemoryRecord("id", scope, MemoryKind.EPISODIC, "summary", "task", evidence, now)
    with pytest.raises(ValueError):
        MemoryRecord("id", scope, "episodic", "summary", "task", ("evidence",), now)
    with pytest.raises(ValueError):
        RetrievalQuery(scope, "question", True)
    with pytest.raises(ValueError):
        MemoryScope("workspace ", "website")
