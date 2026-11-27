"""Public research arguments and deliberately small model response contracts."""

import re
from enum import StrEnum

import pycountry
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..config import ResearchBudget, settings


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Mode(StrEnum):
    AUTO = "auto"
    DIRECT = "direct"
    QUICK = "quick"
    DEEP = "deep"
    SHOPPING = "shopping"
    FACT_CHECK = "fact_check"
    TECHNICAL = "technical"


DEFAULTS = {
    Mode.DIRECT: ResearchBudget(seconds=45, requests=0, pages=0, rounds=0, calls=3, tokens=12000, browsers=0),
    Mode.QUICK: ResearchBudget(seconds=45, requests=4, pages=5, rounds=1, calls=4, tokens=22000, browsers=1),
    Mode.DEEP: ResearchBudget(seconds=220, requests=18, pages=24, rounds=4, calls=11, tokens=75000, browsers=4),
    Mode.SHOPPING: ResearchBudget(seconds=100, requests=12, pages=14, rounds=2, calls=7, tokens=48000, browsers=3),
    Mode.FACT_CHECK: ResearchBudget(seconds=85, requests=10, pages=12, rounds=2, calls=7, tokens=46000, browsers=2),
    Mode.TECHNICAL: ResearchBudget(seconds=80, requests=9, pages=12, rounds=2, calls=7, tokens=44000, browsers=2),
}


def budget_for(mode):
    return settings().research_budgets.get(mode, DEFAULTS[mode])


from .objectives import comparison_request, definition_request


class Question(Strict):
    question: str = Field(min_length=2, max_length=1400)
    mode: Mode = Mode.AUTO
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    freshness: str | None = Field(default=None, pattern=r"^(day|week|month|year)$")
    conversation_id: str | None = Field(default=None, min_length=36, max_length=36)


    @field_validator("country")
    @classmethod
    def supported_country(cls, value):
        if value and not pycountry.countries.get(alpha_2=value):
            raise ValueError("Use an ISO 3166-1 alpha-2 country code")
        return value


class Plan(Strict):
    queries: list[str] = Field(max_length=5)
    gaps: list[str] = Field(default_factory=list, max_length=4)


class RelevanceRating(Strict):
    candidate: int = Field(ge=0, le=11)
    relevance: int = Field(ge=0, le=4)


class RelevanceRatings(Strict):
    ratings: list[RelevanceRating] = Field(max_length=12)


class Claim(Strict):
    text: str = Field(min_length=2, max_length=520)
    kind: str = Field(pattern=r"^(fact|inference|recommendation|conflict)$")
    evidence: list[str] = Field(min_length=1, max_length=4)


class Summary(Strict):
    claims: list[Claim] = Field(max_length=14)
    limitations: list[str] = Field(default_factory=list, max_length=4)


class Support(Strict):
    claim: int = Field(ge=0, le=13)
    status: str = Field(pattern=r"^(supported|partial|unsupported|conflicting)$")
    evidence: list[str] = Field(default_factory=list, max_length=4)


class Verification(Strict):
    checks: list[Support] = Field(max_length=14)


class Direct(Strict):
    answer: str = Field(min_length=2, max_length=5000)


INTENTS = [
    ("website_specific", r"https?://|\bsite:"),
    ("deep_research", r"\b(deep research|comprehensive report|literature review)\b"),
    ("fact_check", r"\b(fact.?check|verify|is (it|this|that) true|debunk)\b"),
    ("product_comparison", r"\b(compare|versus|vs)\b.*\b(products?|laptops?|phones?|retailers?|prices?|models?)\b"),
    ("product_discovery", r"₦|\b(buy|shops?|shopping|affordable|cheapest|retailers?|under [\$£€\d]|best (laptops?|phones?|monitors?))\b"),
    ("academic", r"\b(studies|papers|peer.reviewed|academic|systematic review|arxiv)\b"),
    ("documentation", r"\b(documentation|docs|release notes|api reference)\b"),
    ("financial", r"\b(stock price|market cap|exchange rate|inflation|interest rates?|earnings)\b"),
    ("news", r"\b(news|breaking|headlines)\b"),
    ("local", r"\b(near me|opening hours|local events|restaurants? in|weather in)\b"),
    ("current", r"\b(current|latest|today|tomorrow|yesterday|tonight|recent|recently|this (year|week|month))\b"),
    ("technical", r"\b(technical|open.source|github|benchmark|compare|research)\b"),
]


def route(question, history):
    text = question.question.casefold()
    from .memory import followup as is_followup, relevant_turns

    followup = is_followup(text, history)
    intent = next((name for name, regex in INTENTS if re.search(regex, text)), "general")
    if followup:
        intent = "follow_up"
    if question.mode != Mode.AUTO:
        return intent, question.mode
    if intent == "follow_up":
        if re.search(r"\b(verify|fact.?check)\b", text):
            return intent, Mode.FACT_CHECK
        anchor = relevant_turns(text, history)[0]
        return intent, Mode(anchor["mode"]) if anchor["mode"] != Mode.DIRECT else Mode.QUICK
    mapping = {
        "deep_research": Mode.DEEP, "fact_check": Mode.FACT_CHECK, "product_comparison": Mode.SHOPPING,
        "product_discovery": Mode.SHOPPING, "technical": Mode.TECHNICAL, "documentation": Mode.TECHNICAL,
    }
    direct = re.match(
        r"^(hello|hi|hey)[!. ]*$|^(write|draft|translate|rewrite|summarize|brainstorm|solve)\b"
        r"|^(what is|calculate)\s+[\d+*/(). -]+\??$|^(explain|define|what is)\s+(a |an |the )?"
        r"(python (tuple|list|dictionary)s?|recursion|gravity|photosynthesis|a prime number)\b", text
    )
    if intent == "general" and (direct or definition_request(question.question)) and not question.freshness and not question.country:
        return intent, Mode.DIRECT
    if intent in {"general", "technical", "documentation"} and comparison_request(question.question):
        return intent, Mode.DEEP
    return intent, mapping.get(intent, Mode.QUICK)
