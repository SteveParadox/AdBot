"""Deterministic provenance, shopping offers and independently checked claims."""

import hashlib
import json
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit, urlunsplit

import pycountry
from courlan import extract_domain

from .integrity import (claim_freshness, freshness_status, numerical_support, observed_offer_time,
                        offer_is_current, quoted_support)
from .policy import PublicPolicy, canonical_key
from .retrieval import clean
from .ranking import lexical_scores, source_signals, supporting_groups
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
        "metadata": {k: v for k, v in doc.metadata.items() if k != "schedule_events"}, "provider": provider,
        "credibility": source_signals(doc.url, doc.metadata),
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


def text_evidence(doc, source, question, *, target_date=None, offset_minutes=None, schedule=False):
    if doc.metadata.get("document_type") == "pdf":
        return pdf_evidence(doc, source, question)
    from .schedule import event_day, local_start, schedule_request
    events = []
    if schedule or schedule_request(question) or target_date:
        for index, event in enumerate(doc.metadata.get("schedule_events", [])[:100]):
            day = event_day(event.get("startDate"), offset_minutes)
            if target_date and day != target_date:
                continue
            observation = {**event, "local_date": day}
            converted = local_start(event.get("startDate"), offset_minutes)
            if converted:
                observation["local_start"] = converted
            quote = json.dumps(observation, ensure_ascii=False, separators=(",", ":"))
            if len(quote) <= 1000:
                record = quote_record(source, quote, f"json-ld:event-{index + 1}", "structured")
                record["event_observation"] = {"local_date": day, "original_start": event.get("startDate")}
                events.append(record)
            if len(events) >= 24:
                break
    keywords = terms(question) | terms(source["query"])
    title_match = bool(terms(question) & terms(doc.title))
    scored = []
    for block_number, block in enumerate(doc.blocks, 1):
        context_score = int(bool(terms(block) & keywords))
        for offset, quote in enumerate(re.split(r"(?<=[.!?])\s+", block), 1):
            quote = quote[:460].strip()
            score = len(terms(quote) & keywords) * 2 + context_score
            structured = " | " in quote and title_match
            if (score or structured) and len(quote) >= 8:
                scored.append((score + int(structured), block_number, offset, quote))
    relevance = lexical_scores(question, [row[3] for row in scored])
    scored = [row for _, row in sorted(zip(relevance, scored), key=lambda pair: (-pair[0], -pair[1][0], pair[1][1], pair[1][2]))]
    unique = {}
    for _, block, offset, quote in scored:
        if quote.casefold() not in unique:
            unique[quote.casefold()] = quote_record(source, quote, f"normalized-text:block-{block}:sentence-{offset}")
        if len(unique) == 8:
            break
    return [*events, *unique.values()]


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
            observed_at = observed_offer_time(doc.retrieved, doc.cache_headers)
            current = offer_is_current(observed_at, valid_until)
            if currency and currency != "XXX" and pycountry.currencies.get(alpha_3=currency) and current:
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
            if not current:
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
                "offer_observed_at": observed_at, "offer_valid_until": valid_until or None,
                "offer_freshness": "recent_observation" if current else "stale_or_unknown",
                "geographic_match": geo, "market": country, "source_id": source["id"],
                "extraction_method": raw.get("origin", "json-ld"), "category": raw.get("category", ""),
            }
            origin = raw.get("origin", "json-ld")
            observed_fields = {k: v for k, v in offer.items() if v and k not in {"price", "priceCurrency", "availability"}}
            if price is not None:
                observed_fields.update(price=price, priceCurrency=currency)
            if status:
                observed_fields["availability"] = status
            observation = {"product": raw["name"], "offer": observed_fields,
                           "specifications": data["specifications"], "variant": variant,
                           "brand": raw["brand"], "model": raw["model"], "category": raw.get("category", ""),
                           "product_condition": raw.get("itemCondition", "")}
            if origin == "dom":
                # Price and stock appear only in the validated offer object.
                raw_fields = raw.get("observations", {})
                observation["observed_fields"] = {k: v for k, v in raw_fields.items()
                                                  if k not in {"price_text", "currency_label", "fields"}}
                if price is not None and raw_fields.get("price_text"):
                    observation["observed_fields"]["price_text"] = raw_fields["price_text"]
                observation["observed_fields"]["fields"] = {k: v for k, v in raw_fields.get("fields", {}).items()
                                                             if k != "Availability"}
            structured = quote_record(
                source, json.dumps(observation, ensure_ascii=False),
                f"{origin}:Product[{index}].offers[{offer_index}]", "structured",
            )
            structured["offer_observation"] = {"observed_at": observed_at, "valid_until": valid_until or None,
                                               "volatile_fields": bool(price is not None or status)}
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
        if "offer_observed_at" in product and not offer_is_current(product["offer_observed_at"], product.get("offer_valid_until")):
            product["price"] = product["currency"] = product["availability"] = None
            product["offer_freshness"] = "stale_or_unknown"
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


def select_evidence(evidence, sources, char_budget, freshness=None):
    seen = set()
    counts = Counter()
    packed = []
    spend = 0
    if freshness:
        evidence = sorted(evidence, key=lambda row: freshness_status(
            sources[row["source_id"]].get("published_at"), freshness) != "fresh")
    for record in evidence:
        key = record["quote"].casefold()
        group = sources[record["source_id"]]["independence_group"]
        if key in seen:
            continue
        seen.add(key)
        counts[group] += 1
        if record["kind"] == "structured" and len(record["quote"]) > 1400:
            continue
        quote = record["quote"] if record["kind"] == "structured" else record["quote"][:550]
        row = dict(id=record["id"], source=group, quote=quote,
                   date=record["published_at"], kind=record["kind"])
        if freshness:
            row["publication_freshness"] = freshness_status(sources[record["source_id"]].get("published_at"), freshness)
        if record.get("page"):
            row["page"] = record["page"]
        packed.append((counts[group], len(packed), row))
    result = []
    for _, _, row in sorted(packed):
        size = len(json.dumps(row, ensure_ascii=False))
        if spend + size > char_budget:
            continue
        spend += size
        result.append(row)
    return result


def valid_reference(identifier, evidence, sources):
    record = evidence.get(identifier)
    if not record:
        return False
    source = sources.get(record.get("source_id"))
    if not source:
        return False
    # Legacy unit-test/minimal records may omit redundant provenance; when
    # present these fields must match their authoritative source.
    for field, source_field in (("source_url", "url"), ("content_hash", "content_hash"),
                                ("published_at", "published_at"), ("retrieved_at", "retrieved_at")):
        if field in record and source_field in source and record[field] != source[source_field]:
            return False
    if "id" in record and record["id"] != identifier:
        return False
    if "url" in source:
        try:
            if PublicPolicy().check(source["url"]) != source["url"]:
                return False
        except (ValueError, TypeError, AttributeError):
            return False
    if "page" in record:
        page = record["page"]
        metadata = source.get("metadata", {})
        if (metadata.get("document_type") != "pdf" or type(page) is not int
                or not 1 <= page <= metadata.get("pages_examined", 0)
                or not record.get("location", "").startswith(f"pdf:page-{page}:")):
            return False
    return True


def verified_claims(proposals, checked, evidence, sources, freshness=None):
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
        if len(ids) != len(check.evidence) or any(item not in claim.evidence or not valid_reference(item, evidence, sources) for item in ids):
            continue
        groups = supporting_groups(ids, evidence, sources)
        if check.status == "conflicting" and (len(groups) < 2 or claim.kind != "conflict"):
            continue
        if claim.kind == "conflict" and check.status != "conflicting":
            continue
        quotes = [evidence[item]["quote"] for item in ids]
        if not numerical_support(claim.text, quotes) or not quoted_support(claim.text, quotes):
            continue
        result.append({"text": claim.text, "kind": claim.kind, "evidence": ids,
                       "independent_sources": len(groups),
                       **({"freshness": claim_freshness(ids, evidence, sources, freshness)} if freshness else {})})
    return result


def citation_markdown(claims, evidence, sources):
    numbers = {source: i for i, source in enumerate(sources, 1)}
    lines = []
    for claim in claims:
        if not claim.get("evidence") or any(not valid_reference(i, evidence, sources) for i in claim["evidence"]):
            continue
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
        freshness_label = {
            "stale": " **Publication dates outside requested window.**",
            "mixed": " **Mixed publication freshness.**",
            "unknown": " **Publication freshness unestablished.**",
        }.get(claim.get("freshness"), "")
        lines.append(f"{label}{escaped} {citations}{freshness_label}")
    return "\n\n".join(lines)
