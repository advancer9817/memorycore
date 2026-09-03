"""Tests for caller agent auto-detection from MCP context and headers."""
from __future__ import annotations

import asyncio
import os
from unittest import mock
from unittest.mock import MagicMock
import pytest
from mcp.server.fastmcp import Context
import mcp.types as types

from memorycore import server


def _make_mock_context(client_name: str = "", header_agent: str = "") -> Context:
    params = types.InitializeRequestParams(
        protocolVersion="2024-11-05",
        capabilities=types.ClientCapabilities(),
        clientInfo=types.Implementation(name=client_name or "", version="1.0"),
    )
    mock_session = MagicMock()
    mock_session.client_params = params

    class FakeRequest:
        def __init__(self, headers: dict[str, str]):
            self.headers = headers

    class FakeRequestContext:
        def __init__(self, s):
            self.session = s
            self.meta = None
            self.request_id = "req-test"
            self.request = FakeRequest({"x-agent-id": header_agent}) if header_agent else None

    return Context(request_context=FakeRequestContext(mock_session))


class TestCallerAgentAutoDetection:
    def test_infer_caller_agent_from_client_info(self):
        ctx_claude = _make_mock_context(client_name="Claude Code")
        assert server._infer_caller_agent(ctx_claude) == "claude"

        ctx_codex = _make_mock_context(client_name="OpenAI Codex")
        assert server._infer_caller_agent(ctx_codex) == "codex"

        ctx_hermes = _make_mock_context(client_name="hermes-cli")
        assert server._infer_caller_agent(ctx_hermes) == "hermes"

        ctx_hermes_plugin = _make_mock_context(client_name="hermes-mcore-plugin")
        assert server._infer_caller_agent(ctx_hermes_plugin) == "hermes"

        ctx_opencode = _make_mock_context(client_name="opencode-v1")
        assert server._infer_caller_agent(ctx_opencode) == "opencode"

        ctx_gemini = _make_mock_context(client_name="gemini-cli")
        assert server._infer_caller_agent(ctx_gemini) == "gemini"

        # When MCORE_AGENT_ID is not set in env
        with mock.patch.dict(os.environ, {"MCORE_AGENT_ID": ""}):
            assert server._infer_caller_agent(None) == ""

    def test_infer_caller_agent_from_headers(self):
        ctx_header_hermes = _make_mock_context(header_agent="hermes")
        assert server._infer_caller_agent(ctx_header_hermes) == "hermes"

        ctx_header_claude = _make_mock_context(header_agent="claude")
        assert server._infer_caller_agent(ctx_header_claude) == "claude"

    def test_memory_add_infers_claude_agent(self, isolated_memory_db):
        tool = server.mcp._tool_manager._tools["memory_add"]
        ctx = _make_mock_context(client_name="Claude Code")

        res = asyncio.run(
            tool.run(
                {
                    "type": "decision",
                    "title": "Test auto detect title",
                    "content": "Test auto detect content",
                },
                context=ctx,
            )
        )
        assert res.get("source_agent") == "claude"

    def test_memory_add_infers_hermes_agent(self, isolated_memory_db):
        tool = server.mcp._tool_manager._tools["memory_add"]
        ctx = _make_mock_context(header_agent="hermes")

        res = asyncio.run(
            tool.run(
                {
                    "type": "decision",
                    "title": "Test hermes detect title",
                    "content": "Test hermes detect content",
                },
                context=ctx,
            )
        )
        assert res.get("source_agent") == "hermes"

    def test_memory_add_preserves_explicit_agent(self, isolated_memory_db):
        tool = server.mcp._tool_manager._tools["memory_add"]
        ctx = _make_mock_context(client_name="Claude Code")

        res = asyncio.run(
            tool.run(
                {
                    "type": "decision",
                    "title": "Test explicit title",
                    "content": "Test explicit content",
                    "source_agent": "custom-agent-override",
                },
                context=ctx,
            )
        )
        assert res.get("source_agent") == "custom-agent-override"

    def test_memory_context_infers_agent(self, isolated_memory_db):
        tool = server.mcp._tool_manager._tools["memory_context"]
        ctx = _make_mock_context(client_name="Claude Code")

        res = asyncio.run(
            tool.run(
                {
                    "task": "debug context task",
                },
                context=ctx,
            )
        )
        assert "# memory_context for claude" in res.get("context", "")
