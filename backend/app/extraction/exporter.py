import asyncio
import csv
import io
import json
import time
import threading

from sqlalchemy import select

from ..config import settings
from ..db import Dataset, DatasetExport, ExtractedRecord, RecordRevision, Job, transaction, uid
from ..jobs import owned_job
from ..concurrency import IOExecutor


def csv_value(value):
    text = (
        ""
        if value is None
        else json.dumps(value, ensure_ascii=False)
        if isinstance(value, (dict, list))
        else str(value)
    )
    if text.lstrip(" \t\r\n\ufeff").startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        text = "'" + text
    return text


def flatten(value, prefix=""):
    result = {}
    for key, item in value.items():
        name = prefix + "." + key if prefix else key
        if isinstance(item, dict):
            result.update(flatten(item, name))
        else:
            result[name] = item
    return result


def export(job_id, token, stop=None):
    root = settings().artifact_dir / "exports"
    root.mkdir(parents=True, exist_ok=True)
    with transaction() as session:
        job = owned_job(session, job_id, token)
        artifact = session.get(DatasetExport, job_id)
        dataset = session.get(Dataset, artifact.dataset_id)
        if not dataset or dataset.owner != job.owner:
            raise ValueError("Dataset unavailable")
        version = dataset.version
        dataset_id, kind, options = dataset.id, artifact.format, artifact.options
        definition = job.snapshot["export_schema"]
        columns = options["columns"] or list(definition["fields"])
        batch_size = 1 if options["include_revisions"] else 100
        selected_ids = None
        selected_hashes = None
        if options.get("query") is not None:
            from .query import DatasetQuery, select_records
            selected = select_records(session, dataset.id, definition, DatasetQuery.model_validate(options["query"]), options.get("source_record_hashes"))
            selected_ids = [row.id for row in selected]
            selected_hashes = {row.id: row.content_hash for row in selected}
            artifact.options = {**options, "selected_record_hashes": selected_hashes, "selected_record_ids": selected_ids}

    filename = uid() + "." + kind
    path = root / filename
    with transaction() as session:
        job = owned_job(session, job_id, token)
        job.execution_state = {**job.execution_state, "export_filename": filename}
    written = rows = 0

    def write(file, text):
        nonlocal written
        encoded = text.encode("utf-8")
        written += len(encoded)
        if written > settings().extraction_max_export_bytes:
            raise ValueError("Export exceeds operator size limit; select fewer columns or records")
        file.write(encoded)

    try:
        with path.open("xb") as file:
            if kind == "json":
                write(
                    file,
                    json.dumps({"schema": definition, "dataset_version": version, **({"query": options["query"]} if options.get("query") is not None else {})}, ensure_ascii=False)[:-1]
                    + ',"records":[',
                )
            else:
                buffer = io.StringIO(newline="")
                csv.writer(buffer).writerow(columns)
                write(file, buffer.getvalue())
            cursor = ""
            selected_offset = 0
            while True:
                if stop is not None and stop.is_set():
                    raise InterruptedError("Export worker stopped")
                with transaction() as session:
                    job = owned_job(session, job_id, token)
                    if job.cancel_requested:
                        raise ValueError("Export cancelled")
                    from ..automation import get_policy

                    paused = job.pause_requested or get_policy(session).paused
                    if paused:
                        batch = None
                    else:
                        query = select(ExtractedRecord).where(
                            ExtractedRecord.dataset_id == dataset_id, ExtractedRecord.id > cursor
                        )
                        batch = session.scalars(query.order_by(ExtractedRecord.id).limit(batch_size)).all()
                        if selected_ids is not None:
                            ids = selected_ids[selected_offset:selected_offset + batch_size]
                            found = {r.id: r for r in session.scalars(select(ExtractedRecord).where(ExtractedRecord.dataset_id == dataset_id, ExtractedRecord.id.in_(ids)))}
                            if len(found) != len(ids) or any(found[i].content_hash != selected_hashes[i] for i in ids):
                                raise ValueError("Query records changed during export")
                            batch = [found[i] for i in ids]

                    if session.get(Dataset, dataset_id).version != version:
                        raise ValueError("Dataset changed during export; retry to obtain a consistent version")
                    values = []
                    for row in batch or []:
                        scope = options.get("source_record_hashes")
                        if scope is not None:
                            if row.id not in scope:
                                continue
                            if row.content_hash != scope[row.id] or row.status != "active":
                                raise ValueError("Task records changed during export; re-observe before exporting")
                        value = {
                            "id": row.id,
                            "data": row.data,
                            "provenance": row.provenance,
                            "status": row.status,
                            "validation_status": row.validation_status,
                            "first_seen": row.first_seen,
                            "last_seen": row.last_seen,
                        }
                        if options["include_revisions"]:
                            value["revisions"] = [
                                {"number": r.number, "data": r.data, "provenance": r.provenance}
                                for r in session.scalars(
                                    select(RecordRevision)
                                    .where(RecordRevision.record_id == row.id)
                                    .order_by(RecordRevision.number)
                                )
                            ]
                        values.append(value)
                    next_cursor = batch[-1].id if batch else None
                if paused:
                    if stop is None:
                        raise InterruptedError("Export is paused")
                    stop.wait(0.25)
                    continue
                if not batch:
                    break
                for value in values:
                    if kind == "json":
                        write(file, ("," if rows else "") + json.dumps(value, ensure_ascii=False, allow_nan=False))
                    else:
                        buffer = io.StringIO(newline="")
                        values_flat = flatten(value["data"])
                        csv.writer(buffer).writerow(
                            [csv_value(values_flat.get(column, value["data"].get(column))) for column in columns]
                        )
                        write(file, buffer.getvalue())
                    rows += 1
                cursor = next_cursor
                selected_offset += len(batch)
                with transaction() as session:
                    owned_job(session, job_id, token)
                    artifact = session.get(DatasetExport, job_id)
                    artifact.rows, artifact.bytes = rows, written
            if kind == "json":
                write(file, "]}")
        with transaction() as session:
            owned_job(session, job_id, token)
            if session.get(Dataset, dataset_id).version != version:
                raise ValueError("Dataset changed during export; retry")
            artifact = session.get(DatasetExport, job_id)
            if options.get("source_record_hashes") is not None and rows != len(selected_ids if selected_ids is not None else options["source_record_hashes"]):
                raise ValueError("Task record scope changed during export")
            artifact.filename, artifact.rows, artifact.bytes = filename, rows, written
            artifact.expires_at = time.time() + settings().extraction_export_ttl_seconds
    except BaseException:
        path.unlink(missing_ok=True)
        raise


class ExportRunner:
    def __init__(self, job_id, token):
        self.id, self.token = job_id, token
        with transaction() as session:
            self.cfg = owned_job(session, job_id, token).snapshot["configuration"]
        self.gate = asyncio.Event()
        self.gate.set()

    async def run(self):
        # A bounded dedicated operation; no browser/page objects cross threads.
        async with IOExecutor(1) as executor:
            stop = threading.Event()
            try:
                await executor.run(export, self.id, self.token, stop)
            finally:
                stop.set()


def cleanup(session):
    from sqlalchemy import delete
    from ..db import Dataset, DataChange, ExtractionIssue

    now = time.time()
    for row in session.scalars(
        select(DatasetExport)
        .join(Job, Job.id == DatasetExport.job_id)
        .where(DatasetExport.expires_at < now, Job.status.in_(["completed", "failed", "cancelled"]))
    ):
        if row.filename:
            (settings().artifact_dir / "exports" / row.filename).unlink(missing_ok=True)
            row.filename = None
    active_files = {
        job.execution_state.get("export_filename")
        for job in session.scalars(
            select(Job).where(Job.status.not_in(["completed", "failed", "cancelled"]))
        )
    }
    root = settings().artifact_dir / "exports"
    if root.exists():
        for path in root.iterdir():
            if path.is_file() and path.suffix in {".json", ".csv"} and path.name not in active_files:
                try:
                    if path.stat().st_mtime < now - settings().extraction_export_ttl_seconds:
                        path.unlink(missing_ok=True)
                except (FileNotFoundError, PermissionError):
                    pass
    for dataset in session.scalars(select(Dataset)):
        cutoff = now - dataset.options["retention_days"] * 86400
        deleted = session.execute(
            delete(ExtractedRecord).where(ExtractedRecord.dataset_id == dataset.id, ExtractedRecord.last_seen < cutoff)
        )
        if deleted.rowcount:
            from sqlalchemy import update

            session.execute(update(Dataset).where(Dataset.id == dataset.id).values(version=Dataset.version + 1))
        session.execute(delete(DataChange).where(DataChange.dataset_id == dataset.id, DataChange.created_at < cutoff))
    session.execute(delete(ExtractionIssue).where(ExtractionIssue.created_at < now - settings().retention_days * 86400))
