#!/usr/bin/env python3
"""Local/self-hosted memory MCP v0 for multi-agent shared memory.

Design goal: structured SQLite + FTS5 memory layer with a compact `memory_context`
retrieval surface for Hermes, Codex, Claude Code, and other agents.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sqlite3
import sys
import math
import textwrap
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

SQLITE_VEC_AVAILABLE = False  # removed; vector search now via vector_store.py (Qdrant)

DEFAULT_ROOT = Path(__file__).resolve().parent
DEFAULT_DB = Path(os.environ.get("LOCAL_MEMORY_DB", Path.home() / ".agent-memory" / "local-memory-mcp" / "memory.sqlite3"))
_INITIALIZED_DB_PATHS: set[str] = set()

DEFAULT_CONFIG: dict[str, Any] = {
    "backend": {"primary": "sqlite", "fallback": "sqlite"},
    "openmemory": {"url": "http://127.0.0.1:8765", "user_id": "local-user", "timeout": 30},
    "qdrant": {"url": "http://127.0.0.1:6333", "collection": "agent_memory", "timeout": 30},
    "embedding": {
        "provider": "ollama",
        "model": "nomic-embed-text",
        "dim": 768,
        "ollama_url": "http://127.0.0.1:11434",
        "timeout": 30,
    },
    "context_pack": {"default_token_budget": 2000, "include_stale_warnings": True, "max_records_per_group": 6},
    "temporal": {"enabled": False, "contradiction_detection": "heuristic", "auto_supersede_user_corrections": True},
    "ops_db": {"path": str(DEFAULT_ROOT / "memory_ops.sqlite3")},
}

MEMORY_TYPES = {
    "user_profile",
    "environment_fact",
    "agent_architecture",
    "project_memory",
    "episodic_memory",
    "timeline_event",
    "decision",
    "feedback",
    "skill_candidate",
    "raw_event",
}
STATUSES = {"active", "stale", "archived", "contradicted", "promoted", "candidate"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def as_json(value: Any) -> str:
    if value is None:
        value = []
    return json.dumps(value, ensure_ascii=False)


def from_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def config_path() -> Path:
    return Path(os.environ.get("LOCAL_MEMORY_CONFIG", str(DEFAULT_ROOT / "config.yaml"))).expanduser()


def _parse_yaml_scalar(value: str) -> Any:
    raw = value.strip()
    lowered = raw.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none", "~"}:
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    return raw


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """Parse the small nested config.yaml subset used by this adapter.

    This intentionally avoids adding PyYAML as a runtime dependency. Supported
    syntax is enough for config.yaml: top-level sections with two-space indented
    scalar key/value pairs.
    """
    data: dict[str, Any] = {}
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" ") and stripped.endswith(":"):
            section = stripped[:-1].strip()
            current = data.setdefault(section, {})
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        target = current if line.startswith(" ") and current is not None else data
        target[key.strip()] = _parse_yaml_scalar(value)
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key, value in base.items():
        if isinstance(value, dict):
            merged[key] = _deep_merge(value, {})
        else:
            merged[key] = value
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        config = _deep_merge(DEFAULT_CONFIG, {})
    else:
        config = _deep_merge(DEFAULT_CONFIG, _parse_simple_yaml(path.read_text(encoding="utf-8")))
    openmemory = config.setdefault("openmemory", {})
    if openmemory.get("user_id") == "local-user" and os.environ.get("USER"):
        openmemory["user_id"] = os.environ["USER"]
    return config


def db_path() -> Path:
    path = Path(os.environ.get("LOCAL_MEMORY_DB", str(DEFAULT_DB))).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect() -> sqlite3.Connection:
    """Open a SQLite connection and ensure the schema exists for its DB path.

    Kept as a public helper for external scripts. Internal code should prefer
    managed_conn() so connections are explicitly closed.
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
          metadata_json TEXT NOT NULL DEFAULT '{}'
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


def normalize_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        # Accept JSON list or comma-separated text.
        v = value.strip()
        if v.startswith("["):
            try:
                parsed = json.loads(v)
                return [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                pass
        return [x.strip() for x in v.split(",") if x.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(x).strip() for x in value if str(x).strip()]
    return [str(value).strip()]


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["tags"] = from_json(d.pop("tags_json", "[]"), [])
    d["related_ids"] = from_json(d.pop("related_ids_json", "[]"), [])
    d["metadata"] = from_json(d.pop("metadata_json", "{}"), {})
    return d


def validate_type(memory_type: str) -> str:
    if memory_type not in MEMORY_TYPES:
        raise ValueError(f"type must be one of {sorted(MEMORY_TYPES)}")
    return memory_type


def validate_status(status: str) -> str:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {sorted(STATUSES)}")
    return status


def finite_float(value: Any, name: str, min_value: float | None = None, max_value: float | None = None) -> float:
    try:
        x = float(value)
    except Exception as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(x):
        raise ValueError(f"{name} must be finite")
    if min_value is not None and x < min_value:
        raise ValueError(f"{name} must be >= {min_value}")
    if max_value is not None and x > max_value:
        raise ValueError(f"{name} must be <= {max_value}")
    return x


def fts_phrase(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def add_memory_record(
    memory_type: str,
    title: str,
    content: str,
    scope: str = "global",
    tags: Any = None,
    source: str = "manual",
    source_agent: str = "hermes",
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
        # FTS MATCH is brittle with punctuation/operators. Tokenize to safe
        # word-ish terms, quote each term as a phrase so reserved words like
        # OR/NOT are searched literally, and return no matches for punctuation-
        # only queries instead of passing malformed raw syntax to FTS5.
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
        clauses.append("EXISTS (SELECT 1 FROM json_each(m.tags_json) WHERE lower(json_each.value) IN (%s))" % ",".join("?" for _ in tags_list))
        params.extend(tags_list)
    if status:
        clauses.append("m.status = ?")
        params.append(status)
    sql = base
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY m.importance DESC, m.feedback_score DESC, m.updated_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 100)))
    with managed_conn() as conn:
        rows = [row_to_dict(r) for r in conn.execute(sql, params).fetchall()]
        if rows:
            conn.executemany("UPDATE memories SET last_accessed_at=? WHERE id=?", [(now(), r["id"]) for r in rows])
    return rows


def build_context_pack(task: str, agent: str = "hermes", project_path: str = "", scope: str = "global", token_budget: int = 2000) -> dict[str, Any]:
    # Retrieve broadly, then group. Approximate budget by chars = tokens*4.
    max_chars = max(800, int(token_budget) * 4)
    records = search_memory_records(task, scope=scope, project_path=project_path, status="active", limit=40)
    if not records:
        records = search_memory_records("", scope=scope, project_path=project_path, status="active", limit=20)
    groups_order = [
        "user_profile",
        "environment_fact",
        "agent_architecture",
        "project_memory",
        "decision",
        "timeline_event",
        "skill_candidate",
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
        "",
    ]
    used_ids: list[str] = []
    for group in groups_order:
        items = grouped.get(group) or []
        if not items:
            continue
        section = [f"## {group}"]
        for item in items[:6]:
            snippet = item["content"].replace("\n", " ")
            if len(snippet) > 420:
                snippet = snippet[:417] + "..."
            section.append(f"- [{item['id']}] {item['title']}: {snippet}")
            used_ids.append(item["id"])
        candidate = "\n".join(lines + section) + "\n"
        if len(candidate) > max_chars:
            break
        lines.extend(section + [""])
    text = "\n".join(lines).strip()
    return {"context": text, "records": records, "used_ids": used_ids, "budget_chars": max_chars}


def update_status(memory_id: str, status: str) -> dict[str, Any]:
    validate_status(status)
    with managed_conn() as conn:
        conn.execute("UPDATE memories SET status=?, updated_at=? WHERE id=?", (status, now(), memory_id))
        row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
    if row is None:
        raise ValueError(f"memory not found: {memory_id}")
    return row_to_dict(row)


def add_feedback(memory_id: str, score: float, note: str = "", source_agent: str = "hermes") -> dict[str, Any]:
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
        avg = conn.execute("SELECT AVG(score) FROM feedback_events WHERE memory_id=?", (memory_id,)).fetchone()[0] or 0
        conn.execute("UPDATE memories SET feedback_score=?, updated_at=? WHERE id=?", (float(avg), ts, memory_id))
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




def consolidate(dry_run: bool = True, limit: int = 50) -> dict[str, Any]:
    # v0 heuristic: duplicate-ish titles and stale candidates. No destructive action unless future version.
    rows = list_recent(limit)
    seen: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        key = " ".join(r["title"].lower().split())[:80]
        seen.setdefault(key, []).append(r)
    duplicates = [v for v in seen.values() if len(v) > 1]
    low_feedback = [r for r in rows if float(r.get("feedback_score", 0)) < -0.5]
    return {"dry_run": dry_run, "applied": False, "reason": "v0 consolidate is report-only; use memory_curator_report(dry_run=False) for low-risk lifecycle status changes", "duplicate_title_groups": duplicates, "low_feedback_candidates": low_feedback}


def parse_ts(value: str | None) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return datetime.fromtimestamp(0, timezone.utc)


def normalize_title_key(title: str) -> str:
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", (title or "").lower(), flags=re.UNICODE)
    return " ".join(tokens)[:120]


def curator_report(
    dry_run: bool = True,
    limit: int = 500,
    stale_after_days: int = 60,
    archive_after_days: int = 120,
) -> dict[str, Any]:
    """Heuristic curator report for local memory maintenance.

    Safe defaults:
    - dry_run=True only reports candidates.
    - dry_run=False only changes status for low-risk lifecycle transitions:
      active/candidate -> stale, stale -> archived. It does NOT delete records
      and does NOT auto-create skills from skill_candidate memories.
    """
    rows = list_recent(limit)
    now_dt = datetime.now(timezone.utc)
    stale_cutoff = now_dt - timedelta(days=max(1, int(stale_after_days)))
    archive_cutoff = now_dt - timedelta(days=max(1, int(archive_after_days)))

    by_title: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_title.setdefault(normalize_title_key(r.get("title", "")), []).append(r)
    duplicate_title_groups = [v for k, v in by_title.items() if k and len(v) > 1]

    low_feedback_candidates = [
        r for r in rows
        if r.get("status") in {"active", "candidate"}
        and float(r.get("feedback_score", 0) or 0) < -0.5
    ]
    stale_candidates = [
        r for r in rows
        if r.get("status") in {"active", "candidate"}
        and parse_ts(r.get("updated_at")) < stale_cutoff
        and float(r.get("importance", 0) or 0) < 0.45
        and float(r.get("feedback_score", 0) or 0) <= 0
    ]
    archive_candidates = [
        r for r in rows
        if r.get("status") == "stale"
        and parse_ts(r.get("updated_at")) < archive_cutoff
    ]
    skill_promotion_candidates = [
        r for r in rows
        if r.get("type") == "skill_candidate"
        and r.get("status") in {"active", "candidate"}
        and float(r.get("importance", 0) or 0) >= 0.65
        and float(r.get("feedback_score", 0) or 0) >= 0
    ]

    contradiction_candidates: list[dict[str, Any]] = []
    active_by_key: dict[str, list[dict[str, Any]]] = {}
    contradicted_by_key: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
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
        for r in {item["id"]: item for item in (low_feedback_candidates + stale_candidates)}.values():
            if r.get("status") != "stale":
                update_status(r["id"], "stale")
                actions.append({"id": r["id"], "action": "mark_stale", "title": r.get("title")})
        for r in archive_candidates:
            update_status(r["id"], "archived")
            actions.append({"id": r["id"], "action": "archive", "title": r.get("title")})

    return {
        "dry_run": dry_run,
        "generated_at": now(),
        "scanned": len(rows),
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


mcp = FastMCP("local-memory-mcp")


@mcp.tool()
def memory_add(
    type: str,
    title: str,
    content: str,
    scope: str = "global",
    tags: list[str] | str | None = None,
    source: str = "manual",
    source_agent: str = "hermes",
    project_path: str = "",
    confidence: float = 0.70,
    importance: float = 0.50,
    status: str = "active",
    decay_policy: str = "review",
    related_ids: list[str] | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add a structured memory record to local SQLite memory."""
    return add_memory_record(type, title, content, scope, tags, source, source_agent, project_path, confidence, importance, status, decay_policy, related_ids, metadata)


@mcp.tool()
def memory_search(query: str = "", types: list[str] | str | None = None, scope: str = "", project_path: str = "", tags: list[str] | str | None = None, status: str = "active", limit: int = 10) -> list[dict[str, Any]]:
    """Search structured memory with SQLite FTS5 plus filters."""
    return search_memory_records(query, types, scope, project_path, tags, status, limit)


@mcp.tool()
def memory_context(task: str, agent: str = "hermes", project_path: str = "", scope: str = "global", token_budget: int = 2000) -> dict[str, Any]:
    """Return a compact context pack for a task, grouped by memory class."""
    return build_context_pack(task, agent, project_path, scope, token_budget)


@mcp.tool()
def memory_get(id: str) -> dict[str, Any] | None:
    """Get one memory record by id."""
    return get_record(id)


@mcp.tool()
def memory_list_recent(limit: int = 10) -> list[dict[str, Any]]:
    """List recently updated memory records."""
    return list_recent(limit, cap=100)


@mcp.tool()
def memory_update_status(id: str, status: str) -> dict[str, Any]:
    """Mark a memory active/stale/archived/contradicted/promoted/candidate."""
    return update_status(id, status)


@mcp.tool()
def memory_feedback(id: str, score: float, note: str = "", source_agent: str = "hermes") -> dict[str, Any]:
    """Record whether a retrieved memory helped. Score can be negative or positive."""
    return add_feedback(id, score, note, source_agent)


@mcp.tool()
def memory_timeline(query: str = "", scope: str = "", limit: int = 20) -> list[dict[str, Any]]:
    """Return decision/timeline/feedback memories in chronological order."""
    return timeline(query, scope, limit)


@mcp.tool()
def memory_consolidate(dry_run: bool = True, limit: int = 50) -> dict[str, Any]:
    """Curator helper: detect duplicate/stale candidates. v0 is dry-run oriented."""
    return consolidate(dry_run, limit)


@mcp.tool()
def memory_curator_report(dry_run: bool = True, limit: int = 500, stale_after_days: int = 60, archive_after_days: int = 120) -> dict[str, Any]:
    """Return memory curator candidates; optionally mark stale/archive records without deleting."""
    return curator_report(dry_run, limit, stale_after_days, archive_after_days)


# ─── New unified tools (extraction.py + vector_store.py + dedup.py) ──────────

@mcp.tool()
def memory_ingest(
    messages: list[dict[str, str]],
    user_id: str = "advancer",
    agent_id: str = "hermes",
) -> dict[str, Any]:
    """Extract facts from a conversation and write deduplicated candidates to SQLite.

    Full pipeline: DeepSeek LLM extraction → Qdrant dedup → SQLite candidate.

    Args:
        messages: Conversation as [{"role": "user"|"assistant", "content": "..."}]
        user_id: User scope for vector search filters
        agent_id: Which agent produced the conversation

    Returns:
        {"added": int, "updated": int, "skipped": int, "errors": int, "elapsed_s": float}
    """
    from dedup import ingest
    result = ingest(messages, user_id=user_id, agent_id=agent_id, cfg=load_config())
    return {
        "added": result.added,
        "updated": result.updated,
        "skipped": result.skipped,
        "errors": result.errors,
        "elapsed_s": result.elapsed_s,
        "extraction_elapsed_s": result.extraction_elapsed_s,
    }


@mcp.tool()
def memory_vector_search(
    query: str,
    top_k: int = 10,
    score_threshold: float = 0.0,
) -> list[dict[str, Any]]:
    """Semantic search via Qdrant vector store (nomic-embed-text embeddings).

    Args:
        query: Natural language search query
        top_k: Maximum results to return
        score_threshold: Minimum cosine similarity (0.0 = no filter)

    Returns:
        List of {"id", "score", "text", "payload"} dicts, sorted by score desc.
    """
    from vector_store import get_vector_store
    vs = get_vector_store(load_config())
    results = vs.search(query, top_k=top_k, score_threshold=score_threshold)
    return [
        {"id": r.id, "score": round(r.score, 4), "text": r.text, "payload": r.payload}
        for r in results
    ]


@mcp.tool()
def memory_vector_status() -> dict[str, Any]:
    """Return Qdrant vector store status (availability, collection, count)."""
    from vector_store import get_vector_store
    vs = get_vector_store(load_config())
    return vs.status()

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
    doc = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Local Memory Operations Console</title>
<script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.14.8/dist/cdn.min.js"></script>
<style>
:root{--bg:#0b0d10;--bg2:#11151b;--panel:#151a21;--panel2:#10141a;--ink:#f3f4f6;--muted:#9ca3af;--soft:#cbd5e1;--line:#2a313b;--line2:#3b4451;--accent:#7dd3fc;--accent2:#a7f3d0;--warn:#fbbf24;--bad:#fb7185;--good:#86efac;--violet:#c4b5fd;--shadow:0 18px 55px rgba(0,0,0,.28);--radius:18px}
*{box-sizing:border-box} [x-cloak]{display:none!important}
html{background:var(--bg)} body{margin:0;min-height:100vh;color:var(--ink);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:linear-gradient(180deg,#0b0d10 0%,#0f141b 55%,#0b0d10 100%)}
body:before{content:"";position:fixed;inset:0;pointer-events:none;background:radial-gradient(circle at 10% 0%,rgba(125,211,252,.12),transparent 34%),radial-gradient(circle at 90% 10%,rgba(167,243,208,.08),transparent 30%);opacity:.95}
a{color:var(--accent)} button,input,select{font:inherit} button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.shell{position:relative;display:grid;grid-template-columns:280px minmax(0,1fr);min-height:100vh}.sidebar{position:sticky;top:0;height:100vh;padding:22px;border-right:1px solid var(--line);background:rgba(11,13,16,.84);backdrop-filter:blur(18px)}
.brand{display:grid;gap:7px;margin-bottom:28px}.eyebrow{color:var(--accent2);font:700 11px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.16em;text-transform:uppercase}.brand h1{margin:0;font-size:24px;letter-spacing:-.04em}.brand p{margin:0;color:var(--muted);font-size:13px;line-height:1.5;word-break:break-word}
.nav{display:grid;gap:8px}.nav button{display:flex;align-items:center;justify-content:space-between;gap:12px;width:100%;min-height:44px;padding:10px 12px;border:1px solid transparent;border-radius:12px;background:transparent;color:var(--soft);cursor:pointer;text-align:left}.nav button:hover{background:#131922;border-color:var(--line)}.nav button.active{background:#17212c;border-color:#335167;color:var(--ink)}.pill{display:inline-flex;align-items:center;justify-content:center;min-width:28px;padding:3px 8px;border-radius:999px;background:#0e141b;border:1px solid var(--line);color:var(--muted);font:700 11px/1 ui-monospace,SFMono-Regular,Menlo,monospace}
.side-card{margin-top:24px;padding:14px;border:1px solid var(--line);border-radius:16px;background:rgba(21,26,33,.72)}.side-card h2{margin:0 0 10px;font-size:13px;color:var(--soft)}.side-card .row{display:flex;justify-content:space-between;gap:10px;padding:7px 0;border-top:1px solid rgba(42,49,59,.6);font-size:12px;color:var(--muted)}.side-card .row:first-of-type{border-top:0}.status-dot{width:8px;height:8px;border-radius:999px;background:var(--good);box-shadow:0 0 0 4px rgba(134,239,172,.12)}
.main{padding:26px clamp(18px,4vw,44px) 70px;min-width:0}.hero{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(280px,.7fr);gap:18px;margin-bottom:18px}.panel{border:1px solid var(--line);border-radius:var(--radius);background:linear-gradient(180deg,rgba(21,26,33,.94),rgba(16,20,26,.92));box-shadow:var(--shadow)}.hero-main{padding:26px}.hero-main h2{margin:0 0 10px;font-size:clamp(30px,4vw,54px);line-height:.98;letter-spacing:-.07em}.hero-main p{max-width:760px;margin:0;color:var(--muted);line-height:1.7}.hero-aside{padding:18px;display:grid;gap:12px}.inline-status{display:flex;align-items:center;gap:10px;color:var(--soft)}
.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:18px 0}.metric{padding:16px;border:1px solid var(--line);border-radius:16px;background:rgba(21,26,33,.72)}.metric b{display:block;font-size:28px;letter-spacing:-.04em}.metric span{display:block;margin-top:4px;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}.metric.good b{color:var(--good)}.metric.bad b{color:var(--bad)}
.toolbar{position:sticky;top:12px;z-index:8;display:grid;grid-template-columns:minmax(220px,2fr) repeat(3,minmax(130px,1fr));gap:10px;padding:12px;margin:18px 0;border:1px solid var(--line);border-radius:16px;background:rgba(11,13,16,.82);backdrop-filter:blur(18px)}input,select{width:100%;min-height:42px;border:1px solid var(--line2);border-radius:12px;background:#0b1016;color:var(--ink);padding:9px 12px}select{cursor:pointer}.content-head{display:flex;align-items:end;justify-content:space-between;gap:14px;margin:24px 0 12px}.content-head h2{margin:0;font-size:22px;letter-spacing:-.03em}.content-head p{margin:4px 0 0;color:var(--muted);font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:14px}.record{padding:15px;border:1px solid var(--line);border-radius:16px;background:rgba(21,26,33,.78)}.record h3{margin:0 0 9px;font-size:16px;line-height:1.25}.record p{margin:10px 0;color:#d8dee7;line-height:1.58;max-height:9.5em;overflow:auto}.meta{display:flex;gap:7px;flex-wrap:wrap;color:var(--muted);font-size:12px}.chip{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:999px;padding:4px 8px;background:#0d1218;color:var(--soft);font-size:12px}.chip.type{color:var(--violet)}.chip.active{color:var(--good)}.chip.archived,.chip.stale{color:var(--warn)}.chip.contradicted{color:var(--bad)}.record code{display:block;margin-top:10px;color:var(--muted);font-size:11px;word-break:break-all}.empty{padding:28px;border:1px dashed var(--line2);border-radius:16px;color:var(--muted);text-align:center}
.timeline{position:relative;display:grid;gap:14px}.event{position:relative;padding:15px 16px 15px 44px;border:1px solid var(--line);border-radius:16px;background:rgba(21,26,33,.7)}.event:before{content:"";position:absolute;left:18px;top:22px;width:10px;height:10px;border-radius:999px;background:var(--accent);box-shadow:0 0 0 5px rgba(125,211,252,.11)}.event h3{margin:0 0 7px;font-size:16px}.event p{margin:9px 0 0;color:#d8dee7;line-height:1.6}.bars{display:grid;gap:10px}.bar{display:grid;grid-template-columns:150px minmax(0,1fr) 48px;gap:10px;align-items:center}.bar span{color:var(--soft);font-size:13px;overflow:hidden;text-overflow:ellipsis}.track{height:10px;border:1px solid var(--line);border-radius:999px;background:#0a0f15;overflow:hidden}.fill{height:100%;border-radius:999px;background:linear-gradient(90deg,var(--accent),var(--accent2))}.split{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.curator-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px}.curator-card{padding:15px;border:1px solid var(--line);border-radius:16px;background:rgba(21,26,33,.72)}.curator-card h3{display:flex;justify-content:space-between;gap:10px;margin:0 0 12px;font-size:15px}.curator-card p{margin:8px 0;color:var(--soft);line-height:1.4}.fallback{margin:12px 0;padding:12px;border:1px solid rgba(251,191,36,.35);border-radius:12px;color:var(--warn);background:rgba(251,191,36,.08)}
@media (max-width:980px){.shell{grid-template-columns:1fr}.sidebar{position:relative;height:auto}.nav{grid-template-columns:repeat(2,minmax(0,1fr))}.hero,.split{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.toolbar{position:relative;top:auto;grid-template-columns:1fr 1fr}}
@media (max-width:620px){.main,.sidebar{padding:16px}.toolbar,.metrics,.nav{grid-template-columns:1fr}.bar{grid-template-columns:1fr}.hero-main h2{font-size:34px}}
@media (prefers-reduced-motion:no-preference){.record,.panel,.curator-card,.event{transition:transform .16s ease,border-color .16s ease}.record:hover,.curator-card:hover{transform:translateY(-2px);border-color:#3f5367}}
@media print{body{background:white;color:#111}.sidebar,.toolbar{display:none}.shell{display:block}.panel,.record,.curator-card,.event{box-shadow:none;background:white;color:#111;break-inside:avoid}.main{padding:0}.chip{border-color:#bbb;color:#111}}
</style>
</head>
<body>
<div class="shell" x-data="memoryDashboard()" x-cloak>
  <aside class="sidebar">
    <div class="brand"><div class="eyebrow">Local Memory MCP</div><h1>Operations Console</h1><p>SQLite/FTS5 · __RECORD_COUNT__ records<br>__DB_PATH__</p></div>
    <nav class="nav" aria-label="Dashboard views">
      <button type="button" :class="{active:view==='records'}" @click="view='records'"><span>Records</span><span class="pill" x-text="filteredRows.length"></span></button>
      <button type="button" :class="{active:view==='timeline'}" @click="view='timeline'"><span>Timeline</span><span class="pill" x-text="timelineRows.length"></span></button>
      <button type="button" :class="{active:view==='health'}" @click="view='health'"><span>Health</span><span class="pill" x-text="Object.keys(typeCounts).length"></span></button>
      <button type="button" :class="{active:view==='curator'}" @click="view='curator'"><span>Curator</span><span class="pill" x-text="curatorTotal"></span></button>
    </nav>
    <div class="side-card">
      <h2>Runtime</h2>
      <div class="row"><span>Semantic</span><strong x-text="semantic.available ? 'available' : 'offline'"></strong></div>
      <div class="row"><span>Provider</span><strong x-text="semantic.provider || 'none'"></strong></div>
      <div class="row"><span>Indexed</span><strong x-text="`${semantic.indexed_records || 0}/${semantic.total_records || 0}`"></strong></div>
    </div>
  </aside>
  <main class="main">
    <noscript><div class="fallback">此 dashboard 需要 JavaScript 才能启用过滤、时间线和 curator 视图。</div></noscript>
    <div id="alpine-fallback" class="fallback">正在加载 Alpine.js；如果离线环境无法访问 CDN，静态 JSON 数据仍保留在页面中。</div>
    <section class="hero">
      <div class="panel hero-main"><div class="eyebrow">Structured agent memory</div><h2>把长期记忆变成可治理的本地数据层。</h2><p>面向 Hermes、Codex、Claude Code 的共享记忆控制台。重点展示可行动信号：记录覆盖、反馈健康、curator 候选、时间线和语义索引状态。</p></div>
      <div class="panel hero-aside"><div class="inline-status"><span class="status-dot"></span><strong>Local-only dashboard</strong></div><p style="margin:0;color:var(--muted);line-height:1.6">数据由 Python CLI 注入到页面 JSON；Alpine.js 只负责本地交互状态，不向外部发送记忆内容。</p><div><span class="chip">no build step</span> <span class="chip">Alpine 3.14.8</span></div></div>
    </section>
    <section class="metrics" aria-label="Memory health metrics">
      <div class="metric"><b>__RECORD_COUNT__</b><span>records</span></div>
      <div class="metric"><b>__TYPE_COUNT__</b><span>memory types</span></div>
      <div class="metric good"><b>__POSITIVE_FEEDBACK__</b><span>positive feedback</span></div>
      <div class="metric bad"><b>__NEGATIVE_FEEDBACK__</b><span>negative feedback</span></div>
    </section>
    <section class="toolbar" aria-label="Record filters">
      <input x-model.debounce.120ms="query" type="search" placeholder="搜索 title / content / tags / id..." aria-label="Search records">
      <select x-model="typeFilter" aria-label="Filter by type"><option value="">全部类型</option><template x-for="type in typeOptions" :key="type"><option :value="type" x-text="type"></option></template></select>
      <select x-model="statusFilter" aria-label="Filter by status"><option value="">全部状态</option><template x-for="status in statusOptions" :key="status"><option :value="status" x-text="status"></option></template></select>
      <select x-model="sortBy" aria-label="Sort records"><option value="updated_at">按更新时间</option><option value="importance">按重要性</option><option value="feedback_score">按反馈</option><option value="type">按类型</option></select>
    </section>
    <section x-show="view==='records'">
      <div class="content-head"><div><h2>Records <span class="pill" x-text="filteredRows.length"></span></h2><p>结构化长期记忆，支持搜索、类型、状态和排序。</p></div></div>
      <div class="grid"><template x-for="record in filteredRows" :key="record.id"><article class="record"><h3 x-text="record.title"></h3><div class="meta"><span class="chip type" x-text="record.type"></span><span class="chip" :class="record.status" x-text="record.status"></span><span class="chip" x-text="`importance ${record.importance ?? 0}`"></span><span class="chip" x-text="`feedback ${record.feedback_score ?? 0}`"></span></div><p x-text="record.content"></p><div class="meta"><template x-for="tag in (record.tags || [])" :key="tag"><span class="chip" x-text="tag"></span></template></div><code x-text="record.id"></code></article></template></div>
      <div class="empty" x-show="filteredRows.length === 0">无匹配记录</div>
    </section>
    <section x-show="view==='timeline'">
      <div class="content-head"><div><h2>Decision timeline</h2><p>仅展示 timeline_event / decision / feedback 相关记录。</p></div></div>
      <div class="timeline"><template x-for="event in timelineRows" :key="event.id"><article class="event"><h3 x-text="event.title"></h3><div class="meta"><span x-text="event.created_at"></span><span x-text="event.type"></span><span x-text="event.status"></span></div><p x-text="event.content"></p></article></template></div>
      <div class="empty" x-show="timelineRows.length === 0">暂无 timeline / decision / feedback 记录</div>
    </section>
    <section x-show="view==='health'">
      <div class="content-head"><div><h2>Feedback health</h2><p>分布视图帮助判断记忆库是否偏科、陈旧或反馈不足。</p></div></div>
      <div class="split"><div class="panel" style="padding:16px"><h3>Type distribution</h3><div class="bars"><template x-for="item in bars(typeCounts)" :key="item.key"><div class="bar"><span x-text="item.key"></span><div class="track"><div class="fill" :style="`width:${item.width}%`"></div></div><strong x-text="item.value"></strong></div></template></div></div><div class="panel" style="padding:16px"><h3>Status distribution</h3><div class="bars"><template x-for="item in bars(statusCounts)" :key="item.key"><div class="bar"><span x-text="item.key"></span><div class="track"><div class="fill" :style="`width:${item.width}%`"></div></div><strong x-text="item.value"></strong></div></template></div></div></div>
    </section>
    <section x-show="view==='curator'">
      <div class="content-head"><div><h2>Curator candidates</h2><p>面向去重、归档、矛盾检测和 skill 推广的候选摘要。</p></div></div>
      <div class="curator-grid"><template x-for="group in curatorGroups" :key="group.key"><article class="curator-card"><h3><span x-text="group.label"></span><span class="pill" x-text="group.items.length"></span></h3><template x-for="item in group.items.slice(0, 12)" :key="itemKey(item)"><p x-text="itemLabel(item)"></p></template><p x-show="group.items.length === 0" style="color:var(--good)">无</p></article></template></div>
    </section>
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="local-memory-mcp server and CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    p_add = sub.add_parser("add")
    p_add.add_argument("type")
    p_add.add_argument("title")
    p_add.add_argument("content")
    p_add.add_argument("--scope", default="global")
    p_add.add_argument("--tags", default="")
    p_add.add_argument("--source", default="manual")
    p_add.add_argument("--source-agent", default="hermes")
    p_add.add_argument("--importance", type=float, default=0.5)
    p_search = sub.add_parser("search")
    p_search.add_argument("query", nargs="?", default="")
    p_search.add_argument("--type", dest="types", action="append")
    p_search.add_argument("--limit", type=int, default=10)
    p_ctx = sub.add_parser("context")
    p_ctx.add_argument("task")
    p_ctx.add_argument("--agent", default="hermes")
    p_ctx.add_argument("--scope", default="global")
    p_ctx.add_argument("--project-path", default="")
    p_ctx.add_argument("--budget", type=int, default=2000)
    p_curator = sub.add_parser("curator")
    p_curator.add_argument("--apply", action="store_true", help="mark low-risk stale/archive transitions")
    p_curator.add_argument("--limit", type=int, default=500)
    p_curator.add_argument("--stale-after-days", type=int, default=60)
    p_curator.add_argument("--archive-after-days", type=int, default=120)
    p_curator.add_argument("--summary-only", action="store_true")
    p_sem_index = sub.add_parser("semantic-index")
    p_sem_index.add_argument("--limit", type=int, default=1000)
    p_sem_index.add_argument("--force", action="store_true")
    p_sem_search = sub.add_parser("semantic-search")
    p_sem_search.add_argument("query")
    p_sem_search.add_argument("--limit", type=int, default=10)
    p_sem_search.add_argument("--status", default="active")
    sub.add_parser("semantic-status")
    p_html = sub.add_parser("html")
    p_html.add_argument("out", nargs="?", default=str(DEFAULT_ROOT / "dashboard.html"))
    sub.add_parser("serve")
    args = parser.parse_args(argv)
    if args.cmd == "init":
        with managed_conn():
            pass
        print(db_path())
    elif args.cmd == "add":
        print(json.dumps(add_memory_record(args.type, args.title, args.content, scope=args.scope, tags=args.tags, source=args.source, source_agent=args.source_agent, importance=args.importance), ensure_ascii=False, indent=2))
    elif args.cmd == "search":
        print(json.dumps(search_memory_records(args.query, types=args.types, limit=args.limit), ensure_ascii=False, indent=2))
    elif args.cmd == "context":
        print(build_context_pack(args.task, args.agent, project_path=args.project_path, scope=args.scope, token_budget=args.budget)["context"])
    elif args.cmd == "curator":
        report = curator_report(
            dry_run=not args.apply,
            limit=args.limit,
            stale_after_days=args.stale_after_days,
            archive_after_days=args.archive_after_days,
        )
        payload = report["summary"] if args.summary_only else report
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.cmd in ("semantic-status", "semantic-index", "semantic-search"):
        print(json.dumps({"error": "sqlite-vec removed; use memory_vector_search / memory_vector_status MCP tools"}, indent=2))
    elif args.cmd == "html":
        export_html(Path(args.out))
    elif args.cmd == "serve":
        mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
