"""Memory link graph operations."""
from __future__ import annotations

import uuid
from typing import Any

from local_memory_mcp.models import VALID_RELATION_TYPES, now
from local_memory_mcp.storage.db import managed_conn


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
