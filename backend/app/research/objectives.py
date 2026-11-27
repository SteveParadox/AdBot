"""Conservative domain-independent objective hints."""
import re
from datetime import datetime, timedelta, timezone


def comparison_request(question):
    return bool(re.search(r"\b(compare|comparison|versus|vs)\b", question, re.I))


def comparison_subjects(question):
    if not re.search(r"^\s*compare\b|\b(?:vs\.?|versus)\s+", question, re.I):
        return []
    match = re.match(r"^\s*(?:compare\s+)?(.{1,100}?)\s+(?:vs\.?|versus|and)\s+(.{1,100}?)(?=\s+(?:for|in terms of|regarding)\s+|[?!.]?$)", question.strip(), re.I)
    if not match:
        return []
    parts = [part.strip(" ?!.") for part in match.groups()]
    return parts if all(parts) and parts[0].casefold() != parts[1].casefold() else []


def mentions_subject(subject, text):
    # Word boundaries also support short and punctuation-bearing names (R, C++).
    pattern = re.escape(" ".join(subject.split()))
    return bool(re.search(r"(?<!\w)" + pattern + r"(?!\w)", " ".join(text.split()), re.I))


def definition_request(question):
    # Conservative single-word definitions; explicit modes, current requests
    # and conversation follow-ups take precedence at the router.
    return bool(re.fullmatch(r"\s*(?:[Ww]hat is (?:an? )?|[Dd]efine )[a-z][a-z-]{2,}[?!.]?\s*", question))


RELATIVE = re.compile(r"\b(today|tomorrow|yesterday|tonight)\b", re.I)


def relative_date(question, reference_at, offset_minutes):
    """Resolve a single relative day with the supplied fixed UTC offset."""
    shifts = {"today": 0, "tonight": 0, "tomorrow": 1, "yesterday": -1}
    days = {shifts[m.group().casefold()] for m in RELATIVE.finditer(question)}
    if len(days) != 1:
        return None
    local = datetime.fromtimestamp(reference_at, timezone(timedelta(minutes=offset_minutes or 0)))
    return (local.date() + timedelta(days=days.pop())).isoformat()


def dated_query(question, target_date):
    return RELATIVE.sub(target_date, question) if target_date else question
