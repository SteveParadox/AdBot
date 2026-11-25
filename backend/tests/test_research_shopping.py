"""Product research regression tests (local fixtures, no live retailer traffic)."""

import json
from decimal import Decimal

import pytest
from lxml import html

from app.research.evidence import product_evidence, rank_products, source_record
from app.research.retrieval import Response, extract
from app.research.shopping import comparable_identity, price_value, requirements, suitability, visible_products


@pytest.mark.parametrize("text,currency,expected", [
    ("₦1,200,000.00", "", ("1200000.00", "NGN")),
    ("Price: 500 USD", "", ("500", "USD")),
    ("500", "EUR", ("500", "EUR")),
    ("$500", "", None),
    ("₦500 - ₦900", "", None),
    ("₦500 / month", "", None),
    ("From ₦500", "", None),
    ("₦500", "USD", None),
    ("₦0", "", None),
    ("₦12,00", "", None),
])
def test_price_observation_is_unambiguous(text, currency, expected):
    assert price_value(text, currency) == expected


def page(markup, domain="store.example.com.ng"):
    url = f"https://{domain}/product"
    document = extract(Response(url, markup.encode(), "text/html", "utf-8", {}), True)
    return product_evidence(document, source_record(document, "laptop Nigeria", "fixture"), "NG")


def test_dom_offer_retains_observed_specs_condition_and_provenance():
    products, evidence = page("""
        <main class="product-detail"><h1>Example laptop</h1>
          <p class="price">₦950,000</p>
          <h2>Specifications</h2>
          <table><tr><th>RAM</th><td>16 GB DDR5</td></tr>
            <tr><th>GPU</th><td>NVIDIA RTX 4060</td></tr>
            <tr><th>VRAM</th><td>8 GB</td></tr>
            <tr><th>Condition</th><td>Refurbished</td></tr>
            <tr><th>Availability</th><td>In stock</td></tr>
          </table>
        </main>
    """)
    assert len(products) == 1
    product = products[0]
    assert product["price"] == "950000"
    assert product["currency"] == "NGN"
    assert product["variant"]["condition"] == "refurbished"
    assert product["specifications"]["RAM"] == "16 GB DDR5"
    assert product["extraction_method"] == "dom"
    assert product["availability"] == "In stock"
    assert evidence[0]["location"].startswith("dom:")
    assert json.loads(evidence[0]["quote"])["observed_fields"]["price_text"] == "₦950,000"
    assert product["evidence_id"] == evidence[0]["id"]


@pytest.mark.parametrize("markup", [
    '<main><h1>Review of laptops</h1><p class="price">₦10,000</p></main>',
    '<main class="product-detail"><h1>Laptop</h1><p class="price">₦10,000 / month</p></main>',
    '<main class="product-detail"><h1>Laptop</h1><p>Installment <span class="price">₦10,000</span></p></main>',
    '<main class="product-detail"><h1>Laptop</h1><p class="price">₦10,000</p><p class="price">₦20,000</p></main>',
    '<main class="product-detail"><h1>Laptop</h1><del class="price">₦10,000</del></main>',
    '<main class="product-detail"><h1>Laptop</h1><p hidden class="price">₦10,000</p></main>',
])
def test_ambiguous_or_non_offer_pages_are_not_products(markup):
    assert visible_products(html.fromstring(markup)) == []


def test_separate_cards_do_not_mix_prices_or_specs():
    products, _ = page("""
      <main><div class="product-card"><h2>Model A</h2>
      <p class="price">₦500,000</p><dl><dt>RAM</dt><dd>8 GB</dd></dl></div>
      <div class="product-card"><h2>Model B</h2>
      <p class="price">₦850,000</p><dl><dt>RAM</dt><dd>16 GB</dd></dl></div></main>
    """)
    assert {(p["name"], p["price"], p["specifications"]["RAM"]) for p in products} == {
        ("Model A", "500000", "8 GB"), ("Model B", "850000", "16 GB"),
    }


def offer(domain, price, ram="16 GB", condition="NewCondition", mpn="X16-001", gpu="RTX 4060", vram="8 GB"):
    raw = {"@type": "Product", "name": "Example laptop", "brand": "Example",
           "mpn": mpn, "sku": domain, "_origin": "dom", "_observations": {"fake": "untrusted"},
           "additionalProperty": [{"name": k, "value": v} for k, v in
                                  (("RAM", ram), ("GPU", gpu), ("VRAM", vram)) if v],
           "offers": {"@type": "Offer", "price": price, "priceCurrency": "NGN",
                      "availability": "InStock", "itemCondition": condition}}
    products, evidence = page(f'<script type="application/ld+json">{json.dumps(raw)}</script>', domain)
    assert products[0]["extraction_method"] == "json-ld"
    assert "observed_fields" not in json.loads(evidence[0]["quote"])
    return products[0]


def test_identity_preserves_condition_configuration_and_retailer_offers():
    a = offer("one-shop.com.ng", "950000")
    b = offer("two-shop.com.ng", "1000000")
    refurbished = offer("three-shop.com.ng", "750000", condition="RefurbishedCondition")
    different = offer("four-shop.com.ng", "650000", ram="8 GB")
    unknown = offer("five-shop.com.ng", "550000", condition="")
    assert comparable_identity(a) == comparable_identity(b)
    assert comparable_identity(a) != comparable_identity(refurbished)
    assert comparable_identity(a) != comparable_identity(different)
    assert comparable_identity(unknown) is None
    ranked = rank_products([a, b, refurbished, different, unknown, a],
                           "Laptops under ₦1.5 million with at least 16 GB RAM")
    assert len(ranked) == 5
    assert all(p["comparable_sources"] == 2 for p in ranked if p["comparison_group"] == comparable_identity(a))
    assert ranked[-1]["suitability"]["status"] == "not_met"


def test_rank_uses_verified_requirements_before_lowest_price():
    cheap = offer("one-shop.com.ng", "300000", ram="8 GB", gpu="GTX 1050", vram="4 GB")
    missing = offer("two-shop.com.ng", "500000", ram="", gpu="", vram="")
    good = offer("three-shop.com.ng", "900000")
    ranked = rank_products([cheap, missing, good], "AI engineering laptop under ₦1.5 million, RAM 16 GB and RTX 4060")
    assert [p["suitability"]["status"] for p in ranked] == ["met", "unknown", "not_met"]
    assert ranked[0]["price"] == "900000"
    assert ranked[1]["suitability"]["requirements"][0]["observed"] is None


def test_requirement_parser_does_not_cross_specification_boundaries():
    assert requirements("RAM 16 GB VRAM 8 GB") == [
        ("RAM", "min", Decimal(16)), ("VRAM", "min", Decimal(8)),
    ]
    assert set(requirements("at least 16 GB RAM and storage up to 1 TB")) == {
        ("RAM", "min", Decimal(16)), ("Storage", "max", Decimal(1024)),
    }
    assert suitability({"specifications": {"RAM": "16 GB or 32 GB"}}, "RAM 16 GB")["status"] == "unknown"


def test_unconvertible_currency_is_not_within_budget():
    item = offer("one-shop.com.ng", "100000")
    item["currency"] = "USD"
    result = rank_products([item], "Laptop under ₦1.5 million")[0]
    assert result["budget_requested"] is True
    assert result["within_budget"] is None
