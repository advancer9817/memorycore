"use client";

import dynamic from "next/dynamic";
import { useEffect, useState, useRef, useCallback, useMemo } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { getApiBaseUrl } from "@/lib/api-url";
import {
  type GraphNode,
  type GraphEdge,
  TYPE_COLORS,
  EDGE_COLORS,
  IMPORTANCE_THRESHOLD,
} from "./types";
import type { Graph3DHandle } from "./Graph3D";

function useResizable(initial: number, min: number, max: number, direction: "right" | "left") {
  const [size, setSize] = useState(initial);
  const dragging = useRef(false);
  const startX = useRef(0);
  const startSize = useRef(initial);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    startX.current = e.clientX;
    startSize.current = size;
    const onMove = (ev: MouseEvent) => {
      if (!dragging.current) return;
      const delta = direction === "right" ? ev.clientX - startX.current : startX.current - ev.clientX;
      setSize(Math.min(max, Math.max(min, startSize.current + delta)));
    };
    const onUp = () => {
      dragging.current = false;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [size, min, max, direction]);

  return { size, onMouseDown };
}

const Graph3D = dynamic(() => import("./Graph3D"), { ssr: false });

interface GraphData { nodes: GraphNode[]; edges: GraphEdge[]; }

export default function GraphPage() {
  const [data, setData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [activeTypes, setActiveTypes] = useState<Set<string>>(new Set());
  const [activeEdgeTypes, setActiveEdgeTypes] = useState<Set<string>>(new Set());
  const [activeStatus, setActiveStatus] = useState<string>("all");
  const [highlightImportant, setHighlightImportant] = useState(false);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [fullContent, setFullContent] = useState<string | null>(null);
  const [listCollapsed, setListCollapsed] = useState(false);
  const [graphReady, setGraphReady] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editImportance, setEditImportance] = useState(0.5);
  const [editStatus, setEditStatus] = useState("active");
  const [showHud, setShowHud] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ w: 900, h: 600 });
  const listItemRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const listScrollRef = useRef<HTMLDivElement>(null);

  const [filtersOpen, setFiltersOpen] = useState(false);

  const listPanel = useResizable(260, 160, 420, "right");
  const detailPanel = useResizable(320, 220, 500, "left");
  // onMount prop pattern: avoids forwardRef + next/dynamic HOC ref-transparency issue
  const graph3DHandleRef = useRef<Graph3DHandle | null>(null);

  useEffect(() => {
    const id = setTimeout(() => setSearch(searchInput), 300);
    return () => clearTimeout(id);
  }, [searchInput]);

  useEffect(() => {
    fetch(`${getApiBaseUrl()}/api/graph`)
      .then((r) => r.json())
      .then((p) => {
        const raw = p.data ?? p;
        const nodeIds = new Set(raw.nodes.map((n: GraphNode) => n.id));
        const safeEdges = raw.edges.filter((e: GraphEdge) => nodeIds.has(e.source) && nodeIds.has(e.target));
        setData({ nodes: raw.nodes, edges: safeEdges });
        setActiveTypes(new Set(raw.nodes.map((n: GraphNode) => n.type)));
        setActiveEdgeTypes(new Set(safeEdges.map((e: GraphEdge) => e.relation_type)));
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setDims({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setDims({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (!selectedNode) { setFullContent(null); return; }
    setFullContent(null);
    setIsEditing(false);
    fetch(`${getApiBaseUrl()}/api/v1/memories/${selectedNode.id}`)
      .then((r) => r.json())
      .then((p) => { const rec = p.data ?? p; setFullContent(rec.content ?? rec.text ?? selectedNode.content); })
      .catch(() => setFullContent(selectedNode.content));
  }, [selectedNode?.id]);

  useEffect(() => {
    if (selectedNode) { setEditImportance(selectedNode.importance); setEditStatus(selectedNode.status ?? "active"); }
  }, [selectedNode?.id]);

  const connectedIds = useCallback((): Set<string> | null => {
    if (!selectedNode || !data) return null;
    const ids = new Set<string>();
    ids.add(selectedNode.id);
    for (const e of data.edges) {
      if (e.source === selectedNode.id) ids.add(e.target as string);
      if (e.target === selectedNode.id) ids.add(e.source as string);
    }
    return ids;
  }, [selectedNode, data]);

  const toggleType = useCallback((t: string) => setActiveTypes(prev => { const n = new Set(prev); n.has(t) ? n.delete(t) : n.add(t); return n; }), []);
  const toggleEdgeType = useCallback((t: string) => setActiveEdgeTypes(prev => { const n = new Set(prev); n.has(t) ? n.delete(t) : n.add(t); return n; }), []);

  const resetAll = useCallback(() => {
    if (data) { setActiveTypes(new Set(data.nodes.map(n => n.type))); setActiveEdgeTypes(new Set(data.edges.map(e => e.relation_type))); }
    setSearch(""); setSearchInput(""); setHighlightImportant(false); setSelectedNode(null); setActiveStatus("all");
  }, [data]);

  const allTypes = useMemo(() => data ? Array.from(new Set(data.nodes.map(n => n.type))).sort() : [], [data]);
  const allEdgeTypes = useMemo(() => data ? Array.from(new Set(data.edges.map(e => e.relation_type))).sort() : [], [data]);

  const filteredNodes = useMemo(() => data ? data.nodes.filter(n => {
    if (!activeTypes.has(n.type)) return false;
    if (activeStatus !== "all" && n.status !== activeStatus) return false;
    if (highlightImportant && n.importance < IMPORTANCE_THRESHOLD) return false;
    if (search.length > 1) { const q = search.toLowerCase(); return n.title.toLowerCase().includes(q) || n.type.toLowerCase().includes(q) || n.content.toLowerCase().includes(q); }
    return true;
  }) : [], [data, activeTypes, activeStatus, highlightImportant, search]);

  const sortedListNodes = useMemo(() => [...filteredNodes].sort((a, b) => b.importance - a.importance), [filteredNodes]);
  const filteredNodeIds = useMemo(() => new Set(filteredNodes.map(n => n.id)), [filteredNodes]);
  const filteredEdges = useMemo(() => data ? data.edges.filter(e => activeEdgeTypes.has(e.relation_type) && filteredNodeIds.has(e.source) && filteredNodeIds.has(e.target)) : [], [data, activeEdgeTypes, filteredNodeIds]);
  const importantCount = useMemo(() => data ? data.nodes.filter(n => n.importance >= IMPORTANCE_THRESHOLD).length : 0, [data]);

  const rowVirtualizer = useVirtualizer({
    count: sortedListNodes.length,
    getScrollElement: () => listScrollRef.current,
    estimateSize: () => 52,
    overscan: 5,
  });

  const handleNodeSelect = useCallback((node: GraphNode) => {
    setSelectedNode(prev => {
      if (prev?.id === node.id) return null;
      setTimeout(() => {
        const idx = sortedListNodes.findIndex(n => n.id === node.id);
        if (idx >= 0) rowVirtualizer.scrollToIndex(idx, { align: "auto" });
        graph3DHandleRef.current?.focusNode(node.id);
      }, 50);
      return node;
    });
  }, [sortedListNodes, rowVirtualizer]);

  const handleExportJson = useCallback(() => {
    if (!data) return;
    const blob = new Blob([JSON.stringify({ nodes: filteredNodes, edges: filteredEdges }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = "memory-graph.json"; a.click();
    URL.revokeObjectURL(url);
  }, [data, filteredNodes, filteredEdges]);

  const linked = connectedIds();

  return (
    <div className="flex flex-col h-[calc(100vh-56px)] bg-[#020408]">

      {/* ══ Topbar: brand · search(center) · actions ══ */}
      <div className="flex items-center gap-3 px-4 h-12 shrink-0" style={{ borderBottom: "1px solid rgba(255,255,255,0.06)", background: "#05070c" }}>

        {/* List collapse toggle — in topbar, left of brand */}
        <button
          onClick={() => setListCollapsed(v => !v)}
          className="shrink-0 w-7 h-7 flex items-center justify-center rounded-md transition-all hover:bg-white/5"
          style={{ border: "1px solid rgba(255,255,255,0.07)", color: "#52525b", fontSize: 12 }}
          title={listCollapsed ? "展开列表" : "折叠列表"}
        >{listCollapsed ? "›" : "‹"}</button>

        {/* Brand */}
        <div className="flex items-center gap-2 shrink-0">
          <span className="w-1.5 h-1.5 rounded-full bg-cyan-500 animate-pulse" />
          <span className="font-mono text-xs font-bold uppercase tracking-[0.15em] text-cyan-500/70 select-none">
            NeuralGraph
          </span>
        </div>

        {/* Divider */}
        <span className="w-px h-4 bg-white/8 shrink-0" />

        {/* Search — takes remaining space, centered feel */}
        <div className="flex-1 max-w-lg mx-auto">
          <Input
            className="w-full h-8 rounded-lg text-sm text-zinc-200 placeholder:text-zinc-600"
            style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
            placeholder="搜索记忆标题、内容、类型…"
            value={searchInput}
            onChange={e => setSearchInput(e.target.value)}
          />
        </div>

        {/* Divider */}
        <span className="w-px h-4 bg-white/8 shrink-0" />

        {/* Action buttons */}
        <div className="flex items-center gap-1 shrink-0">
          {data && (
            <span className="font-mono text-xs text-zinc-600 mr-2 select-none whitespace-nowrap">
              <span className="text-zinc-400">{filteredNodes.length}</span>
              <span className="text-zinc-700">/{data.nodes.length}</span>
              <span className="mx-1.5 text-zinc-800">·</span>
              <span className="text-zinc-400">{filteredEdges.length}</span>
              <span className="text-zinc-700"> links</span>
            </span>
          )}

          <button
            onClick={() => setHighlightImportant(v => !v)}
            className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md transition-all"
            style={{
              color: highlightImportant ? "#FBBF24" : "#52525b",
              background: highlightImportant ? "rgba(251,191,36,0.08)" : "transparent",
              border: `1px solid ${highlightImportant ? "rgba(251,191,36,0.2)" : "rgba(255,255,255,0.06)"}`,
            }}
          >
            <span>★</span>
            <span className="font-mono tabular-nums">{importantCount}</span>
          </button>

          <button
            onClick={resetAll}
            className="text-xs text-zinc-500 hover:text-zinc-200 px-2.5 py-1.5 rounded-md hover:bg-white/5 transition-all"
            style={{ border: "1px solid rgba(255,255,255,0.06)" }}
          >重置</button>

          <button
            onClick={handleExportJson}
            className="text-xs text-zinc-500 hover:text-zinc-200 px-2.5 py-1.5 rounded-md hover:bg-white/5 transition-all"
            style={{ border: "1px solid rgba(255,255,255,0.06)" }}
          >导出</button>
        </div>
      </div>

      {/* ══ Main area ══ */}
      <div className="flex-1 relative overflow-hidden">

        {/* 3D canvas */}
        <div ref={containerRef} className="absolute inset-0">
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="font-mono text-xs text-zinc-700 tracking-widest">LOADING…</span>
            </div>
          )}
          {error && (
            <div className="absolute inset-0 flex items-center justify-center text-red-500 text-sm">{error}</div>
          )}
          {data && (
            <>
              {!graphReady && (
                <div className="absolute inset-0 flex items-center justify-center z-10" style={{ background: "rgba(2,4,8,0.7)" }}>
                  <div className="flex items-center gap-2 font-mono text-xs text-cyan-700">
                    <span className="w-1 h-1 rounded-full bg-cyan-500 animate-pulse" />
                    COMPUTING LAYOUT…
                  </div>
                </div>
              )}
              <Graph3D
                onMount={(h) => { graph3DHandleRef.current = h; }}
                nodes={filteredNodes}
                links={filteredEdges}
                search={search}
                highlightImportant={highlightImportant}
                selectedNodeId={selectedNode?.id ?? null}
                linkedNodeIds={linked}
                width={dims.w}
                height={dims.h}
                onNodeClick={handleNodeSelect}
                onBackgroundClick={() => setSelectedNode(null)}
                onReady={() => setGraphReady(true)}
              />
            </>
          )}
        </div>

        {/* ══ Left panel: filters + list ══ */}
        {!listCollapsed && (
          <div
            className="absolute left-0 top-0 bottom-0 z-20 flex flex-col overflow-hidden"
            style={{
              width: listPanel.size,
              background: "rgba(3,5,10,0.94)",
              backdropFilter: "blur(16px)",
              borderRight: "1px solid rgba(255,255,255,0.06)",
            }}
          >
            {/* ── Filter section (collapsible) ── */}
            <div className="shrink-0" style={{ borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
              <button
                onClick={() => setFiltersOpen(v => !v)}
                className="w-full flex items-center justify-between px-3 py-2 text-xs font-mono uppercase tracking-widest transition-colors hover:bg-white/3"
                style={{ color: filtersOpen ? "#06B6D4" : "#52525b" }}
              >
                <span className="flex items-center gap-1.5">
                  <span style={{ fontSize: 9 }}>{filtersOpen ? "▾" : "▸"}</span>
                  FILTER
                  {/* Active filter badge */}
                  {(activeTypes.size < allTypes.length || activeEdgeTypes.size < allEdgeTypes.length || activeStatus !== "all") && (
                    <span className="w-1.5 h-1.5 rounded-full bg-cyan-500" />
                  )}
                </span>
              </button>

              {filtersOpen && (
                <div className="px-3 pb-3 space-y-3">
                  {/* Type filters */}
                  <div>
                    <p className="text-[10px] font-mono text-zinc-700 uppercase tracking-widest mb-1.5">节点类型</p>
                    <div className="flex flex-wrap gap-1">
                      {allTypes.map(t => {
                        const active = activeTypes.has(t);
                        const color = TYPE_COLORS[t] ?? "#64748B";
                        return (
                          <button key={t} onClick={() => toggleType(t)}
                            className="flex items-center gap-1 rounded px-1.5 py-0.5 text-xs transition-all"
                            style={{ color: active ? color : "#52525b", background: active ? `${color}15` : "rgba(255,255,255,0.03)", border: `1px solid ${active ? `${color}30` : "rgba(255,255,255,0.06)"}` }}
                          >
                            <span className="w-1 h-1 rounded-full shrink-0" style={{ background: active ? color : "#3f3f46" }} />
                            {t.replace(/_/g, " ")}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Edge type filters */}
                  <div>
                    <p className="text-[10px] font-mono text-zinc-700 uppercase tracking-widest mb-1.5">连接类型</p>
                    <div className="flex flex-wrap gap-1">
                      {allEdgeTypes.map(e => {
                        const active = activeEdgeTypes.has(e);
                        const color = EDGE_COLORS[e] ?? "#52525b";
                        return (
                          <button key={e} onClick={() => toggleEdgeType(e)}
                            className="rounded px-1.5 py-0.5 text-xs transition-all"
                            style={{ color: active ? color : "#52525b", background: active ? `${color}15` : "rgba(255,255,255,0.03)", border: `1px solid ${active ? `${color}30` : "rgba(255,255,255,0.06)"}` }}
                          >
                            {e.replace(/_/g, " ")}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Status filter */}
                  <div>
                    <p className="text-[10px] font-mono text-zinc-700 uppercase tracking-widest mb-1.5">状态</p>
                    <div className="flex gap-1">
                      {(["all", "active", "candidate", "stale"] as const).map(s => (
                        <button key={s} onClick={() => setActiveStatus(s)}
                          className="rounded px-2 py-0.5 text-xs transition-all"
                          style={{
                            color: activeStatus === s ? "#60A5FA" : "#52525b",
                            background: activeStatus === s ? "rgba(96,165,250,0.1)" : "rgba(255,255,255,0.03)",
                            border: `1px solid ${activeStatus === s ? "rgba(96,165,250,0.25)" : "rgba(255,255,255,0.06)"}`,
                          }}
                        >{s}</button>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* ── Node list ── */}
            <div className="px-3 py-2 shrink-0 flex items-center" style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
              <span className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">
                NODES <span className="text-zinc-400">{sortedListNodes.length}</span>
              </span>
            </div>

            <div ref={listScrollRef} className="flex-1 overflow-y-auto">
              {sortedListNodes.length === 0 && (
                <div className="px-3 py-8 text-center text-xs text-zinc-700 font-mono">
                  无匹配节点<br />
                  <span className="text-zinc-800">尝试调整筛选条件</span>
                </div>
              )}
              <div
                style={{
                  height: `${rowVirtualizer.getTotalSize()}px`,
                  width: "100%",
                  position: "relative",
                }}
              >
                {rowVirtualizer.getVirtualItems().map((virtualRow) => {
                  const node = sortedListNodes[virtualRow.index];
                  const color = TYPE_COLORS[node.type] ?? "#64748B";
                  const isSelected = selectedNode?.id === node.id;
                  const isLinked = linked && !isSelected && linked.has(node.id);
                  return (
                    <div
                      key={node.id}
                      ref={el => { listItemRefs.current[node.id] = el; }}
                      onClick={() => handleNodeSelect(node)}
                      className="px-3 py-2.5 cursor-pointer transition-all absolute top-0 left-0 right-0"
                      style={{
                        transform: `translateY(${virtualRow.start}px)`,
                        borderBottom: "1px solid rgba(255,255,255,0.03)",
                        borderLeft: isSelected ? `2px solid ${color}` : "2px solid transparent",
                        background: isSelected ? `${color}10` : isLinked ? "rgba(255,255,255,0.02)" : "transparent",
                      }}
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="w-2 h-2 rounded-full shrink-0 flex-none" style={{ background: color }} />
                        <p className="text-sm text-zinc-200 leading-tight truncate flex-1 min-w-0">{node.title}</p>
                        {node.importance >= IMPORTANCE_THRESHOLD && <span className="text-amber-400 text-xs shrink-0">★</span>}
                        <span className="text-xs text-zinc-500 shrink-0 font-mono tabular-nums">{node.importance.toFixed(2)}</span>
                      </div>
                      <div className="ml-4 mt-0.5 text-xs text-zinc-700">{node.type.replace(/_/g, " ")}</div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Resize handle */}
            <div onMouseDown={listPanel.onMouseDown} className="absolute top-0 right-0 bottom-0 w-1 cursor-col-resize hover:bg-cyan-500/20 transition-colors" />
          </div>
        )}

        {/* ══ Right detail panel ══ */}
        {selectedNode && (
          <div className="absolute right-0 top-0 bottom-0 z-20 flex" style={{ width: detailPanel.size }}>
            <div onMouseDown={detailPanel.onMouseDown} className="shrink-0 w-1 cursor-col-resize hover:bg-cyan-500/20 transition-colors" />

            <div className="flex-1 flex flex-col overflow-hidden" style={{ background: "rgba(3,5,10,0.95)", backdropFilter: "blur(16px)", borderLeft: "1px solid rgba(255,255,255,0.06)" }}>

              {/* Detail header */}
              <div className="px-4 py-4 shrink-0" style={{ borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
                <div className="flex items-start justify-between gap-2 mb-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-[10px] font-mono uppercase tracking-[0.12em] mb-1" style={{ color: TYPE_COLORS[selectedNode.type] ?? "#64748B" }}>
                      {selectedNode.type.replace(/_/g, " ")}
                    </p>
                    <h2 className="text-sm font-semibold text-zinc-100 leading-snug">{selectedNode.title}</h2>
                  </div>
                  <div className="flex items-center gap-1 shrink-0 mt-0.5">
                    {!isEditing && (
                      <button onClick={() => setIsEditing(true)}
                        className="text-xs text-zinc-600 hover:text-zinc-300 px-2 py-1 rounded transition-all"
                        style={{ border: "1px solid rgba(255,255,255,0.07)" }}>
                        编辑
                      </button>
                    )}
                    <button onClick={() => setSelectedNode(null)}
                      className="text-zinc-600 hover:text-zinc-200 w-7 h-7 flex items-center justify-center rounded text-base transition-all hover:bg-white/5">×</button>
                  </div>
                </div>

                {/* Importance bar */}
                <div className="flex items-center gap-3">
                  <div className="flex-1 h-1 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.06)" }}>
                    <div className="h-full rounded-full transition-all" style={{ width: `${selectedNode.importance * 100}%`, background: selectedNode.importance >= IMPORTANCE_THRESHOLD ? "#FBBF24" : TYPE_COLORS[selectedNode.type] ?? "#06B6D4" }} />
                  </div>
                  <span className="font-mono text-xs text-zinc-500 tabular-nums shrink-0 w-9 text-right">{(selectedNode.importance * 100).toFixed(0)}%</span>
                </div>
              </div>

              {/* Detail body */}
              <div className="flex-1 overflow-y-auto px-4 py-4 space-y-5">
                {isEditing ? (
                  <div className="space-y-4">
                    <div>
                      <label className="text-[10px] text-zinc-600 block mb-2 font-mono uppercase tracking-widest">重要性 {editImportance.toFixed(1)}</label>
                      <input type="range" min="0" max="1" step="0.1" value={editImportance} onChange={e => setEditImportance(parseFloat(e.target.value))} className="w-full accent-cyan-500" />
                    </div>
                    <div>
                      <label className="text-[10px] text-zinc-600 block mb-2 font-mono uppercase tracking-widest">状态</label>
                      <select value={editStatus} onChange={e => setEditStatus(e.target.value)}
                        className="w-full text-sm rounded-lg px-3 py-2"
                        style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.1)", color: "#d4d4d8" }}>
                        {["active", "candidate", "stale", "archived"].map(s => <option key={s} value={s}>{s}</option>)}
                      </select>
                    </div>
                    <div className="flex gap-2">
                      <Button size="sm" className="flex-1 h-8 text-xs bg-cyan-600 hover:bg-cyan-700 text-white border-0"
                        onClick={() => {
                          fetch(`${getApiBaseUrl()}/api/v1/memories/${selectedNode.id}`, {
                            method: "PATCH",
                            body: JSON.stringify({ importance: editImportance, status: editStatus }),
                            headers: { "Content-Type": "application/json" },
                          }).then(() => {
                            setData(prev => prev ? { ...prev, nodes: prev.nodes.map(n => n.id === selectedNode.id ? { ...n, importance: editImportance, status: editStatus } : n) } : prev);
                            setSelectedNode(prev => prev ? { ...prev, importance: editImportance, status: editStatus } : prev);
                            setIsEditing(false);
                          }).catch(() => {});
                        }}>保存</Button>
                      <Button size="sm" variant="outline" className="flex-1 h-8 text-xs border-white/10 text-zinc-400" onClick={() => setIsEditing(false)}>取消</Button>
                    </div>
                  </div>
                ) : (
                  <>
                    {/* Content */}
                    <div>
                      <p className="text-[10px] font-mono uppercase tracking-widest text-zinc-700 mb-2">内容</p>
                      <p className="text-sm text-zinc-300 leading-relaxed whitespace-pre-wrap break-words">
                        {fullContent ?? selectedNode.content ?? "加载中…"}
                      </p>
                    </div>

                    {/* Stats */}
                    <div className="grid grid-cols-3 gap-2">
                      {[
                        ["反馈", selectedNode.feedback_score >= 0 ? `+${selectedNode.feedback_score.toFixed(1)}` : selectedNode.feedback_score.toFixed(1)],
                        ["注入", `${selectedNode.injected_count}×`],
                        ["状态", selectedNode.status],
                      ].map(([label, value]) => (
                        <div key={label} className="rounded-lg px-3 py-2.5" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)" }}>
                          <div className="text-[10px] text-zinc-600 font-mono uppercase tracking-wider">{label}</div>
                          <div className="text-sm text-zinc-200 font-medium mt-1">{value}</div>
                        </div>
                      ))}
                    </div>

                    {/* HUD — collapsed by default */}
                    <div>
                      <button onClick={() => setShowHud(v => !v)}
                        className="flex items-center gap-1.5 text-[10px] font-mono text-zinc-700 hover:text-zinc-500 uppercase tracking-widest transition-colors">
                        <span style={{ fontSize: 8 }}>{showHud ? "▾" : "▸"}</span> HUD DATA
                      </button>
                      {showHud && (
                        <div className="mt-2 rounded-lg font-mono text-xs" style={{ padding: "8px 10px", background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)" }}>
                          <div className="flex justify-between py-0.5">
                            <span className="text-zinc-700">LOC_ADDR</span>
                            <span className="text-cyan-500">0x{selectedNode.id.replace(/-/g, "").slice(0, 8).toUpperCase()}</span>
                          </div>
                          <div className="flex justify-between py-0.5">
                            <span className="text-zinc-700">NODE_VEC (sim)</span>
                            <span className="text-zinc-500">{getMockCoords(selectedNode.id)}<span className="text-zinc-700 text-[9px] ml-1">(模拟)</span></span>
                          </div>
                        </div>
                      )}
                    </div>

                    {/* Related nodes */}
                    {linked && linked.size > 1 && (
                      <div>
                        <p className="text-[10px] font-mono uppercase tracking-widest text-zinc-700 mb-2">关联 ({linked.size - 1})</p>
                        <div className="space-y-0.5">
                          {filteredNodes.filter(n => linked.has(n.id) && n.id !== selectedNode.id).slice(0, 8).map(n => (
                            <button key={n.id} onClick={() => handleNodeSelect(n)}
                              className="w-full text-left px-2 py-2 rounded-lg flex items-center gap-2 transition-colors hover:bg-white/4"
                              style={{ border: "1px solid transparent" }}
                              onMouseEnter={e => (e.currentTarget.style.borderColor = "rgba(255,255,255,0.06)")}
                              onMouseLeave={e => (e.currentTarget.style.borderColor = "transparent")}
                            >
                              <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: TYPE_COLORS[n.type] ?? "#64748B" }} />
                              <span className="text-xs text-zinc-400 truncate">{n.title}</span>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function getMockCoords(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = id.charCodeAt(i) + ((h << 5) - h);
  return `[${((h & 0xFF) / 10).toFixed(1)}, ${(((h >> 8) & 0xFF) / 10).toFixed(1)}, ${(((h >> 16) & 0xFF) / 10).toFixed(1)}]`;
}
