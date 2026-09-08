"""Same-port frontend control service routes for memorycore."""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time
import yaml
from dataclasses import dataclass, field
from ipaddress import ip_address
from typing import Any
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from memorycore.models import MEMORY_TYPES, STATUSES, VALID_RELATION_TYPES, load_config, config_path, row_to_dict
from memorycore.storage.db import _managed_query
from memorycore.storage import (
    add_feedback,
    add_link,
    add_memory_record,
    atomize_report,
    build_context_pack,
    curator_report,
    dashboard_payload,
    get_active_warnings,
    get_audit_log,
    get_context_quality_stats,
    get_memory_stats,
    get_record,
    entity_search,
    list_agent_presence,
    list_recent,
    memory_lineage,
    memory_backup,
    memory_export,
    memory_import,
    memory_rebuild_vectors,
    memory_vector_audit,
    query_links,
    search_memory_records,
    timeline,
    update_memory_content,
    update_status,
)

from memorycore.frontend import _CONFIG, _MUTATING_METHODS
async def _json_body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > _CONFIG.max_body_bytes:
        raise ValueError("request body too large")
    if not raw:
        return {}
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("request body must be a JSON object")
    return parsed


def _check_auth(request: Request) -> Response | None:
    token = _CONFIG.auth_token
    if not token:
        return None
    auth = request.headers.get("authorization", "")
    if auth != f"Bearer {token}":
        return _json_error("unauthorized", "valid bearer token required", 401)
    return None


def _check_origin(request: Request) -> Response | None:
    if request.method.upper() not in _MUTATING_METHODS:
        return None
    origin = request.headers.get("origin") or ""
    if not origin:
        return None
    host = request.headers.get("host") or ""
    if not host:
        return None
    # Compare hostnames only (strip port) so that the UI on a different port
    # (e.g. localhost:3000) can still POST to the API (e.g. localhost:8318).
    origin_host = origin.split("://")[-1].split(":")[0].split("/")[0]
    server_host = host.split(":")[0]
    # Treat localhost and 127.0.0.1 as equivalent
    loopback_aliases = {"localhost", "127.0.0.1", "::1"}
    origin_is_loopback = origin_host in loopback_aliases
    server_is_loopback = server_host in loopback_aliases
    if origin_is_loopback and server_is_loopback:
        return None
    if origin_host and server_host and origin_host != server_host:
        return _json_error("bad_origin", "mutating requests must use same origin", 403)
    return None


def _graph_payload(limit: int = 500, status: str = "active,candidate") -> dict[str, Any]:
    from memorycore.storage.db import read_conn

    status_values = [item.strip() for item in status.split(",") if item.strip()]
    include_all_statuses = not status_values or "all" in status_values

    # Prioritize nodes with higher utility: importance DESC, then feedback_score DESC,
    # then injected_count DESC — deterministic ordering that surfaces useful nodes first.
    order_clause = (
        "ORDER BY COALESCE(importance, 0.5) DESC, "
        "COALESCE(feedback_score, 0.0) DESC, "
        "COALESCE(injected_count, 0) DESC"
    )

    with read_conn() as conn:
        if include_all_statuses:
            rows = conn.execute(
                f"SELECT id, title, type, status, importance, feedback_score, injected_count, content"
                f" FROM memories {order_clause} LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            placeholders = ",".join("?" * len(status_values))
            rows = conn.execute(
                f"SELECT id, title, type, status, importance, feedback_score, injected_count, content"
                f" FROM memories WHERE status IN ({placeholders}) {order_clause} LIMIT ?",
                (*status_values, limit),
            ).fetchall()

        nodes: list[dict[str, Any]] = [
            {
                "id": row[0],
                "title": (row[1] or "")[:80],
                "type": row[2] or "unknown",
                "status": row[3] or "active",
                "importance": round(float(row[4] or 0.5), 2),
                "feedback_score": round(float(row[5] or 0.0), 2),
                "injected_count": int(row[6] or 0),
                "content": (row[7] or "")[:500],
            }
            for row in rows
        ]

        node_ids = {n["id"] for n in nodes}

        # Fetch links connected to the selected node set. Chunk ids to avoid SQLite
        # parameter-limit issues when the UI requests a high graph limit, then keep
        # only links whose endpoints are both present in the returned node set.
        edges: list[dict[str, Any]] = []
        if node_ids:
            link_rows = []
            seen_links = set()
            id_list = list(node_ids)
            chunk_size = 400
            for start in range(0, len(id_list), chunk_size):
                chunk = id_list[start:start + chunk_size]
                placeholders_n = ",".join("?" * len(chunk))
                rows_for_chunk = conn.execute(
                    f"SELECT source_id, target_id, relation_type, weight"
                    f" FROM memory_links"
                    f" WHERE source_id IN ({placeholders_n}) OR target_id IN ({placeholders_n})",
                    (*chunk, *chunk),
                ).fetchall()
                for lrow in rows_for_chunk:
                    link_key = (lrow[0], lrow[1], lrow[2])
                    if link_key not in seen_links:
                        seen_links.add(link_key)
                        link_rows.append(lrow)
            edges = [
                {
                    "source": lrow[0],
                    "target": lrow[1],
                    "relation_type": lrow[2] or "related_to",
                    "weight": lrow[3] if lrow[3] is not None else 1.0,
                }
                for lrow in link_rows
                if lrow[0] in node_ids and lrow[1] in node_ids
            ]

    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "status": "all" if include_all_statuses else ",".join(status_values),
            "dropped_edges": 0,
        },
    }


def _json_ok(data: Any) -> JSONResponse:
    return JSONResponse({"ok": True, "data": data})


def _json_error(code: str, message: str, status: int, detail: Any = None) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if detail is not None:
        error["detail"] = detail
    return JSONResponse({"ok": False, "error": error}, status_code=status)


def _with_cors(response: Response) -> Response:
    response.headers.setdefault("Access-Control-Allow-Origin", "*")
    response.headers.setdefault("Access-Control-Allow-Methods", "GET,POST,PATCH,PUT,DELETE,OPTIONS")
    response.headers.setdefault("Access-Control-Allow-Headers", "authorization,content-type")
    return response


def _str_q(query: dict[str, list[str]], key: str, default: str | None = "") -> str | None:
    values = query.get(key)
    if not values:
        return default
    return values[-1]


def _int_q(query: dict[str, list[str]], key: str, default: int | None) -> int | None:
    value = _str_q(query, key, str(default) if default is not None else None)
    if value is None or value == "None":
        return default
    return int(value)


def _bool_q(query: dict[str, list[str]], key: str, default: bool) -> bool:
    value = _str_q(query, key, "true" if default else "false")
    return str(value).lower() in {"1", "true", "yes", "on"}


def _list_q(query: dict[str, list[str]], key: str) -> list[str]:
    values = query.get(key) or []
    items: list[str] = []
    for value in values:
        items.extend(part.strip() for part in value.split(",") if part.strip())
    return items

