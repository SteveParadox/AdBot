"""Regression tests for public PDF retrieval and page-scoped evidence."""

import json
import time

import httpx
import pytest

from app.research.evidence import citation_markdown, select_evidence, source_record, text_evidence
from app.research.pdf_parser import parse_pdf, validate_result
from app.research.pdf_worker import MAX_BYTES, MAX_PAGES
from app.research.retrieval import DOCUMENTS, Fetcher, Response, extract_pdf
from app.research.search import Hit
from app.research.service import new_metrics

URL = "https://science.example.org/report.pdf"


def fixture_pdf(streams):
    """Build a tiny standards-compliant PDF without a test-only dependency."""
    kids = " ".join(f"{4 + index * 2} 0 R" for index in range(len(streams)))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Count {len(streams)} /Kids [{kids}] >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for index, stream in enumerate(streams):
        objects.extend([
            (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
             f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + index * 2} 0 R >>").encode(),
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
        ])
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


TEXT = b"BT /F1 12 Tf 72 720 Td (Battery storage improved by 25 percent in the controlled experiment.) Tj ET"
TABLE = (
    b"72 500 m 372 500 l S 72 525 m 372 525 l S 72 550 m 372 550 l S "
    b"72 500 m 72 550 l S 222 500 m 222 550 l S 372 500 m 372 550 l S "
    b"BT /F1 12 Tf 80 533 Td (Metric) Tj ET "
    b"BT /F1 12 Tf 230 533 Td (Battery capacity) Tj ET "
    b"BT /F1 12 Tf 80 508 Td (Measured) Tj ET "
    b"BT /F1 12 Tf 230 508 Td (25 kWh) Tj ET"
)


async def test_public_pdf_text_and_ruled_table_page_locations():
    raw = fixture_pdf([TEXT, TABLE])
    result = await parse_pdf(raw)
    assert result["page_count"] == 2
    assert "25 percent" in result["pages"][0]["text"]
    rows = result["pages"][1]["tables"]
    assert any(row["cells"] == ["Measured", "25 kWh"] for row in rows)
    doc = await extract_pdf(Response(URL, raw, "application/pdf", "utf-8", {}))
    source = source_record(doc, "battery capacity storage", "fixture")
    evidence = text_evidence(doc, source, "battery capacity storage")
    assert {row["page"] for row in evidence} == {1, 2}
    table = next(row for row in evidence if row["kind"] == "structured" and "25 kWh" in row["quote"])
    assert json.loads(table["quote"])["first_row"] == ["Metric", "Battery capacity"]
    answer = citation_markdown([{"kind": "fact", "text": "Battery capacity was 25 kWh.",
                               "evidence": [table["id"]]}], {table["id"]: table}, {source["id"]: source})
    assert f"[1 p. 2](<{URL}#page=2>)" in answer
    assert doc.published is None
    assert not doc.metadata["extraction_truncated"]


async def test_page_bound_is_reported():
    result = await parse_pdf(fixture_pdf([TEXT] * (MAX_PAGES + 1)))
    assert result["page_count"] == MAX_PAGES + 1
    assert len(result["pages"]) == MAX_PAGES
    assert result["truncated"] is True


@pytest.mark.parametrize("body", [b"not a PDF", b"%PDF-1.7\nbroken", b"%PDF-" + b"x" * MAX_BYTES],
                         ids=["non-pdf", "malformed-pdf", "oversized-pdf"])
async def test_invalid_pdf_rejected(body):
    with pytest.raises(ValueError):
        await parse_pdf(body)


async def test_robots_header_rejected_before_parser():
    with pytest.raises(ValueError):
        await extract_pdf(Response(URL, fixture_pdf([TEXT]), "application/pdf", "utf-8", {"x-robots-tag": "nosnippet"}))


def test_parser_protocol_rejects_forged_page_locations():
    result = {"title": "", "page_count": 1, "truncated": False,
              "pages": [{"page": 2, "text": "fake", "tables": []}]}
    with pytest.raises(ValueError):
        validate_result(result)


async def test_pdf_empty_text_does_not_create_evidence():
    doc = await extract_pdf(Response(URL, fixture_pdf([b""]), "application/pdf", "utf-8", {}))
    assert not doc.blocks and not doc.table_rows
    assert not text_evidence(doc, source_record(doc, "battery", "fixture"), "battery")


async def test_pdf_fetch_reuses_policy_cache_and_keeps_page_metadata():
    raw = fixture_pdf([TEXT, TABLE])
    requests = []
    metrics = new_metrics()
    DOCUMENTS.items.clear()

    def respond(request):
        requests.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=raw, headers={"Content-Type": "application/pdf", "ETag": '"pdf"'})

    hit = Hit("Report", URL, URL, "Battery report", "fixture", "science.example.org", None,
              time.time(), 1, "web", {}, "battery")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        fetcher = Fetcher("pdf-owner", metrics)
        fetcher.client = client
        first = await fetcher.retrieve(hit, False, None)
        assert first and first.metadata["document_type"] == "pdf"
        assert first.block_locations[0]["page"] == 1
        assert await fetcher.retrieve(hit, False, None) == first
        assert metrics["pdf_parse_attempts"] == 1
        assert all(request.method == "GET" for request in requests)
        assert len([request for request in requests if request.url.path == "/report.pdf"]) == 1


def test_pdf_table_evidence_is_not_truncated_as_invalid_json():
    row = {"id": "e1", "source_id": "s1", "quote": json.dumps({"cells": ["x" * 600]}),
           "kind": "structured", "page": 1, "published_at": None}
    packed = select_evidence([row], {"s1": {"independence_group": "example.org"}}, 2000)
    assert packed[0]["quote"] == row["quote"] and packed[0]["page"] == 1


async def test_parser_timeout_is_bounded():
    with pytest.raises(TimeoutError):
        await parse_pdf(fixture_pdf([TEXT] * 40), timeout=0)
