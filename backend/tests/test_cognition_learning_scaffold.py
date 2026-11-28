import pytest

from app.cognition.learning.contracts import EvaluationReport, FeedbackRecord, eligible_for_review


def test_candidate_review_gate():
    assert eligible_for_review(EvaluationReport("heldout", .5, .7, 20, 0, True))
    assert not eligible_for_review(EvaluationReport("training", .5, .7, 20, 0, False))
    assert not eligible_for_review(EvaluationReport("heldout", .5, .7, 20, 1, True))
    assert not eligible_for_review(EvaluationReport("heldout", .5, .7, 19, 0, True))
    assert not eligible_for_review(EvaluationReport("heldout", .5, .5, 20, 0, True))


def test_invalid_metrics_and_provenance():
    with pytest.raises(ValueError):
        EvaluationReport("heldout", float("nan"), .7, 20, 0, True)
    with pytest.raises(ValueError):
        FeedbackRecord("workspace", "task", "v1", (), False, "lesson")


@pytest.mark.parametrize("cases, regressions, held_out", [
    (20.5, 0, True), (20, False, True), (20, 0, "false"), (True, 0, True),
])
def test_noncanonical_evaluation_metrics(cases, regressions, held_out):
    with pytest.raises(ValueError):
        EvaluationReport("heldout", .5, .7, cases, regressions, held_out)


def test_feedback_rejects_mutable_or_duplicate_evidence():
    for refs in (["e1"], ("e1", "e1")):
        with pytest.raises(ValueError):
            FeedbackRecord("workspace", "task", "v1", refs, True, "lesson")
    with pytest.raises(ValueError):
        FeedbackRecord("workspace", "task", "v1", ("e1",), "false", "lesson")
    with pytest.raises(ValueError):
        eligible_for_review(EvaluationReport("heldout", .5, .7, 20, 0, True), True)
