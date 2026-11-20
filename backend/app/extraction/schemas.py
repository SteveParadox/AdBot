import json
import re
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def bounded_json(value, maximum=65536):
    def visit(item, depth=0):
        if depth > 8:
            raise ValueError("Structured value exceeds nesting limit")
        if isinstance(item, dict):
            if len(item) > 100:
                raise ValueError("Too many object fields")
            for child in item.values():
                visit(child, depth + 1)
        elif isinstance(item, list):
            if len(item) > 100:
                raise ValueError("Too many list elements")
            for child in item:
                visit(child, depth + 1)

    visit(value)
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > maximum:
        raise ValueError("Structured value exceeds size limit")
    return value


class FieldRule(Strict):
    type: Literal[
        "string", "integer", "decimal", "boolean", "date", "datetime", "url", "currency", "list", "object"
    ] = "string"
    required: bool = False
    nullable: bool = True
    method: Literal["css", "xpath", "jsonld", "meta", "source_url", "page_title", "ai"] = "css"
    selector: str = Field("", max_length=500)
    attribute: str | None = Field(None, pattern=r"^[a-zA-Z][a-zA-Z0-9_:.-]{0,63}$")
    path: str = Field("", max_length=300, pattern=r"^[A-Za-z0-9_@.\-]*$")
    multiple: bool = False
    max_length: int = Field(10000, ge=1, le=20000)
    transformations: list[Literal["lower", "upper", "currency_code"]] = Field(default_factory=list, max_length=5)
    decimal_separator: Literal[".", ","] = "."
    date_format: str | None = Field(None, max_length=80)
    minimum: float | None = Field(None, allow_inf_nan=False)
    maximum: float | None = Field(None, allow_inf_nan=False)
    choices: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def safe(self):
        if self.method in {"css", "xpath", "meta"} and not self.selector:
            raise ValueError("A selector or metadata name is required")
        if self.method == "xpath" and (not self.selector.startswith(("/", "./")) or "|" in self.selector):
            raise ValueError("Use a bounded element XPath, without unions")
        if self.method == "xpath" and (
            self.selector.count("[") > 8
            or re.search(
                r"\b(?:preceding|following|ancestor)::|\b(?:count|sum|translate|substring|string-length)\s*\(",
                self.selector,
            )
        ):
            raise ValueError("Expensive XPath axes/functions are not supported")
        return self


class SchemaDefinition(Strict):
    name: str = Field(min_length=1, max_length=120)
    version: int = Field(1, ge=1, le=1000000)
    fields: dict[str, FieldRule] = Field(min_length=1, max_length=50)
    record_selector: str | None = Field(None, max_length=500)
    record_method: Literal["css", "xpath", "jsonld"] = "css"
    jsonld_type: str | None = Field(None, pattern=r"^[A-Za-z]{1,80}$")
    identity_fields: list[str] = Field(default_factory=list, max_length=10)
    ignored_change_fields: list[str] = Field(default_factory=list, max_length=50)
    timezone: str = "UTC"
    ai_instructions: str = Field("", max_length=2000)

    @model_validator(mode="after")
    def safe(self):
        for name in self.fields:
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name):
                raise ValueError("Use simple field names")
        if set(self.identity_fields + self.ignored_change_fields) - self.fields.keys():
            raise ValueError("Identity/change fields must exist in the schema")
        if set(self.identity_fields) & set(self.ignored_change_fields):
            raise ValueError("Identity fields cannot be ignored for change detection")
        if self.record_selector and self.record_method == "xpath" and not self.record_selector.startswith(("/", "./")):
            raise ValueError("Invalid record XPath")
        if self.record_selector and self.record_method == "xpath":
            FieldRule(method="xpath", selector=self.record_selector)
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Use a valid IANA timezone") from exc
        bounded_json(self.model_dump())
        return self


class DatasetOptions(Strict):
    duplicate_policy: Literal["update", "skip", "revision", "review"] = "revision"
    max_records_per_page: int = Field(100, ge=1, le=500)
    max_records: int = Field(10000, ge=1, le=100000)
    max_revisions: int = Field(20, ge=1, le=100)
    retention_days: int = Field(30, ge=1, le=3650)
    missing_threshold: int = Field(3, ge=2, le=20)
    confirm_missing: bool = False
    fuzzy_fields: list[str] = Field(default_factory=list, max_length=5)
    fuzzy_threshold: float = Field(0.95, ge=0.85, le=1)
    max_scrolls: int = Field(0, ge=0, le=10)
    ready_selector: str | None = Field(None, max_length=500)
    empty_state_selector: str | None = Field(None, max_length=500)
    pagination_selector: str | None = Field(None, max_length=500)
    ai_fallback: bool = False
    ai_max_tokens: int = Field(20000, ge=2000, le=100000)


class SchemaInput(Strict):
    definition: SchemaDefinition
    active: bool = True


class DatasetInput(Strict):
    name: str = Field(min_length=1, max_length=120)
    website_id: str
    schema_id: str
    options: DatasetOptions = Field(default_factory=DatasetOptions)


class DatasetPatch(DatasetInput):
    expected_version: int = Field(ge=0)


from .query import DatasetQuery  # noqa: E402


class ExportInput(Strict):
    format: Literal["json", "csv"] = "json"
    columns: list[str] = Field(default_factory=list, max_length=50)
    include_revisions: bool = False
    query: DatasetQuery | None = None

    @field_validator("columns")
    @classmethod
    def unique(cls, values):
        return list(dict.fromkeys(values))
