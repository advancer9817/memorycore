from __future__ import annotations

import json

import local_memory_mcp as lm
from local_memory_mcp.storage import send_agent_message, update_agent_presence


def _dashboard_payload(text: str) -> dict:
    marker = '<script id="memory-data" type="application/json">'
    start = text.index(marker) + len(marker)
    end = text.index("</script>", start)
    return json.loads(text[start:end])


def test_dashboard_payload_includes_ops_data(tmp_path):
    out = tmp_path / "dashboard.html"
    first = lm.add_memory_record("project_memory", "First", "First content")
    second = lm.add_memory_record("project_memory", "Second", "Second content")
    lm.add_link(first["id"], second["id"], relation_type="related_to")
    send_agent_message("alice", "bob", "hello")
    update_agent_presence("bob", status="online")

    lm.export_html(out)
    text = out.read_text(encoding="utf-8")
    payload = _dashboard_payload(text)

    assert payload["links"][0]["source_id"] == first["id"]
    assert payload["mailbox"][0]["to_agent"] == "bob"
    assert payload["presence"][0]["agent_id"] == "bob"
    assert "action_plan" in payload["report"]
    assert "context_quality" in payload


def test_dashboard_contains_ops_views(tmp_path):
    out = tmp_path / "dashboard.html"
    lm.export_html(out)
    text = out.read_text(encoding="utf-8")

    assert "Graph" in text
    assert "Mailbox" in text
    assert "Presence" in text
    assert "Action plan" in text
    assert "Feedback drilldown" in text
