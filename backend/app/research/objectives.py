"""Conservative domain-independent objective hints."""
import re


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


def definition_request(question):
    # Conservative single-word definitions; explicit modes, current requests
    # and conversation follow-ups take precedence at the router.
    return bool(re.fullmatch(r"\s*(?:[Ww]hat is (?:an? )?|[Dd]efine )[a-z][a-z-]{2,}[?!.]?\s*", question))
