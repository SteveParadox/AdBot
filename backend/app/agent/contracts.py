from typing import Literal

from pydantic import Field, model_validator

from ..schemas import Strict
from .structure import RecordCapture


class Target(Strict):
    element_id: str = Field(max_length=20)


class Claim(Strict):
    text: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)


class Decision(Strict):
    observation: str = Field(
        min_length=1, max_length=1000, description="Brief observation summary, not a copy of the page."
    )
    decision: Literal[
        "NAVIGATE",
        "OBSERVE",
        "CLICK",
        "HOVER",
        "FOCUS",
        "PRESS_KEY",
        "SELECT_OPTION",
        "SET_CHECKED",
        "SCROLL_BACK",
        "TYPE",
        "SCROLL",
        "SEARCH",
        "OPEN_TAB",
        "SWITCH_TAB",
        "CLOSE_TAB",
        "GO_BACK",
        "WAIT",
        "EXTRACT",
        "CAPTURE_RECORDS",
        "SUMMARIZE",
        "ASK_USER",
        "COMPLETE",
        "FAIL",
        "DOWNLOAD",
        "EXTRACT_DATASET",
        "EXPORT_DATASET",
    ]
    target: Target | None = None
    subtask_id: str | None = Field(None, max_length=32)
    url: str | None = Field(None, max_length=1800)
    text: str | None = Field(
        None,
        max_length=4000,
        description="For EXTRACT, an excerpt or paraphrase about observed content. Supply source_quote when known. Also required for TYPE, SEARCH, ASK_USER and FAIL.",
    )
    source_quote: str | None = Field(None, min_length=1, max_length=4000,
                                     description="For EXTRACT paraphrases, observed source text supporting the paraphrase.")
    tab_id: str | None = Field(None, max_length=36)
    reason: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(ge=0, le=1)
    expected_result: str = Field(min_length=1, max_length=1000)
    claims: list[Claim] = Field(
        default_factory=list,
        max_length=30,
        description="Required for COMPLETE or SUMMARIZE only. Cite existing evidence_ids from session_memory.evidence. EXTRACT must use text instead of claims.",
    )
    direction: Literal["down", "up"] = "down"

    key: (
        Literal[
            "Tab",
            "Shift+Tab",
            "ArrowDown",
            "ArrowUp",
            "ArrowLeft",
            "ArrowRight",
            "Escape",
            "PageDown",
            "PageUp",
            "Home",
            "End",
            "Enter",
            "Space",
        ]
        | None
    ) = None
    input_method: Literal["auto", "keyboard"] = "auto"
    expected_text: str | None = Field(None, min_length=1, max_length=1000)
    checked: bool | None = None
    option: str | None = Field(
        None, min_length=1, max_length=200, description="Exact observed native option label or value; never invented."
    )
    capture: RecordCapture | None = None

    @model_validator(mode="after")
    def parameters(self):
        if self.source_quote is not None and self.decision != "EXTRACT":
            raise ValueError("source_quote is only supported for EXTRACT")
        if (self.decision == "CAPTURE_RECORDS") != (self.capture is not None):
            raise ValueError("Only CAPTURE_RECORDS accepts an observed group and field mapping")
        if (
            self.decision in {"CLICK", "TYPE", "SEARCH", "DOWNLOAD", "HOVER", "FOCUS", "SELECT_OPTION", "SET_CHECKED"}
            and self.target is None
        ):
            raise ValueError("This action requires an observed element_id")
        if self.decision in {"TYPE", "SEARCH", "EXTRACT", "ASK_USER", "FAIL"} and not self.text:
            raise ValueError("This action requires text")
        if self.decision in {"NAVIGATE", "OPEN_TAB"} and not self.url:
            raise ValueError("Navigation requires a URL")
        if self.decision in {"SWITCH_TAB", "CLOSE_TAB"} and not self.tab_id:
            raise ValueError("Tab action requires tab_id")
        if self.decision == "PRESS_KEY" and not self.key:
            raise ValueError("PRESS_KEY requires a permitted navigation key")
        if self.decision == "SELECT_OPTION" and self.option is None:
            raise ValueError("SELECT_OPTION requires an observed option")
        if self.decision == "SET_CHECKED" and self.checked is None:
            raise ValueError("SET_CHECKED requires the intended checked state")
        if self.decision == "COMPLETE" and not self.claims:
            raise ValueError("Completion requires claims with evidence citations")
        return self


class Criterion(Strict):
    criterion: str = Field(description="Copy one supplied success criterion exactly.")
    met: bool = Field(description="True only when the cited evidence supports this criterion.")
    evidence_ids: list[str] = Field(
        default_factory=list, description="Actual identifiers of the supporting supplied evidence records."
    )


class Verification(Strict):
    checks: list[Criterion] = Field(min_length=1, max_length=60)
    explanation: str = Field(
        max_length=2000, description="One brief sentence summarizing the checks. Do not narrate your analysis."
    )
    complete: bool = Field(description="True only if every check is met with supporting evidence; otherwise false.")


from ..extraction.query import DatasetQuery  # noqa: E402


class TaskInput(Strict):
    website_id: str
    priority: int = Field(0, ge=-10, le=10)
    depends_on: str | None = Field(None, max_length=36)
    objective: str = Field(min_length=8, max_length=4000)
    success_criteria: list[str] = Field(default_factory=list, max_length=20)
    mode: Literal["assisted", "autonomous", "supervised"] = "supervised"
    max_steps: int = Field(500, ge=1, le=500)
    max_tokens: int = Field(60000, ge=2000, le=1000000)
    memory_enabled: bool = True
    visual_reasoning: bool = False
    session_persistence: bool = False
    allow_form_input: bool = False
    allow_search_input: bool = True
    allow_downloads: bool = False
    dataset_id: str | None = Field(None, max_length=36)
    output_format: Literal["answer", "json", "csv"] | None = None
    dataset_query: DatasetQuery | None = None

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
