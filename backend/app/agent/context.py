"""Select bounded model context from the durable task and current page."""
from .routing import words


_STOP_WORDS = {"the", "and", "for", "find", "list", "show", "all", "with", "from"}


def retrieve_evidence(evidence, objective, observation, limit=8, *, phase="", exact=False):
    terms = set(words(objective)) - _STOP_WORDS
    phase_terms = set(words(phase)) - _STOP_WORDS
    url = observation.get("url")

    def relevance(item):
        index, source = item
        source_terms = set(words(source.get("quote", "")))
        return (len(terms & source_terms) + 2 * len(phase_terms & source_terms), source.get("url") == url, index)

    ranked = sorted(enumerate(evidence), key=relevance, reverse=True)
    selected = []
    for _, item in ranked[:limit]:
        quote = item.get("quote", "")
        if exact:
            selected.append({"id": item["id"], "url": item.get("url"), "quote": quote})
            continue
        # Keep exact text while focusing the quote around where task terms occur.
        folded = quote.casefold()
        hits = sorted(index for word in terms | phase_terms if len(word) > 2 and (index := folded.find(word)) >= 0)
        start = max(0, hits[0] - 120) if hits else 0
        selected.append({"id": item["id"], "url": item.get("url"), "quote": quote[start:start + 600]})
    return selected
