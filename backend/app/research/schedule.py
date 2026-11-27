"""Bounded extraction of publisher-declared public schema.org events.

No inferred fixtures, dates, opponents or availability. Event dates are not
document publication dates. No new network destination is introduced.
"""
import json
import re
from datetime import datetime, timedelta, timezone


def schedule_request(question):
    return bool(re.search(r"\b(fixtures?|schedules?|timetables?|kickoffs?|events?|matches)\b", question, re.I))


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
        event = any(isinstance(k, str) and k.rsplit("/", 1)[-1] in
                    {"Event", "SportsEvent", "MusicEvent", "BusinessEvent", "EducationEvent",
                     "TheaterEvent", "Festival", "ExhibitionEvent", "SocialEvent"} for k in kinds)
        if event:
            title = name(value)
            start = plain(value.get("startDate"), 80)
            if title and (event_day(start) or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?", start)):
                record = {"event": title, "startDate": start}
                for field in ("homeTeam", "awayTeam", "location", "superEvent", "organizer"):
                    observed = name(value.get(field))
                    if observed:
                        record[field] = observed
                status = plain(value.get("eventStatus"), 100)
                if status:
                    record["eventStatus"] = status
                result.append(record)
        for key in ("@graph", "mainEntity", "itemListElement", "item", "subEvent", "event"):
            if key in value:
                stack.append(value[key])
    return result
