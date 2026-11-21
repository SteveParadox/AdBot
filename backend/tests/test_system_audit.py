"""Behavioral regressions discovered during the comprehensive implementation audit."""

import time

import pytest
from sqlalchemy import select

from app.db import Dataset, ExtractedRecord, ExtractionRun, Job, transaction
from app.extraction.exporter import cleanup
from app.extraction.persistence import finish, save_page
from app.jobs import claim
from test_extraction import normalized, setup_dataset
from test_planning import decision, state
from app.agent.planning import guard
from test_extraction import definition


def extraction_job(client, target, options=None):
    _, dataset = setup_dataset(client, target, options)
    response = client.post(f"/api/extraction/datasets/{dataset['id']}/run", json={})
    assert response.status_code == 201, response.text
    identifier, token = claim()
    return dataset["id"], identifier, token


def test_reobserved_content_reversion_is_persisted(client, target):
    dataset, identifier, token = extraction_job(client, target)
    for price in ("$12.30", "$15.00", "$12.30"):
        save_page(identifier, token, "https://example.org/catalog", [normalized(price=price)])
    with transaction() as session:
        row = session.scalar(select(ExtractedRecord).where(ExtractedRecord.dataset_id == dataset))
        assert row.data["price"] == "12.30"
        assert row.revision == 3
    save_page(identifier, token, "https://example.org/catalog", [normalized()])
    with transaction() as session:
        assert session.scalar(select(ExtractedRecord)).revision == 3


def test_export_version_tracks_last_seen_and_retention(client, target):
    dataset, identifier, token = extraction_job(client, target)
    save_page(identifier, token, "https://example.org/catalog", [normalized()])
    with transaction() as session:
        previous = session.get(Dataset, dataset).version
        last_seen = session.scalar(select(ExtractedRecord)).last_seen
    # A different source observation updates last_seen without changing content.
    save_page(identifier, token, "https://example.org/catalog?page=2", [normalized()])
    with transaction() as session:
        assert session.scalar(select(ExtractedRecord)).last_seen >= last_seen
        assert session.get(Dataset, dataset).version > previous
        previous = session.get(Dataset, dataset).version
        session.scalar(select(ExtractedRecord)).last_seen = time.time() - 365 * 86400
    with transaction() as session:
        cleanup(session)
    with transaction() as session:
        assert session.scalar(select(ExtractedRecord)) is None
        assert session.get(Dataset, dataset).version > previous


def test_reobserved_review_candidate_is_not_duplicated(client, target):
    from app.db import DataChange

    dataset, identifier, token = extraction_job(client, target, {"duplicate_policy": "review"})
    for price in ("$12.30", "$15", "$15"):
        save_page(identifier, token, "https://example.org/catalog", [normalized(price=price)])
    with transaction() as session:
        candidates = session.scalars(
            select(DataChange).where(DataChange.dataset_id == dataset, DataChange.kind == "review_required")
        ).all()
        assert len(candidates) == 1
        assert session.scalar(select(ExtractedRecord)).data["price"] == "12.30"


def test_empty_capture_cannot_confirm_removal_or_success(client, target):
    _, identifier, token = extraction_job(client, target, {"confirm_missing": True})
    save_page(identifier, token, "https://example.org/catalog", [])
    with transaction() as session:
        job = session.get(Job, identifier)
        job.status = "completed"
        finish(session, job)
        run = session.get(ExtractionRun, identifier)
        assert run.status == "partial"
        assert run.invalid_count > 0


def test_no_capture_cannot_report_a_complete_extraction_run(client, target):
    dataset, identifier, _ = extraction_job(client, target)
    with transaction() as session:
        job = session.get(Job, identifier)
        job.status = "completed"
        finish(session, job)
        assert session.get(ExtractionRun, identifier).status == "partial"
    runs = client.get(f"/api/extraction/datasets/{dataset}/runs").json()["items"]
    assert runs[0]["status"] == "partial"


def test_incompatible_schema_cannot_relabel_existing_dataset(client, target):
    dataset_id, identifier, token = extraction_job(client, target)
    save_page(identifier, token, "https://example.org/catalog", [normalized()])
    incompatible = definition()
    incompatible["identity_fields"] = ["name"]
    schema = client.post("/api/extraction/schemas", json={"definition": incompatible}).json()
    dataset = next(d for d in client.get("/api/extraction/datasets").json()["items"] if d["id"] == dataset_id)
    body = {k: dataset[k] for k in ("name", "website_id", "schema_id", "options")}
    body.update(schema_id=schema["id"], expected_version=dataset["version"])
    response = client.patch("/api/extraction/datasets/" + dataset_id, json=body)
    assert response.status_code == 409, response.text
    saved = next(d for d in client.get("/api/extraction/datasets").json()["items"] if d["id"] == dataset_id)
    assert saved["schema_id"] == dataset["schema_id"]


@pytest.mark.parametrize("key", ["Enter", "Space"])
def test_critical_ambiguity_blocks_keyboard_activation(key):
    with pytest.raises(PermissionError, match="clarification"):
        guard(state("Export JSON and CSV."), decision("PRESS_KEY", key=key), {})


def test_explicit_download_prohibition_overrides_optional_permission():
    with pytest.raises(PermissionError, match="prohibition"):
        guard(
            state("Read the catalog. Don't download files.", allow_downloads=True),
            decision("DOWNLOAD", target={"element_id": "file"}),
            {},
        )


@pytest.mark.parametrize("prohibition", ["Don't", "Don’t", "Mustn't", "Mustn’t", "Do not", "Never"])
def test_explicit_negative_instructions_preserved_and_enforced(prohibition):
    saved = state(f"Read the catalog. {prohibition} submit applications.")
    assert saved["specification"]["constraints"]
    for action, values in [("CLICK", {}), ("PRESS_KEY", {"key": "Enter"})]:
        with pytest.raises(PermissionError, match="prohibition"):
            guard(saved, decision(action, target={"element_id": "submit"}, **values), {})
