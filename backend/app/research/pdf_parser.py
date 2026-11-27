"""Run PDF parsing outside the research worker and validate its output."""

import asyncio
import json
import os
import sys
from pathlib import Path

from .pdf_worker import MAX_BYTES, MAX_OUTPUT, MAX_PAGES, MAX_PAGE_TEXT, MAX_TABLE_ROWS, MAX_CELL, MAX_TOTAL_TEXT

PARSER = Path(__file__).with_name("pdf_worker.py")
ENV_KEYS = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL"}
PDF_TIMEOUT = 15


def validate_result(result):
    if not isinstance(result, dict):
        raise ValueError("Invalid PDF parser response")
    count = result.get("page_count")
    pages = result.get("pages")
    if type(count) is not int or count < 1 or not isinstance(pages, list) or len(pages) > min(MAX_PAGES, count):
        raise ValueError("Invalid PDF page count")
    if not isinstance(result.get("title"), str) or len(result["title"]) > 200 or type(result.get("truncated")) is not bool:
        raise ValueError("Invalid PDF metadata")
    if len(pages) < count and not result["truncated"]:
        raise ValueError("Incomplete PDF coverage was not declared")
    total_text = total_rows = 0
    for index, page in enumerate(pages, 1):
        if not isinstance(page, dict) or type(page.get("page")) is not int or page["page"] != index:
            raise ValueError("Invalid PDF page location")
        if not isinstance(page.get("text"), str) or len(page["text"]) > MAX_PAGE_TEXT:
            raise ValueError("Invalid PDF page text")
        total_text += len(page["text"])
        tables = page.get("tables")
        if not isinstance(tables, list) or len(tables) > 3 * MAX_TABLE_ROWS:
            raise ValueError("Invalid PDF table records")
        total_rows += len(tables)
        seen = set()
        for row in tables:
            if not isinstance(row, dict):
                raise ValueError("Invalid PDF table row")
            table, number, cells = row.get("table"), row.get("row"), row.get("cells")
            if (type(table) is not int or not 1 <= table <= 3
                    or type(number) is not int or not 1 <= number <= MAX_TABLE_ROWS
                    or not isinstance(cells, list) or not 1 <= len(cells) <= 12
                    or any(not isinstance(c, str) or len(c) > MAX_CELL for c in cells)
                    or (table, number) in seen):
                raise ValueError("Invalid PDF table location or cells")
            seen.add((table, number))
    if total_text > MAX_TOTAL_TEXT or total_rows > 160:
        raise ValueError("PDF parser exceeded aggregate extraction limits")
    return result


async def parse_pdf(body, timeout=PDF_TIMEOUT):
    if not body.startswith(b"%PDF-") or len(body) > MAX_BYTES:
        raise ValueError("Invalid or oversized PDF")
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-I", str(PARSER),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env={key: value for key, value in os.environ.items() if key.upper() in ENV_KEYS},
    )
    try:
        async with asyncio.timeout(timeout):
            # Bound output while reading, not after allocating an arbitrary
            # amount of data. Input is at most MAX_BYTES.
            async def feed():
                try:
                    process.stdin.write(body)
                    await process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    process.stdin.close()

            async def receive():
                data = bytearray()
                while chunk := await process.stdout.read(65536):
                    data.extend(chunk)
                    if len(data) > MAX_OUTPUT:
                        raise ValueError("PDF parser output exceeded limit")
                return bytes(data)

            async with asyncio.TaskGroup() as group:
                group.create_task(feed())
                output = group.create_task(receive())
            status = await process.wait()
            if status != 0:
                raise ValueError("PDF extraction failed or was restricted")
            return validate_result(json.loads(output.result()))
    except ExceptionGroup as exc:
        raise ValueError("PDF parser communication failed") from exc
    finally:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        # Drain the remaining pipe without retaining data. A killed subprocess
        # with a full stdout pipe can otherwise leave wait() blocked.
        while await process.stdout.read(65536):
            pass
        await process.wait()
