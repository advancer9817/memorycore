"""Tests for Agent Mailbox Enhanced: TTL expiry + broadcast messages."""
from __future__ import annotations

import time

import pytest

import local_memory_mcp as lm
from local_memory_mcp.storage import (
    cleanup_expired_messages,
    get_agent_inbox,
    managed_conn,
    send_agent_message,
    update_agent_presence,
)


# ---------------------------------------------------------------------------
# TTL: expires_at column exists
# ---------------------------------------------------------------------------


class TestExpiresAtColumn:
    def test_agent_messages_has_expires_at_column(self):
        with managed_conn() as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(agent_messages)").fetchall()}
        assert "expires_at" in cols


# ---------------------------------------------------------------------------
# TTL: send with ttl_seconds
# ---------------------------------------------------------------------------


class TestSendWithTTL:
    def test_send_without_ttl_has_null_expires_at(self):
        msg = send_agent_message("alice", "bob", "no-ttl")
        assert msg.get("expires_at") is None

    def test_send_with_ttl_sets_expires_at(self):
        msg = send_agent_message("alice", "bob", "with-ttl", ttl_seconds=300)
        assert msg.get("expires_at") is not None

    def test_send_with_ttl_expires_at_is_future(self):
        from datetime import datetime, timezone
        msg = send_agent_message("alice", "bob", "future-ttl", ttl_seconds=300)
        expires = datetime.fromisoformat(msg["expires_at"])
        now = datetime.now(timezone.utc)
        assert expires > now

    def test_send_with_zero_ttl_expires_immediately(self):
        """ttl_seconds=0 means expires_at = now, so message is immediately expired."""
        msg = send_agent_message("alice", "bob", "zero-ttl", ttl_seconds=0)
        assert msg.get("expires_at") is not None

    def test_send_with_negative_ttl_expires_in_past(self):
        """ttl_seconds=-1 means expires_at is in the past — useful in tests."""
        from datetime import datetime, timezone
        msg = send_agent_message("alice", "bob", "neg-ttl", ttl_seconds=-1)
        expires = datetime.fromisoformat(msg["expires_at"])
        now = datetime.now(timezone.utc)
        assert expires <= now


# ---------------------------------------------------------------------------
# TTL: inbox filters out expired messages
# ---------------------------------------------------------------------------


class TestInboxFiltersExpired:
    def test_non_expired_message_appears_in_inbox(self):
        send_agent_message("a", "b", "live-msg", ttl_seconds=300)
        inbox = get_agent_inbox("b")
        assert any(m["subject"] == "live-msg" for m in inbox)

    def test_expired_message_not_in_inbox(self):
        # Send message that is already expired (negative TTL)
        send_agent_message("a", "b", "expired-msg", ttl_seconds=-1)
        inbox = get_agent_inbox("b")
        assert not any(m["subject"] == "expired-msg" for m in inbox)

    def test_no_ttl_message_always_appears(self):
        send_agent_message("a", "b", "eternal-msg")
        inbox = get_agent_inbox("b")
        assert any(m["subject"] == "eternal-msg" for m in inbox)

    def test_inbox_status_filter_combined_with_ttl(self):
        """Expired messages should not appear even when filtering by status."""
        send_agent_message("a", "b", "expired-unread", ttl_seconds=-1)
        unread = get_agent_inbox("b", status="unread")
        assert not any(m["subject"] == "expired-unread" for m in unread)


# ---------------------------------------------------------------------------
# cleanup_expired_messages
# ---------------------------------------------------------------------------


class TestCleanupExpiredMessages:
    def test_cleanup_returns_int(self):
        result = cleanup_expired_messages()
        assert isinstance(result, int)

    def test_cleanup_deletes_expired_messages(self):
        send_agent_message("a", "b", "to-clean-1", ttl_seconds=-1)
        send_agent_message("a", "b", "to-clean-2", ttl_seconds=-1)
        deleted = cleanup_expired_messages()
        assert deleted >= 2

    def test_cleanup_leaves_live_messages(self):
        send_agent_message("a", "b", "keep-me", ttl_seconds=300)
        cleanup_expired_messages()
        inbox = get_agent_inbox("b")
        assert any(m["subject"] == "keep-me" for m in inbox)

    def test_cleanup_leaves_no_ttl_messages(self):
        send_agent_message("a", "b", "no-ttl-keep")
        cleanup_expired_messages()
        inbox = get_agent_inbox("b")
        assert any(m["subject"] == "no-ttl-keep" for m in inbox)

    def test_cleanup_returns_zero_when_nothing_expired(self):
        send_agent_message("a", "b", "fresh", ttl_seconds=300)
        result = cleanup_expired_messages()
        assert result == 0

    def test_cleanup_removes_from_db(self):
        msg = send_agent_message("a", "b", "db-clean", ttl_seconds=-1)
        cleanup_expired_messages()
        with managed_conn() as conn:
            row = conn.execute(
                "SELECT id FROM agent_messages WHERE id=?", (msg["id"],)
            ).fetchone()
        assert row is None


# ---------------------------------------------------------------------------
# Broadcast: to_agent="*"
# ---------------------------------------------------------------------------


class TestBroadcastMessage:
    def _setup_agents(self):
        update_agent_presence("agent-alpha", status="online")
        update_agent_presence("agent-beta", status="idle")
        update_agent_presence("agent-gamma", status="offline")

    def test_broadcast_returns_broadcast_flag(self):
        self._setup_agents()
        result = send_agent_message("sender", "*", "Hello all")
        assert result.get("broadcast") is True

    def test_broadcast_includes_sent_to_list(self):
        self._setup_agents()
        result = send_agent_message("sender", "*", "Hello all")
        assert "sent_to" in result
        assert isinstance(result["sent_to"], list)

    def test_broadcast_includes_count(self):
        self._setup_agents()
        result = send_agent_message("sender", "*", "Hello all")
        assert "count" in result
        assert result["count"] == len(result["sent_to"])

    def test_broadcast_sends_to_online_and_idle_only(self):
        self._setup_agents()
        result = send_agent_message("sender", "*", "Broadcast")
        sent_to = result["sent_to"]
        assert "agent-alpha" in sent_to   # online
        assert "agent-beta" in sent_to    # idle
        assert "agent-gamma" not in sent_to  # offline

    def test_broadcast_excludes_sender(self):
        update_agent_presence("broadcaster", status="online")
        update_agent_presence("receiver", status="online")
        result = send_agent_message("broadcaster", "*", "self-exclude")
        assert "broadcaster" not in result["sent_to"]
        assert "receiver" in result["sent_to"]

    def test_broadcast_messages_appear_in_each_recipient_inbox(self):
        self._setup_agents()
        send_agent_message("sender", "*", "inbox-check")
        alpha_inbox = get_agent_inbox("agent-alpha")
        beta_inbox = get_agent_inbox("agent-beta")
        gamma_inbox = get_agent_inbox("agent-gamma")
        assert any(m["subject"] == "inbox-check" for m in alpha_inbox)
        assert any(m["subject"] == "inbox-check" for m in beta_inbox)
        assert not any(m["subject"] == "inbox-check" for m in gamma_inbox)

    def test_broadcast_with_no_online_agents_returns_empty(self):
        """No online/idle agents besides sender → sent_to is empty."""
        update_agent_presence("lonely", status="online")
        result = send_agent_message("lonely", "*", "Empty broadcast")
        assert result["count"] == 0
        assert result["sent_to"] == []

    def test_broadcast_invalid_priority_rejected(self):
        self._setup_agents()
        result = send_agent_message("sender", "*", "bad", priority="bogus")
        assert "error" in result

    def test_normal_send_unchanged_structure(self):
        """Non-broadcast sends must still return original structure."""
        msg = send_agent_message("a", "b", "normal")
        assert "id" in msg
        assert "from_agent" in msg
        assert "to_agent" in msg
        assert "broadcast" not in msg


# ---------------------------------------------------------------------------
# MCP tool: agent_send ttl_seconds parameter
# ---------------------------------------------------------------------------


class TestAgentSendMCPTool:
    def test_agent_send_accepts_ttl_seconds(self):
        from local_memory_mcp.server import agent_send
        result = agent_send("a", "b", "mcp-ttl", ttl_seconds=60)
        assert result.get("expires_at") is not None

    def test_agent_send_ttl_none_by_default(self):
        from local_memory_mcp.server import agent_send
        result = agent_send("a", "b", "mcp-no-ttl")
        assert result.get("expires_at") is None


# ---------------------------------------------------------------------------
# MCP tool: agent_messages_cleanup
# ---------------------------------------------------------------------------


class TestAgentMessagesCleanupMCPTool:
    def test_agent_messages_cleanup_exists_and_callable(self):
        from local_memory_mcp.server import agent_messages_cleanup
        result = agent_messages_cleanup()
        assert "deleted" in result

    def test_agent_messages_cleanup_deletes_expired(self):
        from local_memory_mcp.server import agent_messages_cleanup
        send_agent_message("a", "b", "mcp-clean", ttl_seconds=-1)
        result = agent_messages_cleanup()
        assert result["deleted"] >= 1

    def test_agent_messages_cleanup_exported_in_init(self):
        assert hasattr(lm, "cleanup_expired_messages")
