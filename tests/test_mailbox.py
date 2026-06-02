"""Tests for Agent Mailbox MVP: agent_messages + agent_presence tables and MCP tools."""
from __future__ import annotations

import time

import memorycore as lm
from memorycore.storage import (
    get_agent_inbox,
    get_audit_log,
    list_agent_presence,
    managed_conn,
    send_agent_message,
    update_agent_presence,
)


# ---------------------------------------------------------------------------
# agent_messages
# ---------------------------------------------------------------------------


class TestSendAgentMessage:
    def test_send_returns_record_with_id(self):
        msg = send_agent_message("alice", "bob", "hello", body="world")
        assert msg["id"]
        assert msg["from_agent"] == "alice"
        assert msg["to_agent"] == "bob"
        assert msg["subject"] == "hello"
        assert msg["body"] == "world"
        assert msg["status"] == "unread"
        assert msg["priority"] == "normal"

    def test_send_custom_priority(self):
        msg = send_agent_message("a", "b", "urgent", priority="high")
        assert msg["priority"] == "high"

    def test_send_invalid_priority_rejected(self):
        msg = send_agent_message("a", "b", "x", priority="bogus")
        assert "error" in msg

    def test_send_writes_audit_event(self):
        msg = send_agent_message("alice", "bob", "audit-test")
        events = get_audit_log(event_type="agent_message_send", limit=5)
        assert any(e["detail_json"] and msg["id"] in e["detail_json"] for e in events)

    def test_broadcast_sends_to_all_online_or_idle_agents(self):
        update_agent_presence("sender", status="online")
        update_agent_presence("same-namespace", status="online", metadata={"namespace": "team-a"})
        update_agent_presence("other-namespace", status="idle", metadata={"namespace": "team-b"})
        update_agent_presence("offline-agent", status="offline")

        result = send_agent_message("sender", "*", "broadcast")

        assert result["broadcast"] is True
        assert result["sent_to"] == ["same-namespace", "other-namespace"]
        assert len(get_agent_inbox("same-namespace")) == 1
        assert len(get_agent_inbox("other-namespace")) == 1
        assert get_agent_inbox("offline-agent") == []


class TestAgentInbox:
    def test_inbox_returns_messages_for_recipient(self):
        send_agent_message("alice", "bob", "m1")
        send_agent_message("carol", "bob", "m2")
        send_agent_message("alice", "carol", "m3")
        inbox = get_agent_inbox("bob")
        subjects = [m["subject"] for m in inbox]
        assert "m1" in subjects
        assert "m2" in subjects
        assert "m3" not in subjects

    def test_inbox_filter_by_status(self):
        msg = send_agent_message("a", "b", "s1")
        with managed_conn() as conn:
            conn.execute(
                "UPDATE agent_messages SET status='read', read_at=datetime('now') WHERE id=?",
                (msg["id"],),
            )
        unread = get_agent_inbox("b", status="unread")
        assert all(m["id"] != msg["id"] for m in unread)
        read = get_agent_inbox("b", status="read")
        assert any(m["id"] == msg["id"] for m in read)

    def test_inbox_ordered_newest_first(self):
        send_agent_message("a", "b", "first")
        time.sleep(0.02)
        send_agent_message("a", "b", "second")
        inbox = get_agent_inbox("b")
        assert inbox[0]["subject"] == "second"
        assert inbox[1]["subject"] == "first"

    def test_inbox_limit(self):
        for i in range(5):
            send_agent_message("a", "b", f"msg-{i}")
        inbox = get_agent_inbox("b", limit=3)
        assert len(inbox) == 3

    def test_inbox_marks_read_on_fetch(self):
        send_agent_message("a", "b", "auto-read")
        inbox = get_agent_inbox("b", mark_read=True)
        assert len(inbox) == 1
        assert inbox[0]["status"] == "unread"  # original status at fetch time
        inbox2 = get_agent_inbox("b", status="unread")
        assert len(inbox2) == 0


# ---------------------------------------------------------------------------
# agent_presence
# ---------------------------------------------------------------------------


class TestUpdateAgentPresence:
    def test_upsert_creates_new_entry(self):
        result = update_agent_presence("claude", status="online")
        assert result["agent_id"] == "claude"
        assert result["status"] == "online"
        assert result["last_seen_at"]

    def test_upsert_updates_existing(self):
        update_agent_presence("hermes", status="online")
        result = update_agent_presence("hermes", status="idle")
        assert result["status"] == "idle"

    def test_invalid_status_rejected(self):
        result = update_agent_presence("x", status="bogus")
        assert "error" in result

    def test_metadata_stored(self):
        result = update_agent_presence("codex", status="online", metadata={"task": "review"})
        assert result["metadata"]["task"] == "review"

    def test_presence_does_not_invent_permission_namespace(self):
        result = update_agent_presence("plain-agent", status="online")
        assert "namespace" not in result["metadata"]

    def test_presence_writes_audit_event(self):
        update_agent_presence("audit-agent", status="online")
        events = get_audit_log(event_type="agent_presence_update", limit=5)
        assert any("audit-agent" in (e.get("detail_json") or "") for e in events)


class TestListAgentPresence:
    def test_list_returns_all(self):
        update_agent_presence("a1", status="online")
        update_agent_presence("a2", status="offline")
        entries = list_agent_presence()
        ids = [e["agent_id"] for e in entries]
        assert "a1" in ids
        assert "a2" in ids

    def test_list_filter_by_status(self):
        update_agent_presence("on1", status="online")
        update_agent_presence("off1", status="offline")
        online = list_agent_presence(status="online")
        assert all(e["status"] == "online" for e in online)

    def test_list_ordered_by_last_seen(self):
        update_agent_presence("old", status="online")
        time.sleep(0.05)
        update_agent_presence("new", status="online")
        entries = list_agent_presence()
        ids = [e["agent_id"] for e in entries]
        assert ids.index("new") < ids.index("old")


# ---------------------------------------------------------------------------
# Schema existence
# ---------------------------------------------------------------------------


class TestMailboxSchema:
    def test_agent_messages_table_exists(self):
        with managed_conn() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "agent_messages" in tables

    def test_agent_presence_table_exists(self):
        with managed_conn() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "agent_presence" in tables
