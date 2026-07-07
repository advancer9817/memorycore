"""CLI entry point and deprecated agent functions for memorycore."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

from memorycore.models import DEFAULT_ROOT, load_config, validate_config

logger = logging.getLogger(__name__)


def _get_mcp():
    from memorycore.server import mcp
    return mcp


def agent_handoff_create(
    from_agent: str,
    to_agent: str,
    task: str,
    payload: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    priority: str = "normal",
    ttl_seconds: int | None = 3600,
    auto_route: bool = False,
) -> dict[str, Any]:
    """Create a structured agent handoff request message.

    Set auto_route=True to automatically select the best online agent whose
    capabilities match the task keywords, ignoring the to_agent value.
    ttl_seconds defaults to 3600 (1 hour); set to None to disable expiry.
    """
    return create_agent_handoff(from_agent, to_agent, task, payload, correlation_id, priority, ttl_seconds, auto_route)


def agent_handoff_update(
    message_id: str,
    from_agent: str,
    status: str,
    result: dict[str, Any] | None = None,
    error: str = "",
) -> dict[str, Any]:
    """Acknowledge, complete, or fail an agent handoff request."""
    return update_agent_handoff(message_id, from_agent, status, result, error)


def agent_capability_register(
    agent_id: str,
    capabilities: list[str] | str,
    namespace: str = "default",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Register an agent's capabilities for handoff routing."""
    return register_agent_capability(agent_id, capabilities, namespace, metadata)


def agent_capability_search(
    capability: str = "",
    namespace: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Find agents by capability and optional namespace."""
    return search_agent_capabilities(capability, namespace, limit)


def agent_send(
    from_agent: str,
    to_agent: str,
    subject: str,
    body: str = "",
    priority: str = "normal",
    metadata: dict[str, Any] | None = None,
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    """Send a message from one agent to another (or broadcast to all online/idle agents).

    Args:
        from_agent: Sender agent identifier
        to_agent: Recipient agent identifier, or '*' to broadcast to all online/idle agents
        subject: Message subject line
        body: Message body text (optional)
        priority: low, normal, high, or urgent (default: normal)
        metadata: Optional key-value metadata
        ttl_seconds: Optional time-to-live in seconds; message expires after this duration

    Returns:
        The created message record, or broadcast summary dict when to_agent='*'.
    """
    return send_agent_message(from_agent, to_agent, subject, body, priority, metadata, ttl_seconds)


def agent_messages_cleanup() -> dict[str, Any]:
    """Delete all expired agent messages (where expires_at is set and in the past).

    Returns:
        Dict with 'deleted' count of removed messages.
    """
    deleted = cleanup_expired_messages()
    return {"deleted": deleted}


def agent_inbox(
    agent_id: str,
    status: str = "",
    mark_read: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Retrieve messages for an agent, optionally filtering by status.

    Args:
        agent_id: The agent whose inbox to read
        status: Filter by message status ('unread', 'read', or '' for all)
        mark_read: If true, mark returned unread messages as read
        limit: Maximum messages to return (default 50, max 500)

    Returns:
        List of message dicts, newest first.
    """
    return get_agent_inbox(agent_id, status=status, mark_read=mark_read, limit=limit)


def agent_presence_update(
    agent_id: str,
    status: str = "online",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Update an agent's presence status (heartbeat).

    Args:
        agent_id: The agent identifier
        status: online, idle, busy, or offline
        metadata: Optional key-value metadata (e.g. current task)

    Returns:
        The updated presence record.
    """
    return update_agent_presence(agent_id, status=status, metadata=metadata)


def agent_presence_list(
    status: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List agent presence entries, optionally filtered by status.

    Args:
        status: Filter by presence status ('' for all)
        limit: Maximum entries to return (default 100, max 500)

    Returns:
        List of presence dicts, most recently seen first.
    """
    return list_agent_presence(status=status, limit=limit)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

_OBS_START_TIME = __import__("time").time()


def _start_auto_curator(interval_hours: float = 6.0) -> None:
    """Background thread: run curator(dry_run=False) every interval_hours."""
    import time

    def _loop() -> None:
        # First run after 2 minutes so startup I/O settles first
        time.sleep(120)
        while True:
            try:
                from memorycore.storage.handoff import cleanup_expired_handoffs
                from memorycore.storage.crud import _drain_vector_sync_queue
                from memorycore.storage.governance import auto_expire_stale_reviews
                handoff_cleanup = cleanup_expired_handoffs()
                sync_result = _drain_vector_sync_queue()
                rollup = rollup_report(dry_run=False)
                rollup_summary = rollup.get("summary", {})
                expire_result = auto_expire_stale_reviews(stale_days=14, dry_run=False)
                logger.info(
                    "[auto-curator] handoff_cleaned=%s sync_retried=%s/%s rollup_created=%s rollup_archived=%s expired_reviews=%s",
                    handoff_cleanup.get("cleaned", 0),
                    sync_result.get("succeeded", 0),
                    sync_result.get("failed", 0),
                    rollup_summary.get("created", 0),
                    rollup_summary.get("archived_sources", 0),
                    expire_result.get("expired", 0),
                )
            except Exception as exc:
                logger.warning("[auto-curator] error: %s", exc)
            time.sleep(interval_hours * 3600)

    t = threading.Thread(target=_loop, daemon=True, name="auto-curator")
    t.start()
    logger.info("[auto-curator] scheduled every %.1f hours", interval_hours)



def _start_observability_server(host: str, obs_port: int) -> None:
    """Start a lightweight HTTP server exposing /health and /metrics."""
    from memorycore.storage import get_memory_stats

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence access logs
            pass

        def _send_json(self, code: int, body: dict) -> None:
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            import time
            if self.path == "/health":
                try:
                    stats = get_memory_stats()
                    self._send_json(200, {"status": "ok", "total_memories": stats["total"]})
                except Exception as exc:
                    self._send_json(503, {"status": "error", "reason": str(exc)})
            elif self.path == "/metrics":
                try:
                    stats = get_memory_stats()
                    uptime = round(time.time() - _OBS_START_TIME, 1)
                    self._send_json(200, {**stats, "uptime_s": uptime})
                except Exception as exc:
                    self._send_json(503, {"error": str(exc)})
            else:
                self._send_json(404, {"error": "not found"})

    server = HTTPServer((host, obs_port), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"Observability endpoints: http://{host}:{obs_port}/health  http://{host}:{obs_port}/metrics", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="memorycore server and CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    p_add = sub.add_parser("add")
    p_add.add_argument("type")
    p_add.add_argument("title")
    p_add.add_argument("content")
    p_add.add_argument("--scope", default="global")
    p_add.add_argument("--tags", default="")
    p_add.add_argument("--source", default="manual")
    p_add.add_argument("--source-agent", default="agent")
    p_add.add_argument("--importance", type=float, default=0.5)
    p_search = sub.add_parser("search")
    p_search.add_argument("query", nargs="?", default="")
    p_search.add_argument("--type", dest="types", action="append")
    p_search.add_argument("--limit", type=int, default=10)
    p_ctx = sub.add_parser("context")
    p_ctx.add_argument("task")
    p_ctx.add_argument("--agent", default="agent")
    p_ctx.add_argument("--scope", default="global")
    p_ctx.add_argument("--project-path", default="")
    p_ctx.add_argument("--budget", type=int, default=2000)
    p_curator = sub.add_parser("curator")
    p_curator.add_argument("--apply", action="store_true", help="mark low-risk stale/archive transitions")
    p_curator.add_argument("--limit", type=int, default=500)
    p_curator.add_argument("--stale-after-days", type=int, default=60)
    p_curator.add_argument("--archive-after-days", type=int, default=120)
    p_curator.add_argument("--summary-only", action="store_true")
    p_llm_curator = sub.add_parser("llm-curator")
    p_llm_curator.add_argument("--apply", action="store_true", help="apply LLM curator findings")
    p_llm_curator.add_argument("--limit", type=int, default=200)
    p_llm_curator.add_argument("--sim-threshold", type=float, default=0.72)
    p_llm_curator.add_argument("--summary-only", action="store_true")
    p_rollup = sub.add_parser("rollup")
    p_rollup.add_argument("--apply", action="store_true", help="create durable memories and archive source episodic records")
    p_rollup.add_argument("--limit", type=int, default=250)
    p_rollup.add_argument("--min-count", type=int, default=30)
    p_rollup.add_argument("--max-age-hours", type=float, default=24)
    p_rollup.add_argument("--min-age-count", type=int, default=5)
    p_rollup.add_argument("--source-agent", default="")
    p_rollup.add_argument("--project-path", default="")
    p_rollup.add_argument("--force", action="store_true")
    p_rollup.add_argument("--summary-only", action="store_true")
    p_sem_index = sub.add_parser("semantic-index")
    p_sem_index.add_argument("--limit", type=int, default=1000)
    p_sem_index.add_argument("--force", action="store_true")
    p_sem_search = sub.add_parser("semantic-search")
    p_sem_search.add_argument("query")
    p_sem_search.add_argument("--limit", type=int, default=10)
    p_sem_search.add_argument("--status", default="active")
    p_sem_search.add_argument("--score-threshold", type=float, default=0.0)
    sub.add_parser("semantic-status")
    p_html = sub.add_parser("html")
    p_html.add_argument("out", nargs="?", default=str(DEFAULT_ROOT / "dashboard.html"))
    p_export = sub.add_parser("export", help="Export memories to a JSON file")
    p_export.add_argument("out", nargs="?", default="memory-export.json",
                          help="Output file path (default: memory-export.json)")
    p_export.add_argument("--memories-only", action="store_true",
                          help="Only export memories/links/feedback (skip agent state); recommended for sync")
    p_export.add_argument("--full", action="store_true",
                          help="Export ALL data tables (memories, governance, entities, audit, curator state)")
    p_export.add_argument("--include-audit", action="store_true",
                          help="Also include audit_events in the export")
    p_import = sub.add_parser("import", help="Import memories from a JSON file")
    p_import.add_argument("src", help="Source JSON file path")
    p_import.add_argument("--conflict-policy", default="newer",
                          choices=["skip", "replace", "newer"],
                          help="How to handle conflicts (default: newer — keep whichever is more recent)")
    p_import.add_argument("--full-replace", action="store_true",
                          help="DELETE all rows in each table before importing (full overwrite); rebuilds FTS and vectors after")
    p_import.add_argument("--apply", action="store_true",
                          help="Actually apply the import (default is dry-run)")
    p_serve = sub.add_parser("serve")
    p_serve.add_argument("--host", default="127.0.0.1", help="HTTP bind address")
    p_serve.add_argument("--port", type=int, default=8318, help="HTTP port (default=8318, /mcp plus frontend routes)")
    p_serve.add_argument("--obs-port", type=int, default=0, help="Legacy extra observability HTTP port (0 = disabled; /health and /metrics are on main port)")
    p_serve.add_argument("--auth-token", default=os.environ.get("LOCAL_MEMORY_FRONTEND_TOKEN", ""), help="Bearer token required for /api/*")
    p_serve.add_argument("--allow-insecure-remote", action="store_true", help="Allow non-loopback frontend bind without auth token")
    p_serve.add_argument("--mcp-only", action="store_true", help="Disable frontend / and /api routes while keeping /mcp")
    args = parser.parse_args(argv)
    if args.cmd == "init":
        from memorycore.storage import managed_conn

        with managed_conn():
            pass
        from memorycore.models import db_path

        print(db_path())
    elif args.cmd == "add":
        print(
            json.dumps(
                add_memory_record(
                    args.type,
                    args.title,
                    args.content,
                    scope=args.scope,
                    tags=args.tags,
                    source=args.source,
                    source_agent=args.source_agent,
                    importance=args.importance,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.cmd == "search":
        print(
            json.dumps(
                search_memory_records(args.query, types=args.types, limit=args.limit),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.cmd == "context":
        print(
            build_context_pack(
                args.task, args.agent, project_path=args.project_path,
                scope=args.scope, token_budget=args.budget,
            )["context"]
        )
    elif args.cmd == "curator":
        report = curator_report(
            dry_run=not args.apply,
            limit=args.limit,
            stale_after_days=args.stale_after_days,
            archive_after_days=args.archive_after_days,
        )
        payload = report["summary"] if args.summary_only else report
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.cmd == "llm-curator":
        from memorycore.storage.curator_llm import run_llm_curator

        report = run_llm_curator(
            config=load_config(),
            limit=args.limit,
            sim_threshold=args.sim_threshold,
            apply=args.apply,
            rebuild_vectors=True,
        )
        payload = report.get("summary", report) if args.summary_only else report
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.cmd == "rollup":
        report = rollup_report(
            dry_run=not args.apply,
            limit=args.limit,
            min_count=args.min_count,
            max_age_hours=args.max_age_hours,
            min_age_count=args.min_age_count,
            source_agent=args.source_agent,
            project_path=args.project_path,
            force=args.force,
        )
        payload = report["summary"] if args.summary_only else report
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.cmd == "semantic-status":
        from memorycore.vector_store import get_vector_store

        try:
            payload = get_vector_store(load_config()).status()
        except Exception as exc:
            payload = {"available": False, "degraded": True, "reason": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.cmd == "semantic-search":
        from memorycore.vector_store import get_vector_store

        try:
            filters = {"status": args.status} if args.status else None
            results = get_vector_store(load_config()).search(
                args.query,
                top_k=args.limit,
                filters=filters,
                score_threshold=args.score_threshold,
            )
            payload = [
                {"id": r.id, "score": round(r.score, 4), "text": r.text, "payload": r.payload}
                for r in results
            ]
        except Exception as exc:
            payload = [{"degraded": True, "reason": f"vector store unavailable: {type(exc).__name__}: {exc}"}]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.cmd == "semantic-index":
        payload = rebuild_memory_vectors(dry_run=not args.force, limit=args.limit)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.cmd == "html":
        export_html(Path(args.out))
    elif args.cmd == "export":
        payload = export_memory_payload(
            include_audit=args.include_audit,
            memories_only=args.memories_only,
            full=args.full,
        )
        out_path = Path(args.out)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        counts = payload["counts"]
        total = sum(counts.values())
        mode = "full" if args.full else ("memories-only" if args.memories_only else "default")
        print(f"Exported {total} rows ({mode}) to {out_path}", file=sys.stderr)
        print(json.dumps(counts, ensure_ascii=False))
    elif args.cmd == "import":
        src_path = Path(args.src)
        if not src_path.exists():
            print(f"Error: file not found: {src_path}", file=sys.stderr)
            return 1
        payload = json.loads(src_path.read_text(encoding="utf-8"))
        dry_run = not args.apply
        full_replace = args.full_replace
        result = import_memory_payload(
            payload, dry_run=dry_run,
            conflict_policy=args.conflict_policy,
            full_replace=full_replace,
        )
        if "error" in result:
            print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
            return 1
        mode = "DRY RUN" if dry_run else "APPLIED"
        policy = "full-replace" if full_replace else f"conflict_policy={args.conflict_policy}"
        print(f"[{mode}] {policy}", file=sys.stderr)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.cmd == "serve":
        cfg = load_config()
        for warn in validate_config(cfg):
            logger.warning("config validation: %s", warn)
        # Pre-initialize vector store singleton with config so build_context_pack
        # picks up the correct Ollama URL / Qdrant path on first call.
        try:
            from memorycore.vector_store import get_vector_store
            get_vector_store(cfg)
        except Exception as _vs_err:
            logger.warning("vector store init skipped: %s", _vs_err)
        from memorycore.frontend import configure_frontend
        configure_frontend(
            host=args.host,
            port=args.port,
            auth_token=args.auth_token,
            allow_insecure_remote=args.allow_insecure_remote,
            enabled=not args.mcp_only,
        )
        obs_port = getattr(args, "obs_port", 0)
        if obs_port:
            _start_observability_server(args.host, obs_port)
        _start_auto_curator(interval_hours=6.0)
        if args.port:
            _mcp = _get_mcp(); _mcp.settings.host = args.host
            _mcp = _get_mcp(); _mcp.settings.port = args.port
            if args.mcp_only:
                print(f"Starting MCP server on http://{args.host}:{args.port}/mcp", file=sys.stderr)
            else:
                auth_note = "auth enabled" if args.auth_token else "localhost/no-token"
                print(f"Starting unified service on http://{args.host}:{args.port}/  (/mcp, /api/*, {auth_note})", file=sys.stderr)
            _mcp = _get_mcp(); _mcp.run(transport="streamable-http")
        else:
            _mcp = _get_mcp(); _mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
