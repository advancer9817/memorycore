"""Tests for maintenance D2 (merge) and D3 (clean) loops."""
from __future__ import annotations

import pytest

from memorycore.storage.crud import add_memory_record
from memorycore.storage.maintenance import (
    execute_data_maintenance_clean,
    execute_data_maintenance_merge,
    plan_data_maintenance_clean,
    plan_data_maintenance_merge,
)


@pytest.fixture(autouse=True)
def _no_real_backup(monkeypatch):
    """Never touch the real backup dir from tests."""
    import memorycore.storage.transfer as transfer

    monkeypatch.setattr(
        transfer,
        "memory_backup",
        lambda *a, **k: {"path": "/tmp/fake-backup.sqlite3", "bytes": 123, "quick_check": "ok"},
    )


def _add(title: str, **kwargs) -> dict:
    importance = kwargs.pop("importance", 0.5)
    confidence = kwargs.pop("confidence", 0.8)
    return add_memory_record(
        memory_type="project_memory",
        title=title,
        content=kwargs.pop("content", f"{title} 的详细内容，足够长的正文用于测试。"),
        tags=[],
        source="manual",
        source_agent=kwargs.pop("source_agent", "test-agent"),
        confidence=confidence,
        importance=importance,
        atomize=False,
        **kwargs,
    )


def _force_status_created(record_id: str, status: str, created_at: str) -> None:
    from memorycore.storage.db import managed_conn

    with managed_conn() as conn:
        conn.execute(
            "UPDATE memories SET status=?, created_at=? WHERE id=?",
            (status, created_at, record_id),
        )


# ---------------------------------------------------------------------------
# D2 — merge
# ---------------------------------------------------------------------------


class TestMerge:
    def test_plan_detects_title_duplicates(self):
        for _ in range(3):
            _add("重复主题", importance=0.5)
        plan = plan_data_maintenance_merge(limit=50)
        assert plan["merge_count"] >= 1
        group = plan["merge_groups"][0]
        assert group["count"] == 3
        assert len(group["loser_ids"]) == 2
        assert group["winner_id"] not in group["loser_ids"]

    def test_execute_supersedes_losers_with_lineage(self):
        r1 = _add("相同标题 A", importance=0.3)
        r2 = _add("相同标题 A", importance=0.9)  # winner: highest importance
        r3 = _add("相同标题 A", importance=0.6)
        plan = plan_data_maintenance_merge(limit=50)
        group = plan["merge_groups"][0]

        result = execute_data_maintenance_merge(plan["plan_token"], limit=50)
        assert result["status"] == "succeeded"
        assert result["merged"] == 2

        from memorycore.storage.db import read_conn

        with read_conn() as conn:
            rows = {
                row["id"]: row
                for row in conn.execute(
                    "SELECT id, status, superseded_by FROM memories WHERE id IN (?,?,?)",
                    (r1["id"], r2["id"], r3["id"]),
                ).fetchall()
            }
        winner = max(r1, r2, r3, key=lambda r: r["importance"])
        for rid in (r1["id"], r2["id"], r3["id"]):
            row = rows[rid]
            if rid == winner["id"]:
                assert row["status"] != "superseded"
            else:
                assert row["status"] == "superseded"
                assert row["superseded_by"] == winner["id"]

    def test_execute_idempotent_replay(self):
        r1 = _add("幂等标题", importance=0.3)
        r2 = _add("幂等标题", importance=0.8)
        from memorycore.storage.maintenance import (
            create_maintenance_job,
            run_data_maintenance_job,
        )

        plan = plan_data_maintenance_merge(limit=50)
        job1 = create_maintenance_job(plan["plan_token"], kind="merge")
        first = run_data_maintenance_job(job1["job_id"], plan["plan_token"], action="merge")
        job2 = create_maintenance_job(plan["plan_token"], kind="merge")
        second = run_data_maintenance_job(job2["job_id"], plan["plan_token"], action="merge")
        assert first["status"] == "succeeded"
        assert second["status"] == "succeeded"
        assert second["replayed"] is True

    def test_no_duplicates_plan_clean(self):
        for i in range(3):
            _add(f"唯一主题 {i}")
        plan = plan_data_maintenance_merge(limit=50)
        assert plan["merge_count"] == 0


# ---------------------------------------------------------------------------
# D3 — clean
# ---------------------------------------------------------------------------


class TestClean:
    def test_plan_detects_stale_candidates(self):
        rec = _add("过期候选")
        _force_status_created(rec["id"], "candidate", "2020-01-01T00:00:00+00:00")
        plan = plan_data_maintenance_clean(limit=50)
        assert plan["clean_count"] >= 1
        assert rec["id"] in plan["clean_ids"]

    def test_execute_hard_deletes(self):
        rec = _add("硬删目标")
        _force_status_created(rec["id"], "candidate", "2020-01-01T00:00:00+00:00")
        plan = plan_data_maintenance_clean(limit=50)

        result = execute_data_maintenance_clean(plan["plan_token"], limit=50)
        assert result["status"] == "succeeded"
        assert result["deleted"] >= 1

        from memorycore.storage.db import read_conn

        with read_conn() as conn:
            row = conn.execute("SELECT id FROM memories WHERE id=?", (rec["id"],)).fetchone()
            fts = conn.execute("SELECT id FROM memories_fts WHERE id=?", (rec["id"],)).fetchone()
        assert row is None
        assert fts is None

    def test_skips_used_records(self):
        rec = _add("用过的不许删")
        _force_status_created(rec["id"], "candidate", "2020-01-01T00:00:00+00:00")
        from memorycore.storage.db import managed_conn

        with managed_conn() as conn:
            conn.execute(
                "UPDATE memories SET last_accessed_at=?, effectiveness_score=? WHERE id=?",
                ("2026-08-01T10:00:00+08:00", 0.9, rec["id"]),
            )
        plan = plan_data_maintenance_clean(limit=50)
        assert rec["id"] not in plan["clean_ids"]

    def test_skips_high_importance(self):
        rec = _add("高价值不许删", importance=0.99)
        _force_status_created(rec["id"], "candidate", "2020-01-01T00:00:00+00:00")
        plan = plan_data_maintenance_clean(limit=50)
        assert rec["id"] not in plan["clean_ids"]

    def test_execute_idempotent_replay(self):
        rec = _add("清理幂等")
        _force_status_created(rec["id"], "candidate", "2020-01-01T00:00:00+00:00")
        from memorycore.storage.maintenance import (
            create_maintenance_job,
            run_data_maintenance_job,
        )

        plan = plan_data_maintenance_clean(limit=50)
        job1 = create_maintenance_job(plan["plan_token"], kind="clean")
        first = run_data_maintenance_job(job1["job_id"], plan["plan_token"], action="clean")
        job2 = create_maintenance_job(plan["plan_token"], kind="clean")
        second = run_data_maintenance_job(job2["job_id"], plan["plan_token"], action="clean")
        assert first["status"] == "succeeded"
        assert second["status"] == "succeeded"
        assert second["replayed"] is True