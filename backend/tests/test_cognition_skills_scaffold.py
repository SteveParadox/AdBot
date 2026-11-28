import pytest

from app.cognition.skills.contracts import (
    SkillCandidate, SkillOperation, SkillValidation, eligible_for_review,
)


def candidate():
    return SkillCandidate("catalog", 1, "workspace", "Summarize records", "task",
                          ("evidence",), (SkillOperation.EXTRACT_FIELDS,))


def test_versioned_review_gate():
    skill = candidate()
    assert eligible_for_review(skill, SkillValidation("catalog", 1, 3, 0, True,
                                                     skill.workspace_id, skill.content_digest()))
    assert not eligible_for_review(skill, SkillValidation("catalog", 2, 3, 0, True,
                                                         skill.workspace_id, skill.content_digest()))
    assert not eligible_for_review(skill, SkillValidation("catalog", 1, 3, 1, True,
                                                         skill.workspace_id, skill.content_digest()))
    assert not eligible_for_review(skill, SkillValidation("catalog", 1, 3, 0, False,
                                                         skill.workspace_id, skill.content_digest()))


def test_reject_untyped_operations():
    with pytest.raises(ValueError):
        SkillCandidate("catalog", 1, "workspace", "Summarize records", "task",
                       ("evidence",), ("arbitrary_code",))


def test_review_cannot_be_reused_across_workspaces_or_changed_content():
    from dataclasses import replace

    skill = candidate()
    validation = SkillValidation("catalog", 1, 3, 0, True,
                                 skill.workspace_id, skill.content_digest())
    assert not eligible_for_review(replace(skill, workspace_id="other"), validation)
    assert not eligible_for_review(replace(skill, objective="Different objective"), validation)
    assert not eligible_for_review(skill, SkillValidation("catalog", 1, 3, 0, True))
    with pytest.raises(ValueError):
        replace(skill, operations=[SkillOperation.EXTRACT_FIELDS])
    with pytest.raises(ValueError):
        SkillValidation("catalog", 1, 3, 0, "false")
