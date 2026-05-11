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
import hashlib
import math
import textwrap
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

try:
    import numpy as np
    import sqlite_vec
    SQLITE_VEC_AVAILABLE = True
except Exception:
    np = None
    sqlite_vec = None
    SQLITE_VEC_AVAILABLE = False

DEFAULT_ROOT = Path(__file__).resolve().parent
DEFAULT_DB = Path(os.environ.get("LOCAL_MEMORY_DB", Path.home() / ".agent-memory" / "local-memory-mcp" / "memory.sqlite3"))
_INITIALIZED_DB_PATHS: set[str] = set()

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


def db_path() -> Path:
    path = Path(os.environ.get("LOCAL_MEMORY_DB", str(DEFAULT_DB))).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect() -> sqlite3.Connection:
    """Open a SQLite connection and ensure the schema exists for its DB path.

    Kept as a public helper for external scripts. Internal code should prefer
    managed_conn() so connections are explicitly closed.
    """
    global SQLITE_VEC_AVAILABLE
    path = db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    if SQLITE_VEC_AVAILABLE:
        try:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
        except Exception:
            # Vector search is optional. Keep core SQLite/FTS memory tools alive
            # if the extension is installed but cannot be loaded at runtime.
            SQLITE_VEC_AVAILABLE = False
        finally:
            try:
                conn.enable_load_extension(False)
            except Exception:
                pass
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
    if SQLITE_VEC_AVAILABLE:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory_embedding_index (
              rowid INTEGER PRIMARY KEY AUTOINCREMENT,
              memory_id TEXT NOT NULL UNIQUE,
              provider TEXT NOT NULL DEFAULT 'hashing',
              model TEXT NOT NULL DEFAULT 'hashing-384',
              dim INTEGER NOT NULL DEFAULT 384,
              updated_at TEXT NOT NULL,
              FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_vec USING vec0(embedding float[384]);
            """
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


SEMANTIC_DIM = 384
SEMANTIC_PROVIDER = "hashing"
SEMANTIC_MODEL = "hashing-384"


def semantic_available() -> bool:
    return bool(SQLITE_VEC_AVAILABLE and np is not None)


def embed_text_hashing(text: str, dim: int = SEMANTIC_DIM) -> bytes:
    """Deterministic local embedding fallback.

    This is a lightweight hashed bag-of-words vector. It is not a deep semantic
    model, but it exercises the sqlite-vec plumbing locally and gives a better
    fuzzy recall fallback than exact FTS when no Ollama/sentence model is
    available. Future providers can replace only this embedding function while
    keeping the same vector index/query surface.
    """
    if np is None:
        raise RuntimeError("numpy is required for semantic hashing embeddings")
    vec = np.zeros(dim, dtype=np.float32)
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", text.lower(), flags=re.UNICODE)
    for tok in tokens:
        digest = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "little") % dim
        sign = 1.0 if digest[4] & 1 else -1.0
        vec[bucket] += sign
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec /= norm
    return vec.astype(np.float32).tobytes()


def semantic_index(limit: int = 1000, force: bool = False) -> dict[str, Any]:
    if not semantic_available():
        return {"available": False, "reason": "sqlite-vec/numpy not available", "indexed": 0, "skipped": 0}
    indexed = 0
    skipped = 0
    with managed_conn() as conn:
        rows = conn.execute(
            """
            SELECT m.* FROM memories m
            LEFT JOIN memory_embedding_index e ON e.memory_id = m.id
            WHERE (? OR e.memory_id IS NULL OR e.updated_at < m.updated_at)
            ORDER BY m.updated_at DESC LIMIT ?
            """,
            (1 if force else 0, max(1, min(int(limit), 5000))),
        ).fetchall()
        for row in rows:
            r = row_to_dict(row)
            text = f"{r['type']} {r['scope']} {r['title']} {' '.join(r.get('tags', []))}\n{r['content']}"
            emb = embed_text_hashing(text)
            existing = conn.execute("SELECT rowid FROM memory_embedding_index WHERE memory_id=?", (r["id"],)).fetchone()
            ts = now()
            if existing:
                rid = int(existing["rowid"])
                conn.execute("UPDATE memory_vec SET embedding=? WHERE rowid=?", (emb, rid))
                conn.execute(
                    "UPDATE memory_embedding_index SET provider=?, model=?, dim=?, updated_at=? WHERE memory_id=?",
                    (SEMANTIC_PROVIDER, SEMANTIC_MODEL, SEMANTIC_DIM, ts, r["id"]),
                )
            else:
                cur = conn.execute(
                    "INSERT INTO memory_embedding_index(memory_id,provider,model,dim,updated_at) VALUES (?,?,?,?,?)",
                    (r["id"], SEMANTIC_PROVIDER, SEMANTIC_MODEL, SEMANTIC_DIM, ts),
                )
                rid = int(cur.lastrowid)
                conn.execute("INSERT INTO memory_vec(rowid, embedding) VALUES (?, ?)", (rid, emb))
            indexed += 1
    return {"available": True, "provider": SEMANTIC_PROVIDER, "model": SEMANTIC_MODEL, "dim": SEMANTIC_DIM, "indexed": indexed, "skipped": skipped}


def semantic_search(query: str, limit: int = 10, status: str = "active") -> list[dict[str, Any]]:
    if not semantic_available():
        return []
    semantic_index(limit=1000, force=False)
    emb = embed_text_hashing(query)
    with managed_conn() as conn:
        rows = conn.execute(
            """
            SELECT m.*, v.distance AS semantic_distance
            FROM memory_vec v
            JOIN memory_embedding_index e ON e.rowid = v.rowid
            JOIN memories m ON m.id = e.memory_id
            WHERE v.embedding MATCH ? AND k = ? AND (? = '' OR m.status = ?)
            ORDER BY v.distance
            """,
            (emb, max(1, min(int(limit), 100)), status or "", status or ""),
        ).fetchall()
    out = []
    for row in rows:
        d = row_to_dict(row)
        d["semantic_distance"] = float(row["semantic_distance"])
        out.append(d)
    return out


def semantic_status() -> dict[str, Any]:
    with managed_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        indexed = 0
        if semantic_available():
            indexed = conn.execute("SELECT COUNT(*) FROM memory_embedding_index").fetchone()[0]
    return {
        "available": semantic_available(),
        "provider": SEMANTIC_PROVIDER if semantic_available() else None,
        "model": SEMANTIC_MODEL if semantic_available() else None,
        "dim": SEMANTIC_DIM if semantic_available() else None,
        "total_records": total,
        "indexed_records": indexed,
        "note": "hashing fallback is local/vector plumbing, not a deep embedding model; switch provider to Ollama/sentence-transformers later when available",
    }


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


@mcp.tool()
def memory_semantic_status() -> dict[str, Any]:
    """Return local vector/semantic index status."""
    return semantic_status()


@mcp.tool()
def memory_semantic_index(limit: int = 1000, force: bool = False) -> dict[str, Any]:
    """Build/update the local sqlite-vec memory vector index."""
    return semantic_index(limit, force)


@mcp.tool()
def memory_semantic_search(query: str, limit: int = 10, status: str = "active") -> list[dict[str, Any]]:
    """Search memories through the local sqlite-vec vector index."""
    return semantic_search(query, limit, status)


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
        "semantic": semantic_status(),
        "type_counts": type_counts,
        "status_counts": status_counts,
        "timeline_rows": timeline_rows,
    }
    data_json = json.dumps(payload, ensure_ascii=True).replace("<", "\\u003c")
    doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Local Memory MCP Dashboard</title>
<style>
:root{{--bg:#07111f;--panel:#0f1b2e;--panel2:#13223a;--text:#e6edf3;--muted:#9aa4b2;--line:#28405f;--accent:#7dd3fc;--good:#86efac;--warn:#fbbf24;--bad:#fb7185;--violet:#c4b5fd;}}
*{{box-sizing:border-box}} body{{margin:0;background:radial-gradient(circle at 20% 0%,#162a4a,#07111f 42%,#050912);color:var(--text);font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;}}
header{{position:sticky;top:0;z-index:10;background:rgba(7,17,31,.88);backdrop-filter:blur(14px);border-bottom:1px solid var(--line);padding:18px clamp(16px,4vw,36px)}}
h1{{margin:0;font-size:clamp(24px,3vw,36px)}} .sub{{color:var(--muted);margin-top:6px}} main{{max-width:1320px;margin:auto;padding:26px clamp(16px,4vw,36px) 80px}}
.hero{{display:grid;grid-template-columns:1.4fr .8fr;gap:18px;align-items:stretch}} .card,.panel{{background:linear-gradient(180deg,rgba(19,34,58,.86),rgba(15,27,46,.76));border:1px solid var(--line);border-radius:20px;padding:18px;box-shadow:0 14px 40px rgba(0,0,0,.22)}}
.metrics{{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:12px;margin:18px 0}} .metric{{padding:16px;border-radius:16px;background:rgba(125,211,252,.08);border:1px solid rgba(125,211,252,.22)}} .metric b{{display:block;font-size:26px}} .metric span{{color:var(--muted);font-size:13px}}
.controls{{display:grid;grid-template-columns:2fr repeat(3,1fr);gap:10px;margin:18px 0;position:sticky;top:86px;z-index:8;background:rgba(7,17,31,.82);backdrop-filter:blur(10px);padding:12px;border:1px solid var(--line);border-radius:18px}} input,select,button{{background:#09182a;color:var(--text);border:1px solid var(--line);border-radius:12px;padding:10px 12px}} button{{cursor:pointer}} button:hover{{border-color:var(--accent)}}
.tabs{{display:flex;gap:10px;flex-wrap:wrap;margin:20px 0}} .tab{{border-radius:999px}} .tab.active{{background:var(--accent);color:#03101f;border-color:var(--accent)}}
.view{{display:none}} .view.active{{display:block}} .records{{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px}} article{{border:1px solid var(--line);border-radius:16px;padding:14px;background:rgba(15,27,46,.66)}} article h3{{margin:0 0 8px;font-size:17px}} article p{{line-height:1.55;color:#d7dee8;max-height:9.2em;overflow:auto}} .meta{{color:var(--muted);font-size:12px;display:flex;gap:8px;flex-wrap:wrap}} .chip,.tags span{{display:inline-flex;border:1px solid var(--line);border-radius:999px;padding:3px 8px;margin:6px 6px 0 0;color:var(--violet);font-size:12px}} code{{display:block;color:var(--good);font-size:12px;margin-top:8px;word-break:break-all}}
.timeline{{position:relative;margin-left:8px}} .timeline:before{{content:"";position:absolute;left:12px;top:0;bottom:0;width:2px;background:var(--line)}} .event{{position:relative;margin:0 0 14px 34px}} .event:before{{content:"";position:absolute;left:-28px;top:8px;width:12px;height:12px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 5px rgba(125,211,252,.12)}}
.bars{{display:grid;gap:10px}} .bar{{display:grid;grid-template-columns:150px 1fr 44px;gap:10px;align-items:center}} .track{{height:10px;background:#09182a;border-radius:999px;overflow:hidden;border:1px solid var(--line)}} .fill{{height:100%;background:linear-gradient(90deg,var(--accent),var(--violet))}} .curator-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}} .warn{{color:var(--warn)}} .bad{{color:var(--bad)}} .good{{color:var(--good)}}
@media (max-width:800px){{.hero{{grid-template-columns:1fr}}.metrics{{grid-template-columns:repeat(2,1fr)}}.controls{{position:static;grid-template-columns:1fr}}}}
@media print{{header,.controls,.tabs{{display:none}} body{{background:white;color:#111}} .card,.panel,article{{break-inside:avoid;border-color:#ccc;background:white;color:#111}}}}
</style>
</head>
<body>
<header><h1>Local Memory MCP Dashboard</h1><div class="sub">SQLite/FTS5 · {len(rows)} records · {html.escape(str(db_path()))}</div></header>
<main>
  <section class="hero">
    <div class="card"><h2>记忆层健康总览</h2><p>这是本地/自托管多 agent 共享记忆层的可视化面板：支持记录过滤、时间线视图、反馈健康报告、curator 候选项检查。数据来自本地 SQLite，不依赖云端托管。</p></div>
    <div class="card"><h2>Curator 摘要</h2><div id="curatorSummary"></div><h2>Semantic</h2><div id="semanticSummary"></div></div>
  </section>
  <section class="metrics">
    <div class="metric"><b>{len(rows)}</b><span>records</span></div>
    <div class="metric"><b>{len(type_counts)}</b><span>memory types</span></div>
    <div class="metric"><b>{feedback_positive}</b><span>positive feedback</span></div>
    <div class="metric"><b>{feedback_negative}</b><span>negative feedback</span></div>
  </section>
  <section class="controls">
    <input id="q" placeholder="搜索 title/content/tags/id...">
    <select id="typeFilter"><option value="">全部类型</option></select>
    <select id="statusFilter"><option value="">全部状态</option></select>
    <select id="sortBy"><option value="updated_at">按更新时间</option><option value="importance">按重要性</option><option value="feedback_score">按反馈</option><option value="type">按类型</option></select>
  </section>
  <nav class="tabs"><button class="tab active" data-view="recordsView">Records</button><button class="tab" data-view="timelineView">Timeline</button><button class="tab" data-view="healthView">Feedback Health</button><button class="tab" data-view="curatorView">Curator</button></nav>
  <section id="recordsView" class="view active panel"><h2>Records <span id="count"></span></h2><div id="records" class="records"></div></section>
  <section id="timelineView" class="view panel"><h2>决策 / 时间线</h2><div id="timeline" class="timeline"></div></section>
  <section id="healthView" class="view panel"><h2>反馈健康报告</h2><div class="curator-grid"><div><h3>Type distribution</h3><div id="typeBars" class="bars"></div></div><div><h3>Status distribution</h3><div id="statusBars" class="bars"></div></div></div></section>
  <section id="curatorView" class="view panel"><h2>Curator candidates</h2><div id="curator" class="curator-grid"></div></section>
</main>
<script id="memory-data" type="application/json">{data_json}</script>
<script>
const DATA = JSON.parse(document.getElementById('memory-data').textContent);
const rows = DATA.rows || [];
const $ = (id) => document.getElementById(id);
function esc(s) {{ return String(s ?? '').replace(/[&<>"']/g, m => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[m])); }}
function fillSelect(id, values) {{ const el=$(id); [...values].sort().forEach(v=>{{ const o=document.createElement('option'); o.value=v; o.textContent=v; el.appendChild(o); }}); }}
fillSelect('typeFilter', new Set(rows.map(r=>r.type))); fillSelect('statusFilter', new Set(rows.map(r=>r.status)));
function renderBars(target, counts) {{ const max=Math.max(1,...Object.values(counts)); $(target).innerHTML=Object.entries(counts).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`<div class="bar"><span>${{esc(k)}}</span><div class="track"><div class="fill" style="width:${{Math.round(v/max*100)}}%"></div></div><b>${{v}}</b></div>`).join(''); }}
function filtered() {{ const q=$('q').value.toLowerCase(); const typ=$('typeFilter').value; const st=$('statusFilter').value; const sort=$('sortBy').value; return rows.filter(r=>{{ const hay=[r.id,r.type,r.status,r.title,r.content,(r.tags||[]).join(' ')].join(' ').toLowerCase(); return (!q||hay.includes(q)) && (!typ||r.type===typ) && (!st||r.status===st); }}).sort((a,b)=>{{ if(sort==='type') return String(a.type).localeCompare(String(b.type)); if(sort==='importance'||sort==='feedback_score') return Number(b[sort]||0)-Number(a[sort]||0); return String(b.updated_at||'').localeCompare(String(a.updated_at||'')); }}); }}
function renderRecords() {{ const items=filtered(); $('count').textContent=`(${{items.length}})`; $('records').innerHTML=items.map(r=>`<article><h3>${{esc(r.title)}}</h3><div class="meta"><span>${{esc(r.type)}}</span><span>${{esc(r.status)}}</span><span>importance ${{esc(r.importance)}}</span><span>feedback ${{esc(r.feedback_score)}}</span></div><p>${{esc(r.content)}}</p><div class="tags">${{(r.tags||[]).map(t=>`<span>${{esc(t)}}</span>`).join('')}}</div><code>${{esc(r.id)}}</code></article>`).join('') || '<p class="warn">无匹配记录</p>'; }}
function renderTimeline() {{ const items=(DATA.timeline_rows||[]).slice().sort((a,b)=>String(a.created_at||'').localeCompare(String(b.created_at||''))); $('timeline').innerHTML=items.map(r=>`<div class="event"><h3>${{esc(r.title)}}</h3><div class="meta">${{esc(r.created_at)}} · ${{esc(r.type)}} · ${{esc(r.status)}}</div><p>${{esc(r.content)}}</p></div>`).join('') || '<p class="warn">暂无 timeline/decision/feedback 记录</p>'; }}
function renderCurator() {{ const r=DATA.report||{{}}; const sem=DATA.semantic||{{}}; const groups=[['duplicate_title_groups','重复标题组'],['low_feedback_candidates','低反馈候选'],['stale_candidates','可标记 stale'],['archive_candidates','可归档'],['contradiction_candidates','矛盾候选'],['skill_promotion_candidates','skill_candidate 推广']]; $('curatorSummary').innerHTML=Object.entries(r.summary||{{}}).map(([k,v])=>`<span class="chip">${{esc(k)}}: ${{v}}</span>`).join(''); $('semanticSummary').innerHTML=`<span class="chip">available: ${{esc(sem.available)}}</span><span class="chip">provider: ${{esc(sem.provider||'none')}}</span><span class="chip">indexed: ${{esc(sem.indexed_records||0)}}/${{esc(sem.total_records||0)}}</span>`; $('curator').innerHTML=groups.map(([key,label])=>{{ const arr=r[key]||[]; return `<div class="card"><h3>${{label}} <span class="chip">${{arr.length}}</span></h3>${{arr.slice(0,12).map(x=>Array.isArray(x)?`<p>${{x.map(i=>esc(i.title)).join(' / ')}}</p>`:`<p>${{esc(x.title||x.title_key||x.id)}}</p>`).join('') || '<p class="good">无</p>'}}</div>`; }}).join(''); }}
document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{{ document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active')); document.querySelectorAll('.view').forEach(v=>v.classList.remove('active')); btn.classList.add('active'); $(btn.dataset.view).classList.add('active'); }}));
['q','typeFilter','statusFilter','sortBy'].forEach(id=>$(id).addEventListener('input',renderRecords));
renderRecords(); renderTimeline(); renderBars('typeBars', DATA.type_counts||{{}}); renderBars('statusBars', DATA.status_counts||{{}}); renderCurator();
</script>
</body></html>"""
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
    elif args.cmd == "semantic-status":
        print(json.dumps(semantic_status(), ensure_ascii=False, indent=2))
    elif args.cmd == "semantic-index":
        print(json.dumps(semantic_index(limit=args.limit, force=args.force), ensure_ascii=False, indent=2))
    elif args.cmd == "semantic-search":
        print(json.dumps(semantic_search(args.query, limit=args.limit, status=args.status), ensure_ascii=False, indent=2))
    elif args.cmd == "html":
        export_html(Path(args.out))
    elif args.cmd == "serve":
        mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
