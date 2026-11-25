"""Standalone bounded PDF text/table parser; invoked with isolated Python."""

import io
import json
import sys

MAX_BYTES = 8_000_000
MAX_PAGES = 40
MAX_PAGE_TEXT = 12_000
MAX_TOTAL_TEXT = 180_000
MAX_OUTPUT = 900_000
MAX_TABLE_ROWS = 24
MAX_CELL = 160


def restrict_resources():
    # Linux production workers get a hard process limit, not merely a timeout.
    # Other platforms use the parent's wall-clock timeout and output bounds.
    if sys.platform.startswith("linux"):
        import resource

        memory = 512 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_CPU, (8, 9))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def clean(value, limit):
    return " ".join(str(value or "").split())[:limit]


def parse(body):
    import pdfplumber

    if not body.startswith(b"%PDF-") or len(body) > MAX_BYTES:
        raise ValueError("Invalid or oversized PDF")
    pages = []
    remaining = MAX_TOTAL_TEXT
    truncated = False
    output_bytes = 4096  # Reserve metadata and JSON envelope space.
    total_rows = 0
    with pdfplumber.open(io.BytesIO(body)) as pdf:
        if pdf.doc.encryption is not None or not pdf.doc.is_extractable:
            raise ValueError("Encrypted or extraction-restricted PDF")
        count = len(pdf.pages)
        if not count:
            raise ValueError("PDF contains no pages")
        for page in pdf.pages[:MAX_PAGES]:
            if remaining <= 0:
                truncated = True
                break
            try:
                raw = page.extract_text() or ""
                limit = min(MAX_PAGE_TEXT, remaining)
                text = raw[:limit]
                remaining -= len(text)
                truncated |= len(raw) > limit
                tables = []
                # Only attempt ruled-table extraction on modest geometry.
                # Never extract or execute annotations, embedded files or forms.
                if 4 <= len(page.edges) <= 300:
                    found = page.find_tables()
                    truncated |= len(found) > 3
                    for table_number, table in enumerate(found[:3], 1):
                        rows = table.extract()
                        truncated |= len(rows) > MAX_TABLE_ROWS
                        for index, row in enumerate(rows[:MAX_TABLE_ROWS], 1):
                            if len(row) > 12:
                                truncated = True
                                continue
                            # Never cite a truncated cell as an observed number.
                            if any(len(clean(cell, MAX_CELL + 1)) > MAX_CELL for cell in row):
                                truncated = True
                                continue
                            cells = [clean(cell, MAX_CELL) for cell in row]
                            if any(cells):
                                if total_rows >= 160:
                                    truncated = True
                                    continue
                                tables.append({"table": table_number, "row": index, "cells": cells})
                                total_rows += 1
                record = {"page": page.page_number, "text": text, "tables": tables}
                size = len(json.dumps(record, ensure_ascii=True, separators=(",", ":")).encode("ascii")) + 1
                if output_bytes + size > MAX_OUTPUT:
                    record["tables"] = []
                    truncated = True
                    size = len(json.dumps(record, ensure_ascii=True, separators=(",", ":")).encode("ascii")) + 1
                if output_bytes + size > MAX_OUTPUT:
                    break
                output_bytes += size
                pages.append(record)
            finally:
                page.close()
        metadata = pdf.metadata or {}
        return {"title": clean(metadata.get("Title"), 200), "page_count": count,
                "pages": pages, "truncated": truncated or len(pages) < count}


def main():
    try:
        restrict_resources()
        body = sys.stdin.buffer.read(MAX_BYTES + 1)
        result = parse(body)
        encoded = json.dumps(result, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        if len(encoded) > MAX_OUTPUT:
            raise ValueError("PDF output exceeded bound")
        sys.stdout.buffer.write(encoded)
        return 0
    except Exception:
        # Avoid emitting document-derived exception text or raw PDF bytes.
        return 1


if __name__ == "__main__":
    sys.exit(main())
