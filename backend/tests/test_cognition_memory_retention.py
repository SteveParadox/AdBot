import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.cognition.memory.contracts import MemoryKind, MemoryRecord, MemoryScope, RetrievalQuery
from app.cognition.memory.retention import ResearchMemoryStore


def test_retention_scope_and_capacity():
    async def run():
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        clock = [now]
        store = ResearchMemoryStore(lambda: clock[0], capacity=2)
        scope = MemoryScope("w", "site")
        other = MemoryScope("other", "site")

        def record(owner, summary):
            return MemoryRecord("id", owner, MemoryKind.SEMANTIC, summary, "task",
                                ("evidence",), now + timedelta(hours=1))

        original = record(scope, "public documentation for Python")
        await store.save(original)
        await store.save(original)
        await store.save(record(other, "Python documentation"))
        assert await store.candidates(RetrievalQuery(scope, "Python")) == (original,)
        assert await store.candidates(RetrievalQuery(scope, "unrelated")) == ()
        with pytest.raises(ValueError):
            await store.save(record(scope, "conflicting"))
        with pytest.raises(OverflowError):
            await store.save(record(MemoryScope("third", "site"), "Python"))
        await store.delete(other, "id")
        assert await store.candidates(RetrievalQuery(scope, "Python")) == (original,)
        clock[0] += timedelta(hours=1)
        assert await store.purge_expired() == 1
        assert await store.candidates(RetrievalQuery(scope, "Python")) == ()

    asyncio.run(run())
