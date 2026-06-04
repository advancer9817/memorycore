"use client";

import dynamic from "next/dynamic";
import { useEffect, useState, useRef, useCallback, useMemo } from "react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getApiBaseUrl } from "@/lib/api-url";
import {
  type GraphNode,
  type GraphEdge,
  TYPE_COLORS,
  EDGE_COLORS,
  IMPORTANCE_THRESHOLD,
} from "./types";

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
      const delta = direction === "right"
        ? ev.clientX - startX.current
        : startX.current - ev.clientX;
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

interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export default function GraphPage() {
  const [data, setData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [activeTypes, setActiveTypes] = useState<Set<string>>(new Set());
  const [activeEdgeTypes, setActiveEdgeTypes] = useState<Set<string>>(new Set());
  const [highlightImportant, setHighlightImportant] = useState(false);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [fullContent, setFullContent] = useState<string | null>(null);
  const [listCollapsed, setListCollapsed] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ w: 900, h: 600 });
  const listItemRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const listPanel = useResizable(220, 120, 400, "right");
  const detailPanel = useResizable(280, 180, 480, "left");

  useEffect(() => {
    fetch(`${getApiBaseUrl()}/api/graph`)
      .then((r) => r.json())
      .then((p) => {
        const raw = p.data ?? p;
        const nodeIds = new Set(raw.nodes.map((n: GraphNode) => n.id));
        const safeEdges = raw.edges.filter(
          (e: GraphEdge) => nodeIds.has(e.source) && nodeIds.has(e.target)
        );
        const nodes: GraphNode[] = raw.nodes;
        setData({ nodes, edges: safeEdges });
        setActiveTypes(new Set(nodes.map((n) => n.type)));
        setActiveEdgeTypes(new Set(safeEdges.map((e: GraphEdge) => e.relation_type)));
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() =>
      setDims({ w: el.clientWidth, h: el.clientHeight })
    );
    ro.observe(el);
    setDims({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (!selectedNode) { setFullContent(null); return; }
    setFullContent(null);
    fetch(`${getApiBaseUrl()}/api/v1/memories/${selectedNode.id}`)
      .then((r) => r.json())
      .then((p) => {
        const rec = p.data ?? p;
        setFullContent(rec.content ?? rec.text ?? selectedNode.content);
      })
      .catch(() => setFullContent(selectedNode.content));
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

  const toggleType = useCallback((t: string) => {
    setActiveTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t); else next.add(t);
      return next;
    });
  }, []);

  const toggleEdgeType = useCallback((t: string) => {
    setActiveEdgeTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t); else next.add(t);
      return next;
    });
  }, []);

  const handleNodeSelect = useCallback((node: GraphNode) => {
    setSelectedNode((prev) => {
      if (prev?.id === node.id) return null;
      setTimeout(() => {
        listItemRefs.current[node.id]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }, 50);
      return node;
    });
  }, []);

  const allTypes = useMemo(
    () => (data ? Array.from(new Set(data.nodes.map((n) => n.type))).sort() : []),
    [data]
  );
  const allEdgeTypes = useMemo(
    () => (data ? Array.from(new Set(data.edges.map((e) => e.relation_type))).sort() : []),
    [data]
  );

  const filteredNodes = useMemo(
    () =>
      data
        ? data.nodes.filter((n) => {
            if (!activeTypes.has(n.type)) return false;
            if (highlightImportant && n.importance < IMPORTANCE_THRESHOLD) return false;
            if (search.length > 1) {
              const q = search.toLowerCase();
              return n.title.toLowerCase().includes(q) || n.type.toLowerCase().includes(q) || n.content.toLowerCase().includes(q);
            }
            return true;
          })
        : [],
    [data, activeTypes, highlightImportant, search]
  );

  const sortedListNodes = useMemo(
    () => [...filteredNodes].sort((a, b) => b.importance - a.importance),
    [filteredNodes]
  );

  const filteredNodeIds = useMemo(
    () => new Set(filteredNodes.map((n) => n.id)),
    [filteredNodes]
  );
  const filteredEdges = useMemo(
    () =>
      data
        ? data.edges.filter(
            (e) =>
              activeEdgeTypes.has(e.relation_type) &&
              filteredNodeIds.has(e.source) &&
              filteredNodeIds.has(e.target)
          )
        : [],
    [data, activeEdgeTypes, filteredNodeIds]
  );

  const importantCount = useMemo(
    () => (data ? data.nodes.filter((n) => n.importance >= IMPORTANCE_THRESHOLD).length : 0),
    [data]
  );
  const linked = connectedIds();

  return (
    <div className="flex flex-col h-[calc(100vh-56px)]">
      {/* Header */}
      <div className="relative flex items-center gap-3 px-4 py-2 border-b border-zinc-800 bg-zinc-950 shrink-0">
        <h1 className="text-sm font-semibold text-white whitespace-nowrap">Memory Graph</h1>
        {data && (
          <p className="text-xs text-zinc-500 whitespace-nowrap">
            {filteredNodes.length}/{data.nodes.length} · {filteredEdges.length} links
          </p>
        )}
        <div className="absolute right-4 top-1/2 -translate-y-1/2 flex items-center gap-2">
          <Button
            size="sm"
            variant={highlightImportant ? "default" : "outline"}
            className={highlightImportant
              ? "bg-amber-500 hover:bg-amber-600 text-black border-0 text-xs h-7 px-2"
              : "border-zinc-700 text-zinc-300 hover:text-white text-xs h-7 px-2"}
            onClick={() => setHighlightImportant((v) => !v)}
          >
            ★ {importantCount > 0 && `(${importantCount})`}
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="border-zinc-700 text-zinc-300 hover:text-white text-xs h-7 px-2"
            onClick={() => {
              if (data) {
                setActiveTypes(new Set(data.nodes.map((n) => n.type)));
                setActiveEdgeTypes(new Set(data.edges.map((e) => e.relation_type)));
              }
              setSearch("");
              setHighlightImportant(false);
              setSelectedNode(null);
            }}
          >
            重置
          </Button>
          <Input
            className="w-36 bg-zinc-900 border-zinc-700 text-zinc-100 placeholder:text-zinc-500 h-7 text-xs"
            placeholder="搜索…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-x-2 gap-y-1 px-4 py-1.5 border-b border-zinc-800 bg-zinc-950/80 shrink-0 items-center">
        <span className="text-xs text-zinc-500 shrink-0">类型:</span>
        {allTypes.map((t) => {
          const active = activeTypes.has(t);
          const color = TYPE_COLORS[t] ?? "#A0A09A";
          return (
            <button
              key={t}
              onClick={() => toggleType(t)}
              className="flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium transition-all border"
              style={{
                borderColor: active ? color : "#333",
                color: active ? color : "#555",
                background: active ? `${color}18` : "transparent",
              }}
            >
              <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: active ? color : "#444" }} />
              {t.replace(/_/g, " ")}
            </button>
          );
        })}
        <span className="ml-2 text-xs text-zinc-500 shrink-0">链接:</span>
        {allEdgeTypes.map((e) => {
          const active = activeEdgeTypes.has(e);
          const color = EDGE_COLORS[e] ?? "#888";
          return (
            <button
              key={e}
              onClick={() => toggleEdgeType(e)}
              className="flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium transition-all border"
              style={{
                borderColor: active ? color : "#333",
                color: active ? color : "#555",
                background: active ? `${color}18` : "transparent",
              }}
            >
              {e.replace(/_/g, " ")}
            </button>
          );
        })}
      </div>

      {/* Main area — relative container, everything inside is absolute overlay */}
      <div className="flex-1 relative overflow-hidden bg-zinc-950">
        {/* 3D Graph — fills entire area */}
        <div ref={containerRef} className="absolute inset-0">
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center text-zinc-400 z-10">
              加载图谱…
            </div>
          )}
          {error && (
            <div className="absolute inset-0 flex items-center justify-center text-red-400 z-10">
              {error}
            </div>
          )}
          {data && (
            <Graph3D
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
            />
          )}
        </div>

        {/* Left list panel — absolute overlay */}
        {!listCollapsed && (
          <div
            className="absolute left-0 top-0 bottom-0 z-20 bg-zinc-950/95 backdrop-blur-sm border-r border-zinc-800 flex flex-col overflow-hidden"
            style={{ width: listPanel.size }}
          >
            <div className="px-3 py-2 border-b border-zinc-800 shrink-0">
              <span className="text-xs text-zinc-400 font-medium">
                记忆列表 <span className="text-zinc-600">({sortedListNodes.length})</span>
              </span>
            </div>
            <div className="flex-1 overflow-y-auto">
              {sortedListNodes.map((node) => {
                const color = TYPE_COLORS[node.type] ?? "#A0A09A";
                const isSelected = selectedNode?.id === node.id;
                const isLinked = linked && !isSelected && linked.has(node.id);
                return (
                  <div
                    key={node.id}
                    ref={(el) => { listItemRefs.current[node.id] = el; }}
                    onClick={() => handleNodeSelect(node)}
                    className={`px-3 py-2 cursor-pointer border-b border-zinc-900/50 hover:bg-zinc-800/60 transition-colors ${
                      isSelected ? "bg-zinc-800 border-l-2" : isLinked ? "bg-zinc-800/30" : ""
                    }`}
                    style={isSelected ? { borderLeftColor: "#60A5FA" } : {}}
                  >
                    <div className="flex items-center gap-1.5 mb-0.5">
                      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: color }} />
                      <span className="text-xs text-zinc-500 truncate">{node.type.replace(/_/g, " ")}</span>
                      {node.importance >= IMPORTANCE_THRESHOLD && (
                        <span className="text-amber-400 text-xs ml-auto shrink-0">★</span>
                      )}
                    </div>
                    <p className="text-xs text-zinc-200 leading-snug line-clamp-2">{node.title}</p>
                    <div className="mt-0.5 text-xs text-zinc-600">{node.importance.toFixed(2)}</div>
                  </div>
                );
              })}
            </div>
            {/* Resize handle */}
            <div
              onMouseDown={listPanel.onMouseDown}
              className="absolute top-0 right-0 bottom-0 w-1 cursor-col-resize hover:bg-blue-500/50 active:bg-blue-500/70 transition-colors"
            />
          </div>
        )}

        {/* List collapse toggle — absolute, hugs list edge */}
        <button
          onClick={() => setListCollapsed((v) => !v)}
          className="absolute top-3 z-30 w-5 h-8 rounded-r-md bg-zinc-800/90 hover:bg-zinc-700 border border-l-0 border-zinc-700 flex items-center justify-center text-zinc-400 hover:text-zinc-100 transition-colors text-xs backdrop-blur-sm"
          style={{ left: listCollapsed ? 0 : listPanel.size }}
          title={listCollapsed ? "展开列表" : "折叠列表"}
        >
          {listCollapsed ? "›" : "‹"}
        </button>

        {/* Right detail panel — absolute overlay */}
        {selectedNode && (
          <div
            className="absolute right-0 top-0 bottom-0 z-20 flex"
            style={{ width: detailPanel.size }}
          >
            {/* Resize handle */}
            <div
              onMouseDown={detailPanel.onMouseDown}
              className="shrink-0 w-1 cursor-col-resize hover:bg-blue-500/50 active:bg-blue-500/70 transition-colors"
            />
            <div className="flex-1 bg-zinc-950/95 backdrop-blur-sm border-l border-zinc-800 flex flex-col overflow-hidden shadow-2xl">
              <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800 shrink-0">
                <span className="text-xs font-semibold text-zinc-200 truncate mr-2">{selectedNode.title}</span>
                <button
                  onClick={() => setSelectedNode(null)}
                  className="shrink-0 text-zinc-500 hover:text-zinc-200 text-base leading-none"
                >
                  ×
                </button>
              </div>
              <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
                <Badge
                  variant="outline"
                  className="text-xs"
                  style={{ color: TYPE_COLORS[selectedNode.type] ?? "#aaa", borderColor: TYPE_COLORS[selectedNode.type] ?? "#555" }}
                >
                  {selectedNode.type.replace(/_/g, " ")}
                </Badge>

                <div className="rounded-md bg-zinc-900/80 px-3 py-2">
                  <div className="text-xs text-zinc-500 mb-1">内容</div>
                  <p className="text-xs text-zinc-300 leading-relaxed whitespace-pre-wrap break-words">
                    {fullContent ?? selectedNode.content ?? "加载中…"}
                  </p>
                </div>

                <div>
                  <div className="flex justify-between text-xs text-zinc-500 mb-1">
                    <span>重要性</span>
                    <span>{(selectedNode.importance * 100).toFixed(0)}%</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-zinc-800 overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all"
                      style={{
                        width: `${selectedNode.importance * 100}%`,
                        background: selectedNode.importance >= IMPORTANCE_THRESHOLD ? "#F59E0B" : TYPE_COLORS[selectedNode.type] ?? "#6B9E78",
                      }}
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <Stat label="反馈分" value={selectedNode.feedback_score >= 0 ? `+${selectedNode.feedback_score.toFixed(1)}` : selectedNode.feedback_score.toFixed(1)} />
                  <Stat label="注入次数" value={String(selectedNode.injected_count)} />
                  <Stat label="状态" value={selectedNode.status} />
                  <Stat label="重要性" value={selectedNode.importance.toFixed(2)} highlight={selectedNode.importance >= IMPORTANCE_THRESHOLD} />
                </div>

                {linked && linked.size > 1 && (
                  <div>
                    <div className="text-xs text-zinc-500 mb-1">关联记忆 ({linked.size - 1})</div>
                    <div className="space-y-1">
                      {filteredNodes
                        .filter((n) => linked.has(n.id) && n.id !== selectedNode.id)
                        .slice(0, 6)
                        .map((n) => (
                          <button
                            key={n.id}
                            onClick={() => handleNodeSelect(n)}
                            className="w-full text-left rounded bg-zinc-900/80 px-2 py-1 hover:bg-zinc-800 transition-colors"
                          >
                            <div className="flex items-center gap-1 mb-0.5">
                              <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: TYPE_COLORS[n.type] ?? "#A0A09A" }} />
                              <span className="text-xs text-zinc-500 truncate">{n.type.replace(/_/g, " ")}</span>
                            </div>
                            <p className="text-xs text-zinc-300 line-clamp-1">{n.title}</p>
                          </button>
                        ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="bg-zinc-900/80 rounded-md px-2 py-1.5">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className={`text-xs font-semibold mt-0.5 ${highlight ? "text-amber-400" : "text-zinc-200"}`}>
        {value}
      </div>
    </div>
  );
}
