"""Scoped search eligibility and explicit query-only POST authorization.

A site owner's attestation is required for POST; HTTP method, names and page
markup cannot establish absence of side effects. Never infer a POST permit.
"""
import json
from urllib.parse import parse_qsl, urlsplit
from typing import Literal

from pydantic import Field, model_validator

from ..schemas import Strict
from ..security import normalize


class ApprovedPostSearch(Strict):
    url: str = Field(min_length=8, max_length=1800)
    query_field: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    verified_read_only: Literal[True]

    @model_validator(mode="after")
    def validate_endpoint(self):
        parsed = urlsplit(self.url)
        if parsed.query or parsed.fragment or "*" in self.url:
            raise ValueError("Use an exact POST search endpoint without query, fragment or wildcard")
        self.url = normalize(self.url)
        return self


def matching_post_endpoint(url, endpoints):
    try:
        if urlsplit(url).fragment or urlsplit(url).query:
            return None
        canonical = normalize(url)
    except (ValueError, TypeError, AttributeError):
        return None
    return next((item for item in endpoints if item.get("verified_read_only") is True
                 and item.get("url") == canonical), None)


def validate_post_endpoints(endpoints, policy):
    seen = set()
    for item in endpoints:
        validated = ApprovedPostSearch.model_validate(item).model_dump()
        url = policy.check(validated["url"])
        if url in seen:
            raise ValueError("Duplicate approved POST search endpoint")
        seen.add(url)


def approved_post_payload(url, content_type, body, query, endpoints):
    endpoint = matching_post_endpoint(url, endpoints)
    if not endpoint or not isinstance(body, str) or len(body.encode()) > 4096:
        return False
    field = endpoint["query_field"]
    mime = content_type.split(";", 1)[0].strip().lower()
    try:
        if mime == "application/json":
            # Keep duplicate keys visible, and distinguish objects from arrays.
            class ObjectPairs(list):
                pass
            pairs = json.loads(body, object_pairs_hook=ObjectPairs)
            if not isinstance(pairs, ObjectPairs):
                return False
        elif mime == "application/x-www-form-urlencoded":
            pairs = parse_qsl(body, keep_blank_values=True, strict_parsing=True, max_num_fields=2)
        else:
            return False
    except (ValueError, TypeError, UnicodeError):
        return False
    return pairs == [(field, query)]


def search_interface(element, endpoints=()):
    """Return a candidate kind, never permission to send arbitrary requests."""
    if (not element.get("actionable") or element.get("visible") is False
            or any(element.get(key) for key in ("disabled", "readonly", "sensitive", "blocked_by_modal"))):
        return None
    tag, role, kind = element.get("tag"), element.get("role"), element.get("type")
    hints = element.get("search_interface") or {}
    native = tag == "input" and kind in {"search", "text", ""}
    custom = (tag == "textarea" or hints.get("editable") is True) and role in {"searchbox", "textbox", "combobox"}
    if not (native or custom) or role not in {"searchbox", "textbox", "combobox"}:
        return None
    if not (role == "searchbox" or kind == "search" or hints.get("search_semantics") is True
            or (element.get("form") or {}).get("search")):
        return None
    form = element.get("form")
    if form:
        try:
            url = form.get("action") or ""
            if urlsplit(url).fragment:
                return None
            normalize(url)
        except ValueError:
            return None
        if form.get("method") == "POST":
            return "approved_post" if matching_post_endpoint(url, endpoints) else None
        if form.get("method") != "GET":
            return None
        return "native_get" if native else "scripted_get"
    return "scripted"


SUGGESTIONS = r"""e => {
 const norm=s=>String(s||'').trim().replace(/\s+/g,' ');
 const visible=n=>!!n.getClientRects().length&&getComputedStyle(n).visibility==='visible'&&!n.closest('[hidden],[inert],[aria-hidden=true],[aria-disabled=true]');
 const roots=[...(e.getAttribute('aria-controls')||'').split(/\s+/),...(e.getAttribute('aria-owns')||'').split(/\s+/)]
   .filter(Boolean).map(id=>document.getElementById(id)).filter(Boolean);
 const scope=e.closest('[role=search],search,form');
 if(scope) roots.push(...scope.querySelectorAll('[role=listbox],[role=menu]'));
 const options=[...new Set(roots.flatMap(r=>[...r.querySelectorAll('[role=option],[role=menuitem],a[href]')]))]
   .filter(n=>visible(n)&&!n.matches(':disabled')).slice(0,24);
 return options.map(n=>({label:norm(n.getAttribute('aria-label')||n.innerText).slice(0,180),role:n.getAttribute('role')||n.tagName.toLowerCase()})).filter(n=>n.label);
}"""


SUGGESTION_TARGET = r"""(e,query) => {
 const norm=s=>String(s||'').trim().replace(/\s+/g,' ').toLowerCase();
 const roots=[...(e.getAttribute('aria-controls')||'').split(/\s+/),...(e.getAttribute('aria-owns')||'').split(/\s+/)]
   .filter(Boolean).map(id=>document.getElementById(id)).filter(Boolean);
 const scope=e.closest('[role=search],search,form');
 if(scope) roots.push(...scope.querySelectorAll('[role=listbox],[role=menu]'));
 const found=[...new Set(roots.flatMap(r=>[...r.querySelectorAll('[role=option],[role=menuitem],a[href]')]))]
   .filter(n=>!!n.getClientRects().length&&getComputedStyle(n).visibility==='visible'&&!n.closest('[hidden],[inert],[aria-hidden=true],[aria-disabled=true]')&&!n.matches(':disabled')&&norm(n.getAttribute('aria-label')||n.innerText)===norm(query));
 return found.length===1?found[0]:null;
}"""


SEARCH_BUTTON = r"""e => {
 const scope=e.closest('[role=search],search,form');
 if(!scope) return null;
 const found=[...scope.querySelectorAll('button,[role=button],input[type=submit]')]
   .filter(n=>!!n.getClientRects().length&&getComputedStyle(n).visibility==='visible'&&!n.matches(':disabled')&&!n.closest('[hidden],[inert],[aria-hidden=true],[aria-disabled=true]')&&/^(search|find|go|submit search)$/i.test((n.getAttribute('aria-label')||n.innerText||n.value||'').trim())&&!['formaction','formmethod','formtarget','formenctype','formnovalidate'].some(a=>n.hasAttribute(a)));
 return found.length===1?found[0]:null;
}"""
