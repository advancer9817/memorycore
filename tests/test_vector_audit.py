from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import local_memory_mcp as lm


def test_vector_audit_reports_unavailable_store_gracefully():
    record = lm.add_memory_record(
        "project_memory",
        "Audit unavailable",
        "Vector audit should degrade cleanly.",
        memory_id="vector-audit-unavailable",
        atomize=False,
    )

    fake_store = MagicMock()
    fake_store.status.return_value = {"available": False, "count": 0}

    with patch("local_memory_mcp.vector_store.get_vector_store", return_value=fake_store):
        report = lm.memory_vector_audit(dry_run=True, limit=10)

    assert report["available"] is False
    assert report["checked"] == 1
    assert report["sqlite_active"] == 1
    assert report["missing_vectors"] == [record["id"]]
    assert report["rebuilt"] == 0


def test_vector_audit_detects_missing_vectors():
    present = lm.add_memory_record(
        "project_memory",
        "Vector present",
        "Already indexed memory.",
        memory_id="vector-audit-present",
        atomize=False,
    )
    missing = lm.add_memory_record(
        "project_memory",
        "Vector missing",
        "Missing indexed memory.",
        memory_id="vector-audit-missing",
        atomize=False,
    )

    fake_client = MagicMock()
    fake_client.retrieve.return_value = [SimpleNamespace(id=present["id"])]
    fake_store = SimpleNamespace(
        status=lambda: {"available": True, "count": 1, "dim": 768, "collection": "agent_memory"},
        config=SimpleNamespace(collection="agent_memory"),
        _client=fake_client,
    )

    with patch("local_memory_mcp.vector_store.get_vector_store", return_value=fake_store):
        report = lm.memory_vector_audit(dry_run=True, limit=10)

    assert report["available"] is True
    assert report["checked"] == 2
    assert report["missing_vectors"] == [missing["id"]]
    assert report["vector_count"] == 1
    fake_client.retrieve.assert_called_once()
