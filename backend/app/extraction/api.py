import time
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from ..api_support import Owner, Offset, Limit, collection, owned, output
from ..config import settings
from ..db import (
    Dataset,
    ExtractionSchema,
    ExtractionRun,
    ExtractedRecord,
    RecordRevision,
    ExtractionIssue,
    DataChange,
    DatasetExport,
    Job,
    Website,
    Session,
    transaction,
)
from ..jobs import make_job
from ..schemas import ScheduleInput
from .schemas import SchemaInput, DatasetInput, DatasetPatch, ExportInput
from .templates import templates

router = APIRouter(prefix="/api/extraction", tags=["data extraction"])


@router.get("/templates")
def get_templates(owner: Owner):
    return {"items": templates()}


@router.post("/schemas/validate")
def validate_schema(data: SchemaInput, owner: Owner):
    return {"valid": True, "definition": data.definition.model_dump()}


@router.get("/schemas")
def schemas(owner: Owner, offset: Offset = 0, limit: Limit = 100):
    with Session() as session:
        return collection(
            session,
            select(ExtractionSchema)
            .where(ExtractionSchema.owner == owner)
            .order_by(ExtractionSchema.created_at.desc()),
            offset,
            limit,
        )


def create_schema(session, data, owner, family=None, version=1):
    if (
        session.scalar(select(func.count()).select_from(ExtractionSchema).where(ExtractionSchema.owner == owner))
        >= 1000
    ):
        raise HTTPException(409, "Schema version capacity reached")
    definition = data.definition.model_copy(update={"version": version})
    row = ExtractionSchema(
        owner=owner, name=definition.name, version=version, definition=definition.model_dump(), active=data.active
    )
    if family:
        row.family = family
    session.add(row)
    session.flush()
    return output(row)


@router.post("/schemas", status_code=201)
def add_schema(data: SchemaInput, owner: Owner):
    with transaction() as session:
        return create_schema(session, data, owner)


@router.post("/schemas/{identifier}/versions", status_code=201)
def version_schema(identifier: str, data: SchemaInput, owner: Owner):
    try:
        with transaction() as session:
            old = owned(session, ExtractionSchema, identifier, owner)
            version = (
                session.scalar(
                    select(func.max(ExtractionSchema.version)).where(
                        ExtractionSchema.family == old.family, ExtractionSchema.owner == owner
                    )
                )
                + 1
            )
            return create_schema(session, data, owner, old.family, version)
    except IntegrityError:
        raise HTTPException(409, "Concurrent schema version update; reload") from None


@router.post("/schemas/{identifier}/active")
def activate_schema(identifier: str, owner: Owner, active: bool = True):
    with transaction() as session:
        row = owned(session, ExtractionSchema, identifier, owner)
        row.active = active
        return output(row)


@router.get("/datasets")
def datasets(owner: Owner, offset: Offset = 0, limit: Limit = 100):
    with Session() as session:
        return collection(
            session, select(Dataset).where(Dataset.owner == owner).order_by(Dataset.created_at.desc()), offset, limit
        )


def dataset_values(session, data, owner):
    owned(session, Website, data.website_id, owner)
    schema = owned(session, ExtractionSchema, data.schema_id, owner)
    if not schema.active:
        raise HTTPException(409, "Schema is inactive")
    if set(data.options.fuzzy_fields) - schema.definition["fields"].keys():
        raise HTTPException(422, "Unknown fuzzy fields")
    return schema


@router.post("/datasets", status_code=201)
def add_dataset(data: DatasetInput, owner: Owner):
    with transaction() as session:
        dataset_values(session, data, owner)
        if session.scalar(select(func.count()).select_from(Dataset).where(Dataset.owner == owner)) >= 100:
            raise HTTPException(409, "Dataset capacity reached")
        row = Dataset(
            owner=owner,
            name=data.name,
            website_id=data.website_id,
            schema_id=data.schema_id,
            options=data.options.model_dump(),
        )
        session.add(row)
        session.flush()
        return output(row)


@router.patch("/datasets/{identifier}")
def edit_dataset(identifier: str, data: DatasetPatch, owner: Owner):
    with transaction() as session:
        row = owned(session, Dataset, identifier, owner)
        dataset_values(session, data, owner)
        previous_schema = session.get(ExtractionSchema, row.schema_id)
        if row.website_id != data.website_id:
            raise HTTPException(409, "Create another dataset to change its source website")
        changed = session.execute(
            update(Dataset)
            .where(Dataset.id == identifier, Dataset.version == data.expected_version)
            .values(
                name=data.name,
                schema_id=data.schema_id,
                options=data.options.model_dump(),
                version=data.expected_version + 1,
            )
        ).rowcount
        if not changed:
            raise HTTPException(409, "Dataset changed while editing; reload before saving")
        next_schema = session.get(ExtractionSchema, data.schema_id)

        def contract(definition):
            # Selectors may evolve without relabeling the types and identities
            # of persisted records. Structural changes require a new dataset.
            return (
                definition.get("identity_fields", []),
                {
                    name: {k: v for k, v in rule.items() if k not in {"selector", "attribute", "path", "method"}}
                    for name, rule in definition["fields"].items()
                },
            )

        if contract(previous_schema.definition) != contract(next_schema.definition):
            populated = session.scalar(
                select(ExtractedRecord.id).where(ExtractedRecord.dataset_id == identifier).limit(1)
            )
            pending = session.scalar(
                select(ExtractionRun.job_id)
                .join(Job, Job.id == ExtractionRun.job_id)
                .where(ExtractionRun.dataset_id == identifier, Job.status.not_in(["completed", "failed", "cancelled"]))
                .limit(1)
            )
            if populated or pending:
                raise HTTPException(409, "Create a new dataset for incompatible schema types or record identities")
        session.refresh(row)
        return output(row)


@router.post("/datasets/{identifier}/bind")
def bind_dataset(identifier: str, owner: Owner):
    from .service import bind

    with transaction() as session:
        row = owned(session, Dataset, identifier, owner)
        bind(session, row)
        return {"dataset_id": row.id, "website_id": row.website_id}


@router.post("/datasets/{identifier}/run", status_code=201)
def run_dataset(identifier: str, owner: Owner, idempotency_key: Annotated[str | None, Header(max_length=160)] = None):
    try:
        with transaction() as session:
            row = owned(session, Dataset, identifier, owner)
            site = owned(session, Website, row.website_id, owner)
            job = make_job(session, site, key=idempotency_key, dataset_id=row.id)
            return output(job)
    except (ValueError, IntegrityError):
        raise HTTPException(409, "Queue conflict, inactive schema or idempotency key mismatch") from None


@router.get("/datasets/{identifier}/records")
def records(
    identifier: str, owner: Owner, offset: Offset = 0, limit: Limit = 100, q: str = "", status: str | None = None
):
    with Session() as session:
        owned(session, Dataset, identifier, owner)
        query = (
            select(ExtractedRecord)
            .where(ExtractedRecord.dataset_id == identifier)
            .order_by(ExtractedRecord.first_seen.desc(), ExtractedRecord.id)
        )
        if q:
            # Search serialized data with bound parameters, never SQL fragments.
            from sqlalchemy import String, cast

            query = query.where(cast(ExtractedRecord.data, String).contains(q[:200], autoescape=True))
        if status:
            query = query.where(ExtractedRecord.status == status)
        return collection(session, query, offset, limit)


@router.post("/datasets/{identifier}/schedules", status_code=201)
def schedule_dataset(identifier: str, data: ScheduleInput, owner: Owner):
    from ..db import Schedule, ExtractionSchedule
    from ..main import schedule_values
    from ..api_support import workflow_for

    with transaction() as session:
        dataset = owned(session, Dataset, identifier, owner)
        if dataset.website_id != data.website_id:
            raise HTTPException(422, "Schedule must use the dataset website")
        workflow_for(session, data.workflow_id, data.website_id, owner)
        row = Schedule(**schedule_values(data))
        session.add(row)
        session.flush()
        session.add(ExtractionSchedule(schedule_id=row.id, dataset_id=dataset.id))
        return output(row)


@router.get("/datasets/{identifier}/records/{record_id}/revisions")
def revisions(identifier: str, record_id: str, owner: Owner, offset: Offset = 0, limit: Limit = 100):
    with Session() as session:
        owned(session, Dataset, identifier, owner)
        row = session.get(ExtractedRecord, record_id)
        if not row or row.dataset_id != identifier:
            raise HTTPException(404, "Record not found")
        return collection(
            session,
            select(RecordRevision).where(RecordRevision.record_id == record_id).order_by(RecordRevision.number.desc()),
            offset,
            limit,
        )


@router.get("/datasets/{identifier}/changes")
def changes(identifier: str, owner: Owner, offset: Offset = 0, limit: Limit = 100):
    with Session() as session:
        owned(session, Dataset, identifier, owner)
        return collection(
            session,
            select(DataChange).where(DataChange.dataset_id == identifier).order_by(DataChange.id.desc()),
            offset,
            limit,
        )


@router.get("/datasets/{identifier}/runs")
def runs(identifier: str, owner: Owner, offset: Offset = 0, limit: Limit = 100):
    with Session() as session:
        owned(session, Dataset, identifier, owner)
        values = collection(
            session,
            select(ExtractionRun)
            .where(ExtractionRun.dataset_id == identifier)
            .order_by(ExtractionRun.created_at.desc()),
            offset,
            limit,
        )
        for row in values["items"]:
            job = session.get(Job, row["job_id"])
            row["job_status"] = job.status
            row["status"] = (
                "partial"
                if job.status == "completed" and (row["invalid_count"] or row["truncated"] or not row["pages"])
                else job.status
            )
            row["retry_count"], row["error_message"] = job.retry_count, job.error_message
        return values


@router.get("/runs/{job_id}/issues")
def issues(job_id: str, owner: Owner, offset: Offset = 0, limit: Limit = 100):
    with Session() as session:
        owned(session, Job, job_id, owner)
        return collection(
            session,
            select(ExtractionIssue).where(ExtractionIssue.job_id == job_id).order_by(ExtractionIssue.id.desc()),
            offset,
            limit,
        )


@router.post("/datasets/{identifier}/exports", status_code=201)
def start_export(identifier: str, data: ExportInput, owner: Owner):
    with transaction() as session:
        row = owned(session, Dataset, identifier, owner)
        row = session.scalar(
            select(Dataset).where(Dataset.id == identifier).with_for_update().execution_options(populate_existing=True)
        )
        schema = session.get(ExtractionSchema, row.schema_id)
        for column in data.columns:
            if column.split(".")[0] not in schema.definition["fields"] or len(column) > 200:
                raise HTTPException(422, "Unknown export column")
        if data.query is not None:
            from .query import validate_query
            try:
                validate_query(data.query, schema.definition)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
        site = owned(session, Website, row.website_id, owner)
        job = make_job(session, site, extract=False)
        # Export uses the existing job queue and worker, without crawling again.
        job.snapshot = {**job.snapshot, "export_schema": schema.definition}
        job.job_type = "export"
        artifact = DatasetExport(
            job_id=job.id,
            dataset_id=row.id,
            format=data.format,
            options=data.model_dump(),
            expires_at=time.time() + settings().extraction_export_ttl_seconds,
        )
        session.add(artifact)
        session.flush()
        return output(artifact)


@router.get("/datasets/{identifier}/exports")
def exports(identifier: str, owner: Owner, offset: Offset = 0, limit: Limit = 100):
    with Session() as session:
        owned(session, Dataset, identifier, owner)
        values = collection(
            session,
            select(DatasetExport)
            .where(DatasetExport.dataset_id == identifier)
            .order_by(DatasetExport.expires_at.desc()),
            offset,
            limit,
        )
        for item in values["items"]:
            item["status"] = session.get(Job, item["job_id"]).status
        return values


@router.get("/exports/{job_id}/download")
def download(job_id: str, owner: Owner):
    with Session() as session:
        job = owned(session, Job, job_id, owner)
        row = session.get(DatasetExport, job_id)
        if not row or job.status != "completed" or not row.filename or row.expires_at < time.time():
            raise HTTPException(409, "Export is not ready or has expired")
        owned(session, Dataset, row.dataset_id, owner)
        path = settings().artifact_dir / "exports" / row.filename
        if not path.resolve().is_relative_to((settings().artifact_dir / "exports").resolve()) or not path.is_file():
            raise HTTPException(404, "Export artifact unavailable")
        return FileResponse(
            path,
            filename="dataset-" + row.dataset_id + "." + row.format,
            media_type="application/json" if row.format == "json" else "text/csv; charset=utf-8",
        )


@router.delete("/datasets/{identifier}", status_code=204)
def delete_dataset(identifier: str, owner: Owner):
    with transaction() as session:
        row = owned(session, Dataset, identifier, owner)
        row = session.scalar(
            select(Dataset).where(Dataset.id == identifier).with_for_update().execution_options(populate_existing=True)
        )
        active = session.scalar(
            select(Job.id)
            .join(ExtractionRun, ExtractionRun.job_id == Job.id)
            .where(ExtractionRun.dataset_id == identifier, Job.status.not_in(["completed", "failed", "cancelled"]))
            .limit(1)
        )
        if active:
            raise HTTPException(409, "Cancel or finish dataset jobs before deleting")
        exporting = session.scalar(
            select(Job.id)
            .join(DatasetExport, DatasetExport.job_id == Job.id)
            .where(DatasetExport.dataset_id == identifier, Job.status.not_in(["completed", "failed", "cancelled"]))
            .limit(1)
        )
        if exporting:
            raise HTTPException(409, "Cancel or finish dataset exports before deleting")
        from ..db import ExtractionSchedule, Schedule

        for binding in session.scalars(select(ExtractionSchedule).where(ExtractionSchedule.dataset_id == identifier)):
            session.delete(session.get(Schedule, binding.schedule_id))
        site = session.get(Website, row.website_id)
        if site.configuration.get("extraction_dataset_id") == identifier:
            site.configuration = {**site.configuration, "extraction_dataset_id": None}
        for artifact in session.scalars(select(DatasetExport).where(DatasetExport.dataset_id == identifier)):
            if artifact.filename:
                (settings().artifact_dir / "exports" / artifact.filename).unlink(missing_ok=True)
        session.delete(row)
