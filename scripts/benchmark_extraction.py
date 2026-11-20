"""Isolated, reproducible normalization/persistence/export benchmark. No web traffic."""

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import tracemalloc


def main():
    with tempfile.TemporaryDirectory(prefix="adbot-extraction-benchmark-") as directory:
        root = Path(directory)
        os.environ.update(
            ADBOT_DATABASE_URL="sqlite:///" + str(root / "benchmark.db"),
            ADBOT_API_KEYS="benchmark-only-key-00000000000000000000",
            ADBOT_AI_PROVIDER="disabled",
            ADBOT_AI_FALLBACK_PROVIDER="disabled",
            ADBOT_BROWSER_SESSION_PERSISTENCE="false",
            ADBOT_ARTIFACT_DIR=str(root / "artifacts"),
        )
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
        from app.db import (
            Base,
            engine,
            Website,
            ExtractionSchema,
            Dataset,
            Job,
            DatasetExport,
            transaction,
        )
        from app.extraction.schemas import SchemaDefinition, DatasetOptions
        from app.extraction.engine import process_record
        from app.extraction.persistence import save_page
        from app.extraction.service import snapshot
        from app.extraction.exporter import export
        from sqlalchemy import event

        queries = [0]

        @event.listens_for(engine, "before_cursor_execute")
        def count_queries(*args):
            queries[0] += 1

        Base.metadata.create_all(engine)
        schema = SchemaDefinition.model_validate(
            {
                "name": "Benchmark",
                "identity_fields": ["url"],
                "fields": {
                    "name": {
                        "type": "string",
                        "method": "page_title",
                        "required": True,
                    },
                    "price": {"type": "currency", "method": "page_title"},
                    "url": {"type": "url", "method": "source_url", "required": True},
                },
            }
        ).model_dump()
        with transaction() as session:
            website = Website(
                owner="benchmark",
                name="Fixture",
                base_url="https://example.org",
                allowed_domains=["example.org"],
                configuration={
                    "max_pages": 10,
                    "max_duration_seconds": 300,
                    "retries": 0,
                },
            )
            session.add(website)
            session.flush()
            definition = ExtractionSchema(
                owner="benchmark", name="Benchmark", version=1, definition=schema
            )
            session.add(definition)
            session.flush()
            dataset = Dataset(
                owner="benchmark",
                name="Benchmark",
                website_id=website.id,
                schema_id=definition.id,
                options=DatasetOptions(max_records=1000).model_dump(),
            )
            session.add(dataset)
            session.flush()
            job = Job(
                owner="benchmark",
                website_id=website.id,
                snapshot={"configuration": website.configuration},
                status="running",
                lease_token="benchmark",
                lease_until=time.time() + 300,
                started_at=time.time(),
            )
            session.add(job)
            session.flush()
            snapshot(session, job, dataset.id)
            job_id, dataset_id, website_id = job.id, dataset.id, website.id
        tracemalloc.start()
        queries[0] = 0
        cpu = time.process_time()
        started = time.perf_counter()
        records = [
            process_record(
                {
                    "name": f"Product {i}",
                    "price": "USD 1,234.50",
                    "url": f"https://example.org/product/{i}",
                },
                schema,
                "https://example.org/catalog",
            )
            for i in range(1000)
        ]
        normalized = time.perf_counter()
        for offset in range(0, 1000, 100):
            save_page(
                job_id,
                "benchmark",
                f"https://example.org/catalog/{offset}",
                records[offset : offset + 100],
            )
        persisted = time.perf_counter()
        persistence_queries = queries[0]
        exports = {}
        for kind in ("json", "csv"):
            with transaction() as session:
                job = Job(
                    owner="benchmark",
                    website_id=website_id,
                    job_type="export",
                    snapshot={"export_schema": schema},
                    status="running",
                    lease_token="export",
                    lease_until=time.time() + 300,
                )
                session.add(job)
                session.flush()
                artifact = DatasetExport(
                    job_id=job.id,
                    dataset_id=dataset_id,
                    format=kind,
                    options={"columns": [], "include_revisions": False},
                    expires_at=time.time() + 3600,
                )
                session.add(artifact)
                identifier = job.id
            before = time.perf_counter()
            previous_queries = queries[0]
            export(identifier, "export")
            with transaction() as session:
                artifact = session.get(DatasetExport, identifier)
                exports[kind] = {
                    "seconds": time.perf_counter() - before,
                    "bytes": artifact.bytes,
                    "rows": artifact.rows,
                    "query_count": queries[0] - previous_queries,
                }
        from app.jobs import recover_expired

        with transaction() as session:
            session.get(Job, job_id).lease_until = time.time() - 1
        recovery_started = time.perf_counter()
        recover_expired()
        recovery_seconds = time.perf_counter() - recovery_started
        with transaction() as session:
            assert session.get(Job, job_id).status == "queued"
        finished = time.perf_counter()
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        result = {
            "records": 1000,
            "normalization_seconds": normalized - started,
            "persistence_seconds": persisted - normalized,
            "records_per_second_persistence": 1000 / (persisted - normalized),
            "persistence_query_count": persistence_queries,
            "total_query_count": queries[0],
            "total_seconds": finished - started,
            "process_cpu_seconds": time.process_time() - cpu,
            "peak_python_bytes": peak,
            "exports": exports,
            "errors": 0,
            "expired_read_job_requeue_seconds": recovery_seconds,
        }
        engine.dispose()
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class MemoryCounters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                    (name, ctypes.c_size_t)
                    for name in (
                        "peak_working_set",
                        "working_set",
                        "peak_paged",
                        "paged",
                        "peak_nonpaged",
                        "nonpaged",
                        "pagefile",
                        "peak_pagefile",
                    )
                ]

            memory = MemoryCounters()
            memory.cb = ctypes.sizeof(memory)
            ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(MemoryCounters),
                wintypes.DWORD,
            ]
            if ctypes.windll.psapi.GetProcessMemoryInfo(
                ctypes.windll.kernel32.GetCurrentProcess(),
                ctypes.byref(memory),
                memory.cb,
            ):
                result["process_peak_working_set_bytes"] = memory.peak_working_set
        result["database_bytes"] = sum(
            p.stat().st_size for p in root.glob("benchmark.db*")
        )
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
