"""Regression cases for domain-independent research routing."""
from app.research.contracts import Mode, Question, route
from app.research.objectives import comparison_subjects


def test_comparison_subjects():
    assert comparison_subjects("Compare PostgreSQL and Cassandra for high-throughput applications") == ["PostgreSQL", "Cassandra"]
    assert comparison_subjects("Redis vs Memcached") == ["Redis", "Memcached"]
    assert not comparison_subjects("Explain Redis")


def test_explicit_modes_take_precedence():
    assert route(Question(question="What is cataclysm?", mode=Mode.QUICK), []) == ("general", Mode.QUICK)
    assert route(Question(question="Compare Redis and Memcached", mode=Mode.TECHNICAL), []) == ("technical", Mode.TECHNICAL)



def test_relative_day_respects_local_offset():
    from datetime import datetime, timezone
    from app.research.objectives import dated_query, relative_date

    at = datetime(2026, 11, 27, 23, 30, tzinfo=timezone.utc).timestamp()
    assert relative_date("fixtures today", at, 60) == "2026-11-28"
    assert relative_date("fixtures tomorrow", at, -60) == "2026-11-28"
    assert relative_date("today and tomorrow", at, 60) is None
    assert dated_query("fixtures today", "2026-11-28") == "fixtures 2026-11-28"


def test_short_table_rows_preserve_context():
    from lxml import html
    from app.research.retrieval import html_observations

    tree = html.fromstring("""<table><caption>League fixtures</caption>
        <thead><tr><th>Home</th><th>Away</th><th>Kickoff</th></tr></thead>
        <tbody><tr><td>A FC</td><td>B FC</td><td><time datetime="2026-11-27T20:00:00Z">20:00</time></td></tr>
        <tr hidden><td>Hidden</td><td>Row</td></tr></tbody></table>""")
    rows = html_observations(tree)
    assert len(rows) == 1
    assert "Home: A FC" in rows[0] and "Away: B FC" in rows[0]
    assert "2026-11-27T20:00:00Z" in rows[0]


async def test_retry_uses_alternative_queries():
    import asyncio
    import time
    from datetime import datetime, timezone
    from app.research.contracts import budget_for
    from app.research.service import Research

    question = Question(question="fixtures today", mode=Mode.QUICK, utc_offset_minutes=60)
    gate = asyncio.Event()
    gate.set()

    async def emit(*args, **kwargs):
        pass

    at = datetime(2026, 11, 27, 23, 30, tzinfo=timezone.utc).timestamp()
    engine = Research("test", question, Mode.QUICK, "current", budget_for(Mode.QUICK),
                      time.monotonic() + 45, [], emit, gate, model=object(),
                      reference_at=at, prior_queries=["fixtures 2026-11-28", "fixtures 2026-11-28 official source"])
    queries = await engine.plan(0)
    assert queries and all("2026-11-28" in query for query in queries)
    assert not set(queries) & engine.prior_queries
