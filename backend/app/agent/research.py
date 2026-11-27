"""Read-only discovery and source provenance for research tasks."""
import hashlib
import re
from urllib.parse import urlsplit

from .routing import semantic_terms, words


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

STOP = set("a an the to and or of in on for from with about against versus compare comparison research find show list give all each what which is are please tell me can does do how who where".split())


def terms(value):
    return set(words(value)) - STOP


_GENERIC_RESEARCH = {"best", "top", "recommended", "recommend", "rank", "ranking", "tool", "tools",
                     "product", "products", "option", "options", "good", "ai"}


def research_terms(value):
    aliases = {"production": "generate", "produce": "generate", "producing": "generate",
               "produces": "generate", "produced": "generate", "prices": "price",
               "pricing": "price", "cost": "price", "costs": "price"}
    return {aliases.get(term, term) for term in semantic_terms(value)}


def topic_terms(value):
    tokens = research_terms(value) - STOP
    return tokens - _GENERIC_RESEARCH or tokens


def topical_match(criterion, quote):
    """A conservative discovery hint, not a semantic verification verdict."""
    wanted = topic_terms(criterion)
    return bool(wanted) and len(wanted & research_terms(quote)) >= min(2, len(wanted))


def comparison_entities(objective, declared=()):
    literal = set(words(objective))
    names = [name for name in declared if terms(name) and terms(name) <= literal]
    match = re.search(r"^\s*(?:please\s+)?compare\s+(.+)|\b(?:differences?|comparison)\s+between\s+(.+)",
                      objective, re.I)
    text = (match[1] or match[2]) if match else (
        objective if literal & {"vs", "versus"} else ""
    )
    if text and len(names) < 2:
        prefix = re.match(r".+?\s+for\s+(.+\s+(?:versus|vs\.?|against)\s+.+)", text, re.I)
        if prefix:
            text = prefix[1]
        subjects = re.split(r"\s+(?:on|by|across|in terms of|based on|with respect to|for|using)\s+|[!?;\n]", text, maxsplit=1, flags=re.I)[0]
        parts = re.split(r",\s*(?:and\s+)?|\s+(?:with|against|versus|vs\.?|and)\s+", subjects, flags=re.I)
        if len(parts) > 1:
            names.extend(part.strip(" .") for part in parts if terms(part) and len(words(part)) <= 8)
    return list({name.casefold(): name for name in names}.values())[:8]


def comparison_dimensions(objective, criteria=()):
    if not re.match(r"\s*(?:please\s+)?compare\b", objective, re.I) and not comparison_entities(objective):
        return []
    fields = {}
    prefix = re.match(r"\s*(?:please\s+)?compare\s+(.+?)\s+for\s+.+\s+(?:versus|vs\.?|against)\s+", objective, re.I)
    requirements = [prefix[1]] if prefix else []
    for requirement in (objective, *criteria):
        match = re.search(r"\s+(?:on|by|across|in terms of|based on|with respect to)\s+([^.!?;\n]+)", requirement, re.I)
        if match:
            requirements.append(match[1])
    for requirement in requirements:
        for part in re.split(r"\s+and\s+|,\s*", requirement, flags=re.I):
            name = part.strip()
            if terms(name) and len(words(name)) <= 12:
                fields.setdefault(name.casefold(), name)
    return list(fields.values())[:8]


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
        topical_hits = topic_terms(objective) & research_terms(quote)
        score = 3 * len(hits) + 8 * len(topical_hits) + len(target & context) + 3 * len(matched)
        if hits or matched or topical_hits or len(target & context) >= 2:
            output.append((score, {**chunk, "entities": matched}))
    ranked = [item for _, item in sorted(output, key=lambda pair: pair[0], reverse=True)]
    leaders = []
    for entity in entities:
        best = next((item for item in ranked if entity in item["entities"]), None)
        if best and best not in leaders:
            leaders.append(best)
    return leaders + [item for item in ranked if item not in leaders]


def capture_evidence(observation, store, step_id, entities, criteria, *, max_records=40):
    if len(store) >= max_records:
        return 0
    if (observation.get("http_status") or 0) >= 400:
        return 0
    url = observation["url"]
    seen = {(source["url"].split("#", 1)[0], source["quote"]) for source in store}
    quotes = {(source["quote"], tuple(sorted(source.get("entities", [])))) for source in store}
    added = 0
    for chunk in observation.get("research_chunks", ()):
        quote = chunk["quote"]
        key = (url.split("#", 1)[0], quote)
        relevant = bool(chunk["entities"]) if entities else any(topical_match(item, quote) for item in criteria)
        quote_scope = (quote, tuple(sorted(chunk["entities"])))
        if key in seen or quote_scope in quotes or not relevant:
            continue
        digest = hashlib.sha256("\0".join(key).encode()).hexdigest()[:24]
        store.append({"id": f"dom-{digest}", "url": url, "quote": quote, "step_id": step_id,
                      "entities": chunk["entities"], "heading": chunk["heading"],
                      "source_title": observation.get("title", ""),
                      "criteria_hints": [item for item in criteria if (
                          bool(terms(item) & terms(quote)) if entities else topical_match(item, quote)
                      )]})
        seen.add(key)
        quotes.add(quote_scope)
        added += 1
        if added == 4 or len(store) >= max_records:
            break
    return added


def evidence_subjects(evidence, entities):
    quote = terms(evidence["quote"])
    explicit = [name for name in entities if name in evidence.get("entities", []) or terms(name) <= quote]
    if explicit:
        return explicit
    title = terms(evidence.get("source_title", "") + " " + evidence.get("heading", ""))
    contextual = [name for name in entities if terms(name) <= title]
    return contextual if len(contextual) == 1 else []


def coverage(evidence, entities, criteria):
    return {
        "entities": {entity: [row["id"] for row in evidence if entity in evidence_subjects(row, entities)]
                     for entity in entities},
        "criteria": {criterion: [row["id"] for row in evidence if (
            criterion in row.get("criteria_hints", []) or bool(terms(criterion) & terms(row["quote"]))
            if entities else topical_match(criterion, row["quote"])
        )] for criterion in criteria},
    }


def comparison_coverage(evidence, entities, dimensions):
    """A passage must bind the subject and the dimension within one observed source."""
    result = {}
    for entity in entities:
        entity_terms = terms(entity)
        candidates = [row for row in evidence if entity in evidence_subjects(row, entities)]
        cells = result[entity] = {}
        for dimension in dimensions:
            ranked = []
            for row in candidates:
                quote = row["quote"]
                body_match = topical_match(dimension, quote)
                heading_match = topical_match(dimension, row.get("heading", ""))
                if body_match or heading_match and len(terms(quote)) >= 3:
                    score = (4 * body_match + 2 * (entity_terms <= terms(quote))
                             + (entity_terms <= terms(row.get("source_title", ""))))
                    ranked.append((score, row["id"]))
            cells[dimension] = [identifier for _, identifier in sorted(ranked, key=lambda item: -item[0])]
    return result


def destination_key(url):
    parsed = urlsplit(url)
    return parsed._replace(fragment="").geturl()


def guard_navigation(history, destination, observed_url, evidence_count):
    target = destination_key(destination)
    if target == destination_key(observed_url) or history.get(target) == evidence_count:
        raise ValueError("This research destination was already observed without new evidence. Choose another source.")
    return target



def repair_exact_citations(claims, evidence):
    """Repair only uniquely attributable literal excerpts, not paraphrases."""
    for claim in claims:
        text = " ".join(claim.text.split())
        if len(text) < 20:
            continue
        if any(text in " ".join(evidence[key]["quote"].split()) for key in claim.evidence_ids if key in evidence):
            continue
        candidates = [key for key, row in evidence.items() if text in " ".join(row["quote"].split())]
        if len(candidates) == 1:
            claim.evidence_ids = candidates


def claim_verification_criteria(claims, evidence, *, verify_excerpts=False):
    required = {}
    for index, claim in enumerate(claims, 1):
        text = " ".join(claim.text.split())
        if not verify_excerpts and len(claim.evidence_ids) == 1 and any(
            text == " ".join(evidence[key]["quote"].split())
            for key in claim.evidence_ids if key in evidence
        ):
            continue
        required[f"Claim {index}: {claim.text}"] = set(claim.evidence_ids)
    return required


def verification_failures(verification, criteria, offered, claim_checks):
    problems = []
    checks = verification.checks
    if not verification.complete:
        problems.append("Verifier marked completion false")
    if len(checks) != len(criteria) or {check.criterion for check in checks} != set(criteria):
        problems.append("Verifier did not return exactly one check per required criterion")
    for check in checks:
        label = check.criterion[:160]
        cited = set(check.evidence_ids)
        if not check.met:
            problems.append("Unmet criterion: " + label)
        if not cited:
            problems.append("Missing evidence IDs: " + label)
        elif not cited <= offered:
            problems.append("Unknown or unoffered evidence IDs: " + label)
        elif check.criterion in claim_checks and not cited <= claim_checks[check.criterion]:
            problems.append("Claim citation mismatch: " + label)
    return problems


def citation_candidates(claims, evidence):
    """Bounded suggestions for a subsequent decision; not entailment judgments."""
    output = []
    for claim in claims[:6]:
        subject = topic_terms(claim.text)
        ranked = sorted(evidence.values(), key=lambda row: len(subject & semantic_terms(row["quote"])), reverse=True)
        output.append({
            "text": claim.text[:350], "cited_ids": claim.evidence_ids,
            "candidates": [{"id": row["id"], "quote": row["quote"][:450]}
                           for row in ranked[:2] if subject & semantic_terms(row["quote"])],
        })
    return output
