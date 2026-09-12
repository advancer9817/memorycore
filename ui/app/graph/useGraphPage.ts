"use client";

import { useEffect, useState, useRef, useCallback, useMemo } from "react";
import { useSelector } from "react-redux";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useToast } from "@/hooks/use-toast";
import { useI18n } from "@/hooks/useI18n";
import { getApiBaseUrl } from "@/lib/api-url";
import { RootState } from "@/store/store";
import { type GraphNode, type GraphEdge, KNOWN_EDGE_TYPES, IMPORTANCE_THRESHOLD } from "./types";
import type { Graph3DHandle } from "./Graph3D";

interface GraphData { nodes: GraphNode[]; edges: GraphEdge[]; }

export function useGraphPage() {
  const { toast } = useToast();
  const { messages } = useI18n();
  const g = messages.graph;
  const graphRefreshKey = useSelector((state: RootState) => state.ui.graphRefreshKey);
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
  const [dims, setDims] = useState({ w: 900, h: 600 });
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [limit, setLimit] = useState(2000);
  const [retryKey, setRetryKey] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const listScrollRef = useRef<HTMLDivElement>(null);
  const sortedListNodesRef = useRef<GraphNode[]>([]);
  const graph3DHandleRef = useRef<Graph3DHandle | null>(null);

  useEffect(() => {
    const id = setTimeout(() => setSearch(searchInput), 300);
    return () => clearTimeout(id);
  }, [searchInput]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(null); setGraphReady(false);
    fetch(`${getApiBaseUrl()}/api/v1/graph?status=all&limit=${limit}`, { signal: controller.signal })
      .then((r) => r.json())
      .then((p) => {
        const raw = p.data ?? p;
        const rawNodes = raw.nodes ?? [];
        const rawEdges = raw.edges ?? raw.links ?? [];
        const nodeIds = new Set(rawNodes.map((n: GraphNode) => n.id));
        const safeEdges = rawEdges
          .filter((e: any) => e && nodeIds.has(e.source) && nodeIds.has(e.target))
          .map((e: any) => ({ ...e, relation_type: e.relation_type ?? e.relation ?? "supports" }));
        const edgeTypes = new Set([...KNOWN_EDGE_TYPES, ...safeEdges.map((e: GraphEdge) => e.relation_type)]);
        setData({ nodes: raw.nodes, edges: safeEdges });
        setActiveTypes(new Set(raw.nodes.map((n: GraphNode) => n.type)));
        // 默认只激活语义链接类型，隐藏 supports/part_of 自动关系
        const semanticEdgeTypes = new Set([...edgeTypes].filter(t => t !== "supports" && t !== "part_of"));
        setActiveEdgeTypes(semanticEdgeTypes);
      })
      .catch((e) => { if (e instanceof DOMException && e.name === "AbortError") return; setError(String(e)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [limit, graphRefreshKey, retryKey]);

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
    setFullContent(null); setIsEditing(false);
    fetch(`${getApiBaseUrl()}/api/v1/memories/${selectedNode.id}`)
      .then((r) => r.json())
      .then((p) => { const rec = p.data ?? p; setFullContent(rec.content ?? rec.text ?? selectedNode.content); })
      .catch(() => setFullContent(selectedNode.content));
  }, [selectedNode?.id]);

  useEffect(() => {
    if (selectedNode) { setEditImportance(selectedNode.importance); setEditStatus(selectedNode.status ?? "active"); }
  }, [selectedNode?.id]);

  const connectedIds = useMemo(() => {
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
    if (data) {
      setActiveTypes(new Set(data.nodes.map(n => n.type)));
      setActiveEdgeTypes(new Set([...KNOWN_EDGE_TYPES, ...data.edges.map(e => e.relation_type)]));
    }
    setSearch(""); setSearchInput(""); setHighlightImportant(false); setSelectedNode(null); setActiveStatus("all");
  }, [data]);

  const allTypes = useMemo(() => data ? Array.from(new Set(data.nodes.map(n => n.type))).sort() : [], [data]);
  const allEdgeTypes = useMemo(() => {
    if (!data) return KNOWN_EDGE_TYPES;
    return Array.from(new Set([...KNOWN_EDGE_TYPES, ...data.edges.map(e => e.relation_type)])).sort();
  }, [data]);

  const filteredNodes = useMemo(() => data ? data.nodes.filter(n => {
    if (!activeTypes.has(n.type)) return false;
    if (activeStatus !== "all" && n.status !== activeStatus) return false;
    if (highlightImportant && n.importance < IMPORTANCE_THRESHOLD) return false;
    if (search.length > 1) { const q = search.toLowerCase(); return n.title.toLowerCase().includes(q) || n.type.toLowerCase().includes(q) || n.content.toLowerCase().includes(q); }
    return true;
  }) : [], [data, activeTypes, activeStatus, highlightImportant, search]);

  const sortedListNodes = useMemo(() => [...filteredNodes].sort((a, b) => b.importance - a.importance), [filteredNodes]);
  useEffect(() => { sortedListNodesRef.current = sortedListNodes; }, [sortedListNodes]);
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
        const idx = sortedListNodesRef.current.findIndex(n => n.id === node.id);
        if (idx >= 0) rowVirtualizer.scrollToIndex(idx, { align: "auto" });
        graph3DHandleRef.current?.focusNode(node.id);
      }, 50);
      return node;
    });
  }, [rowVirtualizer]);

  const handleExportJson = useCallback(() => {
    if (!data) return;
    const blob = new Blob([JSON.stringify({ nodes: filteredNodes, edges: filteredEdges }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = "memory-graph.json"; a.click();
    URL.revokeObjectURL(url);
  }, [data, filteredNodes, filteredEdges]);

  const handleSave = useCallback(() => {
    if (!selectedNode) return;
    fetch(`${getApiBaseUrl()}/api/v1/memories/${selectedNode.id}`, {
      method: "PATCH",
      body: JSON.stringify({ importance: editImportance, status: editStatus }),
      headers: { "Content-Type": "application/json" },
    }).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData(prev => prev ? { ...prev, nodes: prev.nodes.map(n => n.id === selectedNode.id ? { ...n, importance: editImportance, status: editStatus } : n) } : prev);
      setSelectedNode(prev => prev ? { ...prev, importance: editImportance, status: editStatus } : prev);
      setIsEditing(false);
    }).catch((err) => {
      toast({ title: g.saveFailed, description: String(err), variant: "destructive" });
    });
  }, [selectedNode, editImportance, editStatus, g.saveFailed, toast]);

  return {
    g, data, loading, error, search, searchInput, setSearchInput,
    activeTypes, activeEdgeTypes, activeStatus, setActiveStatus,
    highlightImportant, setHighlightImportant, selectedNode, setSelectedNode,
    fullContent, listCollapsed, setListCollapsed, graphReady, setGraphReady,
    isEditing, setIsEditing, editImportance, setEditImportance, editStatus, setEditStatus,
    dims, filtersOpen, setFiltersOpen, limit, setLimit,
    containerRef, listScrollRef, graph3DHandleRef,
    allTypes, allEdgeTypes, filteredNodes, sortedListNodes, filteredEdges, importantCount,
    rowVirtualizer, linked: connectedIds,
    toggleType, toggleEdgeType, resetAll, handleNodeSelect, handleExportJson, handleSave,
    handleRetry: () => setRetryKey((k) => k + 1),
  };
}
