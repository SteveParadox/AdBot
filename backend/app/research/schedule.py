"""Bounded extraction of publisher-declared public schema.org events.

No inferred fixtures, dates, opponents or availability. Event dates are not
document publication dates. No new network destination is introduced.
"""
import json
import re
from datetime import datetime, timedelta, timezone


def schedule_request(question):
    return bool(re.search(r"\b(fixtures?|schedules?|timetables?|kick[ -]?offs?|events?|match(?:es)?)\b", question, re.I))


def plain(value, limit):
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def event_day(value, offset_minutes=0):
    try:
        if not isinstance(value, str):
            return None
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return datetime.fromisoformat(value).date().isoformat()
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return None  # Unknown local zone; cannot convert safely.
        return dt.astimezone(timezone(timedelta(minutes=offset_minutes or 0))).date().isoformat()
    except (ValueError, OverflowError):
        return None


def local_start(value, offset_minutes=0):
    if not isinstance(value, str) or not event_day(value, offset_minutes):
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None  # date-only record has no observed kickoff time
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone(timedelta(minutes=offset_minutes or 0))).isoformat(timespec="minutes")


def valid_unzoned_start(value):
    """Accept a valid publisher-local timestamp without inferring a timezone."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?", value):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def name(value):
    return plain(value.get("name"), 120) if isinstance(value, dict) else plain(value, 120)


def structured_events(tree):
    stack = []
    for node in tree.xpath('//script[@type="application/ld+json"]')[:24]:
        raw = node.text or ""
        if len(raw) > 100_000:
            continue
        try:
            stack.append(json.loads(raw))
        except (ValueError, RecursionError):
            continue
    result = []
    seen = set()
    for _ in range(400):
        if not stack or len(result) >= 100:
            break
        value = stack.pop()
        if isinstance(value, list):
            stack.extend(reversed(value[:100]))
            continue
        if not isinstance(value, dict):
            continue
        kinds = value.get("@type", [])
        kinds = [kinds] if isinstance(kinds, str) else kinds if isinstance(kinds, list) else []
        event = any(isinstance(k, str) and ("/" not in k or k.startswith(("https://schema.org/", "http://schema.org/"))) and k.rsplit("/", 1)[-1] in
                    {"Event", "SportsEvent", "MusicEvent", "BusinessEvent", "EducationEvent",
                     "TheaterEvent", "Festival", "ExhibitionEvent", "SocialEvent"} for k in kinds)
        if event:
            title = name(value)
            start = plain(value.get("startDate"), 80)
            if title and (event_day(start) or valid_unzoned_start(start)):
                record = {"event": title, "startDate": start}
                for field in ("homeTeam", "awayTeam", "location", "superEvent", "organizer"):
                    observed = name(value.get(field))
                    if observed:
                        record[field] = observed
                status = plain(value.get("eventStatus"), 100)
                if status:
                    record["eventStatus"] = status
                key = tuple(sorted(record.items()))
                if key not in seen:
                    seen.add(key)
                    result.append(record)
        for key in ("@graph", "mainEntity", "itemListElement", "item", "subEvent", "event"):
            if key in value:
                stack.append(value[key])
    return result
