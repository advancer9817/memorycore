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
async function downloadExport(){ const data=await api('/api/export'); const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'}); const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='mcore-export.json'; a.click(); }
async function backup(){ alert(JSON.stringify(await api('/api/backup',{method:'POST',body:'{}'}),null,2)); }
async function vectorDryRun(){ alert(JSON.stringify(await api('/api/vector/rebuild',{method:'POST',body:JSON.stringify({dry_run:true})}),null,2)); }
mountNav(); refresh();
</script>
</body>
</html>"""
