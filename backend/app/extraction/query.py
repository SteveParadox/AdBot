"""Bounded deterministic selection of captured data. No code or SQL from clients."""
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from functools import cmp_to_key
from typing import Literal, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from ..db import ExtractedRecord


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Filter(Strict):
    field: str = Field(min_length=1, max_length=100)
    op: Literal["eq", "ne", "lt", "lte", "gt", "gte", "contains", "in", "is_null"] = "eq"
    value: Any = None

    @field_validator("value")
    @classmethod
    def bounded(cls, value):
        from .schemas import bounded_json
        bounded_json(value, 4000)
        return value


class Sort(Strict):
    field: str = Field(min_length=1, max_length=100)
    direction: Literal["asc", "desc"] = "asc"


class DatasetQuery(Strict):
    filters: list[Filter] = Field(default_factory=list, max_length=20)
    sort: list[Sort] = Field(default_factory=list, max_length=5)
    limit: int | None = Field(None, ge=1, le=10000)


def scalar(value, kind):
    if value is None:
        return None
    if kind in {"integer", "decimal", "currency"}:
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            raise ValueError("Dataset query requires normalized numeric values") from None
        if not number.is_finite():
            raise ValueError("Dataset query rejects nonfinite numbers")
        return number
    if kind == "boolean":
        if type(value) is not bool:
            raise ValueError("Boolean query values must be true or false")
        return value
    if kind == "date":
        return date.fromisoformat(value).isoformat()
    if kind == "datetime":
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Datetime queries require a timezone")
        return parsed.timestamp()
    if not isinstance(value, str):
        raise ValueError("String query values must be strings")
    return value


def validate_query(query, definition):
    fields = definition["fields"]
    for item in [*query.filters, *query.sort]:
        if item.field not in fields or fields[item.field]["type"] in {"list", "object"}:
            raise ValueError("Query requires a known scalar schema field")
    for item in query.filters:
        kind = fields[item.field]["type"]
        if item.op == "is_null":
            if type(item.value) is not bool:
                raise ValueError("is_null requires a boolean")
        elif item.op == "in":
            if not isinstance(item.value, list) or not 1 <= len(item.value) <= 100:
                raise ValueError("in requires 1 to 100 scalar values")
            for value in item.value:
                scalar(value, kind)
        else:
            if item.op == "contains" and kind not in {"string", "url"}:
                raise ValueError("contains requires a string field")
            scalar(item.value, kind)


def select_records(session, dataset_id, definition, query, scope=None):
    validate_query(query, definition)
    rows = session.scalars(select(ExtractedRecord).where(ExtractedRecord.dataset_id == dataset_id, ExtractedRecord.status == "active").order_by(ExtractedRecord.id).limit(10001)).all()
    if len(rows) > 10000:
        raise ValueError("Dataset query exceeds 10000-record bound; use a smaller dataset")
    if scope is not None:
        rows = [r for r in rows if r.id in scope]
        if len(rows) != len(scope) or any(scope[r.id] != r.content_hash for r in rows):
            raise ValueError("Task records changed during query selection")
    def value(row, field):
        return scalar(row.data.get(field), definition["fields"][field]["type"])
    def matches(row, rule):
        left = value(row, rule.field)
        kind = definition["fields"][rule.field]["type"]
        if rule.op == "is_null":
            return (left is None) == rule.value
        if rule.op == "in":
            return left in [scalar(v, kind) for v in rule.value]
        right = scalar(rule.value, kind)
        if rule.op == "eq":
            return left == right
        if rule.op == "ne":
            return left != right
        if left is None or right is None:
            return False
        if rule.op == "contains":
            return right in left
        if rule.op == "lt":
            return left < right
        if rule.op == "lte":
            return left <= right
        if rule.op == "gt":
            return left > right
        return left >= right
    rows = [r for r in rows if all(matches(r, rule) for rule in query.filters)]
    def compare(a, b):
        for rule in query.sort:
            left, right = value(a, rule.field), value(b, rule.field)
            if left is None or right is None:
                order = (left is None) - (right is None)  # nulls last in either direction
            else:
                order = ((left > right) - (left < right)) * (-1 if rule.direction == "desc" else 1)
            if order:
                return order
        return (a.id > b.id) - (a.id < b.id)
    return sorted(rows, key=cmp_to_key(compare))[:query.limit]



def resolve_query(objective, definition, explicit=None):
    """Compile only a narrow, unambiguous price-ranking phrase; disclose the result."""
    import re
    if explicit is not None:
        query = DatasetQuery.model_validate(explicit)
    else:
        match = re.fullmatch(r"\s*(?:please\s+)?export\s+(?:the\s+)?cheapest\s+(one|two|three|four|five|six|seven|eight|nine|ten|[1-9][0-9]{0,3})\s+(?:products?|items?|records?)(?:\s+(?:as|to|in)\s+(?:csv|json))?[.!]?\s*", objective, re.I)
        if not match:
            return None
        words = "one two three four five six seven eight nine ten".split()
        count = words.index(match[1].lower()) + 1 if match[1].lower() in words else int(match[1])
        if "price" not in definition["fields"] or definition["fields"]["price"]["type"] not in {"integer", "decimal", "currency"}:
            raise ValueError("Cheapest-record queries require a normalized numeric price field")
        query = DatasetQuery(filters=[Filter(field="price", op="is_null", value=False)], sort=[Sort(field="price")], limit=count)
    validate_query(query, definition)
    return query.model_dump()
