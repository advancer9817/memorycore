"""SQLite connection management and schema initialisation."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any

from memorycore.models import (
    _INITIALIZED_DB_PATHS,
    db_path,
    now,
    row_to_dict,
)

logger = logging.getLogger(__name__)
_thread_local = threading.local()
_LOCK_RETRY_ATTEMPTS = 10
_LOCK_RETRY_DELAY = 0.1
_write_lock = threading.RLock()


def _get_thread_conn(path) -> sqlite3.Connection:
    """Return a thread-local SQLite connection, creating it if needed."""
    key = str(path.resolve())
    cache: dict = getattr(_thread_local, "conns", None)
    if cache is None:
        _thread_local.conns = {}
        cache = _thread_local.conns
    if key not in cache:
        conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=500")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        if key not in _INITIALIZED_DB_PATHS:
            init_db(conn)
            _INITIALIZED_DB_PATHS.add(key)
        cache[key] = conn
    return cache[key]


def connect() -> sqlite3.Connection:
    """Return the thread-local SQLite connection for the configured DB path."""
    return _get_thread_conn(db_path())


@contextmanager
def managed_conn():
    with _write_lock:
        conn = connect()
        try:
            yield conn
            _commit_with_retry(conn)
        except Exception:
            conn.rollback()
            raise


def _commit_with_retry(conn: sqlite3.Connection) -> None:
    for attempt in range(_LOCK_RETRY_ATTEMPTS):
        try:
            conn.commit()
            return
        except sqlite3.OperationalError as exc:
            if "database is locked" not in str(exc) or attempt >= _LOCK_RETRY_ATTEMPTS - 1:
                raise
            logger.warning("db locked on commit, retrying (%d/%d)", attempt + 1, _LOCK_RETRY_ATTEMPTS)
            time.sleep(_LOCK_RETRY_DELAY * (attempt + 1))


def _managed_query(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with managed_conn() as conn:
        return [row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


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
          last_injected_at TEXT,
          valid_from TEXT,
          valid_until TEXT
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

        CREATE TABLE IF NOT EXISTS memory_entities (
          id TEXT PRIMARY KEY,
          memory_id TEXT NOT NULL,
          entity TEXT NOT NULL,
          normalized_entity TEXT NOT NULL,
          aliases_json TEXT NOT NULL DEFAULT '[]',
          entity_type TEXT NOT NULL DEFAULT 'concept',
          weight REAL NOT NULL DEFAULT 1.0,
          created_at TEXT NOT NULL,
          FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_memory_entities_memory ON memory_entities(memory_id);
        CREATE INDEX IF NOT EXISTS idx_memory_entities_norm ON memory_entities(normalized_entity);
        CREATE INDEX IF NOT EXISTS idx_memory_entities_type ON memory_entities(entity_type);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_entities_unique ON memory_entities(memory_id, normalized_entity);

        CREATE TABLE IF NOT EXISTS audit_events (
          id TEXT PRIMARY KEY,
          event_type TEXT NOT NULL,
          memory_id TEXT,
          agent TEXT NOT NULL DEFAULT 'unknown',
          detail_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_audit_memory ON audit_events(memory_id);
        CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_events(event_type);
        CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at);

        CREATE TABLE IF NOT EXISTS agent_messages (
          id TEXT PRIMARY KEY,
          from_agent TEXT NOT NULL,
          to_agent TEXT NOT NULL,
          subject TEXT NOT NULL,
          body TEXT NOT NULL DEFAULT '',
          priority TEXT NOT NULL DEFAULT 'normal',
          status TEXT NOT NULL DEFAULT 'unread',
          created_at TEXT NOT NULL,
          read_at TEXT,
          metadata_json TEXT NOT NULL DEFAULT '{}',
          expires_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_agent_msg_to ON agent_messages(to_agent, status);
        CREATE INDEX IF NOT EXISTS idx_agent_msg_from ON agent_messages(from_agent);
        CREATE INDEX IF NOT EXISTS idx_agent_msg_created ON agent_messages(created_at);

        CREATE TABLE IF NOT EXISTS agent_presence (
          agent_id TEXT PRIMARY KEY,
          status TEXT NOT NULL DEFAULT 'offline',
          last_seen_at TEXT NOT NULL,
          metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS context_quality_events (
          id TEXT PRIMARY KEY,
          task TEXT NOT NULL,
          task_type TEXT NOT NULL DEFAULT 'general',
          agent TEXT NOT NULL DEFAULT 'agent',
          project_path TEXT NOT NULL DEFAULT '',
          scope TEXT NOT NULL DEFAULT 'global',
          total_candidates INTEGER NOT NULL DEFAULT 0,
          used_count INTEGER NOT NULL DEFAULT 0,
          filtered_count INTEGER NOT NULL DEFAULT 0,
          hit_rate REAL NOT NULL DEFAULT 0,
          filter_rate REAL NOT NULL DEFAULT 0,
          ineffective_rate REAL NOT NULL DEFAULT 0,
          type_weights_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_context_quality_task_type ON context_quality_events(task_type);
        CREATE INDEX IF NOT EXISTS idx_context_quality_created ON context_quality_events(created_at);

        CREATE TABLE IF NOT EXISTS agent_capabilities (
          agent_id TEXT PRIMARY KEY,
          namespace TEXT NOT NULL DEFAULT 'default',
          capabilities_json TEXT NOT NULL DEFAULT '[]',
          metadata_json TEXT NOT NULL DEFAULT '{}',
          updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_agent_capabilities_namespace ON agent_capabilities(namespace);
        CREATE TABLE IF NOT EXISTS schema_version (
          version INTEGER PRIMARY KEY,
          applied_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES (?, ?)",
        (1, now()),
    )
    _ensure_column(conn, "memories", "injected_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "memories", "ineffective_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "memories", "effectiveness_score", "REAL NOT NULL DEFAULT 0.5")
    _ensure_column(conn, "memories", "last_injected_at", "TEXT")
    _ensure_column(conn, "agent_messages", "expires_at", "TEXT")
    _ensure_column(conn, "memories", "valid_from", "TEXT")
    _ensure_column(conn, "memories", "valid_until", "TEXT")
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
