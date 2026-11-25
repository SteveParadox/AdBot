"""Regression tests for source date, claim and volatile-offer integrity."""

from datetime import datetime, timezone
import json

import pytest

from app.research.contracts import Claim, Verification
from app.research.evidence import citation_markdown, verified_claims, valid_reference
from app.research.integrity import (
    claim_freshness, freshness_status, numerical_support, observed_offer_time,
    offer_is_current, parse_date, publication_date, quoted_support,
)

NOW = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)


def test_date_declarations_are_conservative():
    assert parse_date("2026-11-26", NOW) is None
    assert parse_date("2026-02-30", NOW) is None
    assert parse_date("2026-11-25T01:00:00", NOW) == "2026-11-25"
    date, metadata = publication_date([("meta", "2026-11-24"), ("json", "2026-11-23")], NOW)
    assert date is None and metadata["status"] == "conflicting"
    assert freshness_status("2026-11-24", "day", NOW) == "unknown"
    assert freshness_status("2026-11-24T13:00:00Z", "day", NOW) == "fresh"
    assert freshness_status("2026-11-23", "day", NOW) == "stale"


@pytest.mark.parametrize("claim,quote", [
    ("Profit rose 25%.", "Profit rose 25."),
    ("The loss was 10 NGN.", "The loss was 10 USD."),
    ("The battery holds 25 kWh.", "The battery holds 25 GB."),
    ("The change was 5 percentage points.", "The change was 5 percent."),
    ("Temperature was 10.", "Temperature was -10."),
    ("Version 3.11.4 is supported.", "Version 3.11.2 is supported."),
    ("Published 2026-11-25.", "Published 2026-11-24."),
])
def test_numeric_mismatch_is_not_supported(claim, quote):
    assert not numerical_support(claim, [quote])


def test_numeric_normalization_and_structured_currency():
    assert numerical_support("Revenue was ₦1.5 million.", ["Revenue was NGN 1,500,000."])
    assert numerical_support("Growth was 25 percent.", ["Growth was 25%."])
    offer = json.dumps({"offer": {"price": "1200000", "priceCurrency": "NGN"}})
    assert numerical_support("Price ₦1.2 million.", [offer])
    assert not numerical_support("Price USD 1.2 million.", [offer])
    assert not quoted_support('It said "profits doubled".', ["Profits grew by 10%."])


def test_claim_freshness_is_per_claim_not_per_answer():
    sources = {
        "a": {"published_at": "2026-11-25"},
        "b": {"published_at": "2020-01-02"},
        "c": {"published_at": None},
    }
    evidence = {key: {"source_id": key} for key in sources}
    assert claim_freshness(["a"], evidence, sources, "week", NOW) == "fresh"
    assert claim_freshness(["b"], evidence, sources, "week", NOW) == "stale"
    assert claim_freshness(["a", "b"], evidence, sources, "week", NOW) == "mixed"
    assert claim_freshness(["c"], evidence, sources, "week", NOW) == "unknown"


def test_offer_expiry_and_origin_age():
    assert offer_is_current(NOW.timestamp() - 10, "2026-11-25", NOW)
    assert not offer_is_current(NOW.timestamp() - 121, None, NOW)
    assert not offer_is_current(NOW.timestamp(), "2026-11-24", NOW)
    assert not offer_is_current(NOW.timestamp(), "2026-11-25T11:00:00Z", NOW)
    assert not offer_is_current(NOW.timestamp() + 1, None, NOW)
    assert observed_offer_time(NOW.timestamp(), {"age": "125"}) == NOW.timestamp() - 125
    assert observed_offer_time(NOW.timestamp(), {"age": "unknown"}) is None


def test_bad_reference_and_duplicate_verifier_ids_rejected():
    sources = {"a": {"id": "a", "url": "https://example.org/a", "content_hash": "hash-a",
                     "independence_group": "example.org"}}
    evidence = {"e": {"id": "e", "source_id": "a", "source_url": "https://example.org/a",
                      "content_hash": "hash-a", "quote": "Revenue was 10 NGN."}}
    claim = Claim(text="Revenue was 10 NGN.", kind="fact", evidence=["e"])
    checked = Verification(checks=[{"claim": 0, "status": "supported", "evidence": ["e"]}])
    assert len(verified_claims([claim], checked, evidence, sources)) == 1
    duplicate = Verification(checks=[{"claim": 0, "status": "supported", "evidence": ["e", "e"]}])
    assert not verified_claims([claim], duplicate, evidence, sources)
    evidence["e"]["content_hash"] = "hash-b"
    assert not valid_reference("e", evidence, sources)
    assert not verified_claims([claim], checked, evidence, sources)
    assert not citation_markdown([claim.model_dump()], evidence, sources)


def test_invalid_pdf_page_reference_is_rejected():
    sources = {"a": {"url": "https://example.org/report.pdf",
                     "metadata": {"document_type": "pdf", "pages_examined": 2}}}
    evidence = {"e": {"source_id": "a", "page": 3, "location": "pdf:page-3:line-1"}}
    assert not valid_reference("e", evidence, sources)
    evidence["e"].update(page=2, location="pdf:page-1:line-1")
    assert not valid_reference("e", evidence, sources)
    evidence["e"]["location"] = "pdf:page-2:line-1"
    assert valid_reference("e", evidence, sources)
