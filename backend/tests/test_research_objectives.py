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
