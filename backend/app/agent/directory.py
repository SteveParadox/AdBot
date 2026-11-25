"""Read-only directory collection using visible records and the existing controller."""
from datetime import datetime, timezone
import hashlib
import json
import re
from urllib.parse import parse_qsl, urlsplit

from .classification import primary_chatbot_role
from .contracts import Decision, Target
from .routing import directory_intent  # noqa: F401

_CHATBOT = re.compile(r"\b(?:ai\s+)?chatbot(?:s)?\b|\bconversational\s+ai\b", re.I)
_NEGATIVE_TYPES = {"image generator", "video editor", "audio editor", "seo tool", "code editor", "image editor",
                   "analytics tool", "transcription tool", "design tool"}
_FORWARD = re.compile(r"(?:next(?: page| results| products| tools| articles)?(?:[ \u2192\u203a\u00bb]+)?|(?:load|show) more(?: results| tools| products| articles| entries)?)", re.I)
_PAGE = re.compile(r"(?:page\s+)?(\d+)", re.I)
_PRODUCT_ENTITIES = {"ai chatbots", "ai tools", "products"}
_NON_PRODUCT_KINDS = {"articles", "rankings", "guides", "collections", "reviews"}


def pagination_element(element):
    if element.get("role") not in {"button", "link"}:
        return False
    region = (element.get("context") or {}).get("name", "")
    return ("next" in (element.get("rel") or "").split() or bool(_FORWARD.fullmatch(element.get("name", "").strip()))
            or bool(re.search(r"pag(?:e|ination)|results", region, re.I) and _PAGE.fullmatch(element.get("name", "").strip())))


# DOM reads only. Skip hidden/sensitive containers and bound both cardinality and output.
READ_DIRECTORY = r"""({limit=250, table=false}={}) => {
 const scope = document.querySelector('main,[role=main]') || document.body;
 if (!scope) return null;
 const visible = e => !e.closest('[hidden],[inert],[aria-hidden=true],form,dialog,[role=dialog],nav,aside,footer') &&
   e.getClientRects().length && ['visible',''].includes(getComputedStyle(e).visibility);
 const clean = s => (s || '').replace(/\s+/g, ' ').trim();
 const totalPattern = /^(?:showing\s+(?:\d+\s*[-\u2013]\s*)?\d+\s+(?:of|out of)\s+|total:\s*)?([\d,]+)\s+(?:matching\s+)?(tools|products|results|entries|articles|items|rows|rankings|guides|collections|reviews)(?:\s+found)?[.]?$/i;
 const totals = [...scope.querySelectorAll('p,output,[role=status],[aria-live],[data-total-results]')].slice(0, 500)
   .filter(e=>visible(e) && !e.closest('article,[role=listitem],li,tr,[itemscope]'))
   .map(e=>totalPattern.exec(clean(e.innerText).slice(0, 160))).filter(Boolean);
 const total = totals.length && totals.every(match=>match[1]===totals[0][1] && match[2].toLowerCase()===totals[0][2].toLowerCase()) ? totals[0] : null;
 const candidates = [...scope.querySelectorAll('a[href],button,[role=button],[role=link]')];
 const controlVisible = e=>e.getClientRects().length && getComputedStyle(e).visibility==='visible' &&
   !e.closest('[hidden],[inert],[aria-hidden=true],dialog,[role=dialog]');
 const controlName = e=>clean(e.getAttribute('aria-label') || e.innerText);
 const forward = candidates.filter(e=>controlVisible(e) && (e.rel?.split(/\s+/).includes('next') ||
   /^(?:next(?: page| results| products| tools| articles)?(?:[ \u2192\u203a\u00bb]+)?|(?:load|show) more(?: results| tools| products| articles| entries)?)$/i.test(controlName(e))));
 const pagination = [...scope.querySelectorAll('nav[aria-label],[role=navigation][aria-label]')]
   .filter(e=>/paginat|pages/i.test(e.getAttribute('aria-label')) && controlVisible(e));
 const currentNumbers = pagination.flatMap(nav=>[...nav.querySelectorAll('[aria-current=page]')].map(e=>/^(?:page\s+)?(\d+)$/i.exec(controlName(e))?.[1]).filter(Boolean));
 const current = currentNumbers.length && currentNumbers.every(n=>n===currentNumbers[0]) ? Number(currentNumbers[0]) : null;
 const numbered = pagination.flatMap(nav=>[...nav.querySelectorAll('a[href],button,[role=link],[role=button]')]).filter(e=>{
   const page = /^(?:page\s+)?(\d+)$/i.exec(controlName(e));
   return controlVisible(e) && page && (current===null || Number(page[1])>current);
 });
 const enabled = e=>!e.matches(':disabled,[aria-disabled=true]') && !e.closest('[aria-disabled=true]');
 const busy = !!scope.querySelector('[aria-busy=true]');
 const heading = clean(scope.querySelector('h1,[role=heading]')?.textContent);
 const kind = total?.[2]?.toLowerCase() ||
   (/\b(?:rankings|guides|collections|reviews|articles)\b/i.exec(heading)?.[0]?.toLowerCase()) ||
   (/\b(?:tools|products)\b/i.exec(heading)?.[0]?.toLowerCase() || null);
 const availableForward = new Set([...forward,...numbered].filter(enabled)).size;
 if (table) {
   const tables = [...scope.querySelectorAll('table')].filter(visible);
   if (tables.length!==1) return null;
   const t = tables[0];
   const headers = [...t.querySelectorAll('thead tr:last-child th,thead tr:last-child td')].filter(visible).map(e=>clean(e.innerText).slice(0, 100));
   const members = [...t.querySelectorAll('tbody tr')].filter(e=>visible(e) && e.querySelector('td') && e.closest('table')===t);
   const rows = members.slice(0,limit).map((row,index)=>{
     const cells = [...row.cells].filter(visible).slice(0,32).map(e=>clean(e.innerText).slice(0,250));
     const quote = cells.join(' | ').slice(0,1400);
     return {name:quote.slice(0,800),category:'',description:'',href:location.href,quote,
             cells,headers:headers.slice(0,32),row_key:JSON.stringify(cells), row_index:index};
   }).filter(row=>row.quote);
   const declared = /^\d+$/.test(t.getAttribute('aria-rowcount') || '') ? Number(t.getAttribute('aria-rowcount')) : null;
   const staticTable = !total && declared===null && !forward.length && !pagination.length && !busy &&
     !t.querySelector('[aria-rowindex]') && !t.hasAttribute('aria-rowcount') && !t.closest('[data-virtualized]');
   return {rows,total:total?Number(total[1].replace(/,/g,'')):declared??(staticTable?members.length:null),kind:'rows',
     filtered:false,truncated:members.length>limit || rows.length!==members.length || headers.length>32 ||
       members.slice(0,limit).some(row=>[...row.cells].filter(visible).some(cell=>clean(cell.innerText).length>250)) ||
       rows.some(row=>row.cells.length>=32 || row.cells.join(' | ').length>1400),
     current_page:current,forward_enabled:availableForward,busy,unpaginated:staticTable};
 }
 const semanticSelector = 'article,[role=listitem],li,tbody tr,[itemscope]';
 const cards = [...scope.querySelectorAll(semanticSelector)].filter(visible);
 // Identify repeated sibling cards with a direct link and visible content.
 const overlayCandidates = new Map();
 const scanLimit = Math.max(500,limit*3);
 for (const anchor of [...scope.querySelectorAll('div > a[href]')].slice(0, scanLimit)) {
   const card = anchor.parentElement;
   const group = card.parentElement;
   if (!group || card.closest(semanticSelector) || !visible(card) || !visible(anchor)) continue;
   const name = clean(anchor.getAttribute('aria-label') || anchor.innerText).slice(0, 180);
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
 for (const card of cards.slice(0, scanLimit)) {
   if (suppressed.has(card)) continue;
   const title = card.querySelector('h2,h3,h4,[itemprop=name],th[scope=row],td:first-child');
   const overlay = overlays.get(card);
   const anchor = overlay?.anchor || title?.closest('a[href]') || title?.querySelector('a[href]') || card.querySelector('a[href]');
   if ((!overlay && title && !visible(title)) || !anchor || !visible(anchor)) continue;
   const name = overlay?.name || clean(title?.innerText || title?.textContent || anchor.innerText).slice(0, 180);
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
 if (!total && rows.length<2 && !busy) return null;
 return {rows:rows.slice(0, limit), total:total?Number(total[1].replace(/,/g,'')):null, kind, filtered:!!filtered,
   truncated:cards.length>scanLimit || rows.length>limit || batches.slice(1).some(group=>group.length>1),
   current_page:current, forward_enabled:availableForward, busy};
}"""


def _classify(entity, row):
    if entity.startswith("semantic:"):
        return "unknown", None
    if not entity.startswith("ai chatbot"):
        return "match", None
    category = row["category"].strip().casefold()
    description = row["description"]
    primary, quote = primary_chatbot_role(row)
    if primary != "unknown":
        return primary, quote
    if _CHATBOT.fullmatch(category):
        return "match", None
    if category in _NEGATIVE_TYPES and not _CHATBOT.search(description):
        return "excluded", None
    return "unknown", None


def _action(action, reason, **kwargs):
    return Decision(observation="Visible directory controls and record coverage", decision=action, reason=reason,
                    confidence=1, expected_result="Advance the directory collection", **kwargs)


def directory_link(element, entity=None):
    name = element.get("name", "").casefold()
    match = re.match(r"^(?:(?:browse|view|explore)\s+(?:all\s+)?)?(?:ai\s+)?(tools|products|directory|articles|tables)(?:$|\s+browse\b|\s+directory\b)", name)
    return bool(match and (entity not in _PRODUCT_ENTITIES or match[1] in {"tools", "products", "directory"}))


def _collection_path(path):
    return re.sub(r"/page/\d+$", "", path.rstrip("/")) or "/"


class DirectoryCollection:
    def __init__(self, entity, state, *, max_rows=2000, max_bytes=4_000_000):
        self.entity = entity
        self.max_rows = max_rows
        self.max_bytes = max_bytes
        self.state = state
        for name, default in (("records", {}), ("pages", []), ("attempted", []), ("totals", [])):
            state.setdefault(name, default)

    def advance(self, observation, step_id, policy):
        """Return a validated existing browser action, a terminal reason, or general fallback."""
        state = self.state
        url = observation["url"]
        state.setdefault("entity", self.entity)
        state["terminal"] = False
        if "record_bytes" not in state:
            state["record_bytes"] = sum(self.record_size(row) for row in state["records"].values())
        controls = [e for e in observation.get("elements", []) if e.get("visible") and not e.get("blocked_by_modal")]
        batch = observation.get("directory")
        if any(dialog.get("visible") for dialog in observation.get("dialogs", [])):
            return None, "A dialog obstructs the directory" if state["pages"] else None
        wrong_kind = self.entity in _PRODUCT_ENTITIES and batch and batch.get("kind") in _NON_PRODUCT_KINDS
        if not batch or wrong_kind:
            if state["pages"]:
                return None, ("The visible collection changed to a different record type" if wrong_kind else
                              "Directory records disappeared before coverage could be verified")
            links = {}
            for element in controls:
                href = element.get("href")
                if element.get("actionable") and element.get("role") == "link" and href and directory_link(element, self.entity):
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
        scope = [parsed.scheme, parsed.netloc, _collection_path(parsed.path)]
        prior_scope = state.setdefault("scope", scope)
        if [*prior_scope[:2], _collection_path(prior_scope[2])] != scope:
            return None, "Traversal left the original directory scope"
        state["scope"] = scope
        expected_kinds = {"ai tools": {"tools", "products"}, "ai tool": {"tools", "products"},
                          "products": {"products"}, "product": {"products"}, "articles": {"articles"}}
        if self.entity in expected_kinds and batch.get("kind") not in expected_kinds[self.entity]:
            return None, "The visible collection is not the requested record type" if state["pages"] else None
        state["filtered"] = state.get("filtered", False) or batch["filtered"] or any(
            name.casefold() not in {"page", "p", "offset", "cursor"} for name, _ in parse_qsl(parsed.query)
        )
        state["truncated"] = state.get("truncated", False) or batch["truncated"]
        if batch["total"] is not None and batch["total"] not in state["totals"]:
            state["totals"].append(batch["total"])
        record_ids = set()
        for row in batch["rows"]:
            try:
                source = policy.check(row["href"])
            except ValueError:
                state["truncated"] = True
                continue
            key = source.split("#", 1)[0]
            if self.entity == "table rows":
                key = "table-row:" + hashlib.sha256(row["row_key"].encode()).hexdigest()
                if batch.get("unpaginated"):
                    key += f":{row['row_index']}"
            record_ids.add(key)
            observed, classification_quote = _classify(self.entity, row)
            entry = {key: row[key] for key in ("name", "category", "description", "quote")}
            if self.entity == "table rows":
                entry.update(cells=row["cells"], headers=row["headers"])
            entry.update({"source_url": source, "observed_url": url, "classification": observed,
                     "method": "visible_directory", "observed_at": datetime.now(timezone.utc).isoformat(),
                     "step_id": step_id, "id": "directory-" + hashlib.sha256(key.encode()).hexdigest()[:24]})
            if classification_quote:
                entry["classification_quote"] = classification_quote
            prior = state["records"].get(key)
            if prior:
                if prior["method"] == "semantic_directory":
                    if (observed != "unknown" and observed != prior["classification"]) or prior["classification_quote"] not in row["quote"]:
                        prior.update(classification="unknown", classification_conflict=True, method="visible_directory")
                        prior.pop("classification_quote", None)
                elif prior["classification"] != observed:
                    prior.update(classification="unknown", classification_conflict=True)
                    prior.pop("classification_quote", None)
            elif not prior:
                size = self.record_size(entry)
                if len(state["records"]) >= self.max_rows or state["record_bytes"] + size > self.max_bytes:
                    state["resource_limit"] = True
                    continue
                state["records"][key] = entry
                state["record_bytes"] += size
        signature = hashlib.sha256(json.dumps(sorted(record_ids)).encode()).hexdigest()
        repeated = signature in state["pages"]
        if not repeated:
            state["pages"].append(signature)
        elif state.get("repeat_at") != signature:
            state["repeated_pages"] = state.get("repeated_pages", 0) + 1
        state["repeat_at"] = signature if repeated else None
        if state.get("resource_limit"):
            return None, "Collection reached its configured record or storage budget"
        return self.traverse(observation, batch, controls, signature, repeated, policy)

    def traverse(self, observation, batch, controls, signature, repeated, policy):
        state = self.state
        url = observation["url"]
        tried = state.setdefault("traversal_attempts", {})
        forward = [element for element in controls if pagination_element(element)]
        choices = []
        for element in forward:
            if not element.get("actionable") or element.get("form") or element.get("disabled"):
                continue
            name = element.get("name", "").strip()
            match = _PAGE.fullmatch(name)
            number = int(match[1]) if match else None
            current = batch.get("current_page")
            if number is not None and current is not None and number <= current:
                continue
            href = element.get("href")
            if href:
                try:
                    href = policy.check(href)
                except ValueError:
                    continue
                if href == url or href in state["attempted"]:
                    continue
                destination = urlsplit(href)
                if [destination.scheme, destination.netloc, _collection_path(destination.path)] != state["scope"]:
                    continue
            key = f"{signature}:{href or name.casefold()}"
            if key in tried:
                continue
            # An explicit forward control is preferred. On recovery choose the
            # next numbered link or other observed path once per record state.
            choices.append((number is not None, number or 0, href or name, key, href, element))
        if choices:
            choices.sort(key=lambda item: item[:3])
            _, _, _, key, href, element = choices[0]
            if len(tried) >= 500:
                return None, "Collection reached its bounded traversal attempt limit"
            tried[key] = True
            if repeated:
                state["recovery_actions"] = state.get("recovery_actions", 0) + 1
            if href:
                state["attempted"].append(href)
                return _action("NAVIGATE", "Read an alternative directory page" if repeated else "Read the next directory page", url=href), None
            state["last_pager"] = {"signature": signature, "url": url, "name": element["name"].casefold()}
            return _action("CLICK", "Try an alternative observed pagination control" if repeated else "Load the next visible directory batch",
                           target=Target(element_id=element["element_id"])), None
        # Some client-rendered pagers are enabled before their handler is ready.
        # Wait and reassess the live control once before a single read-only retry.
        previous = state.get("last_pager") or {}
        same_pager = [element for element in forward if not element.get("href") and not element.get("form")
                      and element.get("actionable") and not element.get("disabled")
                      and element.get("name", "").casefold() == previous.get("name")]
        retry_key = f"{signature}:ready_retry"
        if repeated and previous.get("signature") == signature and previous.get("url") == url and len(same_pager) == 1:
            if retry_key not in tried:
                tried[retry_key] = "waiting"
                state["recovery_actions"] = state.get("recovery_actions", 0) + 1
                return _action("WAIT", "Wait for the client-rendered pager before reassessing it"), None
            if tried[retry_key] == "waiting":
                tried[retry_key] = "retried"
                state["recovery_actions"] = state.get("recovery_actions", 0) + 1
                return _action("CLICK", "Retry the revalidated read-only pagination control once",
                               target=Target(element_id=same_pager[0]["element_id"])), None
        scroll = observation.get("scroll", {})
        total = batch.get("total")
        end_reached = scroll.get("at_end", True)
        # Use a bounded scroll only if there is evidence of potentially missing
        # records and more of the document remains below the viewport.
        scroll_key = f"{signature}:scroll"
        can_scroll = total is not None and len(state["records"]) < total and not end_reached
        if can_scroll and (not batch.get("forward_enabled") or repeated) and scroll_key not in tried:
            tried[scroll_key] = True
            state["recovery_actions"] = state.get("recovery_actions", 0) + 1
            return _action("SCROLL", "Inspect the unvisited portion of the visible collection"), None
        terminal_page = [url, signature]
        if repeated and state.get("terminal_page") != terminal_page:
            return None, "Pagination returned a previously collected record batch. Available recovery paths were exhausted"
        if batch.get("forward_enabled") or any(
            not element.get("disabled") and not _PAGE.fullmatch(element.get("name", "").strip()) for element in forward
        ):
            return None, "No authorized forward pagination control was available"
        state["terminal"] = True
        state["terminal_page"] = terminal_page
        return None, self.blocker() or ""

    @staticmethod
    def record_size(row):
        return len(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode())

    def blocker(self):
        state = self.state
        if state.get("filtered") or state.get("truncated"):
            return "The directory was filtered or only part of it could be read"
        if not state["totals"]:
            return "The collection has no observable total. Exhaustive coverage could not be confirmed"
        if len(state["totals"]) != 1 or len(state["records"]) != state["totals"][0]:
            return "Unique records do not match the directory's advertised total"
        if any(row["classification"] == "unknown" for row in state["records"].values()):
            return "Some products could not be classified from their visible category or description"
        return None


def directory_result(state, reason=None):
    rows = list(state.get("records", {}).values())
    matches = [row for row in rows if row["classification"] == "match"]
    total = state["totals"][0] if len(state.get("totals", [])) == 1 else None
    table = state.get("entity") == "table rows"
    explanation = reason or (f"Collected all {len(rows)} rows in the visible table." if table else
                             f"Classified all {len(rows)} unique records in the visible directory and reached its last page.")
    return {
        "strategy": "table_extraction" if table else "directory_collection",
        "partial": reason is not None,
        "directory": {"records": matches, "unique_records": len(rows), "advertised_total": total,
                      "unknown": sum(row["classification"] == "unknown" for row in rows),
                      "pages": len(state.get("pages", [])), "repeated_pages": state.get("repeated_pages", 0),
                      "recovery_actions": state.get("recovery_actions", 0)},
        "claims": [{"text": row["name"], "evidence_ids": [row["id"]]} for row in matches],
        "evidence": [{"id": row["id"], "url": row["observed_url"], "quote": row["quote"], "step_id": row["step_id"],
                      "source_url": row["source_url"], "method": row["method"], "observed_at": row["observed_at"],
                      **({"classification_quote": row["classification_quote"]} if row.get("classification_quote") else {})}
                     for row in matches],
        "verification": {"complete": reason is None, "explanation": explanation},
    }
