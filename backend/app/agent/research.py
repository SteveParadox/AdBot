"""Read-only discovery and source provenance for research tasks."""
import hashlib
import re
from urllib.parse import urlsplit

from .routing import words


READ_RESEARCH = r"""(query) => {
 const excluded = 'nav,aside,header,footer,form,dialog,[hidden],[inert],[aria-hidden=true],[role=navigation],[role=dialog]';
 const root = document.querySelector('main,[role=main]') || document.body;
 const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
 const snippets = new Map();
 const wanted = new Set(query);
 const words = text => new Set(text.toLowerCase().match(/[\p{L}\p{N}]+/gu) || []);
 const hits = text => [...words(text)].filter(term => wanted.has(term)).length;
 const remember = (heading, quote, row) => {
   if (snippets.has(quote)) return;
   const score = hits(quote)*4 + hits(heading);
   if (snippets.size >= 96) {
     let weakest;
     for (const entry of snippets) if (!weakest || entry[1].score < weakest[1].score) weakest = entry;
     if (weakest[1].score >= score) return;
     snippets.delete(weakest[0]);
   }
   snippets.set(quote, {heading, quote, row, score});
 };
 let heading = '', scanned = 0;
 for (let node = walker.nextNode(); node && scanned++ < 6000; node = walker.nextNode()) {
   if (!node.getClientRects().length || node.closest(excluded) || getComputedStyle(node).visibility !== 'visible') continue;
   if (node.matches('h1,h2,h3,h4,h5,h6,[role=heading]')) {
     heading = (node.innerText || '').trim().slice(0,160);
     continue;
   }
   if (node.querySelector('input,textarea,[contenteditable=true]')) continue;
   const block = node.matches('p,li,dd,tr,blockquote,[role=row]') ||
     (node.matches('div,section,article,span') && !node.querySelector('div,section,article,p,ul,ol,dl,table,blockquote,[role=row]'));
   if (!block || node.parentElement.closest('p,li,dd,tr,blockquote,[role=row]')) continue;
   const quote = (node.innerText || '').replace(/\s+/g,' ').trim();
   const linkTextLength = [...node.querySelectorAll('a[href]')].slice(0,12)
     .reduce((length, link) => length + (link.innerText || '').trim().length, 0);
   if (linkTextLength > 0 && linkTextLength >= quote.length * 0.8) continue;
   const row = node.matches('tr,[role=row]') && node.children.length >= 2;
   if (quote.length >= 35 || (row && quote.length >= 10)) {
     // Inspect overlapping windows so a relevant sentence can survive even
     // when it occurs near the end of a long block.
     for (let start=0; start<Math.min(quote.length,24000); start+=560) {
       remember(heading, quote.slice(start,start+700).trim(), row);
       if (start+700>=quote.length) break;
     }
   }
 }
 return [...snippets.values()].sort((a,b)=>b.score-a.score).map(({heading,quote,row})=>({heading,quote,row}));
}"""

STOP = set("a an the to and or of in on for from with about against versus compare comparison research find show list give all each what which is are please".split())


def terms(value):
    return set(words(value)) - STOP


def comparison_entities(objective, declared=()):
    literal = set(words(objective))
    names = [name for name in declared if terms(name) and terms(name) <= literal]
    match = re.match(r"\s*(?:please\s+)?compare\s+(.+)", objective, re.I)
    if match and len(names) < 2:
        subjects = re.split(r"\s+(?:on|by|in terms of|based on|for|using)\s+|[!?;\n]", match[1], maxsplit=1, flags=re.I)[0]
        parts = re.split(r",\s*(?:and\s+)?|\s+(?:with|against|versus|vs\.?|and)\s+", subjects, flags=re.I)
        if len(parts) > 1:
            names.extend(part.strip(" .") for part in parts if terms(part) and len(words(part)) <= 8)
    return list({name.casefold(): name for name in names}.values())[:8]


def comparison_dimensions(objective):
    if not re.match(r"\s*(?:please\s+)?compare\b", objective, re.I):
        return []
    match = re.search(r"\s+(?:on|in terms of|based on)\s+([^.!?;\n]+)", objective, re.I)
    return [name.strip() for name in re.split(r"\s+and\s+|,\s*", match[1], flags=re.I)
            if terms(name) and len(words(name)) <= 8][:8] if match else []


def ranked_chunks(chunks, objective, title, entities=(), criteria=()):
    target = terms(" ".join((objective, *criteria)))
    title_terms = terms(title)
    title_entities = [entity for entity in entities if terms(entity) <= title_terms]
    output = []
    for chunk in chunks:
        quote = chunk["quote"]
        body = terms(quote)
        if len(body) < (2 if chunk.get("row") else 4):
            continue
        heading = chunk["heading"]
        section = terms(heading)
        context = title_terms | section
        matched = [entity for entity in entities if terms(entity) <= body or terms(entity) <= section]
        if not matched and len(title_entities) == 1:
            matched = title_entities
        hits = target & body
        score = 3 * len(hits) + len(target & context) + 3 * len(matched)
        if hits or matched or len(target & context) >= 2:
            output.append((score, {**chunk, "entities": matched}))
    ranked = [item for _, item in sorted(output, key=lambda pair: pair[0], reverse=True)]
    leaders = []
    for entity in entities:
        best = next((item for item in ranked if entity in item["entities"]), None)
        if best and best not in leaders:
            leaders.append(best)
    return leaders + [item for item in ranked if item not in leaders]


def capture_evidence(observation, store, step_id, entities, criteria):
    if len(store) >= 40:
        return 0
    if observation.get("http_status", 200) is not None and observation["http_status"] >= 400:
        return 0
    url = observation["url"]
    seen = {(source["url"].split("#", 1)[0], source["quote"]) for source in store}
    quotes = {source["quote"] for source in store}
    added = 0
    for chunk in observation.get("research_chunks", ()):
        quote = chunk["quote"]
        key = (url.split("#", 1)[0], quote)
        relevant = bool(chunk["entities"]) if entities else bool(terms(quote) & terms(" ".join(criteria)))
        if key in seen or quote in quotes or not relevant:
            continue
        digest = hashlib.sha256("\0".join(key).encode()).hexdigest()[:24]
        store.append({"id": f"dom-{digest}", "url": url, "quote": quote, "step_id": step_id,
                      "entities": chunk["entities"], "heading": chunk["heading"],
                      "criteria_hints": [item for item in criteria if terms(item) & terms(quote)]})
        seen.add(key)
        added += 1
        if added == 4 or len(store) >= 40:
            break
    return added


def coverage(evidence, entities, criteria):
    return {
        "entities": {entity: [row["id"] for row in evidence if entity in row.get("entities", []) or
                              terms(entity) <= terms(row["quote"])] for entity in entities},
        "criteria": {criterion: [row["id"] for row in evidence if criterion in row.get("criteria_hints", []) or
                                 terms(criterion) & terms(row["quote"])] for criterion in criteria},
    }


def destination_key(url):
    parsed = urlsplit(url)
    return parsed._replace(fragment="").geturl()


def guard_navigation(history, destination, observed_url, evidence_count):
    target = destination_key(destination)
    if target == destination_key(observed_url) or history.get(target) == evidence_count:
        raise ValueError("This research destination was already observed without new evidence. Choose another source.")
    return target
