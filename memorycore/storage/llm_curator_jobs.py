from __future__ import annotations

import base64
import json
import uuid
from typing import Any

from memorycore.models import as_json, now
from memorycore.storage.db import managed_conn, read_conn


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _job_row_to_dict(row: Any) -> dict[str, Any]:
    data = dict(row)
    data["params"] = _loads(data.pop("params_json", None), {})
    data["progress"] = _loads(data.pop("progress_json", None), {})
    data["summary"] = _loads(data.pop("summary_json", None), {})
    data["errors"] = _loads(data.pop("error_json", None), [])
    return data


def _batch_row_to_dict(row: Any) -> dict[str, Any]:
    data = dict(row)
    data["error"] = _loads(data.pop("error_json", None), None)
    return data


def _encode_cursor(offset: int) -> str:
    raw = json.dumps({"offset": max(0, int(offset))}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        data = json.loads(raw)
        return max(0, int(data.get("offset") or 0))
    except Exception:
        return 0


def create_llm_curator_job(
    job_id: str | None = None,
    *,
    params: dict[str, Any] | None = None,
    created_by: str = "frontend",
    governance_run_id: str = "",
) -> dict[str, Any]:
    job_id = job_id or str(uuid.uuid4())
    ts = now()
    with managed_conn() as conn:
        conn.execute(
            """
            INSERT INTO llm_curator_jobs (
              id, status, started_at, updated_at, params_json, progress_json,
              summary_json, error_json, governance_run_id, created_by
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                job_id,
                "running",
                ts,
                ts,
                as_json(params or {}),
                as_json({}),
                as_json({}),
                as_json([]),
                governance_run_id or "",
                created_by or "frontend",
            ),
        )
        row = conn.execute("SELECT * FROM llm_curator_jobs WHERE id=?", (job_id,)).fetchone()
    return _job_row_to_dict(row)


def update_llm_curator_job(
    job_id: str,
    *,
    status: str | None = None,
    progress: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
    errors: list[Any] | None = None,
    finished: bool = False,
) -> dict[str, Any] | None:
    ts = now()
    assignments = ["updated_at=?"]
    params: list[Any] = [ts]
    if status is not None:
        assignments.append("status=?")
        params.append(status)
    if progress is not None:
        assignments.append("progress_json=?")
        params.append(as_json(progress))
    if summary is not None:
        assignments.append("summary_json=?")
        params.append(as_json(summary))
    if errors is not None:
        assignments.append("error_json=?")
        params.append(as_json(errors))
    if finished:
        assignments.append("finished_at=?")
        params.append(ts)
    params.append(job_id)
    with managed_conn() as conn:
        conn.execute(f"UPDATE llm_curator_jobs SET {', '.join(assignments)} WHERE id=?", tuple(params))
        row = conn.execute("SELECT * FROM llm_curator_jobs WHERE id=?", (job_id,)).fetchone()
    return _job_row_to_dict(row) if row is not None else None


def get_llm_curator_job(job_id: str) -> dict[str, Any] | None:
    with read_conn() as conn:
        row = conn.execute("SELECT * FROM llm_curator_jobs WHERE id=?", (job_id,)).fetchone()
    return _job_row_to_dict(row) if row is not None else None


def mark_stale_running_jobs_failed() -> int:
    ts = now()
    with managed_conn() as conn:
        rows = conn.execute("SELECT id FROM llm_curator_jobs WHERE status='running'").fetchall()
        for row in rows:
            conn.execute(
                """
                UPDATE llm_curator_jobs
                SET status='failed', updated_at=?, finished_at=?, error_json=?
                WHERE id=?
                """,
                (ts, ts, as_json(["Job was interrupted by service restart; partial results remain available."]), row["id"]),
            )
    return len(rows)


def get_latest_llm_curator_job() -> dict[str, Any] | None:
    with read_conn() as conn:
        row = conn.execute("SELECT * FROM llm_curator_jobs ORDER BY started_at DESC LIMIT 1").fetchone()
    return _job_row_to_dict(row) if row is not None else None


def start_llm_curator_batch(
    job_id: str,
    stage: str,
    batch_index: int,
    *,
    candidate_count: int = 0,
    cursor_token: str = "",
) -> dict[str, Any]:
    batch_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"llm-curator:{job_id}:{stage}:{batch_index}"))
    ts = now()
    with managed_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO llm_curator_batches (
              id, job_id, stage, batch_index, status, started_at, candidate_count,
              finding_count, decision_count, cursor_token, error_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                batch_id,
                job_id,
                stage,
                int(batch_index),
                "running",
                ts,
                int(candidate_count),
                0,
                0,
                cursor_token or "",
                as_json(None),
            ),
        )
        row = conn.execute("SELECT * FROM llm_curator_batches WHERE id=?", (batch_id,)).fetchone()
    return _batch_row_to_dict(row)


def finish_llm_curator_batch(
    batch_id: str,
    *,
    status: str = "succeeded",
    finding_count: int = 0,
    decision_count: int = 0,
    error: Any = None,
) -> dict[str, Any] | None:
    ts = now()
    with managed_conn() as conn:
        conn.execute(
            """
            UPDATE llm_curator_batches
            SET status=?, finished_at=?, finding_count=?, decision_count=?, error_json=?
            WHERE id=?
            """,
            (status, ts, int(finding_count), int(decision_count), as_json(error), batch_id),
        )
        row = conn.execute("SELECT * FROM llm_curator_batches WHERE id=?", (batch_id,)).fetchone()
    return _batch_row_to_dict(row) if row is not None else None


def list_llm_curator_batches(job_id: str, *, after: str | None = None, limit: int = 50) -> dict[str, Any]:
    cap = max(1, min(int(limit), 200))
    params: list[Any] = [job_id]
    where = "WHERE job_id=?"
    offset = _decode_cursor(after)
    params.append(cap + 1)
    params.append(offset)
    with read_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM llm_curator_batches {where} ORDER BY started_at ASC, id ASC LIMIT ? OFFSET ?",
            tuple(params),
        ).fetchall()
    has_more = len(rows) > cap
    rows = rows[:cap]
    items = [_batch_row_to_dict(row) for row in rows]
    next_cursor = _encode_cursor(offset + len(rows))
    return {"items": items, "next_cursor": next_cursor, "has_more": has_more}


def list_llm_curator_decisions(
    job_id: str,
    *,
    after: str | None = None,
    limit: int = 50,
    review_status: str | None = "actionable",
    decision_type: str | None = None,
) -> dict[str, Any]:
    from memorycore.storage.governance import _decision_row_to_dict

    cap = max(1, min(int(limit), 200))
    conditions = ["curator_job_id=?"]
    params: list[Any] = [job_id]
    if review_status == "actionable":
        conditions.append("review_status IN ('needs_review', 'auto_approved') AND recommended_action != 'keep'")
    elif review_status and review_status != "all":
        conditions.append("review_status=?")
        params.append(review_status)
    if decision_type:
        conditions.append("decision_type=?")
        params.append(decision_type)
    offset = _decode_cursor(after)
    params.append(cap + 1)
    params.append(offset)
    where = "WHERE " + " AND ".join(conditions)
    with read_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM governance_decisions {where} ORDER BY created_at ASC, id ASC LIMIT ? OFFSET ?",
            tuple(params),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM governance_decisions WHERE curator_job_id=?",
            (job_id,),
        ).fetchone()[0]
    has_more = len(rows) > cap
    rows = rows[:cap]
    items = [_decision_row_to_dict(row) for row in rows]
    next_cursor = _encode_cursor(offset + len(rows))
    return {"items": items, "next_cursor": next_cursor, "has_more": has_more, "total": total}
