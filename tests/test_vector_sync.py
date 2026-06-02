"""Tests for automatic Qdrant sync on SQLite writes."""
from unittest.mock import MagicMock, patch

import pytest


def make_mock_vs():
    vs = MagicMock()
    vs.upsert.return_value = True
    vs.delete.return_value = True
    return vs


def test_add_triggers_upsert(isolated_memory_db):
    from memorycore.storage import add_memory_record

    mock_vs = make_mock_vs()
    with patch("memorycore.storage.crud._get_vector_store", return_value=mock_vs):
        result = add_memory_record("user_profile", "Test Title", "Test content")

    assert result["id"] is not None
    mock_vs.upsert.assert_called_once()
    args = mock_vs.upsert.call_args
    assert args[0][0] == result["id"]
    assert "Test Title" in args[0][1]


def test_update_content_triggers_upsert(isolated_memory_db):
    from memorycore.storage import add_memory_record, update_memory_content

    mock_vs = make_mock_vs()
    with patch("memorycore.storage.crud._get_vector_store", return_value=mock_vs):
        rec = add_memory_record("project_memory", "Old Title", "Old content")
        mock_vs.reset_mock()
        result = update_memory_content(rec["id"], new_content="New content")

    mock_vs.upsert.assert_called_once()
    args = mock_vs.upsert.call_args
    assert "New content" in args[0][1]


def test_update_status_active_triggers_upsert(isolated_memory_db):
    from memorycore.storage import add_memory_record, update_status

    mock_vs = make_mock_vs()
    with patch("memorycore.storage.crud._get_vector_store", return_value=mock_vs):
        rec = add_memory_record("feedback", "Feedback", "body")
        mock_vs.reset_mock()
        # Updating to active (from active) still upserts
        update_status(rec["id"], "active")

    mock_vs.upsert.assert_called_once()


def test_update_status_non_active_triggers_delete(isolated_memory_db):
    """Non-active status changes must delete the vector, not upsert."""
    from memorycore.storage import add_memory_record, update_status

    mock_vs = make_mock_vs()
    with patch("memorycore.storage.crud._get_vector_store", return_value=mock_vs):
        rec = add_memory_record("feedback", "Feedback", "body")
        mock_vs.reset_mock()
        update_status(rec["id"], "stale")

    mock_vs.delete.assert_called_once_with(rec["id"])
    mock_vs.upsert.assert_not_called()


def test_sync_failure_does_not_raise(isolated_memory_db):
    """Vector sync failure must never propagate to caller."""
    from memorycore.storage import add_memory_record

    mock_vs = make_mock_vs()
    mock_vs.upsert.side_effect = RuntimeError("Qdrant down")
    with patch("memorycore.storage.crud._get_vector_store", return_value=mock_vs):
        result = add_memory_record("user_profile", "Resilience test", "content")

    assert result["id"] is not None


def test_sync_skipped_when_vector_store_none(isolated_memory_db):
    """When _get_vector_store is None, sync is skipped without error."""
    from memorycore.storage import add_memory_record

    with patch("memorycore.storage.crud._get_vector_store", None):
        result = add_memory_record("user_profile", "No vector", "content")

    assert result["id"] is not None
