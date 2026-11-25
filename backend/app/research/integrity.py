"""Conservative publication-date and numerical corroboration primitives.

A recent publication is not proof that the events it describes are recent.
All date observations are publisher declarations, not independent validation.
"""
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

WINDOWS = {"day": 1, "week": 7, "month": 30, "year": 365}
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}(?:$|T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?)$")
ISO_DATE = re.compile(r"(?<![\w\d])\d{4}-\d{2}-\d{2}(?![\d-])")
VERSION = re.compile(r"(?<![\d.])\d+(?:\.\d+){2,}(?![\d.])")
UNITS = (
    r"percentage points?|percent(?:age)?|%|bps|basis points?|"
    r"usd|ngn|eur|gbp|cad|aud|jpy|inr|zar|naira|dollars?|euros?|pounds?|"
    r"gb|tb|mb|kb|gib|tib|mib|kwh|mwh|kw|mw|watts?|w|"
    r"ghz|mhz|khz|hz|kg|mg|km|cm|mm|metres?|meters?|miles?|"
    r"milliseconds?|ms|seconds?|minutes?|hours?|days?|weeks?|months?|years?|"
    r"million|billion|trillion|thousand"
)
NUMBER = re.compile(
    r"(?<![\w.,])(?P<sign>[+\-−])?\s*(?P<symbol>₦|€|£|\$)?\s*"
    r"(?P<currency>USD|NGN|EUR|GBP|CAD|AUD|JPY|INR|ZAR)?\s*"
    r"(?P<value>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\d.,]\d)"
    r"(?:\s*(?P<scale>thousand|million|billion|trillion)\b)?"
    r"(?:\s*(?P<unit>" + UNITS + r")(?=\b|(?<=%)))?", re.I
)
CURRENCIES = {"₦": "NGN", "€": "EUR", "£": "GBP", "$": "$",
              "naira": "NGN", "dollar": "$", "dollars": "$", "euro": "EUR", "euros": "EUR",
              "pound": "GBP", "pounds": "GBP"}
SCALE = {"thousand": 1000, "million": 1000000, "billion": 1000000000, "trillion": 1000000000000}
ALIASES = {"percent": "%", "percentage": "%", "percentage point": "pp", "percentage points": "pp",
           "basis point": "bps", "basis points": "bps", "watts": "w", "watt": "w",
           "milliseconds": "ms", "millisecond": "ms", "seconds": "second", "minutes": "minute",
           "hours": "hour", "days": "day", "weeks": "week", "months": "month", "years": "year",
           "metres": "m", "metre": "m", "meters": "m", "meter": "m", "miles": "mile"}


def parse_date(value, now=None):
    if not isinstance(value, str) or not ISO.fullmatch(value.strip()):
        return None
    value = value.strip()
    now = now or datetime.now(timezone.utc)
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        instant = instant.replace(tzinfo=timezone.utc) if instant.tzinfo is None else instant.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None
    if instant > now:
        return None
    # A date-only or timezone-free declaration cannot prove hour-level timing.
    return value if len(value) == 10 else instant.isoformat()


def publication_date(observations, now=None):
    """Resolve explicit date declarations; conflict means no accepted date."""
    valid = [(origin, parsed) for origin, value in observations if (parsed := parse_date(value, now))]
    days = {datetime.fromisoformat(date).date() for _, date in valid}
    if len(days) > 1:
        return None, {"status": "conflicting", "observations": valid[:8]}
    if not valid:
        return None, {"status": "unknown", "observations": []}
    # Use day precision when declarations disagree within the same day.
    dates = {date for _, date in valid}
    value = valid[0][1] if len(dates) == 1 else next(iter(days)).isoformat()
    return value, {"status": "publisher_declared", "observations": valid[:8]}


def freshness_status(value, window, now=None):
    if not window:
        return "not_requested"
    now = now or datetime.now(timezone.utc)
    parsed = parse_date(value, now)
    if not parsed:
        return "unknown"
    instant = datetime.fromisoformat(parsed)
    instant = instant.replace(tzinfo=timezone.utc) if instant.tzinfo is None else instant
    cutoff = now - timedelta(days=WINDOWS[window])
    # For day-only metadata, require the entire possible interval to be
    # inside the rolling window; boundary dates remain unestablished.
    if len(parsed) == 10:
        if instant + timedelta(days=1) <= cutoff:
            return "stale"
        if instant < cutoff:
            return "unknown"
    return "fresh" if instant >= cutoff else "stale"


def claim_freshness(ids, evidence, sources, window, now=None):
    statuses = []
    for identifier in ids:
        row = evidence[identifier]
        source = sources[row["source_id"]]
        # The source record, not the model or duplicated evidence metadata,
        # is the authority for the declared publication date.
        statuses.append(freshness_status(source.get("published_at"), window, now))
    if not window:
        return "not_requested"
    if statuses and all(status == "fresh" for status in statuses):
        return "fresh"
    if "fresh" in statuses:
        return "mixed"
    if statuses and all(status == "stale" for status in statuses):
        return "stale"
    return "unknown"


def quantities(text):
    """Normalize exact numerical observations, not arbitrary calculations."""
    text = str(text).replace("\u00a0", " ").replace("\u202f", " ")
    found = set()
    # ISO dates and dotted software versions cannot be decomposed into
    # independent numbers that happen to match unrelated facts.
    for pattern, kind in ((ISO_DATE, "date"), (VERSION, "version")):
        for match in pattern.finditer(text):
            found.add((kind, match.group()))
        text = pattern.sub(" ", text)
    # Preserve ranges as two positive endpoints rather than a negative second
    # value. Explicit standalone minus signs remain meaningful.
    text = re.sub(r"(?<=\d)\s*[-–—]\s*(?=\d)", " to ", text)
    for match in NUMBER.finditer(text):
        try:
            value = Decimal(match["value"].replace(",", ""))
            if match["sign"] in {"-", "−"}:
                value = -value
            value *= SCALE.get((match["scale"] or "").casefold(), 1)
        except InvalidOperation:
            continue
        unit = (match["unit"] or "").casefold()
        if unit in SCALE:
            value *= SCALE[unit]
            unit = ""
        prefix = (match["currency"] or "").upper() or CURRENCIES.get(match["symbol"], "")
        suffix = CURRENCIES.get(unit, unit.upper() if unit.upper() in
                                {"USD", "NGN", "EUR", "GBP", "CAD", "AUD", "JPY", "INR", "ZAR"}
                                else "")
        if prefix and suffix and prefix != suffix:
            found.add(("ambiguous_currency", value))
            continue
        unit = prefix or suffix or ALIASES.get(unit, unit)
        found.add((unit, value))
    return found


def numerical_support(claim, quotes):
    expected = quantities(claim)
    observed = set()
    for quote in quotes:
        observed.update(quantities(quote))
    return expected <= observed
