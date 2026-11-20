import re
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .security import Policy, normalize


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TargetConfig(Strict):
    extraction_dataset_id: str | None = Field(None, max_length=36)
    max_pages: int = Field(10, ge=1, le=1000)
    max_depth: int = Field(2, ge=0, le=10)
    navigation_timeout_ms: int = Field(30000, ge=100, le=120000)
    delay_seconds: float = Field(2, ge=0.1, le=300)
    max_duration_seconds: int = Field(600, ge=5, le=3600)
    headless: bool = True
    viewport: Literal["desktop", "mobile"] = "desktop"
    browser: Literal["chromium", "firefox", "webkit"] = "chromium"
    screenshots: bool = False
    discover_links: bool = True
    scroll: bool = False
    respect_robots: bool = True
    retries: int = Field(2, ge=0, le=5)
    wait_until: Literal["domcontentloaded", "load", "networkidle"] = "domcontentloaded"
    wait_selector: str | None = Field(None, max_length=500)
    allowed_patterns: list[str] = Field(default_factory=lambda: ["*"], max_length=50)
    excluded_patterns: list[str] = Field(default_factory=list, max_length=50)


class WebsiteInput(Strict):
    name: str = Field(min_length=1, max_length=120)
    base_url: str
    allowed_domains: list[str] = Field(min_length=1, max_length=20)
    configuration: TargetConfig = Field(default_factory=TargetConfig)
    authorized: Literal[True]

    @field_validator("allowed_domains")
    @classmethod
    def domains(cls, domains):
        result = []
        for d in domains:
            d = d.strip().lower().rstrip(".")
            if not re.fullmatch(r"(?:\*\.)?[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", d) or ".." in d:
                raise ValueError("Use explicit DNS hostnames, with optional *. subdomain prefix")
            result.append(d)
        return list(dict.fromkeys(result))

    @model_validator(mode="after")
    def target(self):
        self.base_url = Policy(self.allowed_domains, self.configuration.model_dump()).check(self.base_url)
        return self


ActionName = Literal[
    "OPEN_URL",
    "WAIT",
    "WAIT_FOR_SELECTOR",
    "CLICK",
    "SCROLL",
    "EXTRACT_TEXT",
    "EXTRACT_LINKS",
    "SCREENSHOT",
    "ASSERT_VISIBLE",
    "ASSERT_TEXT",
    "NAVIGATE_BACK",
    "STOP",
]


class Action(Strict):
    action: ActionName
    selector: str | None = Field(None, min_length=1, max_length=500)
    url: str | None = None
    text: str | None = Field(None, max_length=2000)
    seconds: float = Field(1, ge=0, le=60)
    pixels: int = Field(600, ge=0, le=10000)
    timeout_ms: int = Field(10000, ge=100, le=60000)
    authorized: bool = False

    @model_validator(mode="after")
    def valid_action(self):
        if (
            self.action in {"CLICK", "WAIT_FOR_SELECTOR", "EXTRACT_TEXT", "ASSERT_VISIBLE", "ASSERT_TEXT"}
            and not self.selector
        ):
            raise ValueError("This action requires a selector")
        if self.action == "CLICK" and not self.authorized:
            raise ValueError("CLICK requires explicit authorization")
        if self.action == "OPEN_URL":
            if not self.url:
                raise ValueError("OPEN_URL requires url")
            self.url = normalize(self.url)
        if self.action == "ASSERT_TEXT" and self.text is None:
            raise ValueError("ASSERT_TEXT requires text")
        return self


class Definition(Strict):
    schema_version: Literal[1] = 1
    steps: list[Action] = Field(min_length=1, max_length=100)


class WorkflowInput(Strict):
    website_id: str
    name: str = Field(min_length=1, max_length=120)
    definition: Definition
    enabled: bool = True


class JobInput(Strict):
    priority: int = Field(0, ge=-10, le=10)
    depends_on: str | None = None
    website_id: str
    workflow_id: str | None = None


class ScheduleInput(Strict):
    website_id: str
    workflow_id: str | None = None
    cron_expression: str | None = Field(None, max_length=100)
    timezone: str = "UTC"
    run_at: datetime | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def valid_schedule(self):
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Use a valid IANA timezone") from exc
        if self.cron_expression:
            if len(self.cron_expression.split()) != 5 or not croniter.is_valid(self.cron_expression):
                raise ValueError("Use a valid five-field cron expression")
        elif not self.run_at or self.run_at.utcoffset() is None:
            raise ValueError("One-time schedules require a timezone-aware run_at")
        return self


class SchedulePatch(Strict):
    enabled: bool | None = None
    cron_expression: str | None = None
    timezone: str | None = None
    run_at: datetime | None = None
