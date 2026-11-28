"""Offline fixture assertions for already-authorized research outputs only."""
from dataclasses import dataclass

from .contracts import SkillCandidate, SkillValidation


@dataclass(frozen=True)
class OutputFixture:
    fixture_id: str
    expected: tuple[tuple[str, str], ...]
    actual: tuple[tuple[str, str], ...]
    evidence_verified: bool

    def __post_init__(self):
        if (not isinstance(self.fixture_id, str) or not self.fixture_id.strip()
                or type(self.evidence_verified) is not bool):
            raise ValueError("Invalid fixture identity or evidence flag")
        for values in (self.expected, self.actual):
            if (not isinstance(values, tuple) or len(values) > 100
                    or any(not isinstance(pair, tuple) or len(pair) != 2
                           or any(not isinstance(value, str) or len(value) > 4000 for value in pair)
                           or not pair[0].strip() for pair in values)
                    or len({pair[0] for pair in values}) != len(values)):
                raise ValueError("Invalid structured fixture output")
        if not self.expected:
            raise ValueError("Fixture requires expected output")

    def passed(self) -> bool:
        return self.evidence_verified and dict(self.expected) == dict(self.actual)


def validate_output_fixtures(candidate: SkillCandidate, fixtures: tuple[OutputFixture, ...],
                             expected_ids: tuple[str, ...]) -> SkillValidation:
    """Build a review artifact without running, approving or activating skills."""
    if (not isinstance(candidate, SkillCandidate)
            or not isinstance(fixtures, tuple) or not 1 <= len(fixtures) <= 1000
            or any(not isinstance(item, OutputFixture) for item in fixtures)
            or not isinstance(expected_ids, tuple)
            or any(not isinstance(key, str) or not key.strip() for key in expected_ids)):
        raise ValueError("Invalid fixture suite")
    ids = {fixture.fixture_id for fixture in fixtures}
    if len(ids) != len(fixtures) or len(ids) != len(expected_ids) or ids != set(expected_ids):
        raise ValueError("Fixture manifest mismatch")
    return SkillValidation(candidate.skill_id, candidate.version, len(fixtures),
                           sum(not fixture.passed() for fixture in fixtures),
                           all(fixture.evidence_verified for fixture in fixtures),
                           candidate.workspace_id, candidate.content_digest())
