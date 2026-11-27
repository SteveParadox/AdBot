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


def subject_query(subject, question):
    """Retain explicit criteria without reintroducing competing entities."""
    match = re.search(r"\s+(?:for|in terms of|regarding)\s+(.+)$", question, re.I)
    return " ".join((subject, match.group(1).strip(" ?!.") if match else "official information")).strip()


def prioritize_comparison_hits(ranked, subjects, attempted=()):
    """Reserve an available candidate for each explicit subject, then keep global rank."""
    selected, seen = [], set(attempted)
    for subject in subjects:
        candidates = [hit for hit in ranked if hit.canonical_url not in seen and mentions_subject(
            subject, " ".join((hit.title, hit.description or "", hit.url)))]
        if candidates:
            hit = candidates[0]
            selected.append(hit)
            seen.add(hit.canonical_url)
    chosen = {hit.canonical_url for hit in selected}
    return selected + [hit for hit in ranked if hit.canonical_url not in chosen]


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
    """Resolve one explicit ISO date or relative day with the supplied fixed UTC offset."""
    shifts = {"today": 0, "tonight": 0, "tomorrow": 1, "yesterday": -1}
    days = {shifts[m.group().casefold()] for m in RELATIVE.finditer(question)}
    explicit = set(re.findall(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)", question))
    if explicit:
        if len(explicit) != 1 or days:
            return None
        try:
            return datetime.strptime(next(iter(explicit)), "%Y-%m-%d").date().isoformat()
        except ValueError:
            return None
    if len(days) != 1:
        return None
    local = datetime.fromtimestamp(reference_at, timezone(timedelta(minutes=offset_minutes or 0)))
    return (local.date() + timedelta(days=days.pop())).isoformat()


def dated_query(question, target_date):
    return RELATIVE.sub(target_date, question) if target_date else question
