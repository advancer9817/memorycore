"""SQLite storage layer for local-memory-mcp.

Contains all database operations (CRUD, FTS search, curator, memory_links)
and the export_html dashboard generator.

This module has NO dependency on the MCP framework — it is pure SQLite +
business logic, so both server.py and dedup.py can import it cleanly
without circular import issues.
"""
from __future__ import annotations

import html
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from local_memory_mcp.injection_guard import (
    BOUNDARY_NOTICE,
    check_memory_for_injection,
    warning_for_filtered_memory,
)
from local_memory_mcp.models import (
    DEFAULT_CONFIG,
    DEFAULT_DB,
    _INITIALIZED_DB_PATHS,
    MEMORY_TYPES,
    STATUSES,
    VALID_RELATION_TYPES,
    as_json,
    db_path,
    finite_float,
    from_json,
    fts_phrase,
    normalize_list,
    normalize_title_key,
    now,
    parse_ts,
    row_to_dict,
    validate_status,
    validate_type,
)

__all__ = [
    "connect",
    "managed_conn",
    "init_db",
    "add_memory_record",
    "update_memory_content",
    "search_memory_records",
    "build_context_pack",
    "update_status",
    "add_feedback",
    "list_recent",
    "get_record",
    "timeline",
    "add_link",
    "query_links",
    "consolidate",
    "curator_report",
    "get_memory_stats",
    "export_html",
]


def connect() -> sqlite3.Connection:
    """Open a SQLite connection and ensure the schema exists for its DB path.

    Internal code should prefer managed_conn() so connections are explicitly
    closed.
    """
    path = db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    key = str(path.resolve())
    if key not in _INITIALIZED_DB_PATHS:
        init_db(conn)
        _INITIALIZED_DB_PATHS.add(key)
    return conn


@contextmanager
def managed_conn():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS memories (
          id TEXT PRIMARY KEY,
          type TEXT NOT NULL,
          scope TEXT NOT NULL DEFAULT 'global',
          title TEXT NOT NULL,
          content TEXT NOT NULL,
          tags_json TEXT NOT NULL DEFAULT '[]',
          source TEXT NOT NULL DEFAULT 'manual',
          source_agent TEXT NOT NULL DEFAULT 'unknown',
          project_path TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          last_accessed_at TEXT,
          confidence REAL NOT NULL DEFAULT 0.70,
          importance REAL NOT NULL DEFAULT 0.50,
          status TEXT NOT NULL DEFAULT 'active',
          decay_policy TEXT NOT NULL DEFAULT 'review',
          feedback_score REAL NOT NULL DEFAULT 0,
          related_ids_json TEXT NOT NULL DEFAULT '[]',
          metadata_json TEXT NOT NULL DEFAULT '{}',
          injected_count INTEGER NOT NULL DEFAULT 0,
          ineffective_count INTEGER NOT NULL DEFAULT 0,
          effectiveness_score REAL NOT NULL DEFAULT 0.5,
          last_injected_at TEXT
        );

        CREATE TABLE IF NOT EXISTS feedback_events (
          id TEXT PRIMARY KEY,
          memory_id TEXT NOT NULL,
          score REAL NOT NULL,
          note TEXT NOT NULL DEFAULT '',
          source_agent TEXT NOT NULL DEFAULT 'unknown',
          created_at TEXT NOT NULL,
          FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
          id UNINDEXED,
          title,
          content,
          tags,
          type,
          scope
        );

        CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
          INSERT INTO memories_fts(id, title, content, tags, type, scope)
          VALUES (new.id, new.title, new.content, new.tags_json, new.type, new.scope);
        END;
        CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
          DELETE FROM memories_fts WHERE id = old.id;
        END;
        CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
          DELETE FROM memories_fts WHERE id = old.id;
          INSERT INTO memories_fts(id, title, content, tags, type, scope)
          VALUES (new.id, new.title, new.content, new.tags_json, new.type, new.scope);
        END;

        CREATE INDEX IF NOT EXISTS idx_memories_type_status ON memories(type, status);
        CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(scope);
        CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_path);
        CREATE INDEX IF NOT EXISTS idx_memories_updated ON memories(updated_at);

        CREATE TABLE IF NOT EXISTS memory_links (
          id TEXT PRIMARY KEY,
          source_id TEXT NOT NULL,
          target_id TEXT NOT NULL,
          relation_type TEXT NOT NULL DEFAULT 'related_to',
          weight REAL NOT NULL DEFAULT 1.0,
          note TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          source_agent TEXT NOT NULL DEFAULT 'unknown',
          FOREIGN KEY(source_id) REFERENCES memories(id) ON DELETE CASCADE,
          FOREIGN KEY(target_id) REFERENCES memories(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_links_source ON memory_links(source_id);
        CREATE INDEX IF NOT EXISTS idx_links_target ON memory_links(target_id);
        CREATE INDEX IF NOT EXISTS idx_links_relation ON memory_links(relation_type);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_links_unique ON memory_links(source_id, target_id, relation_type);
        """
    )
    # If an earlier contentless FTS table exists, stored columns read back as NULL;
    # rebuild it as a normal FTS table so JOINs on f.id work correctly.
    try:
        null_fts = conn.execute("SELECT COUNT(*) FROM memories_fts WHERE id IS NULL").fetchone()[0]
    except sqlite3.OperationalError:
        null_fts = 0
    if null_fts:
        conn.executescript(
            """
            DROP TRIGGER IF EXISTS memories_ai;
            DROP TRIGGER IF EXISTS memories_ad;
            DROP TRIGGER IF EXISTS memories_au;
            DROP TABLE IF EXISTS memories_fts;
            CREATE VIRTUAL TABLE memories_fts USING fts5(
              id UNINDEXED, title, content, tags, type, scope
            );
            CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
              INSERT INTO memories_fts(id, title, content, tags, type, scope)
              VALUES (new.id, new.title, new.content, new.tags_json, new.type, new.scope);
            END;
            CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN
              DELETE FROM memories_fts WHERE id = old.id;
            END;
            CREATE TRIGGER memories_au AFTER UPDATE ON memories BEGIN
              DELETE FROM memories_fts WHERE id = old.id;
              INSERT INTO memories_fts(id, title, content, tags, type, scope)
              VALUES (new.id, new.title, new.content, new.tags_json, new.type, new.scope);
            END;
            """
        )
        rows = conn.execute("SELECT id,title,content,tags_json,type,scope FROM memories").fetchall()
        conn.executemany(
            "INSERT INTO memories_fts(id,title,content,tags,type,scope) VALUES (?,?,?,?,?,?)",
            [(r["id"], r["title"], r["content"], r["tags_json"], r["type"], r["scope"]) for r in rows],
        )
    conn.commit()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def add_memory_record(
    memory_type: str,
    title: str,
    content: str,
    scope: str = "global",
    tags: Any = None,
    source: str = "manual",
    source_agent: str = "agent",
    project_path: str = "",
    confidence: float = 0.70,
    importance: float = 0.50,
    status: str = "active",
    decay_policy: str = "review",
    related_ids: Any = None,
    metadata: Any = None,
    memory_id: str | None = None,
) -> dict[str, Any]:
    validate_type(memory_type)
    validate_status(status)
    if not title.strip() or not content.strip():
        raise ValueError("title and content are required")
    confidence_value = finite_float(confidence, "confidence", 0.0, 1.0)
    importance_value = finite_float(importance, "importance", 0.0, 1.0)
    memory_id = memory_id or str(uuid.uuid4())
    ts = now()
    with managed_conn() as conn:
        conn.execute(
            """
            INSERT INTO memories (
              id,type,scope,title,content,tags_json,source,source_agent,project_path,
              created_at,updated_at,confidence,importance,status,decay_policy,
              related_ids_json,metadata_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                memory_id,
                memory_type,
                scope or "global",
                title.strip(),
                content.strip(),
                as_json(normalize_list(tags)),
                source or "manual",
                source_agent or "unknown",
                project_path or "",
                ts,
                ts,
                confidence_value,
                importance_value,
                status,
                decay_policy or "review",
                as_json(normalize_list(related_ids)),
                as_json(metadata or {}),
            ),
        )
        row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
    return row_to_dict(row)


def update_memory_content(
    memory_id: str,
    new_content: str | None = None,
    new_title: str | None = None,
    new_status: str | None = None,
    new_confidence: float | None = None,
    new_importance: float | None = None,
) -> dict[str, Any]:
    """Update an existing memory record's content/title/status.

    Only provided (non-None) fields are updated. Returns updated row as dict.
    Used by the dedup pipeline to update existing memories in-place when
    new information refines an existing fact.
    """
    rows = _managed_query("SELECT id FROM memories WHERE id=? LIMIT 1", (memory_id,))
    if not rows:
        raise ValueError(f"Memory not found: {memory_id}")

    ts = now()
    updates: list[str] = ["updated_at=?"]
    params: list[Any] = [ts]

    if new_content is not None:
        updates.append("content=?")
        params.append(new_content.strip())
    if new_title is not None:
        updates.append("title=?")
        params.append(new_title.strip())
    if new_status is not None:
        validate_status(new_status)
        updates.append("status=?")
        params.append(new_status)
    if new_confidence is not None:
        confidence_value = finite_float(new_confidence, "confidence", 0.0, 1.0)
        updates.append("confidence=?")
        params.append(confidence_value)
    if new_importance is not None:
        importance_value = finite_float(new_importance, "importance", 0.0, 1.0)
        updates.append("importance=?")
        params.append(importance_value)

    params.append(memory_id)
    with managed_conn() as conn:
        conn.execute(
            f"UPDATE memories SET {', '.join(updates)} WHERE id=?",
            params,
        )
        row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
    return row_to_dict(row)


def search_memory_records(
    query: str = "",
    types: Any = None,
    scope: str = "",
    project_path: str = "",
    tags: Any = None,
    status: str = "active",
    limit: int = 10,
) -> list[dict[str, Any]]:
    types_list = normalize_list(types)
    tags_list = [t.lower() for t in normalize_list(tags)]
    clauses = []
    params: list[Any] = []
    base = "SELECT m.* FROM memories m"
    if query.strip():
        terms = re.findall(r"[\w\u4e00-\u9fff]+", query, flags=re.UNICODE)
        if not terms:
            return []
        base += " JOIN memories_fts f ON f.id = m.id"
        fts_query = " OR ".join(fts_phrase(term) for term in terms)
        clauses.append("memories_fts MATCH ?")
        params.append(fts_query)
    if types_list:
        clauses.append("m.type IN (%s)" % ",".join("?" for _ in types_list))
        params.extend(types_list)
    if scope:
        clauses.append("(m.scope = ? OR m.scope = 'global')")
        params.append(scope)
    if project_path:
        clauses.append("(m.project_path = ? OR m.project_path = '')")
        params.append(project_path)
    if tags_list:
        clauses.append(
            "EXISTS (SELECT 1 FROM json_each(m.tags_json) WHERE lower(json_each.value) IN (%s))"
            % ",".join("?" for _ in tags_list)
        )
        params.extend(tags_list)
    if status:
        clauses.append("m.status = ?")
        params.append(status)
    sql = base
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY m.importance DESC, m.effectiveness_score DESC, m.feedback_score DESC, m.updated_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 100)))
    with managed_conn() as conn:
        rows = [row_to_dict(r) for r in conn.execute(sql, params).fetchall()]
        if rows:
            conn.executemany(
                "UPDATE memories SET last_accessed_at=? WHERE id=?",
                [(now(), r["id"]) for r in rows],
            )
    return rows


_GREETINGS = {"hi", "hello", "hey", "你好", "嗯", "好", "继续", "ok", "okay", "yes", "no"}


def _is_greeting(task: str) -> bool:
    return task.strip().lower() in _GREETINGS


def build_context_pack(
    task: str,
    agent: str = "agent",
    project_path: str = "",
    scope: str = "global",
    token_budget: int = 2000,
) -> dict[str, Any]:
    max_chars = max(800, int(token_budget) * 4)
    records = search_memory_records(task, scope=scope, project_path=project_path, status="active", limit=40)
    if not records and len(task.strip()) > 10 and not _is_greeting(task):
        records = search_memory_records("", scope=scope, project_path=project_path, status="active", limit=20)
    groups_order = [
        "skill_candidate",
        "user_profile",
        "environment_fact",
        "agent_architecture",
        "project_memory",
        "decision",
        "timeline_event",
        "episodic_memory",
        "feedback",
    ]
    grouped: dict[str, list[dict[str, Any]]] = {k: [] for k in groups_order}
    for r in records:
        grouped.setdefault(r["type"], []).append(r)
    lines = [
        f"# memory_context for {agent}",
        f"task: {task}",
        f"scope: {scope}",
        f"project_path: {project_path or '(none)'}",
        f"safety: {BOUNDARY_NOTICE}",
        "",
    ]
    used_ids: list[str] = []
    filtered_ids: list[str] = []
    injection_warnings: list[dict[str, Any]] = []
    for group in groups_order:
        items = grouped.get(group) or []
        if not items:
            continue
        # episodic_memory: cap at 2, only positive feedback
        if group == "episodic_memory":
            items = [i for i in items if float(i.get("feedback_score", 0)) >= 0][:2]
            if not items:
                continue
        section = [f"## {group}"]
        section_used_ids: list[str] = []
        for item in items[:6]:
            check = check_memory_for_injection(item)
            if check.is_high_risk:
                filtered_ids.append(item["id"])
                injection_warnings.append(warning_for_filtered_memory(item, check))
                continue
            snippet = item["content"].replace("\n", " ")
            if len(snippet) > 420:
                snippet = snippet[:417] + "..."
            section.append(f"- [{item['id']}] {item['title']}: {snippet}")
            section_used_ids.append(item["id"])
        if len(section) == 1:
            continue
        candidate = "\n".join(lines + section) + "\n"
        if len(candidate) > max_chars:
            break
        lines.extend(section + [""])
        used_ids.extend(section_used_ids)
    text = "\n".join(lines).strip()
    # Record injection: bump injected_count and last_injected_at for used memories.
    if used_ids:
        ts = now()
        with managed_conn() as conn:
            for mid in used_ids:
                conn.execute(
                    """UPDATE memories
                       SET injected_count = injected_count + 1,
                           last_injected_at = ?,
                           last_accessed_at = ?
                       WHERE id = ?""",
                    (ts, ts, mid),
                )
    active_count = sum(1 for r in records if r["status"] == "active")
    warnings = (get_active_warnings(used_ids) if used_ids else []) + injection_warnings
    return {
        "context": text,
        "records": records,
        "used_ids": used_ids,
        "filtered_ids": filtered_ids,
        "warnings": warnings,
        "budget_chars": max_chars,
        "quality": {
            "total_candidates": len(records),
            "used_count": len(used_ids),
            "filtered_count": len(filtered_ids),
            "active_ratio": round(active_count / max(len(records), 1), 3),
            "avg_importance": round(sum(r["importance"] for r in records) / max(len(records), 1), 3),
            "stale_in_results": sum(1 for r in records if r["status"] == "stale"),
            "estimated_tokens": len(text) // 4,
        },
    }


def update_status(memory_id: str, status: str) -> dict[str, Any]:
    validate_status(status)
    with managed_conn() as conn:
        conn.execute("UPDATE memories SET status=?, updated_at=? WHERE id=?", (status, now(), memory_id))
        row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
    if row is None:
        raise ValueError(f"memory not found: {memory_id}")
    return row_to_dict(row)


def add_feedback(
    memory_id: str, score: float, note: str = "", source_agent: str = "agent"
) -> dict[str, Any]:
    score_value = finite_float(score, "score", -10.0, 10.0)
    event_id = str(uuid.uuid4())
    ts = now()
    with managed_conn() as conn:
        if conn.execute("SELECT 1 FROM memories WHERE id=?", (memory_id,)).fetchone() is None:
            raise ValueError(f"memory not found: {memory_id}")
        conn.execute(
            "INSERT INTO feedback_events(id,memory_id,score,note,source_agent,created_at) VALUES (?,?,?,?,?,?)",
            (event_id, memory_id, score_value, note or "", source_agent or "unknown", ts),
        )
        avg = (
            conn.execute("SELECT AVG(score) FROM feedback_events WHERE memory_id=?", (memory_id,)).fetchone()[0]
            or 0
        )
        # Update feedback_score and effectiveness tracking.
        # Positive score → memory was useful (injected_count++, effectiveness up).
        # Negative score → memory was not useful (ineffective_count++, effectiveness down).
        cur = conn.execute(
            "SELECT injected_count, ineffective_count, effectiveness_score FROM memories WHERE id=?",
            (memory_id,),
        ).fetchone()
        inj = int(cur[0] or 0)
        ineff = int(cur[1] or 0)
        eff = float(cur[2] or 0.5)
        if score_value > 0:
            inj += 1
            # Weighted moving average: pull effectiveness toward 1.0
            eff = min(1.0, eff + 0.05 * score_value)
        elif score_value < 0:
            ineff += 1
            # Pull effectiveness toward 0.0
            eff = max(0.0, eff + 0.05 * score_value)
        conn.execute(
            """UPDATE memories
               SET feedback_score=?, injected_count=?, ineffective_count=?,
                   effectiveness_score=?, updated_at=?
               WHERE id=?""",
            (float(avg), inj, ineff, round(eff, 4), ts, memory_id),
        )
        row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
    return {"feedback_id": event_id, "memory": row_to_dict(row)}


def list_recent(limit: int = 10, cap: int | None = None) -> list[dict[str, Any]]:
    limit_value = max(1, int(limit))
    if cap is not None:
        limit_value = min(limit_value, int(cap))
    with managed_conn() as conn:
        rows = conn.execute("SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?", (limit_value,)).fetchall()
    return [row_to_dict(r) for r in rows]


def get_record(memory_id: str) -> dict[str, Any] | None:
    with managed_conn() as conn:
        row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
    return row_to_dict(row) if row else None


def timeline(query: str = "", scope: str = "", limit: int = 20) -> list[dict[str, Any]]:
    rows = search_memory_records(query, types=["timeline_event", "decision", "feedback"], scope=scope, status="active", limit=limit)
    return sorted(rows, key=lambda r: r.get("created_at", ""))


def get_active_warnings(
    memory_ids: list[str],
    min_weight: float = 0.4,
    max_warnings: int = 5,
) -> list[dict[str, Any]]:
    """Query memory_links for contradicts/supersedes relations among given IDs.

    Returns severity-ranked warnings to surface in build_context_pack.
    """
    if not memory_ids:
        return []
    placeholders = ",".join("?" for _ in memory_ids)
    sql = f"""
        SELECT
            ml.source_id, ml.target_id, ml.relation_type, ml.weight, ml.note,
            ms.title AS source_title, ms.feedback_score AS source_fb,
            mt.title AS target_title, mt.feedback_score AS target_fb
        FROM memory_links ml
        JOIN memories ms ON ms.id = ml.source_id
        JOIN memories mt ON mt.id = ml.target_id
        WHERE (ml.source_id IN ({placeholders}) OR ml.target_id IN ({placeholders}))
          AND ml.relation_type IN ('contradicts', 'supersedes')
          AND ml.weight >= ?
          AND ms.status = 'active'
          AND mt.status = 'active'
        ORDER BY ml.weight DESC
        LIMIT ?
    """
    params = memory_ids + memory_ids + [min_weight, max_warnings * 2]
    rows = _managed_query(sql, params)

    warnings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        sig = f"{row['source_id']}→{row['target_id']}→{row['relation_type']}"
        if sig in seen:
            continue
        seen.add(sig)
        severity = "high" if float(row.get("weight") or 0) >= 0.7 else "medium"
        if float(row.get("target_fb") or 0) < -0.5:
            severity = "high"
        note_part = f" — {row['note']}" if row.get("note") else ""
        warnings.append({
            "source_id": row["source_id"],
            "target_id": row["target_id"],
            "relation_type": row["relation_type"],
            "severity": severity,
            "weight": row["weight"],
            "reason": (
                f"'{row['source_title']}' {row['relation_type']} "
                f"'{row['target_title']}'{note_part}"
            ),
        })

    warnings.sort(key=lambda w: (0 if w["severity"] == "high" else 1, -float(w["weight"])))
    return warnings[:max_warnings]


# ---------------------------------------------------------------------------
# memory_links
# ---------------------------------------------------------------------------


def add_link(
    source_id: str,
    target_id: str,
    relation_type: str = "related_to",
    weight: float = 1.0,
    note: str = "",
    source_agent: str = "unknown",
) -> dict[str, Any]:
    """Create a directed link between two memories. Upserts on (source, target, relation)."""
    if relation_type not in VALID_RELATION_TYPES:
        raise ValueError(f"relation_type must be one of {sorted(VALID_RELATION_TYPES)}, got {relation_type!r}")
    weight = max(0.0, min(float(weight), 1.0))
    link_id = str(uuid.uuid4())
    ts = now()
    with managed_conn() as conn:
        for mid in (source_id, target_id):
            if not conn.execute("SELECT 1 FROM memories WHERE id=?", (mid,)).fetchone():
                raise ValueError(f"memory id not found: {mid!r}")
        conn.execute(
            """
            INSERT INTO memory_links(id, source_id, target_id, relation_type, weight, note, created_at, source_agent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, target_id, relation_type) DO UPDATE SET
              weight=excluded.weight, note=excluded.note, source_agent=excluded.source_agent
            """,
            (link_id, source_id, target_id, relation_type, weight, note, ts, source_agent),
        )
        row = conn.execute(
            "SELECT * FROM memory_links WHERE source_id=? AND target_id=? AND relation_type=?",
            (source_id, target_id, relation_type),
        ).fetchone()
    return dict(row)


def query_links(
    memory_id: str,
    direction: str = "both",
    relation_type: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    direction = direction.lower()
    if direction not in ("outgoing", "incoming", "both"):
        raise ValueError("direction must be 'outgoing', 'incoming', or 'both'")
    limit = max(1, min(int(limit), 500))
    rel_filter = " AND relation_type=?" if relation_type else ""
    params_base = [relation_type] if relation_type else []

    with managed_conn() as conn:
        outgoing: list[dict] = []
        incoming: list[dict] = []

        if direction in ("outgoing", "both"):
            rows = conn.execute(
                f"SELECT * FROM memory_links WHERE source_id=?{rel_filter} ORDER BY created_at DESC LIMIT ?",
                [memory_id] + params_base + [limit],
            ).fetchall()
            outgoing = [dict(r) for r in rows]

        if direction in ("incoming", "both"):
            rows = conn.execute(
                f"SELECT * FROM memory_links WHERE target_id=?{rel_filter} ORDER BY created_at DESC LIMIT ?",
                [memory_id] + params_base + [limit],
            ).fetchall()
            incoming = [dict(r) for r in rows]

    return {
        "memory_id": memory_id,
        "outgoing": outgoing,
        "incoming": incoming,
        "total": len(outgoing) + len(incoming),
    }


# ---------------------------------------------------------------------------
# Curator
# ---------------------------------------------------------------------------


def consolidate(dry_run: bool = True, limit: int = 50) -> dict[str, Any]:
    rows = list_recent(limit)
    seen: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        key = normalize_title_key(r.get("title", ""))
        seen.setdefault(key, []).append(r)
    duplicates = [v for v in seen.values() if len(v) > 1]
    low_feedback = [r for r in rows if float(r.get("feedback_score", 0)) < -0.5]
    return {
        "dry_run": dry_run,
        "applied": False,
        "reason": "v0 consolidate is report-only; use memory_curator_report(dry_run=False) for low-risk lifecycle status changes",
        "duplicate_title_groups": duplicates,
        "low_feedback_candidates": low_feedback,
    }


def curator_report(
    dry_run: bool = True,
    limit: int = 500,
    stale_after_days: int = 60,
    archive_after_days: int = 120,
) -> dict[str, Any]:
    now_dt = datetime.now(timezone.utc)
    stale_cutoff = now_dt - timedelta(days=max(1, int(stale_after_days)))
    archive_cutoff = now_dt - timedelta(days=max(1, int(archive_after_days)))
    cap = max(1, min(int(limit), 5000))

    # Duplicate detection: full scan grouped by normalized title key
    all_rows = _managed_query("SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?", (cap,))
    by_title: dict[str, list[dict[str, Any]]] = {}
    for r in all_rows:
        by_title.setdefault(normalize_title_key(r.get("title", "")), []).append(r)
    duplicate_title_groups = [v for k, v in by_title.items() if k and len(v) > 1]

    # Low feedback: dedicated query, not list_recent
    low_feedback_candidates = _managed_query(
        "SELECT * FROM memories WHERE status IN ('active','candidate') AND feedback_score < -0.5 LIMIT ?",
        (cap,),
    )

    # Decay candidates: active, 90+ days unaccessed, low effectiveness
    decay_candidates = _managed_query(
        """SELECT * FROM memories
           WHERE status = 'active'
             AND (last_accessed_at IS NULL OR last_accessed_at < datetime('now', '-90 days'))
             AND effectiveness_score < 0.4
             AND importance < 0.6
           ORDER BY effectiveness_score ASC, last_accessed_at ASC LIMIT ?""",
        (cap,),
    )

    # Evolution candidates: content too short or very low feedback — suggest AI rewrite
    evolution_candidates = _managed_query(
        """SELECT * FROM memories
           WHERE status IN ('active','candidate')
             AND (LENGTH(content) < 50 OR feedback_score < -1.0)
           ORDER BY feedback_score ASC LIMIT ?""",
        (min(cap, 50),),
    )

    # Stale: dedicated query so oldest records are not truncated by list_recent ordering
    stale_candidates = _managed_query(
        """SELECT * FROM memories
           WHERE status IN ('active','candidate')
             AND updated_at < ?
             AND importance < 0.45
             AND feedback_score <= 0
           ORDER BY updated_at ASC LIMIT ?""",
        (stale_cutoff.isoformat(), cap),
    )

    # Archive: stale records past archive cutoff
    archive_candidates = _managed_query(
        "SELECT * FROM memories WHERE status = 'stale' AND updated_at < ? ORDER BY updated_at ASC LIMIT ?",
        (archive_cutoff.isoformat(), cap),
    )

    skill_promotion_candidates = _managed_query(
        """SELECT * FROM memories
           WHERE type = 'skill_candidate'
             AND status IN ('active','candidate')
             AND importance >= 0.65
             AND feedback_score >= 0
           LIMIT ?""",
        (cap,),
    )

    # Contradiction detection
    contradiction_candidates: list[dict[str, Any]] = []
    active_by_key: dict[str, list[dict[str, Any]]] = {}
    contradicted_by_key: dict[str, list[dict[str, Any]]] = {}
    for r in all_rows:
        key = normalize_title_key(r.get("title", ""))
        if not key:
            continue
        if r.get("status") == "active":
            active_by_key.setdefault(key, []).append(r)
        elif r.get("status") == "contradicted":
            contradicted_by_key.setdefault(key, []).append(r)
    for key, active_items in active_by_key.items():
        if key in contradicted_by_key:
            contradiction_candidates.append({
                "title_key": key,
                "active": active_items,
                "contradicted": contradicted_by_key[key],
            })

    actions: list[dict[str, Any]] = []
    if not dry_run:
        seen_ids: set[str] = set()
        for r in low_feedback_candidates + stale_candidates:
            if r["id"] not in seen_ids and r.get("status") != "stale":
                seen_ids.add(r["id"])
                update_status(r["id"], "stale")
                actions.append({"id": r["id"], "action": "mark_stale", "title": r.get("title")})
        for r in archive_candidates:
            update_status(r["id"], "archived")
            actions.append({"id": r["id"], "action": "archive", "title": r.get("title")})

    total_scanned = _managed_query("SELECT COUNT(*) as cnt FROM memories", ())[0]["cnt"]
    return {
        "dry_run": dry_run,
        "generated_at": now(),
        "scanned": total_scanned,
        "duplicate_title_groups": duplicate_title_groups,
        "low_feedback_candidates": low_feedback_candidates,
        "stale_candidates": stale_candidates,
        "archive_candidates": archive_candidates,
        "contradiction_candidates": contradiction_candidates,
        "skill_promotion_candidates": skill_promotion_candidates,
        "actions": actions,
        "summary": {
            "duplicates": len(duplicate_title_groups),
            "low_feedback": len(low_feedback_candidates),
            "stale": len(stale_candidates),
            "archive": len(archive_candidates),
            "contradictions": len(contradiction_candidates),
            "skill_promotions": len(skill_promotion_candidates),
            "actions": len(actions),
        },
    }


# ---------------------------------------------------------------------------
# HTML dashboard
# ---------------------------------------------------------------------------


def export_html(path: Path) -> None:
    rows = list_recent(1000)
    report = curator_report(dry_run=True, limit=1000)
    type_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    feedback_negative = 0
    feedback_positive = 0
    for r in rows:
        type_counts[r["type"]] = type_counts.get(r["type"], 0) + 1
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
        if float(r.get("feedback_score", 0) or 0) < 0:
            feedback_negative += 1
        if float(r.get("feedback_score", 0) or 0) > 0:
            feedback_positive += 1
    timeline_rows = [
        r for r in rows
        if r.get("type") in {"timeline_event", "decision", "feedback"}
    ][:80]
    payload = {
        "rows": rows,
        "report": report,
        "semantic": {"available": False, "note": "vector search via Qdrant (vector_store.py)"},
        "type_counts": type_counts,
        "status_counts": status_counts,
        "timeline_rows": timeline_rows,
    }
    data_json = json.dumps(payload, ensure_ascii=True).replace("<", "\\u003c")
    db_label = html.escape(str(db_path()))
    doc = _DASHBOARD_HTML_TEMPLATE()
    replacements = {
        "__DATA_JSON__": data_json,
        "__RECORD_COUNT__": str(len(rows)),
        "__TYPE_COUNT__": str(len(type_counts)),
        "__POSITIVE_FEEDBACK__": str(feedback_positive),
        "__NEGATIVE_FEEDBACK__": str(feedback_negative),
        "__DB_PATH__": db_label,
    }
    for key, value in replacements.items():
        doc = doc.replace(key, value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8")
    print(path)


def _DASHBOARD_HTML_TEMPLATE() -> str:
    """Return the self-contained Claude-inspired operations dashboard."""
    return """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Local Memory Console · Claude Theme</title>
<script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.14.8/dist/cdn.min.js"></script>
<style>
:root{
  --paper:#f7f1e8;--paper-2:#efe4d3;--paper-3:#e6d8c2;--ink:#2b2118;--ink-2:#4f4033;--muted:#7c6b5a;
  --panel:#fffaf1;--panel-2:#fbf3e7;--line:#dfcfb8;--line-2:#cdb99e;--accent:#d97757;--accent-2:#b85f45;
  --sage:#6f8068;--sage-soft:#e5eadf;--amber:#b7791f;--amber-soft:#f4e6c6;--bad:#a94735;--bad-soft:#f0d3ca;
  --violet:#7a5c8f;--violet-soft:#eadfed;--shadow:0 22px 65px rgba(69,45,23,.12);--radius:22px;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
*{box-sizing:border-box}[x-cloak]{display:none!important}html{background:var(--paper)}body{margin:0;min-height:100vh;color:var(--ink);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:radial-gradient(circle at 12% -4%,rgba(217,119,87,.20),transparent 30%),radial-gradient(circle at 88% 8%,rgba(111,128,104,.16),transparent 30%),linear-gradient(180deg,var(--paper),#f3eadc 48%,#efe3d1)}
body:before{content:"";position:fixed;inset:0;pointer-events:none;background-image:linear-gradient(rgba(43,33,24,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(43,33,24,.026) 1px,transparent 1px);background-size:34px 34px;mask-image:linear-gradient(180deg,rgba(0,0,0,.55),transparent 72%)}
a{color:var(--accent-2)}button,input,select{font:inherit}button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid rgba(217,119,87,.35);outline-offset:2px}.shell{position:relative;display:grid;grid-template-columns:300px minmax(0,1fr);min-height:100vh}.sidebar{position:sticky;top:0;height:100vh;padding:24px;border-right:1px solid var(--line);background:rgba(247,241,232,.78);backdrop-filter:blur(18px)}
.brand{display:grid;gap:10px;margin-bottom:28px}.mark{width:42px;height:42px;border-radius:15px;background:linear-gradient(135deg,var(--accent),#e6aa7b);box-shadow:inset 0 0 0 1px rgba(255,255,255,.35),0 12px 30px rgba(217,119,87,.22)}.eyebrow{color:var(--accent-2);font:800 11px/1 var(--mono);letter-spacing:.14em;text-transform:uppercase}.brand h1{margin:0;font-family:Georgia,"Times New Roman",serif;font-size:28px;line-height:1;letter-spacing:-.04em}.brand p{margin:0;color:var(--muted);font-size:13px;line-height:1.55;word-break:break-word}.nav{display:grid;gap:8px}.nav button{display:flex;align-items:center;justify-content:space-between;gap:12px;width:100%;min-height:46px;padding:11px 12px;border:1px solid transparent;border-radius:15px;background:transparent;color:var(--ink-2);cursor:pointer;text-align:left}.nav button:hover{background:rgba(255,250,241,.62);border-color:var(--line)}.nav button.active{background:var(--panel);border-color:var(--line-2);box-shadow:0 10px 28px rgba(69,45,23,.08);color:var(--ink)}.pill{display:inline-flex;align-items:center;justify-content:center;min-width:28px;padding:4px 8px;border-radius:999px;background:#f3e7d7;border:1px solid var(--line);color:var(--muted);font:800 11px/1 var(--mono)}
.side-card{margin-top:24px;padding:15px;border:1px solid var(--line);border-radius:18px;background:rgba(255,250,241,.64)}.side-card h2{margin:0 0 10px;font-size:13px}.side-card .row{display:flex;justify-content:space-between;gap:10px;padding:8px 0;border-top:1px solid rgba(223,207,184,.75);font-size:12px;color:var(--muted)}.side-card .row:first-of-type{border-top:0}.status-dot{width:9px;height:9px;border-radius:999px;background:var(--sage);box-shadow:0 0 0 5px rgba(111,128,104,.14)}.main{padding:28px clamp(20px,4vw,52px) 78px;min-width:0}.hero{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(280px,.75fr);gap:16px;margin-bottom:16px}.panel{border:1px solid var(--line);border-radius:var(--radius);background:linear-gradient(180deg,rgba(255,250,241,.88),rgba(251,243,231,.82));box-shadow:var(--shadow)}.hero-main{padding:30px}.hero-main h2{max-width:860px;margin:0 0 12px;font-family:Georgia,"Times New Roman",serif;font-size:clamp(34px,4.6vw,66px);line-height:.94;letter-spacing:-.07em}.hero-main p{max-width:800px;margin:0;color:var(--muted);line-height:1.75}.hero-aside{padding:20px;display:grid;gap:14px}.inline-status{display:flex;align-items:center;gap:11px;color:var(--ink-2)}
.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:16px 0}.metric{position:relative;overflow:hidden;padding:17px;border:1px solid var(--line);border-radius:18px;background:rgba(255,250,241,.72)}.metric:after{content:"";position:absolute;right:-28px;top:-32px;width:92px;height:92px;border-radius:999px;background:rgba(217,119,87,.10)}.metric b{display:block;font-family:Georgia,"Times New Roman",serif;font-size:33px;letter-spacing:-.05em}.metric span{display:block;margin-top:3px;color:var(--muted);font:800 11px/1 var(--mono);text-transform:uppercase;letter-spacing:.08em}.metric.good b{color:var(--sage)}.metric.bad b{color:var(--bad)}
.toolbar{position:sticky;top:12px;z-index:8;display:grid;grid-template-columns:minmax(240px,2fr) repeat(3,minmax(138px,1fr));gap:10px;padding:12px;margin:18px 0;border:1px solid var(--line);border-radius:18px;background:rgba(247,241,232,.82);backdrop-filter:blur(18px)}input,select{width:100%;min-height:44px;border:1px solid var(--line-2);border-radius:14px;background:rgba(255,250,241,.86);color:var(--ink);padding:10px 12px}select{cursor:pointer}.content-head{display:flex;align-items:end;justify-content:space-between;gap:14px;margin:26px 0 13px}.content-head h2{margin:0;font-family:Georgia,"Times New Roman",serif;font-size:28px;letter-spacing:-.04em}.content-head p{margin:4px 0 0;color:var(--muted);font-size:13px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}.record{padding:16px;border:1px solid var(--line);border-radius:18px;background:rgba(255,250,241,.78)}.record h3{margin:0 0 10px;font-size:16px;line-height:1.28}.record p{margin:11px 0;color:var(--ink-2);line-height:1.6;max-height:9.5em;overflow:auto}.meta{display:flex;gap:7px;flex-wrap:wrap;color:var(--muted);font-size:12px}.chip{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:999px;padding:5px 8px;background:#f7ead9;color:var(--ink-2);font-size:12px}.chip.type{color:var(--violet);background:var(--violet-soft)}.chip.active{color:var(--sage);background:var(--sage-soft)}.chip.archived,.chip.stale{color:var(--amber);background:var(--amber-soft)}.chip.contradicted{color:var(--bad);background:var(--bad-soft)}.record code{display:block;margin-top:10px;color:var(--muted);font-size:11px;word-break:break-all}.empty{padding:28px;border:1px dashed var(--line-2);border-radius:18px;color:var(--muted);text-align:center;background:rgba(255,250,241,.42)}
.timeline{position:relative;display:grid;gap:14px}.event{position:relative;padding:16px 16px 16px 46px;border:1px solid var(--line);border-radius:18px;background:rgba(255,250,241,.72)}.event:before{content:"";position:absolute;left:18px;top:23px;width:10px;height:10px;border-radius:999px;background:var(--accent);box-shadow:0 0 0 6px rgba(217,119,87,.13)}.event h3{margin:0 0 7px;font-size:16px}.event p{margin:9px 0 0;color:var(--ink-2);line-height:1.6}.bars{display:grid;gap:11px}.bar{display:grid;grid-template-columns:155px minmax(0,1fr) 48px;gap:10px;align-items:center}.bar span{color:var(--ink-2);font-size:13px;overflow:hidden;text-overflow:ellipsis}.track{height:11px;border:1px solid var(--line);border-radius:999px;background:#eadcc8;overflow:hidden}.fill{height:100%;border-radius:999px;background:linear-gradient(90deg,var(--accent),#e0a46f)}.split{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.curator-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}.curator-card{padding:16px;border:1px solid var(--line);border-radius:18px;background:rgba(255,250,241,.72)}.curator-card h3{display:flex;justify-content:space-between;gap:10px;margin:0 0 12px;font-size:15px}.curator-card p{margin:8px 0;color:var(--ink-2);line-height:1.42}.fallback{margin:12px 0;padding:12px;border:1px solid rgba(183,121,31,.35);border-radius:14px;color:var(--amber);background:rgba(244,230,198,.56)}
@media (max-width:980px){.shell{grid-template-columns:1fr}.sidebar{position:relative;height:auto}.nav{grid-template-columns:repeat(2,minmax(0,1fr))}.hero,.split{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.toolbar{position:relative;top:auto;grid-template-columns:1fr 1fr}}
@media (max-width:620px){.main,.sidebar{padding:16px}.toolbar,.metrics,.nav{grid-template-columns:1fr}.bar{grid-template-columns:1fr}.hero-main h2{font-size:38px}.grid{grid-template-columns:1fr}}
@media (prefers-reduced-motion:no-preference){.record,.panel,.curator-card,.event,.nav button{transition:transform .16s ease,border-color .16s ease,box-shadow .16s ease}.record:hover,.curator-card:hover{transform:translateY(-2px);border-color:var(--line-2)}}
@media print{body{background:white;color:#111}.sidebar,.toolbar{display:none}.shell{display:block}.panel,.record,.curator-card,.event{box-shadow:none;background:white;color:#111;break-inside:avoid}.main{padding:0}.chip{border-color:#bbb;color:#111}}
</style>
</head>
<body>
<div class="shell" x-data="memoryDashboard()" x-cloak>
  <aside class="sidebar">
    <div class="brand"><div class="mark" aria-hidden="true"></div><div class="eyebrow">Local Memory MCP</div><h1>Memory Console</h1><p>Claude-inspired warm operations view<br>SQLite/FTS5 &middot; __RECORD_COUNT__ records<br>__DB_PATH__</p></div>
    <nav class="nav" aria-label="Dashboard views">
      <button type="button" :class="{active:view==='records'}" @click="view='records'"><span>Records</span><span class="pill" x-text="filteredRows.length"></span></button>
      <button type="button" :class="{active:view==='timeline'}" @click="view='timeline'"><span>Timeline</span><span class="pill" x-text="timelineRows.length"></span></button>
      <button type="button" :class="{active:view==='health'}" @click="view='health'"><span>Health</span><span class="pill" x-text="Object.keys(typeCounts).length"></span></button>
      <button type="button" :class="{active:view==='curator'}" @click="view='curator'"><span>Curator</span><span class="pill" x-text="curatorTotal"></span></button>
    </nav>
    <div class="side-card"><h2>Runtime</h2><div class="row"><span>Semantic</span><strong x-text="semantic.available ? 'available' : 'offline'"></strong></div><div class="row"><span>Provider</span><strong x-text="semantic.provider || 'Qdrant optional'"></strong></div><div class="row"><span>Indexed</span><strong x-text="`${semantic.indexed_records || 0}/${semantic.total_records || 0}`"></strong></div></div>
  </aside>
  <main class="main">
    <noscript><div class="fallback">此 dashboard 需要 JavaScript 才能启用过滤、时间线和 curator 视图。</div></noscript>
    <div id="alpine-fallback" class="fallback">正在加载 Alpine.js；如果离线环境无法访问 CDN，静态 JSON 数据仍保留在页面中。</div>
    <section class="hero">
      <div class="panel hero-main"><div class="eyebrow">Structured agent memory</div><h2>把长期记忆变成可治理的本地数据层。</h2><p>面向 Hermes、Codex、Claude Code 的共享记忆控制台。Claude 风格的暖纸张、克制橙色和清晰信息密度，用来快速查看记录覆盖、反馈健康、curator 候选和时间线。</p></div>
      <div class="panel hero-aside"><div class="inline-status"><span class="status-dot"></span><strong>Local-only static export</strong></div><p style="margin:0;color:var(--muted);line-height:1.65">数据由 Python CLI 注入到页面 JSON；Alpine.js 只负责本地交互状态，不向外部发送记忆内容。</p><div><span class="chip">no build step</span> <span class="chip">Claude palette</span> <span class="chip">Alpine 3.14.8</span></div></div>
    </section>
    <section class="metrics" aria-label="Memory health metrics"><div class="metric"><b>__RECORD_COUNT__</b><span>records</span></div><div class="metric"><b>__TYPE_COUNT__</b><span>memory types</span></div><div class="metric good"><b>__POSITIVE_FEEDBACK__</b><span>positive feedback</span></div><div class="metric bad"><b>__NEGATIVE_FEEDBACK__</b><span>negative feedback</span></div></section>
    <section class="toolbar" aria-label="Record filters"><input x-model.debounce.120ms="query" type="search" placeholder="搜索 title / content / tags / id..." aria-label="Search records"><select x-model="typeFilter" aria-label="Filter by type"><option value="">全部类型</option><template x-for="type in typeOptions" :key="type"><option :value="type" x-text="type"></option></template></select><select x-model="statusFilter" aria-label="Filter by status"><option value="">全部状态</option><template x-for="status in statusOptions" :key="status"><option :value="status" x-text="status"></option></template></select><select x-model="sortBy" aria-label="Sort records"><option value="updated_at">按更新时间</option><option value="importance">按重要性</option><option value="feedback_score">按反馈</option><option value="type">按类型</option></select></section>
    <section x-show="view==='records'"><div class="content-head"><div><h2>Records <span class="pill" x-text="filteredRows.length"></span></h2><p>结构化长期记忆，支持搜索、类型、状态和排序。</p></div></div><div class="grid"><template x-for="record in filteredRows" :key="record.id"><article class="record"><h3 x-text="record.title"></h3><div class="meta"><span class="chip type" x-text="record.type"></span><span class="chip" :class="record.status" x-text="record.status"></span><span class="chip" x-text="`importance ${record.importance ?? 0}`"></span><span class="chip" x-text="`feedback ${record.feedback_score ?? 0}`"></span></div><p x-text="record.content"></p><div class="meta"><template x-for="tag in (record.tags || [])" :key="tag"><span class="chip" x-text="tag"></span></template></div><code x-text="record.id"></code></article></template></div><div class="empty" x-show="filteredRows.length === 0">无匹配记录</div></section>
    <section x-show="view==='timeline'"><div class="content-head"><div><h2>Decision timeline</h2><p>仅展示 timeline_event / decision / feedback 相关记录。</p></div></div><div class="timeline"><template x-for="event in timelineRows" :key="event.id"><article class="event"><h3 x-text="event.title"></h3><div class="meta"><span x-text="event.created_at"></span><span x-text="event.type"></span><span x-text="event.status"></span></div><p x-text="event.content"></p></article></template></div><div class="empty" x-show="timelineRows.length === 0">暂无 timeline / decision / feedback 记录</div></section>
    <section x-show="view==='health'"><div class="content-head"><div><h2>Feedback health</h2><p>分布视图帮助判断记忆库是否偏科、陈旧或反馈不足。</p></div></div><div class="split"><div class="panel" style="padding:18px"><h3>Type distribution</h3><div class="bars"><template x-for="item in bars(typeCounts)" :key="item.key"><div class="bar"><span x-text="item.key"></span><div class="track"><div class="fill" :style="`width:${item.width}%`"></div></div><strong x-text="item.value"></strong></div></template></div></div><div class="panel" style="padding:18px"><h3>Status distribution</h3><div class="bars"><template x-for="item in bars(statusCounts)" :key="item.key"><div class="bar"><span x-text="item.key"></span><div class="track"><div class="fill" :style="`width:${item.width}%`"></div></div><strong x-text="item.value"></strong></div></template></div></div></div></section>
    <section x-show="view==='curator'"><div class="content-head"><div><h2>Curator candidates</h2><p>面向去重、归档、矛盾检测和 skill 推广的候选摘要。</p></div></div><div class="curator-grid"><template x-for="group in curatorGroups" :key="group.key"><article class="curator-card"><h3><span x-text="group.label"></span><span class="pill" x-text="group.items.length"></span></h3><template x-for="item in group.items.slice(0, 12)" :key="itemKey(item)"><p x-text="itemLabel(item)"></p></template><p x-show="group.items.length === 0" style="color:var(--sage)">无</p></article></template></div></section>
  </main>
</div>
<script id="memory-data" type="application/json">__DATA_JSON__</script>
<script>
document.addEventListener('alpine:init', () => { document.getElementById('alpine-fallback')?.remove(); });
function memoryDashboard(){
  const data = JSON.parse(document.getElementById('memory-data').textContent);
  const rows = data.rows || [];
  const report = data.report || {};
  const semantic = data.semantic || {};
  const unique = (values) => [...new Set(values.filter(Boolean))].sort();
  return {
    data, rows, report, semantic, view:'records', query:'', typeFilter:'', statusFilter:'', sortBy:'updated_at',
    typeCounts: data.type_counts || {}, statusCounts: data.status_counts || {},
    get typeOptions(){ return unique(this.rows.map(r => r.type)); },
    get statusOptions(){ return unique(this.rows.map(r => r.status)); },
    get filteredRows(){ const q=this.query.trim().toLowerCase(); return this.rows.filter(r => { const hay=[r.id,r.type,r.status,r.title,r.content,(r.tags||[]).join(' ')].join(' ').toLowerCase(); return (!q || hay.includes(q)) && (!this.typeFilter || r.type===this.typeFilter) && (!this.statusFilter || r.status===this.statusFilter); }).sort((a,b)=>{ if(this.sortBy==='type') return String(a.type||'').localeCompare(String(b.type||'')); if(this.sortBy==='importance'||this.sortBy==='feedback_score') return Number(b[this.sortBy]||0)-Number(a[this.sortBy]||0); return String(b.updated_at||'').localeCompare(String(a.updated_at||'')); }); },
    get timelineRows(){ return (data.timeline_rows || []).slice().sort((a,b)=>String(a.created_at||'').localeCompare(String(b.created_at||''))); },
    get curatorGroups(){ return [['duplicate_title_groups','重复标题组'],['low_feedback_candidates','低反馈候选'],['stale_candidates','可标记 stale'],['archive_candidates','可归档'],['contradiction_candidates','矛盾候选'],['skill_promotion_candidates','skill_candidate 推广']].map(([key,label]) => ({key,label,items:report[key]||[]})); },
    get curatorTotal(){ return this.curatorGroups.reduce((n,g)=>n+g.items.length,0); },
    bars(counts){ const entries=Object.entries(counts).sort((a,b)=>b[1]-a[1]); const max=Math.max(1,...entries.map(([,v])=>Number(v)||0)); return entries.map(([key,value])=>({key,value,width:Math.round((Number(value)||0)/max*100)})); },
    itemLabel(item){ if(Array.isArray(item)) return item.map(x=>x.title || x.id || 'item').join(' / '); return item.title || item.title_key || item.id || JSON.stringify(item); },
    itemKey(item){ return Array.isArray(item) ? item.map(x=>x.id || x.title).join('|') : (item.id || item.title || item.title_key || JSON.stringify(item)); }
  };
}
</script>
</body></html>"""


# Internal helper: run a query without connection lifecycle in the caller
def _managed_query(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with managed_conn() as conn:
        return [row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


def get_memory_stats() -> dict[str, Any]:
    """Return aggregate statistics: type/status/agent distribution, avg scores, link count."""
    with managed_conn() as conn:
        type_dist = {r["type"]: r["cnt"] for r in conn.execute(
            "SELECT type, COUNT(*) as cnt FROM memories GROUP BY type"
        ).fetchall()}
        status_dist = {r["status"]: r["cnt"] for r in conn.execute(
            "SELECT status, COUNT(*) as cnt FROM memories GROUP BY status"
        ).fetchall()}
        agent_dist = {r["source_agent"]: r["cnt"] for r in conn.execute(
            "SELECT source_agent, COUNT(*) as cnt FROM memories GROUP BY source_agent"
        ).fetchall()}
        agg = conn.execute(
            "SELECT AVG(confidence) as avg_conf, AVG(importance) as avg_imp, "
            "AVG(feedback_score) as avg_fb, COUNT(*) as total FROM memories"
        ).fetchone()
        never_accessed = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE last_accessed_at IS NULL"
        ).fetchone()[0]
        link_count = conn.execute("SELECT COUNT(*) FROM memory_links").fetchone()[0]
    return {
        "total": agg["total"],
        "by_type": type_dist,
        "by_status": status_dist,
        "by_agent": agent_dist,
        "avg_confidence": round(float(agg["avg_conf"] or 0), 3),
        "avg_importance": round(float(agg["avg_imp"] or 0), 3),
        "avg_feedback_score": round(float(agg["avg_fb"] or 0), 3),
        "never_accessed_count": never_accessed,
        "link_count": link_count,
    }
