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
from .structure import RecordCapture, group_signature, map_group, rejected_group

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
    try:
        path = set(words(urlsplit(href).path))
    except ValueError:
        return -100
    context = element.get("context")
    context = str(context.get("heading", "")) if isinstance(context, dict) else ""
    topical = relevance(objective, name)
    score = 5 * topical + 2 * relevance(objective, context) + relevance(objective, href)
    score += 8 * bool((label | path) & _CATALOG)
    score += 2 * bool(label & {"tools", "products", "services"})
    score -= 4 * bool(label & _EDITORIAL)
    return score


def source_eligible(objective, element, *, catalog_only=False):
    name = element.get("name") or ""
    path = urlsplit(element.get("href") or "").path
    label = set(words(name))
    path_words = set(words(path))
    family = {"tool", "tools", "product", "products", "software", "app", "apps",
              "application", "applications", "service", "services"}
    generic_catalog = bool((label | path_words) & _CATALOG)
    if catalog_only and (not generic_catalog or label & _EDITORIAL):
        return False
    if relevance(objective, name) or relevance(objective, path):
        return True
    # A broad product inventory is useful for narrower product queries, but
    # unrelated libraries are not automatically relevant just because of type.
    broad_words = family | _CATALOG | {"all", "view", "see", "explore", "open", "our", "the", "by", "use", "case", "cases", "ai", "of", "and"}
    return (generic_catalog and bool(set(words(objective)) & family) and bool(label & family)
            and not (label - broad_words))


def observed_links(observation, objective, policy, *, excluded=(), catalog_only=False):
    if any(dialog.get("visible") for dialog in observation.get("dialogs", [])):
        return []
    excluded = set(excluded) | {destination_key(observation["url"])}
    candidates = {}
    for element in observation.get("elements", []):
        href = element.get("href")
        if (not href or not element.get("actionable") or element.get("visible") is False or element.get("disabled")
                or element.get("blocked_by_modal") or element.get("form")
                or element.get("role") != "link"):
            continue
        try:
            parsed = urlsplit(href)
            # Do not normalize an in-page fragment into a full navigation.
            if parsed.fragment:
                continue
            href = policy.check(href)
        except ValueError:
            continue
        if urlsplit(href).scheme not in {"http", "https"} or destination_key(href) in excluded:
            continue
        if not source_eligible(objective, {**element, "href": href}, catalog_only=catalog_only):
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


def automatic_capture(observation, groups, objective, *, rejected=(), max_rows=48, diagnostics=None):
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
    diagnostics = diagnostics if diagnostics is not None else {}
    diagnostics.update(record_groups=len(offered), candidate_rows=0, mapping_rejections={})
    def reject(reason):
        counts = diagnostics["mapping_rejections"]
        counts[reason] = counts.get(reason, 0) + 1
    for group in groups.values():
        if group["id"] not in offered:
            continue
        if group.get("kind") not in {"repeated", "row", "semantic"} or rejected_group(observation["url"], group, rejected):
            reject("unsupported_or_rejected_group")
            continue
        rows = group.get("records", [])
        diagnostics["candidate_rows"] += len(rows)
        if not 2 <= len(rows) <= max_rows:
            reject("row_count_outside_automatic_budget")
            continue
        example = rows[0].get("segments", [])[:12]
        identities = [index for index, segment in enumerate(example, 1)
                      if _field_label(segment) in _IDENTITY and not segment.get("truncated")]
        if not identities and len(example) >= 2 and not _field_label(example[0]) and 0 < len(example[0].get("value", "")) <= 160:
            if all(row.get("segments") and not _field_label(row["segments"][0]) for row in rows):
                identities = [1]
        if len(identities) != 1:
            reject("ambiguous_identity")
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
        if not descriptions:
            reject("missing_description")
        matched_mapping = False
        for _, _, position in sorted(descriptions, reverse=True):
            capture = RecordCapture(group=group["id"], identity=identity, fields=[
                {"name": "Name", "position": identity}, {"name": "Description", "position": position},
            ], restrict_to_objective=True)
            try:
                # Automatic mapping must not silently skip ambiguous rows.
                strict = map_group(group, capture)
                mapped = map_group(group, capture, preserve_context=True)
            except ValueError:
                continue
            if len(strict) != len(rows) or set(strict) != set(mapped):
                continue
            if len({" ".join(name.casefold().split()) for name in mapped}) != len(mapped):
                reject("duplicate_identity")
                continue
            if not _field_label(example[position - 1]) and any(
                len(row.get("segments", [])) < position
                or _field_label(row["segments"][position - 1])
                for row in rows
            ):
                continue
            if any(len(name) > 220 or len(words(name)) > 20 or
                   len(fields["Description"]) < 25 or
                   fields["Description"] == fields["Name"]
                   for name, (fields, _) in mapped.items()):
                continue
            relevant = sum(bool(relevance(objective, fields["Description"])) for fields, _ in mapped.values())
            heading_score = relevance(objective, group.get("label", ""))
            # Unrelated cards remain available to the model, but don't spend a
            # classification batch on them purely because they are repeated.
            generic_catalog = not concepts(objective) and bool(
                set(words(group.get("label", ""))) & (_CATALOG | {"tools", "products", "services"})
            )
            if not relevant and not heading_score and not generic_catalog:
                reject("low_lexical_relevance")
                continue
            choices.append((4 * heading_score + 6 * relevant / len(mapped) - (0.5 if group.get("kind") == "semantic" else 0), relevant, capture))
            matched_mapping = True
            break
        if descriptions and not matched_mapping:
            reject("no_confident_mapping")
    if not choices:
        diagnostics["strategy"] = "model_assisted"
        return None
    diagnostics["strategy"] = "automatic_capture"
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
                or outcome.get("information_progress", bool(outcome.get("record_groups_changed")
                                                            or outcome.get("content_changed")))):
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


def compact_page(observation, objective, *, elements, groups, actions=(), form_input=False, read_search=False):
    """Preserve exact IDs and small, relevant page excerpts for read-side decisions."""
    available = [element for element in elements if element.get("actionable")
                 and element.get("visible") is not False
                 and not element.get("blocked_by_modal") and not element.get("disabled")]
    if not form_input:
        available = [element for element in available
                     if (read_search and search_control(element)) or (
                         element.get("role") not in {"textbox", "searchbox", "combobox", "spinbutton", "checkbox",
                                                     "radio", "switch", "option"} and not element.get("form"))]
    available.sort(key=lambda element: (not (read_search and search_control(element)), -source_score(objective, element)))
    fields = {"element_id", "role", "name", "href", "tag", "type", "actionable", "visible",
              "disabled", "readonly", "form", "focused", "context", "expanded", "selected", "blocked_by_modal"}
    concise = []
    for element in available[:18]:
        row = {key: value for key, value in element.items() if key in fields}
        if row.get("href"):
            try:
                urlsplit(row["href"])
            except ValueError:
                continue
        row["name"] = (row.get("name") or "")[:160]
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
                record_groups=[{**group, "examples": group.get("examples", [])[:2]} for group in ranked[:5]],
                research_chunks=observation.get("research_chunks", [])[:4],
                unchanged_scrolls=unchanged_scrolls(observation, actions),
                discovery=observation.get("discovery", {}),
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


_READ_INTENTS = {"structured_extraction", "research", "comparison", "search"}
_NO_SEARCH = re.compile(
    r"\b(?:do\s+not|must\s+not|never|without|no|don['’]t|avoid)\s+"
    r"(?:(?:use|using|perform|performing|fill|filling)\s+)?(?:(?:the|a|any|site|website|read.only)\s+)*"
    r"(?:search(?:es|ing|\s+bars?)?|forms?|form input|enter(?:ing)?\s+(?:text|data)|submit(?:ting)?|submissions?)\b",
    re.I,
)
MAX_SEARCH_ATTEMPTS = 8


def read_search_permission(objective, options, intent, criteria=()):
    return (options.get("mode") == "autonomous" and options.get("allow_search_input") is True
            and intent in _READ_INTENTS
            and not any(_NO_SEARCH.search(text) for text in [objective, *criteria]))


def search_control(element):
    form = element.get("form") or {}
    return bool(element.get("actionable") and element.get("visible") is not False
                and not any(element.get(key) for key in ("disabled", "readonly", "sensitive", "blocked_by_modal"))
                and element.get("tag") == "input" and element.get("type") in {"search", "text"}
                and element.get("role") in {"searchbox", "textbox"}
                and form.get("search") and form.get("method") == "GET" and valid_search_action(form.get("action")))


def valid_search_action(value):
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = urlsplit(value)
        return bool(parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username
                    and not parsed.password and not parsed.fragment)
    except ValueError:
        return False


def objective_query(objective):
    query = re.sub(r"^\s*(?:please\s+)?(?:list|find|search(?:\s+for)?|look\s+up|show(?:\s+me)?|identify|recommend)\s+(?:all\s+)?", "", objective, flags=re.I)
    normalized = " ".join(query.split()).strip(" .?!,")
    if len(normalized) > 200:
        normalized = normalized[:201].rsplit(" ", 1)[0]
    return normalized if len(normalized) <= 200 else ""


def search_query_allowed(objective, query):
    return bool(isinstance(query, str) and 0 < len(query) <= 200 and words(query)
                and set(words(query)) <= set(words(objective)))


def search_attempt_key(element, query):
    action = urlsplit((element.get("form") or {}).get("action", ""))
    return action._replace(query="", fragment="").geturl() + "\n" + " ".join(words(query))


def search_candidate(observation, objective, policy, attempts):
    query = objective_query(objective)
    if (len(attempts) >= MAX_SEARCH_ATTEMPTS or not search_query_allowed(objective, query)
            or any(d.get("visible") for d in observation.get("dialogs", []))):
        return None
    for element in observation.get("elements", []):
        if not search_control(element):
            continue
        try:
            policy.check(element["form"]["action"])
            if search_attempt_key(element, query) in attempts:
                continue
        except ValueError:
            continue
        return Decision(decision="SEARCH", target={"element_id": element["element_id"]}, text=query,
                        observation="An authorized GET search field is visible",
                        reason="Search for the requested entities before exploring more pages",
                        confidence=0.85, expected_result="Relevant search results to inspect and qualify")
    return None


def update_frontier(frontier, observation, objective, policy, excluded):
    excluded = set(excluded) | {destination_key(observation["url"])}
    candidates = {key: value for key, value in frontier.items() if key not in excluded}
    for score, url in observed_links(observation, objective, policy, excluded=excluded):
        key = destination_key(url)
        if score > candidates.get(key, {}).get("score", 0):
            candidates[key] = {"url": url, "score": score, "observed_on": observation["url"]}
    return dict(sorted(candidates.items(), key=lambda item: (-item[1]["score"], item[0]))[:60])


def frontier_candidate(frontier, observation, policy, excluded, *, minimum=5):
    if any(dialog.get("visible") for dialog in observation.get("dialogs", [])):
        return None
    excluded = set(excluded) | {destination_key(observation["url"])}
    for key, item in sorted(frontier.items(), key=lambda pair: (-pair[1]["score"], pair[0])):
        if key in excluded or item["score"] < minimum:
            continue
        try:
            url = policy.check(item["url"])
        except ValueError:
            continue
        if destination_key(url) != key:
            continue
        return Decision(decision="NAVIGATE", url=url, observation="Previously observed authorized unexplored source",
                        reason="Recover discovery using a ranked unexplored source", confidence=0.75,
                        expected_result="Inspect fresh source for qualifying evidence")
    return None


def relevant_group_signatures(observation, objective):
    return {group_signature(group) for group in observation.get("record_groups", [])
            if relevance(objective, str(group.get("examples", [])))
            and group.get("observed_count", 0) > 0}
