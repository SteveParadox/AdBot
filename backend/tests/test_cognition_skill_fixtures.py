import pytest

from app.cognition.skills.contracts import SkillCandidate, SkillOperation, eligible_for_review
from app.cognition.skills.fixtures import OutputFixture, validate_output_fixtures


def test_fixture_review_requires_exact_output_and_complete_manifest():
    candidate = SkillCandidate("report", 1, "workspace", "extract public facts", "task",
                               ("evidence",), (SkillOperation.EXTRACT_FIELDS,))
    fixtures = tuple(OutputFixture(str(i), (("title", "public report"),),
                                   (("title", "public report"),), True) for i in range(3))
    ids = ("0", "1", "2")
    report = validate_output_fixtures(candidate, fixtures, ids)
    assert eligible_for_review(candidate, report)
    failed = OutputFixture("2", (("title", "public report"),),
                           (("title", "wrong"),), True)
    assert not eligible_for_review(candidate, validate_output_fixtures(candidate, fixtures[:2] + (failed,), ids))
    with pytest.raises(ValueError):
        validate_output_fixtures(candidate, fixtures[:2], ids)
    with pytest.raises(ValueError):
        OutputFixture("x", (("field", "a"), ("field", "b")), (), True)
