"""Deterministic provenance, shopping offers and independently checked claims."""

import hashlib
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit, urlunsplit

import pycountry
from courlan import extract_domain

from .policy import PublicPolicy, canonical_key
from .retrieval import clean
from .search import terms
from .shopping import budget_constraint, comparable_identity, condition_value, suitability


def source_domain(url):
    return extract_domain(url, fast=False, blacklist=None) or urlsplit(url).hostname


def source_record(doc, query, provider):
    return {
        "id": hashlib.sha256(doc.url.encode()).hexdigest()[:16],
        "url": doc.url, "canonical_url": doc.canonical, "title": doc.title,
        "domain": urlsplit(doc.url).hostname, "independence_group": source_domain(doc.url),
        "published_at": doc.published, "modified_at": doc.modified,
        "retrieved_at": doc.retrieved, "content_hash": doc.digest, "query": query,
        "metadata": doc.metadata, "provider": provider,
    }


def quote_record(source, quote, location, kind="quote"):
    return {
        "id": hashlib.sha256(f'{source["id"]}:{location}:{quote}'.encode()).hexdigest()[:16],
        "source_id": source["id"], "source_url": source["url"], "source_title": source["title"],
        "quote": quote, "location": location, "kind": kind,
        "retrieved_at": source["retrieved_at"], "published_at": source["published_at"],
        "content_hash": source["content_hash"], "query": source["query"], "source_metadata": source["metadata"],
    }


def pdf_evidence(doc, source, question):
    keywords = terms(question) | terms(source["query"])
    candidates = []
    for block, loc in zip(doc.blocks, doc.block_locations):
        for offset, quote in enumerate(re.split(r"(?<=[.!?])\s+", block), 1):
            quote = quote[:460].strip()
            score = len(terms(quote) & keywords)
            if score and len(quote) >= 25:
                candidates.append((score, loc["page"], quote,
                                   f"pdf:page-{loc['page']}:line-{loc['line']}:sentence-{offset}", "quote"))
    # Keep the observed first row as context, not an inferred semantic header.
    headers = {(row["page"], row["table"]): row["cells"] for row in doc.table_rows if row["row"] == 1}
    for row in doc.table_rows:
        page, table, number = row["page"], row["table"], row["row"]
        observed = {"cells": row["cells"]}
        if number != 1 and (page, table) in headers:
            observed["first_row"] = headers[page, table]
        quote = json.dumps(observed, ensure_ascii=False, separators=(",", ":"))
        score = len(terms(quote) & keywords)
        if score and len(quote) <= 1400:
            candidates.append((score, page, quote, f"pdf:page-{page}:table-{table}:row-{number}", "structured"))
    candidates.sort(key=lambda row: (-row[0], row[1], row[3]))
    unique = {}
    per_page = Counter()
    # Diversity prevents one long page from overwhelming a multi-page report.
    for _, page, quote, location, kind in candidates:
        key = (page, quote.casefold())
        if key in unique or per_page[page] >= 3:
            continue
        unique[key] = {**quote_record(source, quote, location, kind), "page": page}
        per_page[page] += 1
        if len(unique) >= 12:
            break
    return list(unique.values())


def text_evidence(doc, source, question):
    if doc.metadata.get("document_type") == "pdf":
        return pdf_evidence(doc, source, question)
    keywords = terms(question) | terms(source["query"])
    scored = []
    for block_number, block in enumerate(doc.blocks, 1):
        context_score = int(bool(terms(block) & keywords))
        for offset, quote in enumerate(re.split(r"(?<=[.!?])\s+", block), 1):
            quote = quote[:460].strip()
            score = len(terms(quote) & keywords) * 2 + context_score
            if score and len(quote) >= 35:
                scored.append((score, block_number, offset, quote))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    unique = {}
    for _, block, offset, quote in scored:
        if quote.casefold() not in unique:
            unique[quote.casefold()] = quote_record(source, quote, f"normalized-text:block-{block}:sentence-{offset}")
        if len(unique) == 4:
            break
    return list(unique.values())


AVAILABILITY = {
    "InStock": "In stock", "OutOfStock": "Out of stock", "LimitedAvailability": "Limited availability",
    "PreOrder": "Preorder", "PreSale": "Presale", "BackOrder": "Backorder",
    "Discontinued": "Discontinued", "SoldOut": "Sold out", "OnlineOnly": "Online only",
}


def market_hint(country, source, offer):
    if not country:
        return "unknown"
    if offer.get("country"):
        return "explicit" if country == offer["country"] else "excluded"
    if source["domain"].endswith("." + country.lower()):
        return "domain_hint"
    market_currency = {"NG": "NGN", "GB": "GBP", "CA": "CAD", "AU": "AUD", "JP": "JPY",
                       "IN": "INR", "ZA": "ZAR", "KE": "KES", "GH": "GHS", "BR": "BRL"}.get(country)
    if market_currency and offer.get("priceCurrency", "").upper() == market_currency:
        return "currency_hint"
    return "unknown"


COUNTRY_NAMES = {
    entry.name.casefold(): entry.alpha_2 for entry in pycountry.countries if len(entry.name) > 3
}
COUNTRY_NAMES.update({
    "united states": "US", "usa": "US", "united kingdom": "GB", "uk": "GB", "nigerian": "NG",
    "south korea": "KR", "vietnam": "VN", "taiwan": "TW", "russia": "RU", "iran": "IR",
})
COUNTRY_PATTERN = re.compile(
    r"(?<!\w)(" + "|".join(re.escape(value) for value in sorted(COUNTRY_NAMES, key=len, reverse=True)) + r")(?!\w)",
    re.I,
)


def country_from(question, country=None):
    if country:
        return country
    if re.search(r"\b(naira|ngn)\b|₦", question, re.I):
        return "NG"
    # An unqualified mention of a country can be part of the subject. Search
    # hints are inferred only from locality phrases or a retailer nationality.
    match = COUNTRY_PATTERN.search(question)
    if match and (re.search(r"\b(in|for|about|from|within|to)\s+(the\s+)?$", question[:match.start()], re.I)
                  or match.group().casefold() == "nigerian"):
        return COUNTRY_NAMES[match.group().casefold()]
    return None


def product_evidence(doc, source, country):
    products, evidence = [], []
    for index, raw in enumerate(doc.products):
        if not raw["name"]:
            continue
        for offer_index, offer in enumerate(raw["offers"] or [{}]):
            product_url = source["url"]
            if offer.get("url"):
                try:
                    candidate = PublicPolicy().check(urljoin(product_url, offer["url"]))
                    if urlsplit(candidate).hostname == source["domain"]:
                        product_url = candidate
                except ValueError:
                    pass
            geo = market_hint(country, source, offer)
            if geo == "excluded" or (country and geo == "unknown"):
                continue
            currency = offer.get("priceCurrency", "").upper()
            price, valid_until = None, offer.get("priceValidUntil")
            expired = False
            if valid_until:
                try:
                    expired = datetime.fromisoformat(valid_until).date() < datetime.now(timezone.utc).date()
                except ValueError:
                    expired = True
            if currency and currency != "XXX" and pycountry.currencies.get(alpha_3=currency) and not expired:
                try:
                    raw_price = offer.get("price", "")
                    if not re.fullmatch(r"\d{1,12}(?:\.\d{1,6})?", raw_price):
                        raise InvalidOperation
                    price = str(Decimal(raw_price).normalize()) if "." in raw_price else raw_price
                    price = format(Decimal(price), "f") if Decimal(price) > 0 else None
                except InvalidOperation:
                    pass
            availability = offer.get("availability", "")
            status = None
            if re.fullmatch(r"(?:https?://(?:www\.)?schema\.org/)?[A-Za-z]+", availability):
                status = AVAILABILITY.get(availability.rsplit("/", 1)[-1])
            if time.time() - doc.retrieved > 120 or expired:
                status = None
            gtin = raw["gtin"] or raw["gtin13"] or raw["gtin14"]
            variant = {k: raw[k] for k in ("sku", "mpn", "color", "size") if raw[k]}
            offer_condition = condition_value(offer.get("itemCondition"))
            product_condition = condition_value(raw.get("itemCondition"))
            variant["condition"] = (offer_condition if product_condition == "unknown" else product_condition
                                    if offer_condition == "unknown" else offer_condition
                                    if offer_condition == product_condition else "unknown")
            data = {
                "name": raw["name"], "brand": raw["brand"], "model": raw["model"], "gtin": gtin, "variant": variant,
                "specifications": {k: v for k, v in raw["specs"].items() if v},
                "price": price, "currency": currency if price is not None else None,
                "retailer": offer.get("seller") or source["domain"], "availability": status, "url": product_url,
                "warranty": offer.get("warranty") or None, "shipping": offer.get("shipping") or None,
                "review_summary": raw["rating"], "last_verified": doc.retrieved,
                "geographic_match": geo, "market": country, "source_id": source["id"],
                "extraction_method": raw.get("origin", "json-ld"), "category": raw.get("category", ""),
            }
            origin = raw.get("origin", "json-ld")
            observation = {"product": raw["name"], "offer": {k: v for k, v in offer.items() if v},
                           "specifications": data["specifications"], "variant": variant,
                           "brand": raw["brand"], "model": raw["model"], "category": raw.get("category", ""),
                           "product_condition": raw.get("itemCondition", "")}
            if origin == "dom":
                observation["observed_fields"] = raw.get("observations", {})
            structured = quote_record(
                source, json.dumps(observation, ensure_ascii=False),
                f"{origin}:Product[{index}].offers[{offer_index}]", "structured",
            )
            data["evidence_id"] = structured["id"]
            products.append(data)
            evidence.append(structured)
    return products, evidence


def rank_products(products, question, country=None):
    # Exact offer identity preserves storage, memory, condition and seller
    # differences. The same variation can still be compared across retailers.
    text = question.casefold()
    budget_requested, target = budget_constraint(question, country_from(question, country))
    unique = {}
    for product in products:
        key = (canonical_key(product["url"]), product["retailer"], product["price"], product["currency"],
               product["availability"], product["name"], product["model"], product["gtin"],
               json.dumps(product["variant"], sort_keys=True), json.dumps(product["specifications"], sort_keys=True))
        price = Decimal(product["price"]) if product["price"] else None
        product["budget_requested"] = budget_requested
        product["within_budget"] = price <= target[1] if target and target[0] == product["currency"] and price is not None else None
        product["suitability"] = suitability(product, question)
        product["comparison_group"] = comparable_identity(product)
        unique.setdefault(key, product)
    candidates = list(unique.values())
    status_rank = {"met": 0, "not_requested": 0, "unknown": 1, "not_met": 2}
    unavailable = {"Out of stock", "Sold out", "Discontinued"}
    cheapest = bool(re.search(r"\b(?:cheapest|lowest price|least expensive)\b", text))
    ordered = sorted(candidates, key=lambda p: (
        p["availability"] in unavailable,
        p["within_budget"] is False,
        p["budget_requested"] and p["within_budget"] is None,
        status_rank[p["suitability"]["status"]],
        p["within_budget"] is not True,
        p["price"] is None,
        0 if cheapest else -p["suitability"]["score"],
        p["currency"] or "~",
        Decimal(p["price"]) if p["price"] else Decimal("Infinity"),
    ))[:20]
    groups = {}
    for item in ordered:
        identity = item["comparison_group"]
        if identity:
            groups.setdefault((identity, item["currency"]), set()).add(source_domain(item["url"]))
    for item in ordered:
        item["comparable_sources"] = len(groups.get((item["comparison_group"], item["currency"]), ()))
    return ordered


def select_evidence(evidence, sources, char_budget):
    seen = set()
    counts = Counter()
    packed = []
    spend = 0
    for record in evidence:
        key = record["quote"].casefold()
        group = sources[record["source_id"]]["independence_group"]
        if key in seen:
            continue
        seen.add(key)
        counts[group] += 1
        row = dict(id=record["id"], source=group, quote=record["quote"][:550],
                   date=record["published_at"], kind=record["kind"])
        packed.append((counts[group], len(packed), row))
    result = []
    for _, _, row in sorted(packed):
        size = len(json.dumps(row, ensure_ascii=False))
        if spend + size > char_budget:
            continue
        spend += size
        result.append(row)
    return result


def verified_claims(proposals, checked, evidence, sources):
    result = []
    checks = {}
    for check in checked.checks:
        if check.claim in checks:
            checks[check.claim] = None
        else:
            checks[check.claim] = check
    for index, claim in enumerate(proposals):
        check = checks.get(index)
        if not check or check.status not in {"supported", "conflicting"} or not check.evidence:
            continue
        ids = list(dict.fromkeys(check.evidence))
        if any(item not in evidence or item not in claim.evidence for item in ids):
            continue
        groups = {sources[evidence[item]["source_id"]]["independence_group"] for item in ids}
        if check.status == "conflicting" and (len(groups) < 2 or claim.kind != "conflict"):
            continue
        if claim.kind == "conflict" and check.status != "conflicting":
            continue
        if check.status == "supported" and claim.kind == "fact":
            # Numbers and quoted terms need literal corroboration as well as the
            # verifier's semantic support decision.
            claimed = set(re.findall(r"(?<![\w])\d[\d.,]*(?=\b)", claim.text))
            actual = set(re.findall(r"(?<![\w])\d[\d.,]*(?=\b)", " ".join(evidence[item]["quote"] for item in ids)))
            if not claimed <= actual:
                continue
        result.append({"text": claim.text, "kind": claim.kind, "evidence": ids, "independent_sources": len(groups)})
    return result


def citation_markdown(claims, evidence, sources):
    numbers = {source: i for i, source in enumerate(sources, 1)}
    lines = []
    for claim in claims:
        references = []
        for identifier in claim["evidence"]:
            record = evidence[identifier]
            source = sources[record["source_id"]]
            page = record.get("page")
            if (source.get("metadata", {}).get("document_type") == "pdf" and type(page) is int
                    and 1 <= page <= source["metadata"].get("pages_examined", 0)):
                url = urlunsplit(urlsplit(source["url"])._replace(fragment=f"page={page}"))
                label = f"{numbers[record['source_id']]} p. {page}"
            else:
                url = source["url"]
                label = str(numbers[record["source_id"]])
            references.append(f"[{label}](<{url}>)")
        citations = " ".join(dict.fromkeys(references))
        # Model text cannot inject additional Markdown claims, links or HTML.
        escaped = re.sub(r"([\\\x60*_\[\]{}()<>#+!|])", r"\\\1", clean(claim["text"], 520))
        label = {"inference": "**Inference.** ", "recommendation": "**Recommendation.** ",
                 "conflict": "**Sources disagree.** ", "excerpt": "**Retrieved excerpt.** "}.get(claim["kind"], "")
        lines.append(f"{label}{escaped} {citations}")
    return "\n\n".join(lines)
