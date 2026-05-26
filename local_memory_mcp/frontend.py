"""Same-port frontend control service routes for local-memory-mcp."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Any
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from local_memory_mcp.models import MEMORY_TYPES, STATUSES, VALID_RELATION_TYPES, load_config
from local_memory_mcp.storage import (
    add_feedback,
    add_link,
    add_memory_record,
    agent_capability_register,
    agent_capability_search,
    agent_handoff_create,
    agent_handoff_update,
    build_context_pack,
    cleanup_expired_messages,
    consolidate,
    curator_report,
    dashboard_payload,
    get_active_warnings,
    get_agent_inbox,
    get_agent_permission,
    get_audit_log,
    get_context_quality_stats,
    get_memory_stats,
    get_record,
    grant_agent_permission,
    list_agent_presence,
    list_recent,
    memory_backup,
    memory_export,
    memory_import,
    memory_rebuild_vectors,
    query_links,
    search_memory_records,
    send_agent_message,
    timeline,
    update_agent_presence,
    update_memory_content,
    update_status,
)

logger = logging.getLogger(__name__)
_START_TIME = time.time()
_MUTATING_METHODS = {"POST", "PATCH", "PUT", "DELETE"}


@dataclass
class FrontendConfig:
    host: str = "127.0.0.1"
    port: int = 8318
    auth_token: str = ""
    allow_insecure_remote: bool = False
    max_body_bytes: int = 2_000_000
    enabled: bool = True


_CONFIG = FrontendConfig()


def configure_frontend(
    host: str = "127.0.0.1",
    port: int = 8318,
    auth_token: str = "",
    allow_insecure_remote: bool = False,
    enabled: bool = True,
) -> None:
    if enabled:
        validate_frontend_bind(host, auth_token, allow_insecure_remote)
    global _CONFIG
    _CONFIG = FrontendConfig(host=host, port=int(port), auth_token=auth_token or "", allow_insecure_remote=allow_insecure_remote, enabled=enabled)


def validate_frontend_bind(host: str, auth_token: str = "", allow_insecure_remote: bool = False) -> None:
    if _is_loopback_host(host):
        return
    if auth_token or allow_insecure_remote:
        return
    raise ValueError("remote frontend bind requires --auth-token or --allow-insecure-remote")


def _is_loopback_host(host: str) -> bool:
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


async def frontend_index(request: Request) -> Response:
    if not _CONFIG.enabled:
        return Response("frontend disabled", status_code=404)
    return HTMLResponse(_FRONTEND_HTML)


async def frontend_health(request: Request) -> Response:
    try:
        stats = get_memory_stats()
        return _json_ok({"status": "ok", "total_memories": stats["total"]})
    except Exception as exc:
        logger.exception("frontend health failed")
        return _json_error("unavailable", str(exc), 503)


async def frontend_metrics(request: Request) -> Response:
    try:
        return _json_ok({**get_memory_stats(), "uptime_s": round(time.time() - _START_TIME, 1)})
    except Exception as exc:
        logger.exception("frontend metrics failed")
        return _json_error("unavailable", str(exc), 503)


async def frontend_api(request: Request) -> Response:
    if not _CONFIG.enabled:
        return _json_error("not_found", "frontend disabled", 404)
    auth_error = _check_auth(request)
    if auth_error is not None:
        return auth_error
    origin_error = _check_origin(request)
    if origin_error is not None:
        return origin_error
    path = (request.path_params.get("path") or "").strip("/")
    parts = [part for part in path.split("/") if part]
    query = parse_qs(request.url.query)
    try:
        data = await _dispatch_api(request, parts, query)
        if isinstance(data, Response):
            return data
        if isinstance(data, dict) and data.get("error") == "permission_denied":
            return _json_error("permission_denied", "permission denied", 403, data)
        return _json_ok(data)
    except json.JSONDecodeError:
        return _json_error("bad_json", "request body must be valid JSON", 400)
    except ValueError as exc:
        return _json_error("bad_request", str(exc), 400)
    except LookupError as exc:
        return _json_error("not_found", str(exc), 404)
    except Exception as exc:
        logger.exception("frontend api failed: /api/%s", path)
        return _json_error("internal_error", f"{type(exc).__name__}: request failed", 500)


async def _dispatch_api(request: Request, parts: list[str], query: dict[str, list[str]]) -> Any:
    method = request.method.upper()
    body = await _json_body(request) if method in _MUTATING_METHODS else {}

    if parts == ["dashboard"] and method == "GET":
        return dashboard_payload(_int_q(query, "limit", 1000))
    if parts == ["schema", "enums"] and method == "GET":
        return {"memory_types": sorted(MEMORY_TYPES), "statuses": sorted(STATUSES), "relation_types": sorted(VALID_RELATION_TYPES)}

    if parts == ["memories"] and method == "GET":
        return search_memory_records(
            query=_str_q(query, "query", _str_q(query, "q", "")),
            types=_list_q(query, "type") or _list_q(query, "types"),
            scope=_str_q(query, "scope", ""),
            project_path=_str_q(query, "project_path", ""),
            tags=_list_q(query, "tag") or _list_q(query, "tags"),
            status=_str_q(query, "status", "active"),
            limit=_int_q(query, "limit", 50),
        )
    if parts == ["memories", "recent"] and method == "GET":
        return list_recent(_int_q(query, "limit", 50), cap=500)
    if parts == ["memories", "timeline"] and method == "GET":
        return timeline(_str_q(query, "query", _str_q(query, "q", "")), _str_q(query, "scope", ""), _int_q(query, "limit", 50))
    if len(parts) == 2 and parts[0] == "memories" and method == "GET":
        record = get_record(parts[1])
        if record is None:
            raise LookupError(f"memory not found: {parts[1]}")
        return record
    if parts == ["memories"] and method == "POST":
        return add_memory_record(
            body.get("type", "project_memory"), body.get("title", ""), body.get("content", ""),
            scope=body.get("scope", "global"), tags=body.get("tags"), source=body.get("source", "manual"),
            source_agent=body.get("source_agent", "frontend"), project_path=body.get("project_path", ""),
            confidence=body.get("confidence", 0.7), importance=body.get("importance", 0.5),
            status=body.get("status", "active"), decay_policy=body.get("decay_policy", "review"),
            related_ids=body.get("related_ids"), metadata=body.get("metadata"),
        )
    if len(parts) == 2 and parts[0] == "memories" and method == "PATCH":
        return update_memory_content(parts[1], body.get("content"), body.get("title"), body.get("status"), body.get("confidence"), body.get("importance"))
    if len(parts) == 3 and parts[0] == "memories" and parts[2] == "status" and method == "PATCH":
        return update_status(parts[1], body.get("status", ""))
    if len(parts) == 3 and parts[0] == "memories" and parts[2] == "feedback" and method == "POST":
        return add_feedback(parts[1], body.get("score", 0), body.get("note", ""), body.get("source_agent", "frontend"))

    if parts == ["context"] and method == "POST":
        return build_context_pack(body.get("task", ""), body.get("agent", "frontend"), body.get("project_path", ""), body.get("scope", "global"), body.get("token_budget", 2000))
    if parts == ["context", "stats"] and method == "GET":
        return get_context_quality_stats(_int_q(query, "limit", 500))
    if parts == ["curator"] and method == "GET":
        return curator_report(
            dry_run=_bool_q(query, "dry_run", True), limit=_int_q(query, "limit", 500),
            stale_after_days=_int_q(query, "stale_after_days", 60), archive_after_days=_int_q(query, "archive_after_days", 120),
            allow_actions=_list_q(query, "allow_actions"), deny_actions=_list_q(query, "deny_actions"),
        )
    if parts == ["curator", "apply"] and method == "POST":
        return curator_report(
            dry_run=False, limit=int(body.get("limit", 500)),
            stale_after_days=int(body.get("stale_after_days", 60)), archive_after_days=int(body.get("archive_after_days", 120)),
            allow_actions=body.get("allow_actions"), deny_actions=body.get("deny_actions"),
        )
    if parts == ["consolidate"] and method == "POST":
        return consolidate(bool(body.get("dry_run", True)), int(body.get("limit", 50)))

    if parts == ["links"] and method == "POST":
        return add_link(body.get("source_id", ""), body.get("target_id", ""), body.get("relation_type", "related_to"), body.get("weight", 1.0), body.get("note", ""), body.get("source_agent", "frontend"))
    if len(parts) == 2 and parts[0] == "links" and method == "GET":
        return query_links(parts[1], _str_q(query, "direction", "both"), _str_q(query, "relation_type", ""), _int_q(query, "limit", 50))
    if parts == ["warnings"] and method == "POST":
        return get_active_warnings(body.get("memory_ids", []), body.get("min_weight", 0.4), body.get("max_warnings", 5))

    if parts == ["agents", "presence"] and method == "GET":
        return list_agent_presence(_str_q(query, "status", ""), _int_q(query, "limit", 100))
    if parts == ["agents", "presence"] and method == "POST":
        return update_agent_presence(body.get("agent_id", ""), body.get("status", "online"), body.get("metadata"))
    if len(parts) == 3 and parts[0] == "agents" and parts[2] == "inbox" and method == "GET":
        return get_agent_inbox(parts[1], _str_q(query, "status", ""), _bool_q(query, "mark_read", False), _int_q(query, "limit", 50))
    if parts == ["agents", "messages"] and method == "POST":
        return send_agent_message(body.get("from_agent", "frontend"), body.get("to_agent", ""), body.get("subject", ""), body.get("body", ""), body.get("priority", "normal"), body.get("metadata"), body.get("ttl_seconds"))
    if parts == ["agents", "messages", "cleanup"] and method == "POST":
        return {"deleted": cleanup_expired_messages()}
    if len(parts) == 3 and parts[0] == "agents" and parts[2] == "permission" and method == "GET":
        return get_agent_permission(parts[1])
    if len(parts) == 3 and parts[0] == "agents" and parts[2] == "permission" and method == "POST":
        return grant_agent_permission(parts[1], body.get("namespace", "default"), body.get("can_read", True), body.get("can_write", True), body.get("can_broadcast", True), body.get("scopes"), body.get("types"), body.get("tags"))
    if len(parts) == 3 and parts[0] == "agents" and parts[2] == "capabilities" and method == "POST":
        return agent_capability_register(parts[1], body.get("capabilities", []), body.get("namespace", "default"), body.get("metadata"))
    if parts == ["agents", "capabilities"] and method == "GET":
        return agent_capability_search(_str_q(query, "capability", ""), _str_q(query, "namespace", ""), _int_q(query, "limit", 50))
    if parts == ["handoffs"] and method == "POST":
        return agent_handoff_create(body.get("from_agent", "frontend"), body.get("to_agent", ""), body.get("task", ""), body.get("payload"), body.get("correlation_id"), body.get("priority", "normal"), body.get("ttl_seconds"))
    if len(parts) == 2 and parts[0] == "handoffs" and method == "PATCH":
        return agent_handoff_update(parts[1], body.get("from_agent", "frontend"), body.get("status", ""), body.get("result"), body.get("error", ""))

    if parts == ["audit"] and method == "GET":
        return get_audit_log(_str_q(query, "memory_id", None), _str_q(query, "event_type", None), _int_q(query, "limit", 50))
    if parts == ["export"] and method == "GET":
        return memory_export(_bool_q(query, "include_audit", False))
    if parts == ["import"] and method == "POST":
        return memory_import(body.get("payload", body), body.get("dry_run", True), body.get("conflict_policy", "skip"))
    if parts == ["backup"] and method == "POST":
        return memory_backup(body.get("path"))
    if parts == ["vector", "status"] and method == "GET":
        from local_memory_mcp.vector_store import get_vector_store
        return get_vector_store(load_config()).status()
    if parts == ["vector", "search"] and method == "GET":
        from local_memory_mcp.vector_store import get_vector_store
        results = get_vector_store(load_config()).search(_str_q(query, "query", _str_q(query, "q", "")), _int_q(query, "top_k", 10), float(_str_q(query, "score_threshold", "0")))
        return [{"id": r.id, "score": round(r.score, 4), "text": r.text, "payload": r.payload} for r in results]
    if parts == ["vector", "rebuild"] and method == "POST":
        return memory_rebuild_vectors(body.get("dry_run", True), body.get("limit", 5000))

    raise LookupError(f"route not found: /api/{'/'.join(parts)}")


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
    if host and host not in origin:
        return _json_error("bad_origin", "mutating requests must use same origin", 403)
    return None


def _json_ok(data: Any) -> JSONResponse:
    return JSONResponse({"ok": True, "data": data})


def _json_error(code: str, message: str, status: int, detail: Any = None) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if detail is not None:
        error["detail"] = detail
    return JSONResponse({"ok": False, "error": error}, status_code=status)


def _str_q(query: dict[str, list[str]], key: str, default: str | None = "") -> str | None:
    values = query.get(key)
    if not values:
        return default
    return values[-1]


def _int_q(query: dict[str, list[str]], key: str, default: int) -> int:
    value = _str_q(query, key, str(default))
    return int(value or default)


def _bool_q(query: dict[str, list[str]], key: str, default: bool) -> bool:
    value = _str_q(query, key, "true" if default else "false")
    return str(value).lower() in {"1", "true", "yes", "on"}


def _list_q(query: dict[str, list[str]], key: str) -> list[str]:
    values = query.get(key) or []
    items: list[str] = []
    for value in values:
        items.extend(part.strip() for part in value.split(",") if part.strip())
    return items


_FRONTEND_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Local Memory MCP Control</title>
<style>
:root{--paper:#f7f1e8;--panel:#fffaf1;--ink:#2b2118;--muted:#7c6b5a;--line:#dfcfb8;--accent:#d97757;--bad:#a94735;--good:#6f8068}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:Inter,system-ui,sans-serif}.shell{display:grid;grid-template-columns:260px 1fr;min-height:100vh}.side{border-right:1px solid var(--line);padding:20px;background:#f3eadc}.brand{font-family:Georgia,serif;font-size:28px;font-weight:700;letter-spacing:-.04em}.muted{color:var(--muted)}button,input,textarea,select{font:inherit}button{border:1px solid var(--line);border-radius:12px;background:var(--panel);padding:9px 12px;cursor:pointer}button.primary{background:var(--accent);border-color:var(--accent);color:white}nav{display:grid;gap:8px;margin-top:22px}nav button{text-align:left}nav button.active{outline:2px solid rgba(217,119,87,.35)}main{padding:24px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}.card{border:1px solid var(--line);border-radius:18px;background:var(--panel);padding:16px}.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}.stack{display:grid;gap:10px}input,textarea,select{width:100%;border:1px solid var(--line);border-radius:12px;background:white;padding:10px}textarea{min-height:110px}.pill{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:3px 8px;color:var(--muted);font-size:12px}.err{color:var(--bad)}.ok{color:var(--good)}pre{white-space:pre-wrap;word-break:break-word;background:#f3eadc;border-radius:12px;padding:12px;max-height:420px;overflow:auto}.records{display:grid;gap:10px}.record{border:1px solid var(--line);border-radius:14px;padding:12px;background:white}.record h3{margin:0 0 8px}.hidden{display:none}@media(max-width:850px){.shell{grid-template-columns:1fr}.side{border-right:0;border-bottom:1px solid var(--line)}}
</style>
</head>
<body>
<div class="shell">
  <aside class="side">
    <div class="brand">Local Memory</div>
    <p class="muted">同端口控制台 · <code>/mcp</code> 保持可用</p>
    <label class="stack">API Token <input id="token" type="password" placeholder="Bearer token（如启用）"></label>
    <nav id="nav"></nav>
  </aside>
  <main>
    <div class="row"><h1 id="title">Overview</h1><button onclick="refresh()">刷新</button><span id="status" class="muted"></span></div>
    <section id="overview" class="view"></section>
    <section id="records" class="view hidden"></section>
    <section id="curator" class="view hidden"></section>
    <section id="agents" class="view hidden"></section>
    <section id="ops" class="view hidden"></section>
    <section id="raw" class="view hidden"><pre id="rawOut"></pre></section>
  </main>
</div>
<script>
const views = {overview:'Overview',records:'Records',curator:'Curator',agents:'Agents',ops:'Ops',raw:'Raw JSON'};
let current = 'overview';
let state = {};
const $ = id => document.getElementById(id);
function headers(){ const h={'Content-Type':'application/json'}; const t=$('token').value.trim(); if(t) h.Authorization='Bearer '+t; return h; }
async function api(path, opts={}){ const r=await fetch(path,{...opts,headers:{...headers(),...(opts.headers||{})}}); const j=await r.json(); if(!j.ok) throw new Error(j.error?.message || 'request failed'); return j.data; }
function setStatus(msg, cls='muted'){ $('status').className=cls; $('status').textContent=msg; }
function esc(s){ return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function mountNav(){ $('nav').innerHTML=Object.entries(views).map(([k,v])=>`<button class="${k===current?'active':''}" onclick="show('${k}')">${v}</button>`).join(''); }
function show(v){ current=v; mountNav(); Object.keys(views).forEach(k=>$(k).classList.toggle('hidden',k!==v)); $('title').textContent=views[v]; render(); }
async function refresh(){ try{ setStatus('加载中...'); state.dashboard=await api('/api/dashboard'); state.metrics=await api('/metrics'); setStatus('已更新','ok'); render(); }catch(e){ setStatus(e.message,'err'); } }
function render(){ if(!state.dashboard) return; const d=state.dashboard; $('overview').innerHTML=`<div class="grid"><div class="card"><h2>${d.rows.length}</h2><p>records</p></div><div class="card"><h2>${Object.keys(d.type_counts||{}).length}</h2><p>types</p></div><div class="card"><h2>${d.mailbox.length}</h2><p>messages</p></div><div class="card"><h2>${d.presence.length}</h2><p>agents</p></div></div>`; $('records').innerHTML=`<div class="grid"><div class="card stack"><h2>Create memory</h2><input id="mTitle" placeholder="title"><textarea id="mContent" placeholder="content"></textarea><select id="mType"><option>project_memory</option><option>feedback</option><option>decision</option><option>user_profile</option></select><button class="primary" onclick="createMemory()">创建</button></div><div class="card stack"><h2>Search</h2><input id="q" placeholder="query"><button onclick="searchMemories()">搜索</button></div></div><div id="recordList" class="records">${recordHtml(d.rows)}</div>`; $('curator').innerHTML=`<div class="grid"><div class="card"><h2>Action plan</h2>${(d.report.action_plan||[]).map(a=>`<p><span class="pill">${esc(a.action)}</span> ${esc(a.title||a.id)} · ${esc(a.reason)}</p>`).join('')||'<p class="muted">无计划动作</p>'}</div><div class="card stack"><h2>Apply curator</h2><p class="muted">会执行当前低风险 status transition。</p><button class="primary" onclick="applyCurator()">执行 apply</button></div></div>`; $('agents').innerHTML=`<div class="grid"><div class="card"><h2>Presence</h2>${d.presence.map(a=>`<p><b>${esc(a.agent_id)}</b> <span class="pill">${esc(a.status)}</span></p>`).join('')||'<p class="muted">无</p>'}</div><div class="card"><h2>Mailbox</h2>${d.mailbox.map(m=>`<p><b>${esc(m.subject)}</b><br><span class="muted">${esc(m.from_agent)} → ${esc(m.to_agent)}</span></p>`).join('')||'<p class="muted">无</p>'}</div></div>`; $('ops').innerHTML=`<div class="grid"><div class="card stack"><h2>Export</h2><button onclick="downloadExport()">下载 JSON</button></div><div class="card stack"><h2>Backup</h2><button onclick="backup()">创建默认备份</button></div><div class="card stack"><h2>Vector rebuild</h2><button onclick="vectorDryRun()">Dry-run</button></div></div>`; $('rawOut').textContent=JSON.stringify(d,null,2); }
function recordHtml(rows){ return rows.slice(0,80).map(r=>`<article class="record"><h3>${esc(r.title)}</h3><p>${esc(r.content)}</p><span class="pill">${esc(r.type)}</span> <span class="pill">${esc(r.status)}</span><br><code>${esc(r.id)}</code></article>`).join(''); }
async function createMemory(){ await api('/api/memories',{method:'POST',body:JSON.stringify({title:$('mTitle').value,content:$('mContent').value,type:$('mType').value,source_agent:'frontend'})}); await refresh(); }
async function searchMemories(){ const rows=await api('/api/memories?query='+encodeURIComponent($('q').value)); $('recordList').innerHTML=recordHtml(rows); }
async function applyCurator(){ await api('/api/curator/apply',{method:'POST',body:JSON.stringify({})}); await refresh(); }
async function downloadExport(){ const data=await api('/api/export'); const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'}); const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='lmmcp-export.json'; a.click(); }
async function backup(){ alert(JSON.stringify(await api('/api/backup',{method:'POST',body:'{}'}),null,2)); }
async function vectorDryRun(){ alert(JSON.stringify(await api('/api/vector/rebuild',{method:'POST',body:JSON.stringify({dry_run:true})}),null,2)); }
mountNav(); refresh();
</script>
</body>
</html>"""
