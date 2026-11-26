"""Bounded extraction-first helpers for authorized read-side tasks.

Ranking and structural mapping produce candidates, never evidence of semantic
membership or coverage. The existing capture, classifier and verifier remain
authoritative. No site-specific selectors, paths or product names.
"""
import re
from urllib.parse import urlsplit

from .contracts import Decision
from .routing import words, semantic_terms
from .research import destination_key
from .structure import RecordCapture, map_group, rejected_group

_GENERIC = set("a an the list show find collect identify give provide please of for to and or all every best top ai software tool tools product products option options".split())
_CATALOG = {"catalog", "catalogue", "directory", "marketplace", "listings", "categories", "browse", "library", "inventory"}
_EDITORIAL = {"article", "articles", "guide", "guides", "blog", "rankings", "tutorial", "pages", "publish", "publishing"}
_IDENTITY = {"record heading", "name", "title", "product", "tool", "item", "company", "provider", "service"}
_DESCRIPTION = {"description", "purpose", "function", "category", "summary", "features", "details", "use case"}
_ALIASES = {"buying": "buy", "buyers": "buy", "buyer": "buy", "shopping": "buy", "purchase": "buy",
            "purchasing": "buy", "comparison": "compare", "comparisons": "compare",
            "comparing": "compare", "compares": "compare", "utilities": "utility"}


def concepts(value):
    return {_ALIASES.get(word, word) for word in semantic_terms(value)} - _GENERIC


def relevance(objective, value):
    return len(concepts(objective) & concepts(value))


def source_score(objective, element):
    name = element.get("name") or ""
    label = set(words(name))
    href = element.get("href") or ""
    path = set(words(urlsplit(href).path))
    context = str((element.get("context") or {}).get("heading", ""))
    topical = relevance(objective, name)
    score = 5 * topical + 2 * relevance(objective, context) + relevance(objective, href)
    score += 8 * bool((label | path) & _CATALOG)
    score += 2 * bool(label & {"tools", "products", "services"})
    score -= 4 * bool(label & _EDITORIAL)
    return score


def observed_links(observation, objective, policy, *, excluded=(), catalog_only=False):
    if any(dialog.get("visible") for dialog in observation.get("dialogs", [])):
        return []
    excluded = set(excluded) | {destination_key(observation["url"])}
    candidates = {}
    for element in observation.get("elements", []):
        href = element.get("href")
        if (not href or not element.get("actionable") or element.get("disabled")
                or element.get("blocked_by_modal") or element.get("form")
                or element.get("role") != "link"):
            continue
        try:
            href = policy.check(href)
        except ValueError:
            continue
        if urlsplit(href).scheme not in {"http", "https"} or destination_key(href) in excluded:
            continue
        if catalog_only and not (set(words(element.get("name") or "")) | set(words(urlsplit(href).path))) & _CATALOG:
            continue
        score = source_score(objective, {**element, "href": href})
        if score > 0 and score > candidates.get(destination_key(href), (0, ""))[0]:
            candidates[destination_key(href)] = (score, href)
    return sorted(candidates.values(), key=lambda item: (-item[0], item[1]))


def navigation_candidate(observation, objective, policy, *, excluded=(), minimum=5, catalog_only=False):
    ranked = observed_links(observation, objective, policy, excluded=excluded, catalog_only=catalog_only)
    if not ranked or ranked[0][0] < minimum:
        return None
    return Decision(decision="NAVIGATE", url=ranked[0][1],
                    observation="A relevant unvisited link is available",
                    reason="Explore an observed authorized source likely to contain new information",
                    confidence=0.75, expected_result="New candidate records or source evidence")


def _field_label(segment):
    return " ".join(words(segment.get("label", "")))


def automatic_capture(observation, groups, objective, *, rejected=(), max_rows=48):
    """Map explicit, coherent repeated identities, not arbitrary page headings.

    Validate against full observed rows, not their clipped summaries. Semantic
    classification still decides whether each individual candidate qualifies.
    """
    if (observation.get("http_status") or 0) >= 400 or any(
        dialog.get("visible") for dialog in observation.get("dialogs", [])
    ):
        return None
    offered = {group["id"] for group in observation.get("record_groups", [])}
    choices = []
    for group in groups.values():
        if (group["id"] not in offered or group.get("kind") not in {"repeated", "row"}
                or rejected_group(observation["url"], group, rejected)):
            continue
        rows = group.get("records", [])
        if not 2 <= len(rows) <= max_rows:
            continue
        example = rows[0].get("segments", [])[:12]
        identities = [index for index, segment in enumerate(example, 1)
                      if _field_label(segment) in _IDENTITY and not segment.get("truncated")]
        if len(identities) != 1:
            continue
        identity = identities[0]
        descriptions = []
        for index, segment in enumerate(example, 1):
            value = segment.get("value", "")
            if index == identity or segment.get("truncated") or len(value) < 25:
                continue
            if value == example[identity - 1].get("value"):
                continue
            label = _field_label(segment)
            descriptions.append((int(label in _DESCRIPTION), len(value), index))
        for _, _, position in sorted(descriptions, reverse=True):
            capture = RecordCapture(group=group["id"], identity=identity, fields=[
                {"name": "Name", "position": identity}, {"name": "Description", "position": position},
            ], restrict_to_objective=True)
            try:
                mapped = map_group(group, capture, preserve_context=True)
            except ValueError:
                continue
            if len(mapped) < 2 or len(mapped) < len(rows) * 0.8:
                continue
            if any(len(name) > 220 or len(words(name)) > 20 or
                   len(fields["Description"]) < 25 or
                   fields["Description"] == fields["Name"]
                   for name, (fields, _) in mapped.items()):
                continue
            relevant = sum(bool(relevance(objective, " ".join(excerpts))) for _, excerpts in mapped.values())
            heading_score = relevance(objective, group.get("label", ""))
            # Unrelated cards remain available to the model, but don't spend a
            # classification batch on them purely because they are repeated.
            generic_catalog = not concepts(objective) and bool(
                set(words(group.get("label", ""))) & (_CATALOG | {"tools", "products", "services"})
            )
            if not relevant and not heading_score and not generic_catalog:
                continue
            choices.append((4 * heading_score + 3 * relevant, len(mapped), capture))
            break
    if not choices:
        return None
    _, _, capture = max(choices, key=lambda choice: (choice[0], choice[1], -choice[2].group))
    return Decision(decision="CAPTURE_RECORDS", capture=capture,
                    observation="Observed repeated records with distinct names and descriptions",
                    reason="Capture coherent candidates before navigating further; qualify each against the objective",
                    confidence=0.9, expected_result="Source-backed candidate records for semantic classification")


def unchanged_scrolls(observation, actions):
    count = 0
    for action in reversed(actions):
        outcome = action.get("outcome")
        if (action.get("action") not in {"SCROLL", "SCROLL_BACK"} or not isinstance(outcome, dict)
                or outcome.get("after_url") != observation.get("url")
                or outcome.get("record_groups_changed") or outcome.get("content_changed")
                or outcome.get("information_progress")):
            break
        count += 1
    return count


def ranked_excerpt(objective, text, *, limit=1400):
    """Return literal bounded excerpts rather than synthetic summaries."""
    if not isinstance(text, str):
        return ""
    chunks = []
    for block in re.split(r"\n{1,}|(?<=[.!?])\s+", text[:160000]):
        block = block.strip()
        for offset in range(0, len(block), 500):
            chunk = block[offset:offset + 500].strip()
            if chunk:
                chunks.append((relevance(objective, chunk), len(chunks), chunk))
    selected, used = [], 0
    for score, index, chunk in sorted(chunks, key=lambda item: (-item[0], item[1])):
        if used >= limit:
            break
        chunk = chunk[:max(0, limit - used - 2)]
        if chunk:
            selected.append((index, chunk))
            used += len(chunk) + 2
    return "\n\n".join(chunk for _, chunk in sorted(selected))


def compact_page(observation, objective, *, elements, groups, actions=(), form_input=False):
    """Preserve exact IDs and small, relevant page excerpts for read-side decisions."""
    available = [element for element in elements if element.get("actionable")
                 and not element.get("blocked_by_modal") and not element.get("disabled")]
    if not form_input:
        available = [element for element in available
                     if element.get("role") not in {"textbox", "searchbox", "combobox", "spinbutton", "checkbox",
                                                    "radio", "switch", "option"} and not element.get("form")]
    available.sort(key=lambda element: -source_score(objective, element))
    fields = {"element_id", "role", "name", "href", "tag", "type", "actionable", "visible",
              "disabled", "readonly", "form", "focused", "context", "expanded", "selected", "blocked_by_modal"}
    concise = []
    for element in available[:18]:
        row = {key: value for key, value in element.items() if key in fields}
        row["name"] = row.get("name", "")[:160]
        if isinstance(row.get("context"), dict):
            row["context"] = {key: str(value)[:120] for key, value in row["context"].items()
                              if key in {"heading", "region"}}
        concise.append(row)
    ranked = sorted(groups, key=lambda group: (
        group.get("kind") == "detail",
        -relevance(objective, str(group.get("label", "")) + " " + str(group.get("examples", []))),
    ))
    page = {key: observation[key] for key in (
        "url", "title", "tab_id", "http_status", "scroll", "dialogs", "fingerprint", "directory_candidates",
    ) if key in observation}
    page.update(text=ranked_excerpt(objective, observation.get("text", "")),
                viewport_text=ranked_excerpt(objective, observation.get("viewport_text", ""), limit=350),
                headings=observation.get("headings", [])[:8], elements=concise,
                record_groups=ranked[:5], research_chunks=observation.get("research_chunks", [])[:4],
                unchanged_scrolls=unchanged_scrolls(observation, actions),
                note="Record groups and text are observed candidates, not proof of membership. "
                     "Prefer capturing or classifying records to scrolling unchanged content.")
    return page


def task_token_allowance(maximum, spent, *, fallback_reserve, primary, purpose=None, handoff=False):
    """Never reserve already spent tokens; preserve a small finalization reserve."""
    remaining = max(0, maximum - spent)
    final = (min(4000, maximum // 10, remaining // 2) if purpose == "decide" else
             min(2000, maximum // 20, remaining // 3) if purpose == "classify" else 0)
    available = remaining - final
    fallback = min(fallback_reserve, maximum // 3, available // 3) if primary and not handoff else 0
    return max(0, available - fallback), fallback, final
