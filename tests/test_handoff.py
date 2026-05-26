from __future__ import annotations

from local_memory_mcp.storage import (
    agent_capability_register,
    agent_capability_search,
    agent_handoff_create,
    agent_handoff_update,
    get_agent_inbox,
)


def test_agent_handoff_create_sets_schema_and_correlation_id():
    handoff = agent_handoff_create(
        from_agent="planner",
        to_agent="coder",
        task="Implement feature",
        payload={"files": ["a.py"]},
    )

    assert handoff["workflow"] == "handoff"
    assert handoff["handoff_status"] == "requested"
    assert handoff["correlation_id"]
    inbox = get_agent_inbox("coder")
    assert inbox[0]["metadata"]["workflow"] == "handoff"
    assert inbox[0]["metadata"]["correlation_id"] == handoff["correlation_id"]


def test_agent_handoff_update_creates_response_message():
    handoff = agent_handoff_create("planner", "coder", "Do work")

    result = agent_handoff_update(
        handoff["id"],
        from_agent="coder",
        status="done",
        result={"summary": "completed"},
    )

    assert result["handoff_status"] == "done"
    assert result["correlation_id"] == handoff["correlation_id"]
    planner_inbox = get_agent_inbox("planner")
    assert planner_inbox[0]["metadata"]["response_to"] == handoff["id"]
    assert planner_inbox[0]["metadata"]["handoff_status"] == "done"


def test_agent_handoff_update_rejects_invalid_status():
    handoff = agent_handoff_create("planner", "coder", "Do work")

    result = agent_handoff_update(handoff["id"], from_agent="coder", status="bogus")

    assert "error" in result


def test_agent_capability_registry_upserts_and_searches():
    first = agent_capability_register("coder", capabilities=["python", "tests"], namespace="team-a")
    second = agent_capability_register("reviewer", capabilities=["review"], namespace="team-a")

    assert first["agent_id"] == "coder"
    assert second["capabilities"] == ["review"]
    matches = agent_capability_search(capability="python", namespace="team-a")
    assert [match["agent_id"] for match in matches] == ["coder"]
