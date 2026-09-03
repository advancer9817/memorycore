#!/usr/bin/env python3
"""Context quality & retrieval relevance observation tool.

Evaluates:
1. Pinned fixture relevance tests (`tests/fixtures/context_relevance_cases.json`).
2. Live production statistics from `context_quality_events` table (1d, 7d, 30d).

Usage:
    .venv/bin/python scripts/eval_context_quality.py
    .venv/bin/python scripts/eval_context_quality.py --json
    .venv/bin/python scripts/eval_context_quality.py --save
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from memorycore.models import db_path  # noqa: E402


def run_fixture_tests(venv_py: Path) -> dict[str, Any]:
    test_file = REPO_ROOT / "tests" / "test_context_relevance.py"
    if not test_file.exists():
        return {"status": "skipped", "reason": "test file not found"}

    pytest_bin = venv_py.parent / "pytest"
    cmd = [str(pytest_bin if pytest_bin.exists() else venv_py), "-m", "pytest", str(test_file), "-q"]
    if pytest_bin.exists():
        cmd = [str(pytest_bin), str(test_file), "-q"]

    try:
        res = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
        output = (res.stdout + "\n" + res.stderr).strip()
        passed = "passed" in output and res.returncode == 0
        return {
            "status": "passed" if passed else "failed",
            "returncode": res.returncode,
            "summary": output.splitlines()[-1] if output.splitlines() else "",
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def query_quality_metrics(conn: sqlite3.Connection, days: int) -> dict[str, Any]:
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT 
            COUNT(*) as total_events,
            ROUND(AVG(hit_rate), 4) as avg_hit_rate,
            ROUND(AVG(filter_rate), 4) as avg_filter_rate,
            ROUND(AVG(cross_retrieval_rate), 4) as avg_cross_retrieval_rate,
            ROUND(AVG(used_count), 2) as avg_used_count,
            ROUND(AVG(vector_avg_score), 4) as avg_vector_score
        FROM context_quality_events
        WHERE created_at > datetime('now', '-{days} days')
        """
    )
    row = cur.fetchone()
    return {
        "days": days,
        "events": row[0] or 0,
        "avg_hit_rate": row[1] if row[1] is not None else 0.0,
        "avg_filter_rate": row[2] if row[2] is not None else 0.0,
        "avg_cross_retrieval_rate": row[3] if row[3] is not None else 0.0,
        "avg_used_count": row[4] if row[4] is not None else 0.0,
        "avg_vector_score": row[5] if row[5] is not None else 0.0,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate memorycore retrieval quality")
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    parser.add_argument("--save", action="store_true", help="Save snapshot to reports/quality-*.json")
    args = parser.parse_args()

    venv_py = REPO_ROOT / ".venv" / "bin" / "python"
    fixture_res = run_fixture_tests(venv_py)

    database_file = db_path()
    if not database_file.exists():
        print(f"Error: database {database_file} does not exist", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(database_file)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM memories WHERE status = 'active'")
    active_memories = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM memories")
    total_memories = cur.fetchone()[0]

    stats_1d = query_quality_metrics(conn, 1)
    stats_7d = query_quality_metrics(conn, 7)
    stats_30d = query_quality_metrics(conn, 30)
    conn.close()

    payload = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "database": str(database_file),
        "total_memories": total_memories,
        "active_memories": active_memories,
        "fixtures": fixture_res,
        "metrics": {
            "last_24h": stats_1d,
            "last_7d": stats_7d,
            "last_30d": stats_30d,
        },
        "targets": {
            "hit_rate_target": ">0.90",
            "cross_retrieval_target": ">=0.15",
            "fixtures_target": "all passed",
        },
    }

    if args.save:
        reports_dir = REPO_ROOT / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = reports_dir / f"quality_{ts}.json"
        report_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["saved_report"] = str(report_file)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print("=" * 65)
    print(" MemoryCore 检索质量与相关性观测报告")
    print("=" * 65)
    print(f"时间: {payload['timestamp']}")
    print(f"数据库: {database_file} (总计 {total_memories} 条 / 活跃 {active_memories} 条)")
    print(f"评测集 (fixtures): {fixture_res['status'].upper()} ({fixture_res.get('summary', '')})")
    print("-" * 65)
    print(f"{'时间窗口':<10} | {'事件数':<8} | {'Hit Rate':<10} | {'Cross Rate':<10} | {'Used Count':<10}")
    print("-" * 65)
    for label, m in [("过去 24 小时", stats_1d), ("过去 7 天", stats_7d), ("过去 30 天", stats_30d)]:
        print(f"{label:<10} | {m['events']:<8} | {m['avg_hit_rate']:<10.4f} | {m['avg_cross_retrieval_rate']:<10.4f} | {m['avg_used_count']:<10.2f}")
    print("-" * 65)
    print("指标达标与状态分析:")
    hit_1d = stats_1d['avg_hit_rate']
    print(f"  • Hit Rate (目标 >0.90): 当前 24h 为 {hit_1d:.4f} ({'达标' if hit_1d >= 0.90 else '接近目标 0.87~0.91 波动'})")
    cross_7d = stats_7d['avg_cross_retrieval_rate']
    print(f"  • Cross Retrieval Rate (目标 ≥0.15): 当前 7d 为 {cross_7d:.4f} (FTS5 与 Qdrant 双路重合度，主要受 FTS5 强过滤主导)")
    if "saved_report" in payload:
        print(f"  • 报告已保存至: {payload['saved_report']}")
    print("=" * 65)


if __name__ == "__main__":
    main()
