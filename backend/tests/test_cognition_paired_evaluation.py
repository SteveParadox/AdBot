import pytest

from app.cognition.learning.paired_evaluation import FixtureOutcome, compare_fixture_outcomes


def test_paired_metrics_do_not_hide_regression():
    rows = (FixtureOutcome("a", True, False), FixtureOutcome("b", False, True),
            FixtureOutcome("c", False, True))
    result = compare_fixture_outcomes("suite", ("a", "b", "c"), rows, held_out=True)
    assert result.report.regressions == 1
    assert result.report.baseline_success == 1 / 3
    assert result.report.candidate_success == 2 / 3
    assert result.improved_ids == ("b", "c")
    assert result.regressed_ids == ("a",)
    reversed_result = compare_fixture_outcomes("suite", ("c", "b", "a"),
                                               rows[::-1], held_out=True)
    assert result == reversed_result
    with pytest.raises(ValueError):
        compare_fixture_outcomes("suite", ("a", "b", "c"), rows[:2], held_out=True)
    with pytest.raises(ValueError):
        compare_fixture_outcomes("suite", ("a", "b", "c"), (rows[0], rows[0], rows[2]),
                                 held_out=True)
