"""Read-only directory collection using visible records and the existing controller."""
from datetime import datetime, timezone
import hashlib
import json
import re
from urllib.parse import parse_qsl, urlsplit

from .contracts import Decision, Target

_DIRECTORY = re.compile(r"(?:list|collect|show|find)\s+(?:all|every)\s+(ai chatbots?|ai tools?|products?|directory entries|articles)[.!]?", re.I)
_CHATBOT = re.compile(r"\b(?:ai\s+)?chatbot(?:s)?\b|\bconversational\s+ai\b", re.I)
_NEGATIVE_TYPES = {"image generator", "video editor", "audio editor", "seo tool", "code editor", "image editor",
                   "analytics tool", "transcription tool", "design tool"}
_FORWARD = re.compile(r"(?:next(?: page)?(?:[ ?â€ºÂ»]+)?|load more(?: results| tools| products)?|show more(?: results)?)", re.I)

# DOM reads only. Skip hidden/sensitive containers and bound both cardinality and output.
READ_DIRECTORY = r"""() => {
 const scope = document.querySelector('main,[role=main]');
 if (!scope) return null;
 const visible = e => !e.closest('[hidden],[inert],[aria-hidden=true],form,dialog,[role=dialog],nav,aside,footer') &&
   e.getClientRects().length && ['visible',''].includes(getComputedStyle(e).visibility);
 const clean = s => (s || '').replace(/\s+/g, ' ').trim();
 const totalPattern = /^showing\s+(?:\d+\s*[-\u2013]\s*)?\d+\s+of\s+([\d,]+)\s+(?:matching\s+)?(tools|products|results|entries|articles|items)\b/i;
 const totals = [...scope.querySelectorAll('p,output,[role=status],[aria-live]')].slice(0, 500)
   .filter(e=>visible(e) && !e.closest('article,[role=listitem],li,tr,[itemscope]'))
   .map(e=>totalPattern.exec(clean(e.innerText).slice(0, 160))).filter(Boolean);
 if (!totals.length || totals.some(match=>match[1]!==totals[0][1] || match[2].toLowerCase()!==totals[0][2].toLowerCase())) return null;
 const total = totals[0];
 const candidates = [...scope.querySelectorAll('a[href],button,[role=button],[role=link]')];
 const forwardVisible = candidates.filter(e=>e.getClientRects().length && getComputedStyle(e).visibility==='visible' &&
   !e.closest('[hidden],[inert],[aria-hidden=true],dialog,[role=dialog]') &&
   /^(?:next(?: page)?(?:[ ???]+)?|load more(?: results| tools| products)?|show more(?: results)?)$/i.test(clean(e.getAttribute('aria-label') || e.innerText)));
 const semanticSelector = 'article,[role=listitem],li,tbody tr,[itemscope]';
 const cards = [...scope.querySelectorAll(semanticSelector)].filter(visible);
 // Some accessible cards use an overlay link instead of a heading. Identify
 // repeated sibling containers by a direct labeled link and visible content.
 const overlayCandidates = new Map();
 for (const anchor of [...scope.querySelectorAll('div > a[href][aria-label]')].slice(0, 500)) {
   const card = anchor.parentElement;
   const group = card.parentElement;
   if (!group || card.closest(semanticSelector) || !visible(card) || !visible(anchor)) continue;
   const name = clean(anchor.getAttribute('aria-label')).slice(0, 180);
   const text = clean(card.innerText).slice(0, 1400);
   const content = [...card.children].find(child => child !== anchor && visible(child));
   if (!name || !text.includes(name) || !content || text.length < name.length + 20) continue;
   const siblings = overlayCandidates.get(group) || new Map();
   if (!siblings.has(card)) siblings.set(card, {anchor, name});
   overlayCandidates.set(group, siblings);
 }
 const overlays = new Map();
 for (const siblings of overlayCandidates.values()) {
   if (siblings.size < 2) continue;
   for (const [card, value] of siblings) {
     cards.push(card);
     overlays.set(card, value);
   }
 }
 const groups = new Map();
 const suppressed = new Set();
 for (const card of cards.slice(0, 500)) {
   if (suppressed.has(card)) continue;
   const title = card.querySelector('h2,h3,h4,[itemprop=name],th[scope=row],td:first-child');
   const overlay = overlays.get(card);
   const anchor = overlay?.anchor || title?.closest('a[href]') || title?.querySelector('a[href]') || card.querySelector('a[href]');
   if ((!overlay && (!title || !visible(title))) || !anchor || !visible(anchor)) continue;
   const name = overlay?.name || clean(title.innerText || title.textContent).slice(0, 180);
   const quote = clean(card.innerText).slice(0, 1400);
   if (!name || !quote.includes(name)) continue;
   const label = [...card.querySelectorAll('[itemprop=category],[data-category-label],.category')].find(visible);
   const category = clean(label?.innerText).slice(0, 160) ||
     (/(?:^|\n)\s*(?:category|type):\s*([^\n]+)/i.exec(card.innerText)?.[1] || '').trim().slice(0, 160);
   const paragraphs = [...card.querySelectorAll('p,[itemprop=description]')].filter(visible).slice(0, 5).map(n=>clean(n.innerText));
   const description = (paragraphs.length ? paragraphs : card.innerText.split('\n').map(clean).filter(line=>line.length>=35).slice(0, 4)).join(' ').slice(0, 600);
   const href = anchor.href;
   if (!/^https?:\/\//i.test(href) || href.length > 1800) continue;
   // Count one record per card, even when the card contains its own tag list.
   for (const nested of card.querySelectorAll('article,[role=listitem],li,tbody tr,[itemscope]')) suppressed.add(nested);
   const group = groups.get(card.parentElement) || [];
   group.push({name, category, description, href, quote});
   groups.set(card.parentElement, group);
 }
 const batches = [...groups.values()].sort((a,b)=>b.length-a.length);
 const rows = batches[0] || [];
 const filtered = [...scope.querySelectorAll('input[type=search],input[role=searchbox],input[placeholder*=search i]')].some(e=>e.getClientRects().length && e.value.trim()) ||
   [...scope.querySelectorAll('button[aria-pressed=true],select')].some(e=>visible(e) && /filter|tag|category|pricing/i.test(e.closest('fieldset,[role=group],section')?.getAttribute('aria-label')||e.name||'') && !/^(?:all|any)(?:\b|$)/i.test(e.innerText || e.selectedOptions?.[0]?.textContent || ''));
 return {rows:rows.slice(0, 150), total:Number(total[1].replace(/,/g,'')), kind:total[2].toLowerCase(), filtered:!!filtered,
   truncated:cards.length>500 || rows.length>150 || batches.slice(1).some(group=>group.length>1),
   forward_enabled:forwardVisible.filter(e=>!e.matches(':disabled,[aria-disabled=true]')).length,
   busy:!!scope.querySelector('[aria-busy=true]')};
}"""


def directory_intent(objective, options, has_dataset=False):
    match = _DIRECTORY.fullmatch(objective.strip())
    criteria = options.get("success_criteria", [])
    if not match or has_dataset or options.get("output_format") not in {None, "answer"}:
        return None
    if any(criterion.strip().casefold().rstrip(".!?") != objective.strip().casefold().rstrip(".!?")
           for criterion in criteria):
        return None
    return match[1].casefold()


def _classify(entity, row):
    if not entity.startswith("ai chatbot"):
        return "match"
    category = row["category"].strip().casefold()
    description = row["description"]
    if _CHATBOT.fullmatch(category) or re.search(r"\b(?:is|offers)\s+(?:an?\s+)?(?:ai\s+)?chatbot\b", description, re.I):
        return "match"
    if category in _NEGATIVE_TYPES and not _CHATBOT.search(description):
        return "excluded"
    return "unknown"


def _action(action, reason, **kwargs):
    return Decision(observation="Visible directory controls and record coverage", decision=action, reason=reason,
                    confidence=1, expected_result="Advance the directory collection", **kwargs)


def _directory_link(element):
    name = element.get("name", "").casefold()
    return re.match(r"^(?:(?:browse|view|explore)\s+(?:all\s+)?)?(?:ai\s+)?(?:tools|products|directory|articles)(?:$|\s+browse\b|\s+directory\b)", name)


class DirectoryCollection:
    def __init__(self, entity, state):
        self.entity = entity
        self.state = state
        for name, default in (("records", {}), ("pages", []), ("attempted", []), ("totals", [])):
            state.setdefault(name, default)

    def advance(self, observation, step_id, policy):
        """Return a validated existing browser action, a terminal reason, or general fallback."""
        state = self.state
        url = observation["url"]
        controls = [e for e in observation.get("elements", []) if e.get("visible") and not e.get("blocked_by_modal")]
        batch = observation.get("directory")
        if any(dialog.get("visible") for dialog in observation.get("dialogs", [])):
            return None, "A dialog obstructs the directory" if state["pages"] else None
        if not batch:
            if state["pages"]:
                return None, "Directory records disappeared before coverage could be verified"
            links = {}
            for element in controls:
                href = element.get("href")
                if element.get("actionable") and element.get("role") == "link" and href and _directory_link(element):
                    try:
                        href = policy.check(href)
                    except ValueError:
                        continue
                    if href != url and href not in state["attempted"]:
                        links[href] = element
            if len(links) == 1:
                href = next(iter(links))
                state["attempted"].append(href)
                return _action("NAVIGATE", "Open the observed directory link", url=href), None
            return None, None
        if batch["busy"]:
            state["loading_checks"] = state.get("loading_checks", 0) + 1
            if state["loading_checks"] <= 2:
                return _action("WAIT", "Wait for the directory to finish loading"), None
            return None, "The directory still reports that results are loading"
        state["loading_checks"] = 0

        parsed = urlsplit(url)
        scope = [parsed.scheme, parsed.netloc, parsed.path]
        if state.setdefault("scope", scope) != scope:
            return None, "Traversal left the original directory scope"
        expected_kinds = {"ai tools": {"tools", "products"}, "ai tool": {"tools", "products"},
                          "products": {"products"}, "product": {"products"}, "articles": {"articles"}}
        if self.entity in expected_kinds and batch.get("kind") not in expected_kinds[self.entity]:
            return None, "The visible collection is not the requested record type" if state["pages"] else None
        state["filtered"] = state.get("filtered", False) or batch["filtered"] or any(
            name.casefold() not in {"page", "p", "offset", "cursor"} for name, _ in parse_qsl(parsed.query)
        )
        state["truncated"] = state.get("truncated", False) or batch["truncated"]
        if batch["total"] not in state["totals"]:
            state["totals"].append(batch["total"])
        record_ids = set()
        for row in batch["rows"]:
            try:
                source = policy.check(row["href"])
            except ValueError:
                state["truncated"] = True
                continue
            key = source.split("#", 1)[0]
            record_ids.add(key)
            observed = _classify(self.entity, row)
            entry = {key: row[key] for key in ("name", "category", "description", "quote")}
            entry.update({"source_url": source, "observed_url": url, "classification": observed,
                     "method": "visible_directory", "observed_at": datetime.now(timezone.utc).isoformat(),
                     "step_id": step_id, "id": "directory-" + hashlib.sha256(key.encode()).hexdigest()[:24]})
            prior = state["records"].get(key)
            if prior and prior["classification"] != observed:
                prior["classification"] = "unknown"
            elif not prior and len(state["records"]) < 500:
                state["records"][key] = entry
            elif not prior:
                state["truncated"] = True
        signature = hashlib.sha256(json.dumps(sorted(record_ids)).encode()).hexdigest()
        if signature in state["pages"]:
            state["repeated_pages"] = state.get("repeated_pages", 0) + 1
            return None, "Pagination returned a previously collected record batch"
        state["pages"].append(signature)
        forward = [e for e in controls if _FORWARD.fullmatch(e.get("name", "").strip()) and e.get("role") in {"button", "link"}]
        actionable = [e for e in forward if e.get("actionable") and not e.get("form") and not e.get("disabled")]
        if len(actionable) == 1:
            element = actionable[0]
            if element.get("href"):
                href = element["href"]
                try:
                    href = policy.check(href)
                except ValueError:
                    return None, "The next directory page is outside the authorized scope"
                if href == url or href in state["attempted"]:
                    state["repeated_pages"] = state.get("repeated_pages", 0) + 1
                    return None, "The next directory link has already been visited"
                state["attempted"].append(href)
                return _action("NAVIGATE", "Read the next directory page", url=href), None
            return _action("CLICK", "Load the next visible directory batch", target=Target(element_id=element["element_id"])), None
        if actionable or batch.get("forward_enabled") or any(not e.get("disabled") for e in forward):
            return None, "No unique authorized forward pagination control was available"
        state["terminal"] = True
        reason = self.blocker()
        return None, reason or ""

    def blocker(self):
        state = self.state
        if state.get("filtered") or state.get("truncated"):
            return "The directory was filtered or only part of it could be read"
        if len(state["totals"]) != 1 or len(state["records"]) != state["totals"][0]:
            return "Unique records do not match the directory's advertised total"
        if any(row["classification"] == "unknown" for row in state["records"].values()):
            return "Some products could not be classified from their visible category or description"
        return None


def directory_result(state, reason=None):
    rows = list(state.get("records", {}).values())
    matches = [row for row in rows if row["classification"] == "match"]
    total = state["totals"][0] if len(state.get("totals", [])) == 1 else None
    explanation = reason or f"Classified all {len(rows)} unique records in the visible directory and reached its last page."
    return {
        "strategy": "directory_collection",
        "partial": reason is not None,
        "directory": {"records": matches, "unique_records": len(rows), "advertised_total": total,
                      "unknown": sum(row["classification"] == "unknown" for row in rows),
                      "pages": len(state.get("pages", [])), "repeated_pages": state.get("repeated_pages", 0)},
        "claims": [{"text": row["name"], "evidence_ids": [row["id"]]} for row in matches],
        "evidence": [{"id": row["id"], "url": row["observed_url"], "quote": row["quote"], "step_id": row["step_id"],
                      "source_url": row["source_url"], "method": row["method"], "observed_at": row["observed_at"]}
                     for row in matches],
        "verification": {"complete": reason is None, "explanation": explanation},
    }
