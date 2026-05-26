from __future__ import annotations

import json

from local_memory_mcp.storage import (
    add_memory_record,
    get_audit_log,
    get_agent_inbox,
    grant_agent_permission,
    list_agent_presence,
    send_agent_message,
    update_agent_presence,
)


def test_unconfigured_agent_permissions_are_backward_compatible():
    record = add_memory_record(
        memory_type="project_memory",
        title="Compat",
        content="Default agents can still write without explicit policy.",
        source_agent="legacy-agent",
    )

    assert record["source_agent"] == "legacy-agent"


def test_write_permission_denial_is_audited():
    grant_agent_permission(
        "readonly-agent",
        namespace="default",
        can_read=True,
        can_write=False,
        scopes=["global"],
        types=["project_memory"],
    )

    result = add_memory_record(
        memory_type="project_memory",
        title="Denied",
        content="This write should be rejected.",
        source_agent="readonly-agent",
    )

    assert result["error"] == "permission_denied"
    events = get_audit_log(event_type="permission_denied", limit=5)
    assert len(events) == 1
    detail = json.loads(events[0]["detail_json"])
    assert detail["operation"] == "memory.write"
    assert detail["agent_id"] == "readonly-agent"


def test_permission_filters_scope_type_and_tags():
    grant_agent_permission(
        "scoped-agent",
        namespace="default",
        can_write=True,
        scopes=["project-a"],
        types=["feedback"],
        tags=["allowed"],
    )

    allowed = add_memory_record(
        memory_type="feedback",
        title="Allowed",
        content="All filters match.",
        scope="project-a",
        tags=["allowed", "extra"],
        source_agent="scoped-agent",
    )
    denied = add_memory_record(
        memory_type="project_memory",
        title="Denied",
        content="Type does not match.",
        scope="project-a",
        tags=["allowed"],
        source_agent="scoped-agent",
    )

    assert allowed["id"]
    assert denied["error"] == "permission_denied"


def test_broadcast_denial_is_audited():
    grant_agent_permission("sender", namespace="team-a", can_broadcast=False)
    update_agent_presence("recipient", status="online", metadata={"namespace": "team-a"})

    result = send_agent_message("sender", "*", "hello")

    assert result["error"] == "permission_denied"
    events = get_audit_log(event_type="permission_denied", limit=5)
    assert any("agent.broadcast" in event["detail_json"] for event in events)


def test_broadcast_is_limited_to_sender_namespace():
    grant_agent_permission("sender", namespace="team-a", can_broadcast=True)
    update_agent_presence("same", status="online", metadata={"namespace": "team-a"})
    update_agent_presence("other", status="online", metadata={"namespace": "team-b"})

    result = send_agent_message("sender", "*", "namespace broadcast")

    assert result["sent_to"] == ["same"]
    assert len(get_agent_inbox("same")) == 1
    assert get_agent_inbox("other") == []


def test_presence_namespace_uses_permission_default_when_missing_metadata():
    grant_agent_permission("namespaced-agent", namespace="team-x")

    result = update_agent_presence("namespaced-agent", status="online")
    entries = list_agent_presence(status="online")

    assert result["metadata"]["namespace"] == "team-x"
    assert entries[0]["metadata"]["namespace"] == "team-x"
