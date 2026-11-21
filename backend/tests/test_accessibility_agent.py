import pytest

from app.jobs import claim
from app.worker import execute
from test_agent import agent_config, agent_servers, new_task, set_url  # noqa: F401


@pytest.mark.browser
async def test_planner_semantic_tools_transport_and_durable_traces(client, target, agent_config, agent_servers):  # noqa: F811
    set_url(client, target, "/agent/accessibility")
    task = new_task(
        client,
        target,
        objective="Search Backend Engineer jobs, enable remote only, then sort newest and cite the confirmation.",
        allow_form_input=True,
    )
    await execute(*claim())
    result = client.get("/api/agent/tasks/" + task["id"]).json()
    assert result["status"] == "completed", (result.get("error_message") or "")+"\n"+"\n".join(f["error"] for f in result.get("memory",{}).get("failures",[]))
    steps = client.get(f"/api/agent/tasks/{task['id']}/steps").json()["items"]
    assert {"TYPE", "SET_CHECKED", "SELECT_OPTION", "EXTRACT", "COMPLETE"} <= {s["decision"]["decision"] for s in steps}
    for step in steps[:3]:
        assert step["outcome"]["semantic"]["strategy"]
        assert step["outcome"]["interaction"]["verified"]
        assert "focus_after" in step["outcome"]["interaction"]
    assert result["planning"]["initialized"]
    assert "sensitive-test-key-92384" not in str(steps) + str(result)
