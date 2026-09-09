"""PostgreSQL 16 + pgvector native connection management and schema initialisation.

Replaces legacy SQLite connection management with high-performance psycopg ConnectionPool,
native pgvector extension support, smart row factory, and transparent SQL translation.
Supports dynamic PG circle / cluster configuration overrides via configure_database().
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pgvector.psycopg import register_vector

from memorycore.models import (
    DEFAULT_ROOT,
    _INITIALIZED_DB_PATHS,
    load_config,
    now,
    row_to_dict,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global Configuration & Pool State
# ---------------------------------------------------------------------------
_pool_lock = threading.RLock()
_active_pool: ConnectionPool | None = None
_active_config: dict[str, Any] | None = None
_config_overrides: dict[str, Any] = {}
_thread_local = threading.local()


def get_database_config() -> dict[str, Any]:
    """Resolve active PostgreSQL configuration with precedence:

    1. Explicit runtime overrides via configure_database()
    2. Environment variables:
       - MCORE_DATABASE_URL / DATABASE_URL (full URI)
       - MCORE_PG_DATABASE / LOCAL_MEMORY_PG_DB / PGDATABASE
       - MCORE_PG_HOST / PGHOST
       - MCORE_PG_PORT / PGPORT
       - MCORE_PG_USER / PGUSER
       - MCORE_PG_PASSWORD / PGPASSWORD
       - MCORE_PG_MIN_POOL / MCORE_PG_MAX_POOL / MCORE_PG_TIMEOUT / PGSSLMODE
    3. config.yaml database section
    4. Hardcoded safe production defaults (127.0.0.1:5432 / mcore / mcore_user)
    """
    cfg_file = load_config().get("database", {}) if callable(load_config) else {}

    # Environment variables
    env_url = os.environ.get("MCORE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    env_host = os.environ.get("MCORE_PG_HOST") or os.environ.get("PGHOST")
    env_port = os.environ.get("MCORE_PG_PORT") or os.environ.get("PGPORT")
    env_db = (
        os.environ.get("MCORE_PG_DATABASE")
        or os.environ.get("LOCAL_MEMORY_PG_DB")
        or os.environ.get("PGDATABASE")
    )
    env_user = os.environ.get("MCORE_PG_USER") or os.environ.get("PGUSER")
    env_password = os.environ.get("MCORE_PG_PASSWORD") or os.environ.get("PGPASSWORD")
    env_ssl = os.environ.get("PGSSLMODE")
    env_min_pool = os.environ.get("MCORE_PG_MIN_POOL")
    env_max_pool = os.environ.get("MCORE_PG_MAX_POOL")
    env_timeout = os.environ.get("MCORE_PG_TIMEOUT")

    host = _config_overrides.get("host") or env_host or cfg_file.get("host") or "127.0.0.1"
    port = int(
        _config_overrides.get("port")
        or (env_port and int(env_port))
        or cfg_file.get("port")
        or 5432
    )
    name = (
        _config_overrides.get("name")
        or env_db
        or cfg_file.get("name")
        or "mcore"
    )
    user = (
        _config_overrides.get("user")
        or env_user
        or cfg_file.get("user")
        or "mcore_user"
    )
    password = (
        _config_overrides.get("password")
        or env_password
        or cfg_file.get("password")
        or "mcore_secure_password_2026"
    )
    sslmode = (
        _config_overrides.get("sslmode")
        or env_ssl
        or cfg_file.get("sslmode")
        or "prefer"
    )
    min_pool_size = int(
        _config_overrides.get("min_pool_size")
        or (env_min_pool and int(env_min_pool))
        or cfg_file.get("min_pool_size")
        or 2
    )
    max_pool_size = int(
        _config_overrides.get("max_pool_size")
        or (env_max_pool and int(env_max_pool))
        or cfg_file.get("max_pool_size")
        or 10
    )
    timeout = float(
        _config_overrides.get("timeout")
        or (env_timeout and float(env_timeout))
        or cfg_file.get("timeout")
        or 30.0
    )

    return {
        "url": env_url or f"postgresql://{user}:{password}@{host}:{port}/{name}?sslmode={sslmode}",
        "host": host,
        "port": port,
        "name": name,
        "user": user,
        "password": password,
        "sslmode": sslmode,
        "min_pool_size": min_pool_size,
        "max_pool_size": max_pool_size,
        "timeout": timeout,
    }


def configure_database(**kwargs: Any) -> dict[str, Any]:
    """Hot-replace or override PostgreSQL circle/cluster configuration at runtime.

    Example:
        configure_database(name="mcore_test", max_pool_size=5)
    """
    global _config_overrides
    with _pool_lock:
        _config_overrides.update(kwargs)
        close_pool()
        cfg = get_database_config()
        logger.info("PostgreSQL configuration updated: %s:%s/%s (user=%s)", cfg["host"], cfg["port"], cfg["name"], cfg["user"])
        return cfg


def reset_database_config() -> None:
    """Clear explicit overrides and reload defaults."""
    global _config_overrides
    with _pool_lock:
        _config_overrides.clear()
        close_pool()


# ---------------------------------------------------------------------------
# Smart Row Factory
# ---------------------------------------------------------------------------
class SmartRow(dict):
    """Row object supporting both dictionary key access and integer tuple index access.

    Ensures zero friction across legacy SQLite row indexing (e.g. row[0]) and
    modern key mapping (e.g. row["title"]).
    Also normalizes:
    - datetime/date objects to ISO format strings
    - *_json columns that were returned by psycopg as dict/list into json strings
    """

    def __init__(self, values: Sequence[Any], description: Sequence[Any]):
        super().__init__()
        normalized_values = []
        for col, val in zip(description, values):
            if isinstance(val, (datetime.datetime, datetime.date)):
                val = val.isoformat()
            elif col.name.endswith("_json") and isinstance(val, (dict, list)):
                val = json.dumps(val, ensure_ascii=False)
            self[col.name] = val
            normalized_values.append(val)
        self._values = normalized_values

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, int):
            return self._values[item]
        return super().__getitem__(item)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)


def smart_row_factory(cursor: Any):
    desc = cursor.description
    if not desc:
        return lambda values: values

    def make_row(values: Sequence[Any]) -> SmartRow:
        return SmartRow(values, desc)

    return make_row


# ---------------------------------------------------------------------------
# SQL Translation & Emulation Engine
# ---------------------------------------------------------------------------
def translate_query(sql: str) -> str:
    """Translate SQLite idioms to PostgreSQL 16 standard syntax.

    - Replaces '?' parameter markers with '%s' (ignoring string literals).
    - Translates PRAGMA table_info(<table>) to information_schema.columns query.
    - Translates sqlite_master to information_schema.tables.
    - Adapts INSERT OR IGNORE to ON CONFLICT DO NOTHING.
    - Handles memories_fts dummy checks.
    """
    raw = sql.strip()

    # Intercept PRAGMA table_info & PRAGMA index_list
    if raw.upper().startswith("PRAGMA "):
        m = re.match(r"PRAGMA\s+table_info\s*\(\s*([a-zA-Z0-9_]+)\s*\)", raw, re.I)
        if m:
            table = m.group(1)
            return (
                f"SELECT 0 as cid, column_name as name, data_type as type, "
                f"CASE WHEN is_nullable = 'NO' THEN 1 ELSE 0 END as notnull, "
                f"column_default as dflt_value, 0 as pk "
                f"FROM information_schema.columns "
                f"WHERE table_name = '{table}' AND table_schema = 'public' "
                f"ORDER BY ordinal_position"
            )
        m_idx = re.match(r"PRAGMA\s+index_list\s*\(\s*([a-zA-Z0-9_]+)\s*\)", raw, re.I)
        if m_idx:
            table = m_idx.group(1)
            return (
                f"SELECT 0 as seq, indexname as name, 0 as \"unique\", 'c' as origin, 0 as partial "
                f"FROM pg_indexes "
                f"WHERE tablename = '{table}' AND schemaname = 'public'"
            )
        return "SELECT 1 WHERE 1=0"

    # Tokenize and replace ? placeholders with %s outside quotes
    parts: list[str] = []
    in_quote = False
    quote_char = None
    i = 0
    while i < len(raw):
        c = raw[i]
        if not in_quote:
            if c in ("'", '"'):
                in_quote = True
                quote_char = c
                parts.append(c)
            elif c == "?":
                parts.append("%s")
            else:
                parts.append(c)
        else:
            parts.append(c)
            if c == quote_char:
                if i + 1 < len(raw) and raw[i + 1] == quote_char:
                    parts.append(raw[i + 1])
                    i += 1
                else:
                    in_quote = False
        i += 1
    translated = "".join(parts)

    # INSERT OR IGNORE translation
    translated = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO\s+", "INSERT INTO ", translated, flags=re.I)
    if "INSERT INTO schema_version" in translated and "ON CONFLICT" not in translated:
        translated += " ON CONFLICT (version) DO NOTHING"

    # INSERT OR REPLACE translation
    if re.search(r"INSERT\s+OR\s+REPLACE\s+INTO\s+", raw, re.I):
        if "vector_sync_queue" in raw:
            translated = re.sub(r"INSERT\s+OR\s+REPLACE\s+INTO\s+", "INSERT INTO ", translated, flags=re.I)
            translated += " ON CONFLICT (id) DO UPDATE SET operation=EXCLUDED.operation, retry_count=EXCLUDED.retry_count, max_retries=EXCLUDED.max_retries, last_attempt_at=EXCLUDED.last_attempt_at, error=EXCLUDED.error"
        elif "agent_presence" in raw:
            translated = re.sub(r"INSERT\s+OR\s+REPLACE\s+INTO\s+", "INSERT INTO ", translated, flags=re.I)
            translated += " ON CONFLICT (agent_id) DO UPDATE SET status=EXCLUDED.status, last_seen_at=EXCLUDED.last_seen_at, metadata_json=EXCLUDED.metadata_json"
        elif "curator_review_log" in raw:
            translated = re.sub(r"INSERT\s+OR\s+REPLACE\s+INTO\s+", "INSERT INTO ", translated, flags=re.I)
            translated += " ON CONFLICT (memory_id, review_type) DO UPDATE SET reviewed_at=EXCLUDED.reviewed_at"
        elif "llm_curator_batches" in raw:
            translated = re.sub(r"INSERT\s+OR\s+REPLACE\s+INTO\s+", "INSERT INTO ", translated, flags=re.I)
            translated += " ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status, candidate_count=EXCLUDED.candidate_count, finding_count=EXCLUDED.finding_count, decision_count=EXCLUDED.decision_count, cursor_token=EXCLUDED.cursor_token, error_json=EXCLUDED.error_json"
        elif "user_profile_attrs" in raw:
            translated = re.sub(r"INSERT\s+OR\s+REPLACE\s+INTO\s+", "INSERT INTO ", translated, flags=re.I)
            translated += " ON CONFLICT (user_id, attribute) DO UPDATE SET value=EXCLUDED.value, confidence=EXCLUDED.confidence, immutable=EXCLUDED.immutable, source_ids_json=EXCLUDED.source_ids_json, updated_at=EXCLUDED.updated_at"
        else:
            translated = re.sub(r"INSERT\s+OR\s+REPLACE\s+INTO\s+", "INSERT INTO ", translated, flags=re.I)
            m_cols = re.search(r"\(([^)]+)\)\s+VALUES", translated)
            pk = "agent_id" if "agent_presence" in raw else "id"
            if m_cols:
                cols = [c.strip() for c in m_cols.group(1).split(",")]
                updates = [f"{c}=EXCLUDED.{c}" for c in cols if c != pk]
                if updates:
                    set_clause = ", ".join(updates)
                    translated += f" ON CONFLICT ({pk}) DO UPDATE SET {set_clause}"
                else:
                    translated += f" ON CONFLICT ({pk}) DO NOTHING"
            else:
                translated += f" ON CONFLICT ({pk}) DO NOTHING"

    # Replace SQLite rowid with PostgreSQL ctid
    if "rowid" in translated:
        translated = re.sub(r"\browid\b", "ctid", translated, flags=re.I)

    # Timestamp syntax cleaning (SQLite text timestamp compatibility on PG TIMESTAMPTZ)
    if "_at" in translated or "_until" in translated or "_from" in translated:
        translated = re.sub(r"NULLIF\s*\(\s*([a-zA-Z0-9_]+_(?:at|until|from))\s*,\s*['\"]['\"]\s*\)", r"\1", translated, flags=re.I)
        translated = re.sub(r"([a-zA-Z0-9_]+_(?:at|until|from))\s*=\s*['\"]['\"]", r"\1 IS NULL", translated, flags=re.I)
        translated = re.sub(r"([a-zA-Z0-9_]+_(?:at|until|from))\s*!=\s*['\"]['\"]", r"\1 IS NOT NULL", translated, flags=re.I)

    # Tie-breaker for created_at sorting
    if "ORDER BY created_at DESC" in translated and "ctid" not in translated:
        translated = translated.replace("ORDER BY created_at DESC", "ORDER BY created_at DESC, ctid DESC")

    # sqlite_master emulation
    if "sqlite_master" in translated:
        translated = translated.replace(
            "sqlite_master",
            "(SELECT table_name as name, 'table' as type FROM information_schema.tables WHERE table_schema='public' "
            "UNION ALL "
            "SELECT indexname as name, 'index' as type FROM pg_indexes WHERE schemaname='public') sm",
        )

    # memories_fts dummy count probe
    if "memories_fts" in translated and "WHERE id IS NULL" in translated:
        return "SELECT 0 as count"

    return translated


# ---------------------------------------------------------------------------
# PgCursorWrapper & PgConnectionWrapper
# ---------------------------------------------------------------------------
def _adapt_param(val: Any) -> Any:
    if isinstance(val, dict):
        return json.dumps(val, ensure_ascii=False)
    return val


def _adapt_params(params: Any) -> Any:
    if isinstance(params, (list, tuple)):
        return tuple(_adapt_param(v) for v in params)
    return _adapt_param(params)


class PgCursorWrapper:
    """Wraps psycopg Cursor to provide transparent SQL translation and SQLite parity."""

    def __init__(self, cursor: psycopg.Cursor):
        self._cursor = cursor

    def execute(self, sql: str, params: Any = None) -> PgCursorWrapper:
        translated = translate_query(sql)
        if params is not None:
            adapted = _adapt_params(params)
            self._cursor.execute(translated, adapted)
        else:
            self._cursor.execute(translated)
        return self

    def executemany(self, sql: str, seq_of_params: Sequence[Any]) -> PgCursorWrapper:
        translated = translate_query(sql)
        adapted_seq = [_adapt_params(p) for p in seq_of_params]
        self._cursor.executemany(translated, adapted_seq)
        return self

    def fetchone(self) -> Any:
        return self._cursor.fetchone()

    def fetchall(self) -> list[Any]:
        return self._cursor.fetchall()

    def fetchmany(self, size: int = 1) -> list[Any]:
        return self._cursor.fetchmany(size)

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def description(self) -> Any:
        return self._cursor.description

    @property
    def lastrowid(self) -> Any:
        return None

    def close(self) -> None:
        self._cursor.close()

    def __iter__(self) -> Iterator[Any]:
        return iter(self._cursor)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)


class PgConnectionWrapper:
    """Wraps psycopg Connection to mimic sqlite3.Connection behavior."""

    def __init__(self, raw_conn: psycopg.Connection):
        self._raw_conn = raw_conn
        self.row_factory = smart_row_factory

    def cursor(self) -> PgCursorWrapper:
        cur = self._raw_conn.cursor(row_factory=smart_row_factory)
        return PgCursorWrapper(cur)

    def execute(self, sql: str, params: Any = None) -> PgCursorWrapper:
        cur = self.cursor()
        return cur.execute(sql, params)

    def executemany(self, sql: str, seq_of_params: Sequence[Any]) -> PgCursorWrapper:
        cur = self.cursor()
        return cur.executemany(sql, seq_of_params)

    def executescript(self, script: str) -> None:
        with self._raw_conn.cursor() as cur:
            cur.execute(script)
        self.commit()

    def commit(self) -> None:
        self._raw_conn.commit()

    def rollback(self) -> None:
        self._raw_conn.rollback()

    def close(self) -> None:
        # If pool-managed, raw_conn.close() returns it to pool
        self._raw_conn.close()

    def __enter__(self) -> PgConnectionWrapper:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type:
            self.rollback()
        else:
            self.commit()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._raw_conn, name)


# ---------------------------------------------------------------------------
# Connection Pool Management
# ---------------------------------------------------------------------------
def _configure_pool_connection(conn: psycopg.Connection) -> None:
    """Invoked on each freshly created pooled connection."""
    conn.row_factory = smart_row_factory
    register_vector(conn)


def get_pool() -> ConnectionPool:
    """Retrieve or initialize the active PostgreSQL ConnectionPool."""
    global _active_pool, _active_config
    if _active_pool is not None and not _active_pool.closed:
        return _active_pool

    with _pool_lock:
        if _active_pool is not None and not _active_pool.closed:
            return _active_pool

        cfg = get_database_config()
        conninfo = (
            f"host={cfg['host']} port={cfg['port']} dbname={cfg['name']} "
            f"user={cfg['user']} password={cfg['password']} sslmode={cfg['sslmode']}"
        )
        logger.info("Initializing PostgreSQL ConnectionPool to %s:%s/%s (min=%d, max=%d)", cfg["host"], cfg["port"], cfg["name"], cfg["min_pool_size"], cfg["max_pool_size"])
        pool = ConnectionPool(
            conninfo=conninfo,
            min_size=cfg["min_pool_size"],
            max_size=cfg["max_pool_size"],
            timeout=cfg["timeout"],
            configure=_configure_pool_connection,
            open=True,
        )
        _active_pool = pool
        _active_config = cfg

        # Auto-initialize schema once
        try:
            with pool.connection() as raw:
                wrapper = PgConnectionWrapper(raw)
                init_db(wrapper)
        except Exception as exc:
            logger.warning("Auto init_db on pool startup: %s", exc)

        return _active_pool


def reset_pool() -> None:
    """Close and reset current connection pool."""
    close_pool()


def close_pool() -> None:
    """Close active pool if open."""
    global _active_pool, _active_config
    with _pool_lock:
        if _active_pool is not None:
            try:
                _active_pool.close()
            except Exception:
                pass
            _active_pool = None
            _active_config = None


# ---------------------------------------------------------------------------
# Public Connection Interfaces
# ---------------------------------------------------------------------------
def connect() -> PgConnectionWrapper:
    """Return a wrapped connection for the active PostgreSQL database."""
    pool = get_pool()
    raw = pool.getconn()
    return PgConnectionWrapper(raw)


@contextmanager
def managed_conn():
    """Context manager for write transactions with auto-commit and rollback."""
    pool = get_pool()
    with pool.connection() as raw:
        wrapper = PgConnectionWrapper(raw)
        try:
            yield wrapper
            wrapper.commit()
        except Exception:
            wrapper.rollback()
            raise


@contextmanager
def read_conn():
    """Context manager for read queries."""
    pool = get_pool()
    with pool.connection() as raw:
        wrapper = PgConnectionWrapper(raw)
        yield wrapper


def _managed_query(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Execute a read query and return rows formatted as dictionaries."""
    with read_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [row_to_dict(r) for r in rows]


def _ensure_column(conn: Any, table: str, column: str, definition: str) -> None:
    """Ensure a column exists in a PostgreSQL table."""
    cur = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s AND column_name = %s AND table_schema = 'public'",
        (table, column),
    )
    if not cur.fetchone():
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _drop_dead_tables(conn: Any, table_names: list[str]) -> None:
    """Drop obsolete dead tables."""
    for name in table_names:
        try:
            conn.execute(f'DROP TABLE IF EXISTS "{name}" CASCADE')
        except Exception:
            pass


def init_db(conn: Any) -> None:
    """Initialize PostgreSQL database schema from schema.sql."""
    schema_file = Path(__file__).resolve().parent / "schema.sql"
    if schema_file.is_file():
        sql_text = schema_file.read_text(encoding="utf-8")
        conn.executescript(sql_text)
    else:
        logger.warning("schema.sql not found at %s", schema_file)
    try:
        conn.execute(
            "INSERT INTO schema_version(version, applied_at) VALUES (%s, %s) ON CONFLICT (version) DO NOTHING",
            (1, now()),
        )
    except Exception as exc:
        logger.debug("init_db schema_version insert: %s", exc)


def db_path() -> Path:
    """Compatibility helper returning a string-like Path descriptor of the DB."""
    cfg = get_database_config()
    return Path(f"{cfg['host']}:{cfg['port']}/{cfg['name']}")
