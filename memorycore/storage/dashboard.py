"""HTML dashboard export."""
from __future__ import annotations

import html
import json
from pathlib import Path

from memorycore.storage.db import db_path, read_conn
from memorycore.storage.crud import list_recent
from memorycore.storage.curator import curator_report
from memorycore.storage.search import get_context_quality_stats


def dashboard_payload(limit: int = 1000) -> dict[str, object]:
    cap = max(1, min(int(limit), 5000))
    rows = list_recent(cap)
    report = curator_report(dry_run=True, limit=cap)
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
    with read_conn() as conn:
        links = [dict(r) for r in conn.execute("SELECT * FROM memory_links ORDER BY created_at DESC LIMIT 200").fetchall()]
        mailbox = [dict(r) for r in conn.execute("SELECT * FROM agent_messages ORDER BY created_at DESC, rowid DESC LIMIT 100").fetchall()]
        presence = [dict(r) for r in conn.execute("SELECT * FROM agent_presence ORDER BY last_seen_at DESC LIMIT 100").fetchall()]
    return {
        "rows": rows,
        "report": report,
        "semantic": {"available": False, "note": "vector search via Qdrant (vector_store.py)"},
        "type_counts": type_counts,
        "status_counts": status_counts,
        "timeline_rows": timeline_rows,
        "links": links,
        "mailbox": mailbox,
        "presence": presence,
        "context_quality": get_context_quality_stats(),
        "feedback_positive": feedback_positive,
        "feedback_negative": feedback_negative,
    }


def export_html(path: Path) -> None:
    payload = dashboard_payload(1000)
    rows = payload["rows"]
    type_counts = payload["type_counts"]
    data_json = json.dumps(payload, ensure_ascii=True).replace("<", "\\u003c")
    db_label = html.escape(str(db_path()))
    doc = _DASHBOARD_HTML_TEMPLATE()
    replacements = {
        "__DATA_JSON__": data_json,
        "__RECORD_COUNT__": str(len(rows)),
        "__TYPE_COUNT__": str(len(type_counts)),
        "__POSITIVE_FEEDBACK__": str(payload["feedback_positive"]),
        "__NEGATIVE_FEEDBACK__": str(payload["feedback_negative"]),
        "__DB_PATH__": db_label,
    }
    for key, value in replacements.items():
        doc = doc.replace(key, value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8")
    print(path)


def _DASHBOARD_HTML_TEMPLATE() -> str:
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
      <button type="button" :class="{active:view==='graph'}" @click="view='graph'"><span>Graph</span><span class="pill" x-text="links.length"></span></button>
      <button type="button" :class="{active:view==='mailbox'}" @click="view='mailbox'"><span>Mailbox</span><span class="pill" x-text="mailbox.length"></span></button>
      <button type="button" :class="{active:view==='presence'}" @click="view='presence'"><span>Presence</span><span class="pill" x-text="presence.length"></span></button>
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
    <section x-show="view==='health'"><div class="content-head"><div><h2>Feedback health</h2><p>分布视图帮助判断记忆库是否偏科、陈旧或反馈不足。</p></div></div><div class="split"><div class="panel" style="padding:18px"><h3>Type distribution</h3><div class="bars"><template x-for="item in bars(typeCounts)" :key="item.key"><div class="bar"><span x-text="item.key"></span><div class="track"><div class="fill" :style="`width:${item.width}%`"></div></div><strong x-text="item.value"></strong></div></template></div></div><div class="panel" style="padding:18px"><h3>Status distribution</h3><div class="bars"><template x-for="item in bars(statusCounts)" :key="item.key"><div class="bar"><span x-text="item.key"></span><div class="track"><div class="fill" :style="`width:${item.width}%`"></div></div><strong x-text="item.value"></strong></div></template></div></div></div><div class="content-head"><div><h2>Feedback drilldown</h2><p>Context pack 质量趋势：hit/filter/ineffective rate。</p></div></div><div class="grid"><article class="record"><h3>Context quality</h3><p x-text="`packs ${contextQuality.total_packs || 0}, hit ${contextQuality.avg_hit_rate || 0}, filter ${contextQuality.avg_filter_rate || 0}, ineffective ${contextQuality.avg_ineffective_rate || 0}`"></p></article><template x-for="item in bars(contextQuality.by_task_type || {})" :key="item.key"><article class="record"><h3 x-text="item.key"></h3><p x-text="JSON.stringify((contextQuality.by_task_type || {})[item.key])"></p></article></template></div></section>
    <section x-show="view==='curator'"><div class="content-head"><div><h2>Curator candidates</h2><p>面向去重、归档、矛盾检测和 skill 推广的候选摘要。</p></div></div><div class="curator-grid"><template x-for="group in curatorGroups" :key="group.key"><article class="curator-card"><h3><span x-text="group.label"></span><span class="pill" x-text="group.items.length"></span></h3><template x-for="item in group.items.slice(0, 12)" :key="itemKey(item)"><p x-text="itemLabel(item)"></p></template><p x-show="group.items.length === 0" style="color:var(--sage)">无</p></article></template></div><div class="content-head"><div><h2>Action plan</h2><p>Curator dry-run preview，包含原因和 rollback metadata。</p></div></div><div class="grid"><template x-for="action in (report.action_plan || [])" :key="action.id + action.action"><article class="record"><h3 x-text="`${action.action}: ${action.title || action.id}`"></h3><p x-text="`reason=${action.reason}, rollback=${JSON.stringify(action.rollback || {})}`"></p></article></template></div></section>
    <section x-show="view==='graph'"><div class="content-head"><div><h2>Memory link graph</h2><p>最近的 memory_links 关系边。</p></div></div><div class="grid"><template x-for="link in links" :key="link.id"><article class="record"><h3 x-text="link.relation_type"></h3><p x-text="`${link.source_id} → ${link.target_id}`"></p><div class="meta"><span class="chip" x-text="`weight ${link.weight}`"></span><span class="chip" x-text="link.source_agent"></span></div></article></template></div><div class="empty" x-show="links.length === 0">暂无 memory links</div></section>
    <section x-show="view==='mailbox'"><div class="content-head"><div><h2>Mailbox inbox</h2><p>最近 agent_messages，包括 handoff workflow metadata。</p></div></div><div class="grid"><template x-for="msg in mailbox" :key="msg.id"><article class="record"><h3 x-text="msg.subject"></h3><p x-text="msg.body || JSON.stringify(msg.metadata || {})"></p><div class="meta"><span class="chip" x-text="msg.from_agent"></span><span class="chip" x-text="`to ${msg.to_agent}`"></span><span class="chip" x-text="msg.status"></span></div></article></template></div><div class="empty" x-show="mailbox.length === 0">暂无 mailbox 消息</div></section>
    <section x-show="view==='presence'"><div class="content-head"><div><h2>Agent presence</h2><p>在线状态与 namespace metadata。</p></div></div><div class="grid"><template x-for="agent in presence" :key="agent.agent_id"><article class="record"><h3 x-text="agent.agent_id"></h3><p x-text="JSON.stringify(agent.metadata || {})"></p><div class="meta"><span class="chip" x-text="agent.status"></span><span class="chip" x-text="agent.last_seen_at"></span></div></article></template></div><div class="empty" x-show="presence.length === 0">暂无 presence</div></section>
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
  const parseJson = (value, fallback) => { try { return JSON.parse(value || ''); } catch { return fallback; } };
  return {
    data, rows, report, semantic, view:'records', query:'', typeFilter:'', statusFilter:'', sortBy:'updated_at',
    links: data.links || [], mailbox: (data.mailbox || []).map(m => ({...m, metadata: parseJson(m.metadata_json, {})})), presence: (data.presence || []).map(p => ({...p, metadata: parseJson(p.metadata_json, {})})), contextQuality: data.context_quality || {},
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
