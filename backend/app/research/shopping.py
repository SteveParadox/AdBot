"""Conservative product observations and explainable offer ranking.

No model-generated values, external image requests, exchange-rate assumptions,
or cross-retailer merging on a shared title.
"""

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation

import pycountry


PRICE = re.compile(
    r"^(?:current price\s*[:\-]?\s*|sale price\s*[:\-]?\s*|price\s*[:\-]?\s*)?"
    r"(?P<before>₦|€|£|[A-Z]{3})?\s*(?P<amount>(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{1,12})(?:\.[0-9]{1,2})?)"
    r"\s*(?P<after>[A-Z]{3})?$", re.I,
)
SYMBOLS = {"₦": "NGN", "€": "EUR", "£": "GBP"}
SPEC_NAMES = {
    "ram": "RAM", "memory": "RAM", "system memory": "RAM",
    "storage": "Storage", "ssd": "Storage", "hard drive": "Storage",
    "vram": "VRAM", "graphics memory": "VRAM", "gpu memory": "VRAM", "video memory": "VRAM",
    "gpu": "GPU", "graphics": "GPU", "graphics card": "GPU",
    "processor": "CPU", "cpu": "CPU", "screen": "Display", "display": "Display",
    "battery": "Battery", "weight": "Weight", "condition": "Condition",
    "brand": "Brand", "manufacturer": "Brand", "model": "Model", "model number": "Model",
    "mpn": "MPN", "manufacturer part number": "MPN", "sku": "SKU", "gtin": "GTIN",
    "color": "Color", "colour": "Color", "size": "Size", "warranty": "Warranty",
    "shipping": "Shipping", "availability": "Availability",
}


def tidy(value, limit=250):
    return " ".join(str(value or "").split())[:limit]


def norm(value):
    return tidy(value).casefold()


def currency_code(value):
    value = SYMBOLS.get(value, value.upper())
    return value if value != "XXX" and len(value) == 3 and pycountry.currencies.get(alpha_3=value) else None


def price_value(value, currency=""):
    """Accept a single explicitly denominated amount, not ranges or installments."""
    match = PRICE.fullmatch(tidy(value, 100))
    if not match:
        return None
    tokens = [currency_code(v) for v in (match["before"], match["after"], currency) if v]
    if not tokens or None in tokens or len(set(tokens)) != 1:
        return None
    try:
        amount = Decimal(match["amount"].replace(",", ""))
        if amount <= 0 or amount >= Decimal("1000000000000"):
            return None
    except InvalidOperation:
        return None
    return format(amount, "f"), tokens[0]


def visible(node):
    for parent in (node, *node.iterancestors()):
        if parent.tag in {"script", "style", "template", "noscript", "del", "s", "strike", "aside", "nav", "footer"}:
            return False
        if any(parent.get(k) is not None for k in ("hidden", "inert", "data-ad")) or parent.get("aria-hidden") == "true":
            return False
        css = norm(parent.get("style")).replace(" ", "")
        flags = " ".join(parent.get(k, "") for k in ("class", "id", "aria-label"))
        if "display:none" in css or "visibility:hidden" in css or "line-through" in css:
            return False
        if re.search(r"(?:^|[\W_])(old-price|original-price|regular-price|was-price|compare-at|installment|"
                     r"monthly|deposit|shipping-price|sponsored|advertisement|related-products)(?:$|[\W_])", flags, re.I):
            return False
    return True


def text_of(node, limit=250):
    # Do not incorporate hidden descendant text or struck-through list prices.
    parts = [str(t) for t in node.xpath(".//text()")[:100] if visible(t.getparent())]
    return tidy(" ".join(parts), limit)


def one(values):
    unique = list(dict.fromkeys(v for v in values if v))
    return unique[0] if len(unique) == 1 else None


def labeled_fields(scope):
    fields = {}
    for row in scope.xpath(".//tr | .//dt")[:100]:
        if not visible(row):
            continue
        if row.tag == "tr":
            cells = row.xpath("./th | ./td")
            if len(cells) != 2:
                continue
            label, value = map(text_of, cells)
        else:
            other = row.getnext()
            if other is None or other.tag != "dd" or not visible(other):
                continue
            label, value = text_of(row), text_of(other)
        key = SPEC_NAMES.get(norm(label).rstrip(":"))
        if key and value:
            fields.setdefault(key, set()).add(value)
    return {key: next(iter(values)) for key, values in fields.items() if len(values) == 1}


def visible_products(tree):
    """Extract only locally scoped, explicit observations; never join unrelated cards."""
    scopes = tree.xpath("//*[contains(concat(' ', normalize-space(@itemtype), ' '), ' https://schema.org/Product ')"
                        " or contains(concat(' ', normalize-space(@itemtype), ' '), ' http://schema.org/Product ')"
                        " or @data-product or contains(concat(' ', normalize-space(@class), ' '), ' product-detail ')"
                        " or contains(concat(' ', normalize-space(@class), ' '), ' product-card ')]")[:32]
    # Prefer leaf scopes to avoid pairing one card's price with another name.
    scopes = [s for s in scopes if not any(s is not other and s in other.iterancestors() for other in scopes)]
    if not scopes:
        mains = tree.xpath("//main | //*[@role='main']")
        # Unmarked articles and reviews are not offers. Require a declared
        # product page or explicit identity fields alongside a single heading.
        product_meta = any(norm(n.get("content")) == "product" for n in tree.xpath("//meta[@property='og:type']"))
        if len(mains) == 1:
            fields = labeled_fields(mains[0])
            if product_meta or any(key in fields for key in ("SKU", "MPN", "GTIN")):
                scopes = mains
    result = []
    for scope in scopes[:16]:
        if not visible(scope):
            continue
        names = scope.xpath(".//*[@itemprop='name' and not(self::meta)]")
        headings = names or scope.xpath(".//h1") or scope.xpath(".//h2") or scope.xpath(".//h3")
        name = one(text_of(n) for n in headings[:20] if visible(n))
        # Multiple distinct headings in a purported offer are ambiguous.
        if not name:
            continue
        currency = one(tidy(n.get("content") or text_of(n), 12) for n in
                       scope.xpath(".//*[@itemprop='priceCurrency']")[:10] if visible(n)) or ""
        if not currency and len(scopes) == 1:
            currency = one(tidy(n.get("content"), 12) for n in
                           tree.xpath("//meta[@property='product:price:currency']")[:5]) or ""
        amounts = {}
        for node in scope.xpath(".//*[@itemprop='price' or contains(concat(' ',normalize-space(@class),' '),' price ')"
                                " or contains(concat(' ',normalize-space(@class),' '),' product-price ')"
                                " or contains(concat(' ',normalize-space(@class),' '),' sale-price ')"
                                " or contains(concat(' ',normalize-space(@class),' '),' current-price ')]"
                                " | .//p | .//span")[:250]:
            if not visible(node) or node.tag == "meta":
                continue
            raw = text_of(node, 100)
            marked = node.get("itemprop") == "price" or bool(set(node.get("class", "").split()) &
                     {"price", "product-price", "sale-price", "current-price"})
            if not marked and not re.match(r"^(?:current |sale )?price\s*:", raw, re.I):
                continue
            # Reject a price within a financing/discount context rather than
            # taking a bare numeric span out of its surrounding text.
            context = text_of(node.getparent(), 500) if node.getparent() is not None else raw
            if re.search(r"\b(?:per month|monthly|installments?|deposit|starting at|from|was|save)\b|/mo\b", context, re.I):
                continue
            parsed = price_value(raw, currency)
            if parsed:
                amounts.setdefault(parsed, raw)
        if len(amounts) != 1:
            continue
        (price, code), raw_price = next(iter(amounts.items()))
        fields = labeled_fields(scope)
        availability = {"in stock": "InStock", "out of stock": "OutOfStock", "sold out": "SoldOut",
                        "preorder": "PreOrder", "pre-order": "PreOrder"}.get(norm(fields.get("Availability")))
        specs = {k: v for k, v in fields.items() if k not in
                 {"Brand", "Model", "MPN", "SKU", "GTIN", "Color", "Size", "Condition", "Warranty", "Shipping", "Availability"}}
        offer = {"price": price, "priceCurrency": code, "itemCondition": fields.get("Condition", ""),
                 "availability": availability or "", "warranty": {"description": fields.get("Warranty", "")},
                 "shippingDetails": {"description": fields.get("Shipping", "")}}
        result.append({
            "name": name, "brand": fields.get("Brand", ""), "model": fields.get("Model", ""),
            "sku": fields.get("SKU", ""), "mpn": fields.get("MPN", ""), "gtin": fields.get("GTIN", ""),
            "color": fields.get("Color", ""), "size": fields.get("Size", ""),
            "additionalProperty": [{"name": k, "value": v} for k, v in specs.items()],
            "offers": [offer], "_origin": "dom", "_observations": {
                "name": name, "price_text": raw_price, "currency_label": currency, "fields": fields,
            },
        })
    return result


def condition_value(value):
    raw = norm(value).rsplit("/", 1)[-1].replace("-", "").replace(" ", "")
    return {"newcondition": "new", "new": "new", "usedcondition": "used", "used": "used",
            "refurbishedcondition": "refurbished", "refurbished": "refurbished",
            "damagedcondition": "damaged", "damaged": "damaged",
            "openbox": "open box"}.get(raw, "unknown")


def valid_gtin(value):
    value = tidy(value)
    if not re.fullmatch(r"\d{8}|\d{12,14}", value) or len(set(value)) == 1:
        return None
    check = sum(int(digit) * (3 if i % 2 == 0 else 1) for i, digit in enumerate(reversed(value[:-1])))
    return value.zfill(14) if (-check) % 10 == int(value[-1]) else None


def comparable_identity(product):
    """Conservative exact identifier AND known condition AND observed configuration."""
    variant = product.get("variant", {})
    condition = variant.get("condition")
    if condition not in {"new", "used", "refurbished", "open box", "damaged"}:
        return None
    gtin = valid_gtin(product.get("gtin"))
    brand, mpn = norm(product.get("brand")), norm(variant.get("mpn"))
    if gtin:
        identity = ("gtin", gtin)
    elif brand and mpn:
        identity = ("mpn", brand, mpn)
    else:
        return None
    config = sorted((norm(k), norm(v)) for k, v in product.get("specifications", {}).items())
    options = sorted((k, norm(variant[k])) for k in ("color", "size") if variant.get(k))
    # Unknown/mismatched configuration is not treated as equivalent.
    return hashlib.sha256(json.dumps([identity, condition, config, options], sort_keys=True).encode()).hexdigest()[:20]


def capacity(value):
    # Permit common unambiguous annotations without interpreting multiple
    # capacities, model names or marketing claims as an observed amount.
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(GB|TB|MB)(?:\s+(?:DDR[345]|GDDR[456X]+|LPDDR[45X]+|SSD|NVME|HDD|RAM|VRAM))*\s*",
                         value or "", re.I)
    if not match:
        return None
    return Decimal(match[1]) * {"gb": 1, "tb": 1024, "mb": Decimal(1) / 1024}[match[2].lower()]


def requirements(question):
    text = question.casefold()
    found = {}
    spec = r"(?:vram|graphics memory|gpu memory|video memory|ram|system memory|storage|ssd)"
    amount = r"(\d+(?:\.\d+)?)\s*(gb|tb|mb)"
    modifier = r"(at least|minimum(?: of)?|at most|maximum(?: of)?|no more than|under|up to|exactly|>=|<=)?"
    patterns = (
        (rf"\b({spec})\s*(?:of|:)?\s*{modifier}\s*{amount}\b", False),
        (rf"{modifier}\s*\b{amount}\s*(?:of\s+)?({spec})\b", True),
    )
    occupied = []
    for pattern, reverse in patterns:
        for match in re.finditer(pattern, text):
            if reverse and any(match.start() < end and start < match.end() for start, end in occupied):
                continue
            if not reverse:
                occupied.append(match.span())
            label, mod, num, unit = (match[4], match[1], match[2], match[3]) if reverse else match.groups()
            key = SPEC_NAMES[label]
            op = ("max" if mod and (mod.startswith("maximum") or mod in
                  {"at most", "no more than", "under", "up to", "<="})
                  else "exact" if mod == "exactly" else "min")
            found.setdefault(key, set()).add((op, capacity(num + unit)))
    # Preserve multiple compatible bounds rather than letting one overwrite
    # another; contradictory user requirements cannot all be satisfied.
    return [(key, op, target) for key, values in sorted(found.items())
            for op, target in sorted(values) if target is not None]


def suitability(product, question):
    specs = {}
    for name, value in product.get("specifications", {}).items():
        key = SPEC_NAMES.get(norm(name), name)
        specs.setdefault(key, set()).add(tidy(value))
    observed = {key: one(values) for key, values in specs.items()}
    rules = requirements(question)
    checks = []
    for key, op, target in rules:
        actual = capacity(observed.get(key))
        status = ("unknown" if actual is None else "met" if
                  (actual >= target if op == "min" else actual <= target if op == "max" else actual == target)
                  else "not_met")
        checks.append({"requirement": f"{key} {op} {target} GB", "observed": observed.get(key),
                       "status": status})
    # Named GPU constraints use only the explicitly observed graphics field.
    # A name in the query is not a license to infer specifications.
    requested_gpu = set(re.findall(r"\b(?:rtx|gtx|rx)\s*\d{3,4}(?:\s*(?:ti|super|xt|xtx))?\b", question, re.I))
    if requested_gpu and not re.search(r"\b(?:compare|versus|vs\.?|or)\b", question, re.I):
        actual = observed.get("GPU")
        models = {re.sub(r"\s+", "", m.casefold()) for m in
                  re.findall(r"\b(?:rtx|gtx|rx)\s*\d{3,4}(?:\s*(?:ti|super|xtx|xt))?\b", actual or "", re.I)}
        for wanted in sorted(requested_gpu):
            checks.append({"requirement": f"GPU {wanted.upper()}", "observed": actual,
                           "status": "unknown" if not models else
                           "met" if re.sub(r"\s+", "", wanted.casefold()) in models else "not_met"})
    # A condition preference is explicit only in ordinary purchase wording.
    # Comparisons and alternatives do not require every offer to be new.
    condition = product.get("variant", {}).get("condition", "unknown")
    if not re.search(r"\b(?:compare|versus|vs\.?|or)\b", question, re.I):
        wanted = None
        if re.search(r"\b(?:new only|brand new|not (?:used|refurbished)|new (?:laptops?|phones?|products?))\b", question, re.I):
            wanted = "new"
        elif re.search(r"\b(?:refurbished only|refurbished (?:laptops?|phones?|products?))\b", question, re.I):
            wanted = "refurbished"
        elif re.search(r"\b(?:used only|second.hand (?:laptops?|phones?|products?)|used (?:laptops?|phones?|products?))\b", question, re.I):
            wanted = "used"
        if wanted:
            checks.append({"requirement": f"Condition {wanted}", "observed": condition,
                           "status": "unknown" if condition == "unknown" else
                           "met" if condition == wanted else "not_met"})
    # A workload heuristic, not a benchmark or claim of model compatibility.
    ai = bool(re.search(r"\b(?:ai engineering|machine learning|deep learning|local llms?|ai training)\b", question, re.I))
    workload = []
    if ai:
        for key, threshold in (("RAM", 16), ("VRAM", 8)):
            if any(rule[0] == key for rule in rules):
                continue
            actual = capacity(observed.get(key))
            workload.append({"requirement": f"{key} heuristic ≥ {threshold} GB", "observed": observed.get(key),
                             "status": "unknown" if actual is None else "met" if actual >= threshold else "not_met"})
    hard = [c["status"] for c in checks]
    soft = [c["status"] for c in workload]
    return {"requirements": checks, "workload_hints": workload,
            "status": "not_met" if "not_met" in hard else "unknown" if "unknown" in hard else "met" if hard else "not_requested",
            "score": sum(2 if s == "met" else -2 if s == "not_met" else 0 for s in soft)}
