"""Bounded conversation-local context, derived from user turns and observed entities."""

import re
from decimal import Decimal

from .evidence import country_from
from .shopping import budget_constraint, requirements
from .search import terms

MAX_TURNS = 32
MAX_SELECTED = 3
MAX_ENTITIES = 20
MAX_SOURCES = 40
RESET = re.compile(r"\b(?:new topic|unrelated question|start over|forget (?:the )?(?:previous|earlier) (?:context|requirements))\b", re.I)
FOLLOW = re.compile(
    r"\b(?:those|these|them|that (?:claim|one|product|source|report|answer)|previous|earlier|above|"
    r"what about|how about|more recent|other retailers|cheapest|same (?:budget|requirements|country)|"
    r"(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|last|\d{1,2}(?:st|nd|rd|th)) "
    r"(?:one|product|option|source|result)|(?:product|option|source|result) (?:#\s*)?\d{1,2}|"
    r"(?:increase|raise|lower|reduce|change|remove|drop|keep) (?:the |my )?(?:budget|ram|storage|vram|requirements|country)|"
    r"make it|instead|continue)\b", re.I,
)
ORDINALS = {word: index for index, word in enumerate(
    ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
     "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth",
     "eighteenth", "nineteenth", "twentieth"), 1)}
REFERENCE = re.compile(
    r"\b(?:(?P<kind>product|option|source|result)\s*#?\s*(?P<number>\d{1,2})|"
    r"(?P<ordinal>" + "|".join(ORDINALS) + r"|last|\d{1,2}(?:st|nd|rd|th))\s+(?P<noun>one|product|option|source|result))\b",
    re.I,
)
FRESHNESS = (
    ("day", r"\b(?:today|last 24 hours|past 24 hours)\b"),
    ("week", r"\b(?:this week|past week|last week|last 7 days)\b"),
    ("month", r"\b(?:this month|last month|past month|more recent|newer|updated)\b"),
    ("year", r"\b(?:this year|past year|last year)\b"),
)
GPU = re.compile(r"\b(?:rtx|gtx|rx)\s*\d{3,4}(?:\s*(?:ti|super|xtx|xt))?\b", re.I)
CATEGORY = re.compile(r"\b(?:laptops?|notebooks?|macbooks?|chromebooks?|phones?|smartphones?|iphones?|monitors?|tablets?|ipads?)\b", re.I)
WORKLOAD = re.compile(r"\b(?:ai engineering|machine learning|deep learning|local llms?|ai training)\b", re.I)
CONDITION = re.compile(r"\b(?:brand new|new only|refurbished only|used only|(?:new|used|refurbished) (?:laptops?|phones?|products?))\b", re.I)


def followup(text, history):
    if not history or RESET.search(text):
        return False
    if REFERENCE.search(text) or FOLLOW.search(text):
        return True
    if re.search(r"\b(?:that claim|sources?|verify it|explain it)\b", text, re.I) and len(terms(text)) <= 8:
        return True
    return any(len(p.get("name") or "") >= 5 and p["name"].casefold() in text.casefold()
               for turn in history for p in turn.get("products", [])) and len(terms(text)) <= 12


def relevant_turns(text, history):
    """Recency breaks lexical ties; prefer matched names for older entities."""
    query = terms(text)
    scored = []
    for index, turn in enumerate(history):
        names = [p.get("name") or "" for p in turn.get("products", [])]
        titles = [s.get("title") or "" for s in turn.get("sources", [])]
        lexical = len(query & terms(turn["question"] + " " + " ".join(names + titles)))
        named = any(len(name) >= 5 and name.casefold() in text.casefold() for name in names + titles)
        scored.append((int(named), lexical, index, turn))
    if not scored:
        return []
    # Explicit position references always resolve against the most recent
    # matching result list, not a reordered similarity list.
    if REFERENCE.search(text):
        kind = REFERENCE.search(text).group("kind") or REFERENCE.search(text).group("noun")
        key = "sources" if kind.casefold() == "source" else "products"
        anchor = next((turn for turn in reversed(history) if turn.get(key)), history[-1])
    elif any(score[0] for score in scored):
        anchor = max(scored, key=lambda row: row[:3])[-1]
    elif re.search(r"\b(?:previous|earlier)\b", text, re.I) and any(score[1] for score in scored):
        anchor = max(scored, key=lambda row: row[:3])[-1]
    else:
        anchor = history[-1]
    others = [row[-1] for row in sorted(scored, key=lambda row: row[:3], reverse=True)
              if row[1] and row[-1] is not anchor]
    return [anchor, *others[:MAX_SELECTED - 1]]


def user_slots(text, country):
    slots = {}
    requested, budget = budget_constraint(text, country)
    if requested:
        slots["budget"] = [budget[0], format(budget[1], "f")] if budget else None
    for key, op, target in requirements(text):
        slots.setdefault(key, []).append([op, format(target, "f")])
    for key, regex in (("gpu", GPU), ("category", CATEGORY), ("condition", CONDITION), ("workload", WORKLOAD)):
        matches = list(dict.fromkeys(m.group().casefold() for m in regex.finditer(text)))
        if matches:
            slots[key] = matches[:4]
    for key in ("budget", "RAM", "VRAM", "Storage", "gpu", "condition"):
        name = {"RAM": "ram", "VRAM": "vram", "Storage": "(?:storage|ssd)"}.get(key, key)
        if re.search(rf"\b(?:remove|drop|ignore|no|without) (?:the |my )?{name}(?: (?:limit|requirement|constraint))?\b", text, re.I):
            slots[key] = None
    return slots


def constraint_text(slots):
    parts = []
    if slots.get("budget"):
        currency, limit = slots["budget"]
        parts.append(f"budget {currency} {limit}")
    for key in ("RAM", "VRAM", "Storage"):
        for op, target in slots.get(key) or []:
            phrase = {"min": "at least", "max": "up to", "exact": "exactly"}[op]
            parts.append(f"{key} {phrase} {target} GB")
    for key in ("category", "gpu", "condition", "workload"):
        parts.extend(slots.get(key) or [])
    return ", ".join(parts)


def compact_turn(turn):
    return {"id": turn.get("id", ""), "question": turn["question"][:1400],
            "answer": turn.get("answer", "")[:900], "mode": turn["mode"]}


def resolve_references(text, anchor):
    refs, unresolved = [], []
    for match in REFERENCE.finditer(text):
        kind = (match["kind"] or match["noun"]).casefold()
        rows = anchor.get("sources" if kind == "source" else "products", [])
        ordinal = (match["ordinal"] or "").casefold()
        number = int(match["number"]) if match["number"] else (
            len(rows) if ordinal == "last" else ORDINALS.get(ordinal, 0)
        )
        if not number and re.match(r"\d", ordinal):
            number = int(re.match(r"\d+", ordinal).group())
        if 1 <= number <= len(rows):
            row = rows[number - 1]
            refs.append({"kind": "source" if kind == "source" else "product",
                         "index": number, "name": row.get("title") or row.get("name") or "",
                         "url": row.get("url"), "turn_id": anchor.get("id", "")})
        else:
            unresolved.append(match.group()[:80])
    # A literal name can resolve a unique product, never a fuzzy invented one.
    if not refs and not unresolved:
        matches = [p for p in anchor.get("products", []) if len(p.get("name") or "") >= 5
                   and p["name"].casefold() in text.casefold()]
        if len(matches) == 1:
            refs.append({"kind": "product", "index": anchor["products"].index(matches[0]) + 1,
                         "name": matches[0]["name"], "url": matches[0].get("url"),
                         "turn_id": anchor.get("id", "")})
        elif len(matches) > 1:
            unresolved.append("ambiguous product name")
    return refs[:4], unresolved[:4]


def build_context(question, history, intent, mode):
    """Freeze the effective context at submission; never import old claims as evidence."""
    text = question.question
    selected = relevant_turns(text, history) if intent == "follow_up" and not RESET.search(text) else []
    anchor = selected[0] if selected else {}
    old = anchor.get("memory") or {}
    country = country_from(text, question.country) or (old.get("country") if old else anchor.get("country"))
    if re.search(r"\b(?:any country|worldwide|globally|remove (?:the )?country)\b", text, re.I) and not question.country:
        country = None
    freshness = question.freshness or next((name for name, pattern in FRESHNESS if re.search(pattern, text, re.I)), None)
    if not freshness:
        freshness = old.get("freshness") if old else anchor.get("freshness")
    if not freshness and intent in {"news", "current"}:
        freshness = "week" if intent == "news" else "month"
    if re.search(r"\b(?:any date|no date limit|remove (?:the )?freshness)\b", text, re.I) and not question.freshness:
        freshness = None
    slots = dict(old.get("slots", {})) if old else user_slots(anchor.get("question", ""), country) if anchor else {}
    updates = user_slots(text, country)
    # Common short budget revisions inherit currency only when a previous
    # explicit monetary budget exists.
    if "budget" not in updates and slots.get("budget"):
        match = re.search(r"\b(?:make it|increase (?:it|the budget) to|reduce (?:it|the budget) to)\s+(\d+(?:\.\d+)?)\s*(million|thousand|k|m)\b", text, re.I)
        if match:
            scale = {"million": 1000000, "m": 1000000, "thousand": 1000, "k": 1000}[match[2].casefold()]
            updates["budget"] = [slots["budget"][0], format(Decimal(match[1]) * scale, "f")]
    prior_country = old.get("country") if old else anchor.get("country")
    if prior_country and country != prior_country and "budget" not in updates:
        # Do not silently apply an old market's price limit to a new market.
        slots.pop("budget", None)
    for key, value in updates.items():
        if value is None:
            slots.pop(key, None)
        else:
            slots[key] = value
    refs, unresolved = resolve_references(text, anchor) if anchor else ([], [])
    alternative = bool(re.search(r"\b(?:other|different|additional|new) (?:retailers|sources|products|options)\b", text, re.I))
    urls = [r["url"] for r in refs if r.get("url")]
    if anchor and not alternative and not urls and not unresolved:
        urls = [s.get("url") for s in anchor.get("sources", [])[:4] if s.get("url")]
    if alternative or (prior_country and country != prior_country):
        urls = []
    # Keep old user wording as a separate model context field. Never append
    # historical prices or product descriptions to provider search queries.
    topic = old.get("topic") or anchor.get("question") or text
    effective = constraint_text(slots) if str(mode) == "shopping" else ""
    if "budget" in updates and updates["budget"] is None and not re.search(r"\b(?:remove|drop|ignore|no|without) (?:the |my )?budget\b", text, re.I):
        unresolved.append("budget currency or amount")
    return {
        "version": 1, "country": country, "freshness": freshness, "slots": slots,
        "topic": topic[:1400], "constraints": effective, "references": refs,
        "unresolved": unresolved, "source_urls": urls[:4], "turns": [compact_turn(t) for t in selected],
        "anchor_id": anchor.get("id"), "alternative": alternative,
    }
