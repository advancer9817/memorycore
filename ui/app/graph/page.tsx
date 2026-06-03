"use client";

import dynamic from "next/dynamic";
import { useEffect, useState, useRef, useCallback } from "react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getApiBaseUrl } from "@/lib/api-url";
import Link from "next/link";
import {
  type GraphNode,
  type GraphEdge,
  TYPE_COLORS,
  EDGE_COLORS,
  IMPORTANCE_THRESHOLD,
} from "./types";

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
  const containerRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ w: 900, h: 600 });

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

  const allTypes = data ? Array.from(new Set(data.nodes.map((n) => n.type))).sort() : [];
  const allEdgeTypes = data ? Array.from(new Set(data.edges.map((e) => e.relation_type))).sort() : [];

  const filteredNodes = data
    ? data.nodes.filter((n) => {
        if (!activeTypes.has(n.type)) return false;
        if (highlightImportant && n.importance < IMPORTANCE_THRESHOLD) return false;
        if (search.length > 1) {
          const q = search.toLowerCase();
          return n.title.toLowerCase().includes(q) || n.type.toLowerCase().includes(q);
        }
        return true;
      })
    : [];

  const filteredNodeIds = new Set(filteredNodes.map((n) => n.id));
  const filteredEdges = data
    ? data.edges.filter(
        (e) =>
          activeEdgeTypes.has(e.relation_type) &&
          filteredNodeIds.has(e.source) &&
          filteredNodeIds.has(e.target)
      )
    : [];

  const importantCount = data ? data.nodes.filter((n) => n.importance >= IMPORTANCE_THRESHOLD).length : 0;

  return (
    <div className="flex flex-col h-[calc(100vh-56px)]">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-zinc-800 bg-zinc-950 shrink-0 gap-4">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold text-white">Memory Graph</h1>
          {data && (
            <p className="text-xs text-zinc-400">
              {filteredNodes.length}/{data.nodes.length} nodes · {filteredEdges.length}/{data.edges.length} links
            </p>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap justify-end">
          <Button
            size="sm"
            variant={highlightImportant ? "default" : "outline"}
            className={highlightImportant
              ? "bg-amber-500 hover:bg-amber-600 text-black border-0 text-xs h-7"
              : "border-zinc-700 text-zinc-300 hover:text-white text-xs h-7"}
            onClick={() => setHighlightImportant((v) => !v)}
          >
            ★ 重要记忆 {importantCount > 0 && `(${importantCount})`}
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="border-zinc-700 text-zinc-300 hover:text-white text-xs h-7"
            onClick={() => {
              if (data) {
                setActiveTypes(new Set(data.nodes.map((n) => n.type)));
                setActiveEdgeTypes(new Set(data.edges.map((e) => e.relation_type)));
              }
              setSearch("");
              setHighlightImportant(false);
            }}
          >
            重置
          </Button>
          <Input
            className="w-52 bg-zinc-900 border-zinc-700 text-zinc-100 placeholder:text-zinc-500 h-8 text-sm"
            placeholder="搜索节点…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-x-4 gap-y-1.5 px-6 py-2 border-b border-zinc-800 bg-zinc-950/80 shrink-0 items-center">
        <span className="text-xs text-zinc-500 shrink-0">类型:</span>
        {allTypes.map((t) => {
          const active = activeTypes.has(t);
          const color = TYPE_COLORS[t] ?? "#A0A09A";
          return (
            <button
              key={t}
              onClick={() => toggleType(t)}
              className="flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium transition-all border"
              style={{
                borderColor: active ? color : "#333",
                color: active ? color : "#555",
                background: active ? `${color}18` : "transparent",
              }}
            >
              <span
                className="w-2 h-2 rounded-full shrink-0"
                style={{ background: active ? color : "#444" }}
              />
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
              className="flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium transition-all border"
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

      {/* Main area */}
      <div className="flex flex-1 overflow-hidden">
        <div ref={containerRef} className="flex-1 overflow-hidden relative bg-zinc-950">
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center text-zinc-400">
              加载图谱…
            </div>
          )}
          {error && (
            <div className="absolute inset-0 flex items-center justify-center text-red-400">
              {error}
            </div>
          )}
          {data && (
            <Graph3D
              nodes={filteredNodes}
              links={filteredEdges}
              search={search}
              highlightImportant={highlightImportant}
              width={dims.w}
              height={dims.h}
              onNodeClick={setSelectedNode}
            />
          )}
        </div>

        {/* Detail panel */}
        {selectedNode && (
          <div className="w-72 shrink-0 border-l border-zinc-800 bg-zinc-950 flex flex-col overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
              <span className="text-sm font-semibold text-zinc-200">节点详情</span>
              <button
                onClick={() => setSelectedNode(null)}
                className="text-zinc-500 hover:text-zinc-200 text-lg leading-none"
              >
                ×
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
              <div>
                <Badge
                  variant="outline"
                  className="text-xs mb-2"
                  style={{ color: TYPE_COLORS[selectedNode.type] ?? "#aaa", borderColor: TYPE_COLORS[selectedNode.type] ?? "#555" }}
                >
                  {selectedNode.type.replace(/_/g, " ")}
                </Badge>
                <p className="text-sm font-medium text-zinc-100 leading-snug">
                  {selectedNode.title}
                </p>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <Stat label="重要性" value={selectedNode.importance.toFixed(2)} highlight={selectedNode.importance >= IMPORTANCE_THRESHOLD} />
                <Stat label="反馈分" value={selectedNode.feedback_score >= 0 ? `+${selectedNode.feedback_score.toFixed(1)}` : selectedNode.feedback_score.toFixed(1)} />
                <Stat label="注入次数" value={String(selectedNode.injected_count)} />
                <Stat label="状态" value={selectedNode.status} />
              </div>

              {/* Importance bar */}
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
                      background: selectedNode.importance >= IMPORTANCE_THRESHOLD
                        ? "#F59E0B"
                        : TYPE_COLORS[selectedNode.type] ?? "#6B9E78",
                    }}
                  />
                </div>
              </div>

              <Link
                href={`/memory/${selectedNode.id}`}
                className="block w-full text-center text-xs text-violet-400 hover:text-violet-300 border border-violet-800 hover:border-violet-600 rounded-md py-1.5 transition-colors"
              >
                查看完整记忆 →
              </Link>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="bg-zinc-900 rounded-md px-3 py-2">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className={`text-sm font-semibold mt-0.5 ${highlight ? "text-amber-400" : "text-zinc-200"}`}>
        {value}
      </div>
    </div>
  );
}
