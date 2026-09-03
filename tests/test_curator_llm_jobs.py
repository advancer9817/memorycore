"""Unit tests for LLM Curator job registry and cooldown mechanisms."""
import time
import pytest


"""Unit tests for LLM Curator job registry and cooldown mechanisms."""
import datetime
import os
import time
import pytest
from unittest.mock import patch

from memorycore.models import now, local_now
from memorycore.storage.db import managed_conn, read_conn
from memorycore.storage.curator_llm.core import (
    _cleanup_reviewed_ids,
    _get_recently_reviewed_ids,
    _mark_reviewed,
)
from memorycore.storage.llm_curator_jobs import (
    create_llm_curator_job,
    get_llm_curator_job,
    mark_stale_running_jobs_failed,
)


def test_job_registry_ttl_cleanup(tmp_path):
    """mark_stale_running_jobs_failed marks dead-process running jobs as failed."""
    # Create a job with non-existent dead PID
    dead_pid = 99999999
    job_id = "test-job-stale-pid"
    with managed_conn() as conn:
        conn.execute("DELETE FROM llm_curator_jobs WHERE id=?", (job_id,))
    create_llm_curator_job(job_id=job_id, params={"limit": 10})
    with managed_conn() as conn:
        conn.execute(
            "UPDATE llm_curator_jobs SET status='running', progress_json=? WHERE id=?",
            (f'{{"pid": {dead_pid}}}', job_id),
        )

    marked = mark_stale_running_jobs_failed()
    assert marked >= 1
    job = get_llm_curator_job(job_id)
    assert job is not None
    assert job["status"] == "failed"
    assert "interrupted" in str(job.get("errors", []))

    # Clean up
    with managed_conn() as conn:
        conn.execute("DELETE FROM llm_curator_jobs WHERE id=?", (job_id,))


def test_review_cooldown_skips_recent_memories():
    """Memories reviewed within cooldown period should be in recently reviewed set."""
    test_id = "test-memory-id-12345"
    with managed_conn() as conn:
        conn.execute("DELETE FROM curator_review_log WHERE memory_id=?", (test_id,))

    try:
        _mark_reviewed([test_id], review_type="llm_curator")
        recently = _get_recently_reviewed_ids(review_type="llm_curator")
        assert test_id in recently
    finally:
        with managed_conn() as conn:
            conn.execute("DELETE FROM curator_review_log WHERE memory_id=?", (test_id,))


def test_review_cooldown_expired_memory_not_skipped():
    """Memories reviewed beyond cooldown period should not be returned by _get_recently_reviewed_ids,
    and entries beyond reviewed_ids_max_age_seconds should be physically cleaned up by _cleanup_reviewed_ids."""
    test_id_cooldown = "test-memory-id-cooldown-expired"
    test_id_stale = "test-memory-id-max-age-expired"
    ts_now = local_now()
    past_cooldown = (ts_now - datetime.timedelta(seconds=7201)).isoformat(timespec="seconds")
    past_max_age = (ts_now - datetime.timedelta(seconds=86401)).isoformat(timespec="seconds")

    with managed_conn() as conn:
        conn.execute("DELETE FROM curator_review_log WHERE memory_id IN (?, ?)", (test_id_cooldown, test_id_stale))
        conn.execute("INSERT INTO curator_review_log(memory_id, review_type, reviewed_at) VALUES (?, 'llm_curator', ?)", (test_id_cooldown, past_cooldown))
        conn.execute("INSERT INTO curator_review_log(memory_id, review_type, reviewed_at) VALUES (?, 'llm_curator', ?)", (test_id_stale, past_max_age))

    try:
        # 1. Beyond cooldown window (7200s): should not be in recently reviewed
        recently = _get_recently_reviewed_ids(review_type="llm_curator")
        assert test_id_cooldown not in recently
        assert test_id_stale not in recently

        # 2. Beyond max age (86400s): should be deleted by _cleanup_reviewed_ids
        _cleanup_reviewed_ids()
        with read_conn() as conn:
            row_cooldown = conn.execute("SELECT memory_id FROM curator_review_log WHERE memory_id=?", (test_id_cooldown,)).fetchone()
            row_stale = conn.execute("SELECT memory_id FROM curator_review_log WHERE memory_id=?", (test_id_stale,)).fetchone()
        assert row_cooldown is not None  # Not past max_age yet, still retained for history
        assert row_stale is None         # Past max_age, deleted
    finally:
        with managed_conn() as conn:
            conn.execute("DELETE FROM curator_review_log WHERE memory_id IN (?, ?)", (test_id_cooldown, test_id_stale))



def test_large_pool_sampling_limit():
    """_find_candidate_pairs processes all eligible memories."""
    import memorycore.storage.curator_llm as clm
    from unittest.mock import MagicMock, patch

    memories = [{"id": f"id-{i}", "title": f"T{i}", "content": f"C{i}", "importance": 0.5}
                for i in range(600)]

    vs = MagicMock()
    vs.search.return_value = []

    with patch("memorycore.storage.curator_llm._get_recently_reviewed_ids", return_value=set()):
        pairs = clm._find_candidate_pairs(vs, memories, sim_threshold=0.6)
    assert isinstance(pairs, list)


def test_run_llm_curator_applies_and_rebuilds_vectors(monkeypatch):
    """Explicit rebuild_vectors=True path should run the governance runner and rebuild."""
    import memorycore.storage.curator_llm as clm

    report = {"summary": {"semantic_duplicates": 1}, "errors": []}
    governance = {"decisions_created": 1, "decisions": [], "auto_applied": [{"applied": {"downgraded": 1}}]}
    monkeypatch.setattr(
        "memorycore.storage.curator_llm.report.llm_curator_report",
        lambda **_: report,
    )
    monkeypatch.setattr(
        "memorycore.storage.governance.convert_llm_findings_to_decisions",
        lambda report, auto_apply: governance,
    )

    rebuild_calls = []
    monkeypatch.setattr(
        "memorycore.storage.memory_rebuild_vectors",
        lambda: rebuild_calls.append(True) or {"rebuilt": 1},
    )
    monkeypatch.setattr(
        "memorycore.storage.audit.log_audit_event",
        lambda *args, **kwargs: None,
    )

    result = clm.run_llm_curator(config={}, limit=10, sim_threshold=0.7, apply=True, rebuild_vectors=True)

    assert result["summary"] == {"semantic_duplicates": 1}
    assert result["governance"] == governance
    assert result["applied"] == {"governance_auto_applied": 1}
    assert result["rebuild_vectors"] == {"rebuilt": 1}
    assert rebuild_calls == [True]


def test_run_llm_curator_skips_rebuild_by_default(monkeypatch):
    """Default rebuild_vectors=False: curator must NOT trigger full vector rebuild."""
    import memorycore.storage.curator_llm as clm

    report = {"summary": {"semantic_duplicates": 0}, "errors": []}
    governance = {"decisions_created": 0, "decisions": [], "auto_applied": []}
    monkeypatch.setattr(
        "memorycore.storage.curator_llm.report.llm_curator_report",
        lambda **_: report,
    )
    monkeypatch.setattr(
        "memorycore.storage.governance.convert_llm_findings_to_decisions",
        lambda report, auto_apply: governance,
    )

    rebuild_calls = []
    monkeypatch.setattr(
        "memorycore.storage.memory_rebuild_vectors",
        lambda: rebuild_calls.append(True) or {"rebuilt": 1},
    )
    monkeypatch.setattr(
        "memorycore.storage.audit.log_audit_event",
        lambda *args, **kwargs: None,
    )

    result = clm.run_llm_curator(config={}, limit=10, sim_threshold=0.7, apply=True)

    assert result["summary"] == {"semantic_duplicates": 0}
    assert "rebuild_vectors" not in result
    assert rebuild_calls == []


def test_llm_curator_cli_summary_only(monkeypatch, capsys):
    """The scheduler script can call the LLM curator through the CLI."""
    import memorycore.server as server

    monkeypatch.setattr(server, "load_config", lambda: {})
    monkeypatch.setattr(
        "memorycore.storage.curator_llm.run_llm_curator",
        lambda **_: {"summary": {"split_candidates": 2}, "errors": []},
    )

    assert server.main(["llm-curator", "--limit", "5", "--summary-only"]) == 0
    assert '"split_candidates": 2' in capsys.readouterr().out


def test_run_llm_curator_incremental_passes_require_accessed(monkeypatch, tmp_path):
    """require_accessed flag should propagate into _fetch_active_memories calls."""
    import memorycore.storage.curator_llm.report as report_mod

    calls: list[bool] = []

    def fake_fetch(limit, require_accessed=False):
        calls.append(bool(require_accessed))
        return []

    monkeypatch.setattr(report_mod, "_fetch_active_memories", fake_fetch)
    monkeypatch.setattr(report_mod, "_get_vector_store", lambda *a, **k: type("VS", (), {"available": False})())
    monkeypatch.setattr(report_mod, "_load_extraction_config", lambda *a, **k: type("LC", (), {"temperature": 0.6})())

    report_mod.run_llm_curator_incremental(
        job_id="j-require", config={}, limit=50, sim_threshold=0.8,
        apply=False, rebuild_vectors=False, require_accessed=True,
    )
    assert calls and all(calls), f"require_accessed not propagated: {calls}"


def test_run_llm_curator_report_passes_require_accessed(monkeypatch):
    """llm_curator_report should forward require_accessed into memory fetch."""
    import memorycore.storage.curator_llm.report as report_mod

    calls: list[bool] = []

    def fake_fetch(limit, require_accessed=False):
        calls.append(bool(require_accessed))
        return []

    monkeypatch.setattr(report_mod, "_fetch_active_memories", fake_fetch)
    monkeypatch.setattr(report_mod, "_get_vector_store", lambda *a, **k: type("VS", (), {"available": False})())
    monkeypatch.setattr(report_mod, "_load_extraction_config", lambda *a, **k: type("LC", (), {"temperature": 0.6})())

    report_mod.llm_curator_report(config={}, limit=50, require_accessed=True)
    assert calls == [True]
