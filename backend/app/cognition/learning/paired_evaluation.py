"""Offline comparison of independently verified public report fixture outcomes."""
from dataclasses import dataclass
from hashlib import sha256
import json

from .contracts import EvaluationReport


@dataclass(frozen=True)
class FixtureOutcome:
    fixture_id: str
    baseline_passed: bool
    candidate_passed: bool

    def __post_init__(self):
        if (not isinstance(self.fixture_id, str) or not self.fixture_id.strip()
                or type(self.baseline_passed) is not bool
                or type(self.candidate_passed) is not bool):
            raise ValueError("Invalid fixture outcome")


@dataclass(frozen=True)
class PairedReport:
    report: EvaluationReport
    fixture_digest: str
    improved_ids: tuple[str, ...]
    regressed_ids: tuple[str, ...]


def compare_fixture_outcomes(suite_id: str, expected_ids: tuple[str, ...],
                             outcomes: tuple[FixtureOutcome, ...], *,
                             held_out: bool) -> PairedReport:
    """Derive metrics from the same fixed fixture IDs; no model or policy update."""
    if (not isinstance(expected_ids, tuple) or not 1 <= len(expected_ids) <= 10000
            or any(not isinstance(key, str) or not key.strip() for key in expected_ids)
            or len(set(expected_ids)) != len(expected_ids)):
        raise ValueError("Invalid fixture manifest")
    if (not isinstance(outcomes, tuple) or len(outcomes) != len(expected_ids)
            or any(not isinstance(row, FixtureOutcome) for row in outcomes)):
        raise ValueError("Invalid paired outcomes")
    by_id = {row.fixture_id: row for row in outcomes}
    if set(by_id) != set(expected_ids) or len(by_id) != len(outcomes):
        raise ValueError("Missing, duplicate or unexpected fixture")
    rows = tuple(by_id[key] for key in sorted(expected_ids))
    improved = tuple(row.fixture_id for row in rows if not row.baseline_passed and row.candidate_passed)
    regressed = tuple(row.fixture_id for row in rows if row.baseline_passed and not row.candidate_passed)
    total = len(rows)
    report = EvaluationReport(suite_id, sum(row.baseline_passed for row in rows) / total,
                              sum(row.candidate_passed for row in rows) / total,
                              total, len(regressed), held_out)
    manifest = json.dumps(sorted(expected_ids), ensure_ascii=True, separators=(",", ":"))
    return PairedReport(report, sha256(manifest.encode()).hexdigest(), improved, regressed)
