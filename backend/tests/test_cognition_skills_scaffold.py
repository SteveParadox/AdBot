import pytest

from app.cognition.skills.contracts import (
    SkillCandidate, SkillOperation, SkillValidation, eligible_for_review,
)


def candidate():
    return SkillCandidate("catalog", 1, "workspace", "Summarize records", "task",
                          ("evidence",), (SkillOperation.EXTRACT_FIELDS,))


def test_versioned_review_gate():
    skill = candidate()
    assert eligible_for_review(skill, SkillValidation("catalog", 1, 3, 0, True))
    assert not eligible_for_review(skill, SkillValidation("catalog", 2, 3, 0, True))
    assert not eligible_for_review(skill, SkillValidation("catalog", 1, 3, 1, True))
    assert not eligible_for_review(skill, SkillValidation("catalog", 1, 3, 0, False))


def test_reject_untyped_operations():
    with pytest.raises(ValueError):
        SkillCandidate("catalog", 1, "workspace", "Summarize records", "task",
                       ("evidence",), ("arbitrary_code",))
