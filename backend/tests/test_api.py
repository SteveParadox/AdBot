import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.db import Job, Session, transaction
from app.jobs import claim, recover_expired, tick
from conftest import OTHER_AUTH


def test_auth_required(client):
    assert client.get("/api/websites", headers={"Authorization": ""}).status_code == 401
    assert client.get("/api/health", headers={"Authorization": ""}).status_code == 200
    assert client.get("/api/ready").status_code == 200


def test_ownership(client, target):
    assert client.get("/api/websites/" + target["id"], headers=OTHER_AUTH).status_code == 404
    assert client.get("/api/websites", headers=OTHER_AUTH).json()["items"] == []
    job = client.post("/api/jobs", json={"website_id": target["id"]}).json()
    assert client.get(f"/api/jobs/{job['id']}/pages", headers=OTHER_AUTH).status_code == 404
    assert client.post(f"/api/jobs/{job['id']}/cancel", headers=OTHER_AUTH).status_code == 404


def test_idempotency_conflict_and_queue_cancellation(client, target):
    body = {"website_id": target["id"]}
    headers = {"Idempotency-Key": "stable-request"}
    one = client.post("/api/jobs", json=body, headers=headers)
    two = client.post("/api/jobs", json=body, headers=headers)
    assert one.status_code == two.status_code == 201
    assert one.json()["id"] == two.json()["id"]
    workflow = client.post(
        "/api/workflows",
        json={
            "name": "Read",
            "website_id": target["id"],
            "definition": {"steps": [{"action": "ASSERT_VISIBLE", "selector": "h1"}]},
        },
    ).json()
    assert client.post("/api/jobs", json=body | {"workflow_id": workflow["id"]}, headers=headers).status_code == 409
    job_id = one.json()["id"]
    assert client.post(f"/api/jobs/{job_id}/cancel").json()["status"] == "cancelled"
    assert claim() is None
    assert client.post(f"/api/jobs/{job_id}/retry").status_code == 201


def test_immutable_job_snapshot(client, target):
    job = client.post("/api/jobs", json={"website_id": target["id"]}).json()
    edited = {k: v for k, v in target.items() if k in {"name", "base_url", "allowed_domains", "configuration"}}
    edited["configuration"]["max_pages"] = 1
    edited["authorized"] = True
    assert client.patch("/api/websites/" + target["id"], json=edited).status_code == 200
    with Session() as session:
        assert session.get(Job, job["id"]).snapshot["configuration"]["max_pages"] == 10


def test_durable_schedule_idempotence(client, target):
    response = client.post(
        "/api/schedules", json={"website_id": target["id"], "cron_expression": "0 * * * *", "timezone": "Africa/Lagos"}
    )
    assert response.status_code == 201, response.text
    due = response.json()["next_run_at"]
    assert tick(due + 1) == 1
    assert tick(due + 1) == 0
    assert client.get("/api/jobs").json()["total"] == 1
    identifier = response.json()["id"]
    assert client.patch(f"/api/schedules/{identifier}", json={"enabled": False}).json()["enabled"] is False
    assert client.patch(f"/api/schedules/{identifier}", json={"timezone": "Not/A_Zone"}).status_code == 422


def test_expired_worker_recovery_and_fencing(client, target):
    job = client.post("/api/jobs", json={"website_id": target["id"]}).json()
    identifier, token = claim()
    assert identifier == job["id"]
    assert claim() is None
    with transaction() as session:
        item = session.get(Job, identifier)
        item.lease_until = time.time() - 1
    recover_expired()
    with Session() as session:
        item = session.get(Job, identifier)
        assert item.status == "queued" and item.retry_count == 1 and item.lease_token is None
    from app.jobs import heartbeat

    assert not heartbeat(identifier, token)


def test_simultaneous_claim_has_one_winner(client, target):
    client.post("/api/jobs", json={"website_id": target["id"]})
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    assert sum(item is not None for item in results) == 1


def test_global_and_per_domain_capacity(client, target):
    client.post("/api/jobs", json={"website_id": target["id"]})
    client.post("/api/jobs", json={"website_id": target["id"]})
    first = claim()
    assert first and claim() is None
    for address in ["8.8.8.8", "1.1.1.1"]:
        result = client.post(
            "/api/websites",
            json={
                "name": "Capacity fixture",
                "base_url": f"https://{address}/",
                "allowed_domains": [address],
                "authorized": True,
            },
        )
        assert result.status_code == 201
        client.post("/api/jobs", json={"website_id": result.json()["id"]})
    assert claim() is not None
    assert claim() is None


def test_active_target_delete_rejected(client, target):
    job = client.post("/api/jobs", json={"website_id": target["id"]}).json()
    assert client.delete("/api/websites/" + target["id"]).status_code == 409
    client.post(f"/api/jobs/{job['id']}/cancel")
    assert client.delete("/api/websites/" + target["id"]).status_code == 204


def test_workflow_schema_and_version(client, target):
    data = {
        "website_id": target["id"],
        "name": "Workflow",
        "definition": {"steps": [{"action": "CLICK", "selector": "a"}]},
    }
    assert client.post("/api/workflows", json=data).status_code == 422
    data["definition"]["steps"][0]["authorized"] = True
    result = client.post("/api/workflows", json=data)
    assert result.status_code == 201
    workflow = result.json()
    assert client.patch("/api/workflows/" + workflow["id"], json=data).json()["version"] == 2
    data["definition"]["steps"] = [{"action": "EVALUATE", "javascript": "alert(1)"}]
    assert client.post("/api/workflows", json=data).status_code == 422


def test_sse_replay_and_artifact_ownership(client, target):
    identifier = client.post("/api/jobs", json={"website_id": target["id"]}).json()["id"]
    client.post(f"/api/jobs/{identifier}/cancel")
    logs = client.get(f"/api/jobs/{identifier}/logs").json()["items"]
    response = client.get(f"/api/jobs/{identifier}/events", headers={"Last-Event-ID": str(logs[0]["id"])})
    assert response.status_code == 200
    assert f"id: {logs[0]['id']}\n" not in response.text
    assert "cancellation_requested" in response.text
    assert client.get(f"/api/artifacts/{identifier}-missing.png").status_code == 404
    assert client.get(f"/api/jobs/{identifier}/events", headers={"Last-Event-ID": "oops"}).status_code == 422


def test_analytics_actual_data(client, target):
    client.post("/api/jobs", json={"website_id": target["id"]})
    response = client.get("/api/analytics/overview").json()
    assert response["websites"] == 1 and response["jobs"] == 1 and response["pages"] == 0
    assert response["daily_pages"] == []
    assert client.get("/api/jobs?limit=201").status_code == 422


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://169.254.169.254/",
        "http://localhost/",
        "http://127.0.0.1:8000/",
        "https://example.com@127.0.0.1/",
    ],
)
def test_unsafe_targets(client, url):
    result = client.post(
        "/api/websites",
        json={
            "name": "Bad",
            "base_url": url,
            "allowed_domains": ["127.0.0.1", "localhost", "169.254.169.254"],
            "authorized": True,
        },
    )
    assert result.status_code == 422
