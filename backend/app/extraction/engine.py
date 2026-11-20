"""Browser capture is separate from pure normalization and schema validation."""

import hashlib
import html
import json
import re
import unicodedata
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit, urlunsplit, quote
from zoneinfo import ZoneInfo

from .schemas import SchemaDefinition, bounded_json


CAPTURE = r"""({schema,limit}) => {
 const select=(root,s,method)=> {
   if(typeof root?.querySelectorAll!=='function')root=document;
   if(!s)return [root];
   if(method==='xpath'){
     const out=[], result=document.evaluate(s,root,null,XPathResult.ORDERED_NODE_ITERATOR_TYPE,null);
     let n; while((n=result.iterateNext())&&out.length<limit+1)out.push(n); return out;
   }
   return Array.from(root.querySelectorAll(s)).slice(0,limit+1);
 };
 const path=(o,p)=>p.split('.').filter(Boolean).reduce((v,k)=>v==null?null:v[k],o);
 const metadata=[]; let metadataBytes=0,metadataErrors=0;
 const bounded=(v,depth=0)=>{if(depth>8)throw new Error('Metadata nesting limit');if(v&&typeof v==='object'){const entries=Array.isArray(v)?v:Object.values(v);if(entries.length>100)throw new Error('Metadata width limit');for(const child of entries)bounded(child,depth+1);}};
 const walk=(v,depth=0)=>{
   if(!v)return;if(depth>8||metadata.length>=500){metadataErrors++;return;}
   if(Array.isArray(v)){for(const child of v.slice(0,100))walk(child,depth+1);return;}
   if(typeof v==='object'){if(v['@type'])metadata.push(v); if(v['@graph'])walk(v['@graph'],depth+1);}
 };
 const scripts=Array.from(document.querySelectorAll('script[type="application/ld+json"]'));if(scripts.length>20)metadataErrors++;
 for(const script of scripts.slice(0,20)){
   metadataBytes+=script.textContent.length;if(metadataBytes>262144){metadataErrors++;break;}
   try{const parsed=JSON.parse(script.textContent);bounded(parsed);walk(parsed);}catch{metadataErrors++;}
 }
 const eligible=metadata.filter(v=>!schema.jsonld_type||[v['@type']].flat().includes(schema.jsonld_type));
 const roots=schema.record_method==='jsonld'?eligible:select(document,schema.record_selector,schema.record_method);
 const records=[]; let outputBytes=0,truncated=roots.length>limit;
 for(const root of roots.slice(0,limit)){
   let values={};
   for(const [name,rule] of Object.entries(schema.fields)){
     let v=null;
     if(rule.method==='source_url')v=location.href;
     else if(rule.method==='page_title')v=document.title;
     else if(rule.method==='jsonld')v=path(schema.record_method==='jsonld'?root:eligible[0],rule.path||name);
     else if(rule.method==='meta')v=Array.from(document.querySelectorAll('meta')).find(m=>m.name===rule.selector||m.getAttribute('property')===rule.selector)?.content;
     else if(rule.method!=='ai'){
       const nodes=select(root,rule.selector,rule.method);
       const read=n=>rule.attribute?n.getAttribute?.(rule.attribute):(n.innerText??n.textContent??'');
       v=rule.multiple?nodes.slice(0,100).map(read):nodes[0]?read(nodes[0]):null;
     }
     // Bound transfer as well as persisted output. Oversized values fail, not truncate silently.
     values[name]=v==null?null:JSON.stringify(v).length>25000?{__extraction_oversized:true}:v;
   }
   values._observed_text=(root===document?(document.body?.innerText||''):(root?.innerText??root?.textContent??JSON.stringify(root)??'')).slice(0,14000);
   let bytes=JSON.stringify(values).length;
   if(bytes>65536){values={_record_error:'Record exceeds transfer budget'};bytes=JSON.stringify(values).length;}
   if(outputBytes+bytes>1048576){truncated=true;break;}
   outputBytes+=bytes;records.push(values);
 }
 return {records,truncated,metadataErrors, text:(document.body?.innerText||'').slice(0,14000)};
}"""


async def capture(page, definition, limit):
    return await page.evaluate(CAPTURE, {"schema": definition, "limit": limit})


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def clean_text(value):
    return " ".join(unicodedata.normalize("NFKC", html.unescape(str(value))).split())


def normalize_value(value, rule, source_url, zone):
    if isinstance(value, dict) and value.get("__extraction_oversized"):
        raise ValueError("Oversized extracted field")
    if value is None or value == "":
        if rule.required or not rule.nullable:
            raise ValueError("Required value is missing")
        return None
    bounded_json(value, 25000)
    kind = rule.type
    text = clean_text(value)
    if len(text) > rule.max_length:
        raise ValueError("Field exceeds maximum length")
    if kind in {"string", "url", "date", "datetime", "currency"}:
        for transform in rule.transformations:
            if transform == "lower":
                text = text.lower()
            elif transform in {"upper", "currency_code"}:
                text = text.upper()
    if kind == "string":
        result = text
    elif kind in {"decimal", "currency", "integer"}:
        number = text
        if kind == "currency":
            number = re.sub(r"^[A-Za-z$€£₦¥\s]+|[A-Za-z$€£₦¥\s]+$", "", number)
        if rule.decimal_separator == ",":
            number = number.replace(".", "").replace(",", ".")
        else:
            if "," in number and not re.fullmatch(r"[+-]?\d{1,3}(,\d{3})+(\.\d+)?", number):
                raise ValueError("Ambiguous decimal punctuation")
            number = number.replace(",", "")
        decimal = Decimal(number)
        if not decimal.is_finite() or abs(decimal.adjusted()) > 30:
            raise ValueError("Invalid numeric magnitude")
        if rule.minimum is not None and decimal < Decimal(str(rule.minimum)):
            raise ValueError("Value below minimum")
        if rule.maximum is not None and decimal > Decimal(str(rule.maximum)):
            raise ValueError("Value above maximum")
        if kind == "integer" and decimal != decimal.to_integral():
            raise ValueError("Expected integer")
        result = int(decimal) if kind == "integer" else format(decimal, "f")
    elif kind == "boolean":
        if isinstance(value, bool):
            result = value
        elif text.lower() in {"true", "yes", "1", "false", "no", "0"}:
            result = text.lower() in {"true", "yes", "1"}
        else:
            raise ValueError("Expected explicit boolean")
    elif kind == "url":
        parts = urlsplit(urljoin(source_url, text))
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            raise ValueError("Expected HTTP(S) URL without credentials")
        host = parts.hostname.rstrip(".").lower().encode("idna").decode()
        host = "[" + host + "]" if ":" in host else host
        netloc = (
            host
            if parts.port is None or (parts.scheme, parts.port) in {("http", 80), ("https", 443)}
            else host + ":" + str(parts.port)
        )
        result = urlunsplit(
            (parts.scheme.lower(), netloc, quote(parts.path or "/", safe="/%:@-._~!$&'()*+,;="), parts.query, "")
        )
    elif kind in {"date", "datetime"}:
        if rule.date_format:
            parsed = datetime.strptime(text, rule.date_format)
        elif kind == "date":
            return date.fromisoformat(text).isoformat()
        else:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if kind == "date":
            result = parsed.date().isoformat()
        else:
            result = (
                (parsed if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo(zone)))
                .astimezone(timezone.utc)
                .isoformat()
            )
    else:
        result = (
            [clean_text(value)]
            if kind == "list" and isinstance(value, str) and not value.lstrip().startswith("[")
            else json.loads(value)
            if isinstance(value, str)
            else value
        )
        if not isinstance(result, list if kind == "list" else dict):
            raise ValueError("Incorrect structured field type")
        bounded_json(result, rule.max_length)
        if isinstance(result, list):
            result = [clean_text(value) if isinstance(value, str) else value for value in result]
            result = list({json.dumps(v, sort_keys=True): v for v in result}.values())
    if rule.choices and str(result) not in rule.choices:
        raise ValueError("Value is not an allowed choice")
    return result


def process_record(raw, definition, source_url, methods=None):
    schema = SchemaDefinition.model_validate(definition)
    bounded_json(raw)
    data, errors, original = {}, {}, {}
    for name, rule in schema.fields.items():
        value = raw.get(name)
        try:
            data[name] = normalize_value(value, rule, source_url, schema.timezone)
            if data[name] != value:
                original[name] = value
        except (ValueError, TypeError, InvalidOperation, OverflowError):
            data[name] = None
            errors[name] = "Missing, invalid or oversized " + rule.type
    status = "invalid" if errors else "incomplete" if any(v is None for v in data.values()) else "valid"
    identity_values = (
        [data.get(name) for name in schema.identity_fields] if schema.identity_fields else [source_url, data]
    )
    if schema.identity_fields and any(value is None for value in identity_values):
        errors["_identity"] = "Identity fields must be present"
        status = "invalid"
    meaningful = {key: value for key, value in data.items() if key not in schema.ignored_change_fields}
    provenance = {
        "source_url": source_url,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": schema.version,
        "schema_name": schema.name,
        "extraction_method": methods or sorted({r.method for r in schema.fields.values()}),
        "validation_status": status,
    }
    if raw.get("_evidence"):
        provenance["evidence"] = raw["_evidence"]
    bounded_json(data)
    return {
        "data": data,
        "original": original,
        "errors": errors,
        "validation_status": status,
        "identity": digest(identity_values),
        "content_hash": digest(meaningful),
        "provenance": provenance,
    }
