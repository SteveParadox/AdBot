import time
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

from sqlalchemy import delete, func, select, update, or_

from ..db import (
    Dataset,
    ExtractionRun,
    ExtractedRecord,
    ExtractionObservation,
    ExtractionIssue,
    RecordRevision,
    DataChange,
    Frontier,
    emit,
    transaction,
)
from ..jobs import owned_job
from .engine import digest


def issue(job_id, token, source_url, kind, details):
    with transaction() as session:
        owned_job(session, job_id, token)
        run = session.get(ExtractionRun, job_id)
        # Bound diagnostic growth independently of hostile page repetition.
        if (
            session.scalar(select(func.count()).select_from(ExtractionIssue).where(ExtractionIssue.job_id == job_id))
            < 1000
        ):
            session.add(ExtractionIssue(job_id=job_id, source_url=source_url, kind=kind, details=details))
        run.invalid_count += 1


def save_page(job_id, token, source_url, records, truncated=False, *, empty_confirmed=False):
    with transaction() as session:
        job = owned_job(session, job_id, token)
        snap = job.snapshot["extraction"]
        dataset_id = snap["dataset_id"]
        # First write serializes same-dataset pages on SQLite as well as PostgreSQL.
        session.execute(update(Dataset).where(Dataset.id == dataset_id).values(updated_at=time.time()))
        dataset = session.get(Dataset, dataset_id)
        if not dataset or dataset.owner != job.owner:
            raise ValueError("Dataset is unavailable")
        run = session.get(ExtractionRun, job_id)
        fingerprint = digest(
            [source_url, [(r["identity"], r["content_hash"], r["errors"]) for r in records], empty_confirmed]
        )
        observed = session.scalar(
            select(ExtractionObservation.id).where(
                ExtractionObservation.job_id == job_id, ExtractionObservation.fingerprint == fingerprint
            )
        )
        run.truncated = run.truncated or truncated
        if observed:
            # A previously observed page can reappear after another page/job
            # changed the same identities. Dedupe against current state too.
            current = dict(
                session.execute(
                    select(ExtractedRecord.identity, ExtractedRecord.content_hash).where(
                        ExtractedRecord.dataset_id == dataset_id,
                        ExtractedRecord.identity.in_([r["identity"] for r in records]),
                        ExtractedRecord.status == "active",
                        ExtractedRecord.last_job_id == job_id,
                    )
                ).all()
            )
            if all(
                r["errors"]
                or current.get(r["identity"]) == r["content_hash"]
                or snap["options"]["duplicate_policy"] in {"skip", "review"}
                and r["identity"] in current
                for r in records
            ):
                return
        else:
            session.add(ExtractionObservation(job_id=job_id, fingerprint=fingerprint))
            run.pages += 1
        if not records and not empty_confirmed:
            run.invalid_count += 1
            session.add(
                ExtractionIssue(
                    job_id=job_id,
                    source_url=source_url,
                    kind="empty_capture",
                    details={
                        "error": "No records observed; verify selectors and page readiness before confirming absence"
                    },
                )
            )
        options = snap["options"]
        count = session.scalar(
            select(func.count()).select_from(ExtractedRecord).where(ExtractedRecord.dataset_id == dataset_id)
        )
        scope = dict(job.execution_state.get("agent_record_scope", {}))

        def remember(row):
            if job.job_type == "agent":
                if row.id not in scope and len(scope) >= 10000:
                    run.truncated = True
                    return
                scope[row.id] = row.content_hash

        for result in records:
            result["provenance"] = {**result["provenance"], "schema_id": snap["schema_id"]}
            if result["errors"]:
                run.invalid_count += 1
                if run.invalid_count <= 1000:
                    session.add(
                        ExtractionIssue(
                            job_id=job_id,
                            source_url=source_url,
                            kind="validation",
                            details={"errors": result["errors"]},
                        )
                    )
                continue
            row = session.scalar(
                select(ExtractedRecord).where(
                    ExtractedRecord.dataset_id == dataset_id, ExtractedRecord.identity == result["identity"]
                )
            )
            if row is None and count >= options["max_records"]:
                run.truncated = True
                continue
            now = time.time()
            if row is None:
                row = ExtractedRecord(
                    dataset_id=dataset_id,
                    identity=result["identity"],
                    content_hash=result["content_hash"],
                    data=result["data"],
                    original=result["original"],
                    provenance=result["provenance"],
                    validation_status=result["validation_status"],
                    last_job_id=job_id,
                )
                session.add(row)
                session.flush()
                kind, details = "new", {"schema_version": result["provenance"]["schema_version"]}
                fuzzy = options.get("fuzzy_fields", [])
                if fuzzy:
                    # Flag only. Never merge similar titles or discard distinct entities.
                    signature = " | ".join(str(result["data"].get(k, ""))[:100] for k in fuzzy).casefold()[:500]
                    for candidate in session.scalars(
                        select(ExtractedRecord)
                        .where(ExtractedRecord.dataset_id == dataset_id, ExtractedRecord.id != row.id)
                        .limit(20)
                    ):
                        other = " | ".join(str(candidate.data.get(k, ""))[:100] for k in fuzzy).casefold()[:500]
                        if (
                            signature
                            and other
                            and SequenceMatcher(
                                None, signature.split()[:40], other.split()[:40], autojunk=False
                            ).ratio()
                            >= options["fuzzy_threshold"]
                        ):
                            session.add(
                                DataChange(
                                    dataset_id=dataset_id,
                                    record_id=row.id,
                                    kind="possible_duplicate",
                                    details={"candidate_id": candidate.id},
                                )
                            )
                            break
                count += 1
            else:
                row.last_seen, row.last_job_id, row.missing_count = now, job_id, 0
                # last_seen is exported, so even unchanged content invalidates
                # an in-flight snapshot. This is not a business change event.
                dataset.version += 1
                if row.status != "active":
                    row.status = "active"
                    dataset.version += 1
                    session.add(DataChange(dataset_id=dataset_id, record_id=row.id, kind="rediscovered", details={}))
                if row.content_hash == result["content_hash"] or options["duplicate_policy"] == "skip":
                    if row.content_hash == result["content_hash"]:
                        remember(row)
                    run.valid_count += 1
                    continue
                if options["duplicate_policy"] == "review":
                    session.add(
                        DataChange(
                            dataset_id=dataset_id,
                            record_id=row.id,
                            kind="review_required",
                            details={"candidate": result["data"]},
                        )
                    )
                    run.valid_count += 1
                    continue
                changed = [k for k, v in result["data"].items() if row.data.get(k) != v]
                kind, details = (
                    "updated",
                    {
                        "fields": changed,
                        "before": {k: row.data.get(k) for k in changed},
                        "after": {k: result["data"][k] for k in changed},
                        "previous_hash": row.content_hash,
                        "current_hash": result["content_hash"],
                        "summary": "Changed fields: " + ", ".join(changed),
                    },
                )
                if "price" in changed:
                    try:
                        kind = (
                            "price_increase"
                            if Decimal(result["data"]["price"]) > Decimal(row.data["price"])
                            else "price_decrease"
                        )
                    except (InvalidOperation, ValueError, TypeError):
                        pass
                row.revision += 1
                row.data, row.original, row.content_hash = result["data"], result["original"], result["content_hash"]
                row.provenance, row.validation_status = result["provenance"], result["validation_status"]
            remember(row)
            session.add(DataChange(dataset_id=dataset_id, record_id=row.id, kind=kind, details=details))
            session.add(RecordRevision(record_id=row.id, number=row.revision, data=row.data, provenance=row.provenance))
            session.execute(
                delete(RecordRevision).where(
                    RecordRevision.record_id == row.id, RecordRevision.number <= row.revision - options["max_revisions"]
                )
            )
            run.valid_count += 1
            dataset.version += 1
        if job.job_type == "agent":
            job.execution_state = {**job.execution_state, "agent_record_scope": scope}
        emit(
            session,
            job_id,
            "records_extracted",
            "Structured page processed",
            valid=run.valid_count,
            invalid=run.invalid_count,
        )
        # Bound change history independently of update frequency; revisions have
        # their own per-record ceiling. Keep the newest events for this dataset.
        keep = (
            select(DataChange.id)
            .where(DataChange.dataset_id == dataset_id)
            .order_by(DataChange.id.desc())
            .limit(options["max_records"] * options["max_revisions"])
        )
        session.execute(delete(DataChange).where(DataChange.dataset_id == dataset_id, DataChange.id.not_in(keep)))


def finish(session, job):
    run = session.get(ExtractionRun, job.id)
    if run is None or run.finalized:
        return
    run.status = (
        "partial" if job.status == "completed" and (run.invalid_count or run.truncated or not run.pages) else job.status
    )
    if job.status not in {"completed", "failed", "cancelled"}:
        return
    run.finalized = True
    snap = job.snapshot["extraction"]
    options = snap["options"]
    # Removal is opt-in and only for exhaustive, successful crawls. Workflow/agent
    # observations, failed pages, page/depth limits and truncation never delete data.
    unresolved = session.scalar(
        select(func.count()).select_from(Frontier).where(Frontier.job_id == job.id, Frontier.crawl_status != "visited")
    )
    complete = (
        job.job_type == "crawl"
        and job.status == "completed"
        and run.pages > 0
        and not run.truncated
        and run.invalid_count == 0
        and not unresolved
        and job.pages_visited < job.snapshot["configuration"]["max_pages"]
    )
    if not options["confirm_missing"] or not complete:
        return
    session.execute(update(Dataset).where(Dataset.id == run.dataset_id).values(updated_at=time.time()))
    for row in session.scalars(
        select(ExtractedRecord).where(
            ExtractedRecord.dataset_id == run.dataset_id,
            or_(ExtractedRecord.last_job_id != job.id, ExtractedRecord.last_job_id.is_(None)),
            ExtractedRecord.status != "removed",
        )
    ):
        row.missing_count += 1
        session.execute(update(Dataset).where(Dataset.id == run.dataset_id).values(version=Dataset.version + 1))
        row.status = "removed" if row.missing_count >= options["missing_threshold"] else "missing"
        session.add(
            DataChange(
                dataset_id=run.dataset_id,
                record_id=row.id,
                kind=row.status,
                details={"confirmations": row.missing_count, "previous_hash": row.content_hash},
            )
        )
