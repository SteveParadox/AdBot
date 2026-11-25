"""Bounded subquestion planning and evidence-based deep research coverage."""

from dataclasses import dataclass, field

from pydantic import Field

from .contracts import Strict


class GapCheck(Strict):
    question_id: str = Field(min_length=1, max_length=16)
    status: str = Field(pattern=r"^(covered|partial|missing|conflicting)$")
    evidence: list[str] = Field(default_factory=list, max_length=4)


class Coverage(Strict):
    checks: list[GapCheck] = Field(max_length=5)


def normalize(text):
    return " ".join(text.split()).casefold()


@dataclass
class Subquestion:
    id: str
    question: str
    status: str = "missing"
    evidence: list[str] = field(default_factory=list)
    searches: int = 0


class GapPlan:
    def __init__(self, objective, gaps=()):
        self.questions = []
        seen = set()
        for text in (objective, *gaps):
            text = " ".join(text.split())[:1400 if not self.questions else 240]
            key = normalize(text)
            if not key or key in seen:
                continue
            seen.add(key)
            self.questions.append(Subquestion(f"q{len(self.questions) + 1}", text))
            if len(self.questions) == 5:
                break

    def pending(self):
        return sorted(
            (q for q in self.questions if q.status != "covered"),
            key=lambda q: (q.searches, q.status != "conflicting"),
        )

    def complete(self):
        return bool(self.questions) and not self.pending()

    def snapshot(self):
        return [{"id": q.id, "question": q.question, "status": q.status,
                 "evidence": list(q.evidence), "searches": q.searches} for q in self.questions]

    def apply(self, assessment, offered, sources, evidence):
        """Fail closed for absent/duplicate checks, unknown IDs and unsupported conflicts."""
        checks = {}
        for check in assessment.checks if assessment else ():
            checks[check.question_id] = None if check.question_id in checks else check
        for q in self.questions:
            q.status, q.evidence = "missing", []
            check = checks.get(q.id)
            if not check or check.status == "missing":
                continue
            ids = list(dict.fromkeys(check.evidence))
            if not ids or len(ids) != len(check.evidence):
                continue
            if any(i not in offered or i not in evidence or evidence[i]["source_id"] not in sources for i in ids):
                continue
            groups = {sources[evidence[i]["source_id"]]["independence_group"] for i in ids}
            if check.status == "conflicting" and len(groups) < 2:
                continue
            q.status, q.evidence = check.status, ids

    def unanswered(self, claims):
        """A covered research question must also have support used in the final answer."""
        cited = {i for claim in claims if claim["kind"] != "excerpt" for i in claim["evidence"]}
        return [q for q in self.questions if q.status != "covered" or not cited.intersection(q.evidence)]
