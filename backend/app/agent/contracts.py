from typing import Literal

from pydantic import Field, model_validator

from ..schemas import Strict


class Target(Strict):
    element_id: str = Field(max_length=20)


class Claim(Strict):
    text: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)


class Decision(Strict):
    observation: str = Field(min_length=1, max_length=1000)
    decision: Literal[
        "NAVIGATE",
        "OBSERVE",
        "CLICK",
        "TYPE",
        "SCROLL",
        "SEARCH",
        "OPEN_TAB",
        "SWITCH_TAB",
        "CLOSE_TAB",
        "GO_BACK",
        "WAIT",
        "EXTRACT",
        "SUMMARIZE",
        "ASK_USER",
        "COMPLETE",
        "FAIL",
        "DOWNLOAD",
    ]
    target: Target | None = None
    url: str | None = Field(None, max_length=1800)
    text: str | None = Field(None, max_length=4000)
    tab_id: str | None = Field(None, max_length=36)
    reason: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(ge=0, le=1)
    expected_result: str = Field(min_length=1, max_length=1000)
    claims: list[Claim] = Field(default_factory=list, max_length=30)
    direction: Literal["down", "up"] = "down"

    @model_validator(mode="after")
    def parameters(self):
        if self.decision in {"CLICK", "TYPE", "SEARCH", "DOWNLOAD"} and self.target is None:
            raise ValueError("This action requires an observed element_id")
        if self.decision in {"TYPE", "SEARCH", "EXTRACT", "ASK_USER", "FAIL"} and not self.text:
            raise ValueError("This action requires text")
        if self.decision in {"NAVIGATE", "OPEN_TAB"} and not self.url:
            raise ValueError("Navigation requires a URL")
        if self.decision in {"SWITCH_TAB", "CLOSE_TAB"} and not self.tab_id:
            raise ValueError("Tab action requires tab_id")
        if self.decision == "COMPLETE" and not self.claims:
            raise ValueError("Completion requires claims with evidence citations")
        return self


class Criterion(Strict):
    criterion: str
    met: bool
    evidence_ids: list[str] = Field(default_factory=list)


class Verification(Strict):
    complete: bool
    explanation: str = Field(max_length=2000)
    checks: list[Criterion] = Field(min_length=1, max_length=20)


class TaskInput(Strict):
    website_id: str
    objective: str = Field(min_length=8, max_length=4000)
    success_criteria: list[str] = Field(default_factory=list, max_length=20)
    mode: Literal["assisted", "autonomous", "supervised"] = "supervised"
    max_steps: int = Field(30, ge=1, le=100)
    max_tokens: int = Field(60000, ge=2000, le=1000000)
    memory_enabled: bool = True
    visual_reasoning: bool = False
    session_persistence: bool = False
    allow_form_input: bool = False
    allow_downloads: bool = False

    @model_validator(mode="after")
    def criteria(self):
        if any(not s.strip() or len(s) > 1000 for s in self.success_criteria):
            raise ValueError("Success criteria must be nonempty and at most 1000 characters")
        if not self.success_criteria:
            self.success_criteria = [self.objective]
        return self


class ReviewInput(Strict):
    step_id: int
    approved: bool
    answer: str = Field("", max_length=4000)
