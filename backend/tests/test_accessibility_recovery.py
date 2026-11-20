import time

import pytest

from app.db import AgentStep, AgentTask, Job, Session, transaction
from app.jobs import claim, recover_expired
from test_agent import agent_config  # noqa: F401


@pytest.mark.parametrize("action", ["SET_CHECKED", "SELECT_OPTION"])
def test_expired_selection_dispatch_requires_inspection(client, target, agent_config, action):  # noqa: F811
    response = client.post(
        "/api/agent/tasks",
        json={
            "website_id": target["id"],
            "objective": "Inspect public form controls without inventing completion.",
            "allow_form_input": True,
        },
    )
    assert response.status_code == 201, response.text
    identifier, token = claim()
    with transaction() as session:
        job = session.get(Job, identifier)
        job.lease_until = time.time() - 1
        session.add(
            AgentStep(
                job_id=identifier,
                number=1,
                status="executing",
                decision={"decision": action, "target": {"element_id": "observed"}},
                observation={"url": target["base_url"]},
            )
        )
    recover_expired()
    with Session() as session:
        job = session.get(Job, identifier)
        assert job.status == "failed" and "manual review" in job.error_message.lower()
        assert (
            session.get(AgentTask, identifier).memory["planning"]["specification"]["objective"]
            == response.json()["objective"]
        )
