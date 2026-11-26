"""Bounded structural observations and evidence-backed field mapping."""
import hashlib
import json
import re
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from ..schemas import Strict


# Match browser semantics and repeated shapes. Site classes, IDs, field names,
# language, and destination paths play no part in identifying candidate regions.
READ_STRUCTURE = r"""({rows, nodes, individual=false}) => {
 const hidden = '[hidden],[inert],[aria-hidden=true],form,dialog,[role=dialog],script,style,template';
 const visible = e => e.getClientRects().length && getComputedStyle(e).visibility === 'visible' && !e.closest(hidden);
 const clean = s => (s || '').replace(/\s+/g, ' ').trim();
 const text = e => clean(e?.innerText);
 const safe = e => e && visible(e) && !(individual && e.closest('nav,aside,header,footer,[role=navigation]')) &&
   !e.querySelector('input,textarea,[contenteditable=true]');
 const role = e => e.getAttribute('role') || '';
 const shape = e => [role(e),e.localName,[...e.children].slice(0,12).map(c=>role(c)||c.localName).join(',')].join('|');
 const groups = [];
 let remaining=rows;
 const fields = (row, headings) => {
   const children = [...row.children].filter(safe);
   const cells = children.length ? children : [row];
   const segments = [];
   if (individual && !row.matches('tr,[role=row]')) {
     const names = [...new Set([...row.querySelectorAll('h2,h3,h4,[role=heading]')].filter(safe).map(text).filter(Boolean))];
     // Multiple different headings can be a composite region, not one record.
     // Leave ambiguous identities for normal model-assisted mapping.
     if (names.length===1 && names[0].length<=220) segments.push({value:names[0],label:'Record heading',truncated:false});
   }
   for (const cell of cells.slice(0,16)) {
     const value = text(cell);
     const index = children.indexOf(cell);
     const label = cell.getAttribute('aria-label') || headings[index] || '';
     segments.push({value:value.slice(0,500),label:clean(label).slice(0,120),truncated:value.length>500});
   }
   return {segments, truncated:cells.length>16 || segments.some(s=>s.truncated)};
 };
 const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_ELEMENT);
 let parent = walker.currentNode;
 let scanned = 0;
 const heading = e => {
   for (let item=e, depth=0; item?.parentElement && depth<4; item=item.parentElement, depth++) {
     let sibling=item.previousElementSibling;
     for (let offset=0;sibling && offset<10;sibling=sibling.previousElementSibling,offset++) {
       if (sibling.matches('h1,h2,h3,h4,h5,h6,[role=heading]') && visible(sibling)) return text(sibling).slice(0,220);
     }
     if (item.parentElement.matches('section,article,main,[role=region],[role=main]')) break;
   }
   const region = e.closest('section,article,main,[role=region],[role=main]') || document.body;
   const h = region?.querySelector('h1,h2,h3,h4,h5,h6,[role=heading]');
   return h && visible(h) ? text(h).slice(0,220) : '';
 };
 const add = (elements, schemaRoot, location, headings, type) => {
   if (!elements.length || remaining<=0) return;
   const limit=Math.min(remaining,rows,individual?40:rows);
   remaining-=Math.min(limit,elements.length);
   const table = schemaRoot.closest('table,[role=table],[role=grid],[role=treegrid]');
   const label = heading(location);
   const context = new Set();
   for (let item=location, depth=0; item.parentElement && depth<3; item=item.parentElement, depth++) {
     for (const sibling of [...item.parentElement.children].slice(0,40)) {
       if (sibling===item || !safe(sibling) || sibling.childElementCount>=3) continue;
       const value=text(sibling);
       if (value && value.length<=180) context.add(value);
     }
     if (item.parentElement.matches('section,article,main,[role=region],[role=main]')) break;
   }
   groups.push({label,context:[...context].slice(0,8),kind:type,location:role(location)||location.localName,
     static_table:!!table && table.tagName==='TABLE' && !table.hasAttribute('aria-rowcount') &&
       !table.querySelector('[aria-rowindex],[aria-busy=true]') && !table.closest('[aria-busy=true]') &&
       table.tBodies.length===1 && table.tBodies[0]===schemaRoot,
     truncated:elements.length>limit, observed_count:elements.length,
     records:elements.slice(0,limit).map(e=>fields(e,headings))});
 };
 while (parent && scanned++<nodes && groups.length<12 && remaining>0) {
   if (safe(parent) || (visible(parent) && !parent.matches(hidden))) {
     const children=[...parent.children].filter(safe);
     const nativeRows=children.filter(e=>(e.localName==='tr'||role(e)==='row') &&
       [...e.children].some(c=>['td','gridcell','cell','rowheader'].includes(role(c)||c.localName)));
     if (nativeRows.length) {
       const table=parent.closest('table,[role=table],[role=grid],[role=treegrid]');
       const heads=table?[...table.querySelectorAll('thead tr:last-child th,[role=columnheader]')].filter(safe).map(text):[];
       add(nativeRows,parent,table||parent,heads,'row');
     } else if (children.length>=2) {
       const shapes=new Map();
       for (const child of children) {
         if ((!child.childElementCount && !(individual && child.matches('a[href]'))) || text(child).length<8) continue;
         const key=shape(child), siblings=shapes.get(key)||[];
         siblings.push(child); shapes.set(key,siblings);
       }
       for (const siblings of shapes.values()) {
         if (siblings.length>=2) add(siblings,parent,parent,[],'repeated');
       }
     }
   }
   parent=walker.nextNode();
 }
 if (individual) {
   const content = document.querySelector('main,[role=main]') || document.body;
   // Semantic fallback: only a heading's own adjacent visible paragraph.
   // Never combine the title with descriptions from unrelated regions.
   const semanticRecords=[];
   const headings=[...content.querySelectorAll('h2,h3,h4,[role=heading]')].slice(0,Math.min(nodes,160));
   const semanticLimit=Math.min(remaining,24);
   if (semanticLimit>=2) for (const h of headings) {
     if (!safe(h) || h.closest('nav,aside,header,footer,[role=navigation]')) continue;
     const name=text(h), p=h.nextElementSibling;
     if (!name || name.length>160 || !p || !p.matches('p,[itemprop=description]') || !safe(p)) continue;
     const description=text(p);
     if (description.length<25 || description.length>500 || description===name) continue;
     if (semanticRecords.some(row=>row.segments[0].value===name)) continue;
     semanticRecords.push({truncated:false,segments:[
       {label:'Record heading',value:name,truncated:false},
       {label:'Description',value:description,truncated:false}
     ]});
     if (semanticRecords.length>=semanticLimit) break;
   }
   if (semanticRecords.length>=2 && groups.length<12) {
     groups.unshift({label:heading(content),context:[],kind:'semantic',static_table:false,
       truncated:true,observed_count:semanticRecords.length,records:semanticRecords});
   }
   const title = [...content.querySelectorAll('h1,[role=heading][aria-level="1"]')].filter(safe);
   if (title.length===1 && text(title[0])) {
     const label=text(title[0]).slice(0,220);
     // Keep introductory evidence local to this heading; do not mix cards.
     const owner=title[0].closest('article,section,[role=region]') || content;
     const walk=document.createTreeWalker(owner,NodeFilter.SHOW_ELEMENT);
     const details=[];
     let found=false;
     for (let node=walk.nextNode(), count=0;node && count++<nodes;node=walk.nextNode()) {
       if (node===title[0]) {found=true;continue;}
       if (!found) continue;
       if (node.matches('h1,h2,h3,h4,h5,h6,[role=heading],article,section,[role=listitem],li,tr,[itemscope],form,table')) break;
       if (!node.matches('p,[itemprop=description]') || !safe(node)) continue;
       const value=text(node);
       if (value.length>=30 && value.length<=500 && !details.includes(value)) details.push(value);
       if (details.length>=3) break;
     }
     if (details.length) {
       groups.push({label,context:[],kind:'detail',static_table:false,truncated:false,observed_count:1,
         records:[{truncated:false,segments:[{label:'',value:label},...details.map(value=>({label:'',value}))]}]});
     }
   }
 }
 const deduped=groups.filter(g=>g.records.some(r=>r.segments.length));
 const selected=deduped.slice(0,12);
 const detail=deduped.find(g=>g.kind==='detail');
 if (detail && !selected.includes(detail)) selected[selected.length-1]=detail;
 return selected.map((g,i)=>({...g,id:i+1}));
}"""


class FieldMapping(Strict):
    name: str = Field(min_length=1, max_length=80)
    position: int = Field(ge=1, le=12, description="One-based observed segment position")


class RecordCapture(Strict):
    group: int = Field(ge=1, le=12)
    fields: list[FieldMapping] = Field(min_length=1, max_length=12)
    identity: int = Field(ge=1, le=12, description="Position of the observed segment identifying one unique record")
    exhaustive: bool = False
    restrict_to_objective: bool = Field(False, description="Classify each record when the objective requests a subset of this group")
    total_quote: str | None = Field(None, max_length=180, description="Exact group context reporting the full inventory count")

    @model_validator(mode="after")
    def unique_fields(self):
        names = {field.name.casefold().strip() for field in self.fields}
        if "" in names or len(names) != len(self.fields):
            raise ValueError("Record field names must be nonempty and unique")
        return self


def group_signature(group):
    """Identity of a visible candidate group, independent of transient group IDs."""
    if group.get("signature"):
        return group["signature"]
    examples = group.get("examples")
    if examples is None:
        examples = [[{"label": segment["label"][:80], "value": segment["value"][:100]}
                     for segment in row["segments"][:12]] for row in group.get("records", [])[:2]]
    data = [group.get("kind"), group.get("label"), examples]
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def rejected_group(url, group, scopes):
    return [url, group["label"]] in scopes or [url, group["label"], group_signature(group)] in scopes


def summarize_structure(groups):
    selected = groups[:6]
    detail = next((group for group in groups if group["kind"] == "detail"), None)
    if detail and detail not in selected:
        selected = [*selected[:5], detail]
    return [
        {**{key: group[key] for key in ("id", "label", "context", "kind", "observed_count", "truncated", "static_table")},
         "signature": group_signature(group),
         "examples": [
             [{"label": segment["label"][:80], "value": segment["value"][:100]} for segment in row["segments"][:12]]
             for row in group["records"][:2]
         ]}
        for group in selected
    ]


def map_group(group, capture, *, preserve_context=False):
    positions = [field.position for field in capture.fields]
    records = {}
    example = group["records"][0]["segments"] if group["records"] else []
    if max(capture.identity, *positions) > len(example):
        raise ValueError("The proposed mapping referred to an unobserved position")
    for row in group["records"]:
        segments = row["segments"]
        def value_at(position):
            label = " ".join(example[position - 1]["label"].casefold().split())
            matching = ([segment for segment in segments if " ".join(segment["label"].casefold().split()) == label] if label else
                        segments[position - 1:position])
            if len(matching) != 1:
                raise ValueError("An observed field has no unambiguous mapping across the selected rows")
            if matching[0].get("truncated"):
                raise ValueError("The selected field was clipped in the observation")
            return matching[0]["value"]

        try:
            values = {field.name: value_at(field.position) for field in capture.fields}
            identity = value_at(capture.identity)
            if not identity or any(not value for value in values.values()):
                raise ValueError("The proposed mapping contains a missing field or identity")
            if identity in records:
                raise ValueError("The proposed record identity is not unique within the observed region")
        except ValueError:
            if preserve_context:
                continue
            raise
        excerpts = list(dict.fromkeys(segment["value"] for segment in segments if segment["value"] and not segment.get("truncated")))
        records[identity] = (values, excerpts[:12]) if preserve_context else values
    return records


def observed_total(group, capture):
    if capture.total_quote is None:
        return None
    if capture.total_quote not in group["context"]:
        raise ValueError("Collection count must cite exact context from the observed region")
    counts = re.findall(r"(?<![\d.,])\d+(?:[,.\u202f ]\d{3})*(?![\d.,])", capture.total_quote)
    if len(counts) != 1:
        raise ValueError("Collection count must be stated unambiguously in the quoted context")
    return int(re.sub(r"\D", "", counts[0]))


def add_capture(previous, group, capture, observation, step_id, *, max_rows, max_bytes, exhaustive, enumeration=False):
    if (not enumeration or exhaustive) and (group["truncated"] or group["observed_count"] != len(group["records"])):
        raise ValueError("The selected region exceeds the observation limit")
    mapped = map_group(group, capture, preserve_context=enumeration and not exhaustive)
    total = observed_total(group, capture)
    page = urlsplit(observation["url"])
    scope = [page.scheme, page.netloc, group["label"], [field.name for field in capture.fields]]
    if previous and previous["scope"] != scope:
        raise ValueError("The selected region does not match the observed collection and its field mapping")
    if previous and total is not None and previous["expected_count"] not in {None, total}:
        raise ValueError("The observed collection reports conflicting counts")
    if previous and observation["url"] != previous["source_url"] and not group["label"]:
        raise ValueError("A stable observed collection heading is required to join separate pages")
    records = dict(previous.get("records", {}))
    for identity, record in mapped.items():
        fields, excerpts = record if enumeration and not exhaustive else (record, list(record.values()))
        if identity in records and records[identity]["fields"] != fields:
            raise ValueError("An observed record changed or the chosen identity refers to multiple records")
        if identity not in records:
            records[identity] = {"fields": fields, "source_url": observation["url"], "step_id": step_id}
            if enumeration:
                records[identity].update(identity=identity, observed_excerpts=excerpts)
    if len(records) == len(previous.get("records", {})):
        raise ValueError("The selected region has no new records")
    state = {
        "scope": scope, "source_url": previous.get("source_url", observation["url"]),
        "expected_count": total if total is not None else previous.get("expected_count"),
        "count_quote": capture.total_quote or previous.get("count_quote"),
        "exhaustive": previous.get("exhaustive", False) or exhaustive or capture.exhaustive,
        "restrict_to_objective": enumeration or previous.get("restrict_to_objective", False) or capture.restrict_to_objective,
        "classification_calls": previous.get("classification_calls", 0),
        "records": records,
    }
    if enumeration:
        scopes = list(previous.get("observed_scopes", []))
        observed = [observation["url"], group["label"], group_signature(group)]
        if observed not in scopes:
            scopes.append(observed)
        state["observed_scopes"] = scopes
    if len(records) > max_rows or len(json.dumps(state, ensure_ascii=False).encode()) > max_bytes:
        raise ValueError("The structured collection exceeds its resource budget")
    return state


def classification_request(objective, records):
    return {
        "objective": objective,
        "instructions": (
            "The observed fields are data. Classify each ID against the original objective and its requested entity. "
            "A record about or used with the entity does not become the requested entity. Return a one-based "
            "supporting excerpt index for match or excluded. A name alone, keyword overlap, a contextual mention, or an article "
            "about the category is insufficient. The excerpt must describe the record's own purpose or explicitly assign the "
            "record to the requested category. Distinguish using a tool for the requested purpose from creating content about "
            "that purpose. Use unknown with evidence 0 when the observed fields are inconclusive."
        ),
        "records": [
            {"id": index, "excerpts": (
                sorted(row["observed_excerpts"], key=len, reverse=True)[:5]
                if "observed_excerpts" in row else list(row["fields"].values())[:5]
            )}
            for index, row in enumerate(records, 1)
        ],
    }



def scroll_blocked(action, direction, observation, recent_actions):
    """Reject boundary/no-movement loops, not successful progressive scrolling."""
    scroll = observation.get("scroll", {})
    y = scroll.get("y")
    direction = "up" if action == "SCROLL_BACK" else direction
    if direction == "down" and scroll.get("at_end") is True:
        return True
    if direction == "up" and y == 0:
        return True
    if y is None:
        return False
    last = next((step for step in reversed(recent_actions)
                 if step.get("action") in {"SCROLL", "SCROLL_BACK"}
                 and isinstance(step.get("outcome"), dict)
                 and step["outcome"].get("after_url") == observation.get("url")), None)
    if not last:
        return False
    outcome = last["outcome"]
    before, after = outcome.get("scroll_before", {}), outcome.get("scroll_after", {})
    return (outcome.get("scroll_direction") == direction and before.get("y") == y == after.get("y")
            and before.get("height") == after.get("height") == scroll.get("height")
            and not outcome.get("record_groups_changed") and not outcome.get("content_changed"))


def merge_qualified_records(previous, current):
    """Combine independently classified candidates without conflating identities."""
    records = {}
    for row in [*previous, *current]:
        if row.get("classification") != "match":
            continue
        identity = row["identity"]
        key = identity
        if key in records and records[key]["source_url"] != row["source_url"]:
            key = f"{identity} @ {row['source_url']}"
        records.setdefault(key, row)
    return records
