"use client";

import dynamic from "next/dynamic";
import { useEffect, useState, useRef, useCallback } from "react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { useRouter } from "next/navigation";
import { getApiBaseUrl } from "@/lib/api-url";

const ForceGraph3D = dynamic(
  () => import("react-force-graph").then((m) => ({ default: m.ForceGraph3D })),
  { ssr: false }
);

interface GraphNode {
  id: string;
  title: string;
  type: string;
  status: string;
  x?: number;
  y?: number;
  z?: number;
}

interface GraphEdge {
  source: string;
  target: string;
  relation_type: string;
  weight: number;
}

interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

const TYPE_COLORS: Record<string, string> = {
  project_memory: "#DA7756",
  feedback: "#6B9E78",
  user_profile: "#5B8DD9",
  decision: "#C4A35A",
  environment_fact: "#9B72CF",
  reference: "#E07B8C",
  episodic_memory: "#7DBDCF",
  skill_candidate: "#D4854E",
  unknown: "#A0A09A",
};

const EDGE_LABELS: Record<string, string> = {
  related_to: "related",
  supports: "supports",
  contradicts: "contradicts",
  part_of: "part of",
  supersedes: "supersedes",
};

const EDGE_COLORS: Record<string, string> = {
  related_to: "#444",
  supports: "#6B9E78",
  contradicts: "#E07B8C",
  part_of: "#555",
  supersedes: "#DA7756",
};

export default function GraphPage() {
  const router = useRouter();
  const [data, setData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ w: 900, h: 600 });

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch(`${getApiBaseUrl()}/api/graph`);
        const payload = await res.json();
        setData(payload.data ?? payload);
      } catch (err) {
        setError(String(err));
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      setDims({ w: el.clientWidth, h: el.clientHeight });
    });
    ro.observe(el);
    setDims({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  const graphData = data
    ? {
        nodes: data.nodes.map((n) => ({
          ...n,
          color: TYPE_COLORS[n.type] ?? TYPE_COLORS.unknown,
        })),
        links: data.edges.map((e) => ({
          source: e.source,
          target: e.target,
          relation_type: e.relation_type,
          weight: e.weight,
          color: EDGE_COLORS[e.relation_type] ?? EDGE_COLORS.related_to,
        })),
      }
    : { nodes: [], links: [] };

  const handleNodeClick = useCallback(
    (node: GraphNode) => router.push(`/memory/${node.id}`),
    [router]
  );

  const nodeLabel = useCallback(
    (node: GraphNode) =>
      `<div style="background:rgba(0,0,0,.8);padding:6px 10px;border-radius:6px;font-size:12px;max-width:260px">
        <b style="color:${TYPE_COLORS[node.type] ?? "#fff"}">${node.type.replace(/_/g, " ")}</b><br/>
        ${(node.title ?? node.id).slice(0, 120)}
      </div>`,
    []
  );

  const highlightNodes = search.length > 1
    ? new Set(
        (data?.nodes ?? [])
          .filter(
            (n) =>
              (n.title ?? "").toLowerCase().includes(search.toLowerCase()) ||
              n.type.toLowerCase().includes(search.toLowerCase())
          )
          .map((n) => n.id)
      )
    : new Set<string>();

  const nodeColor = useCallback(
    (node: GraphNode) => {
      if (search.length > 1 && highlightNodes.size > 0) {
        return highlightNodes.has(node.id)
          ? (TYPE_COLORS[node.type] ?? TYPE_COLORS.unknown)
          : "rgba(100,100,100,0.2)";
      }
      return TYPE_COLORS[node.type] ?? TYPE_COLORS.unknown;
    },
    [search, highlightNodes]
  );

  const types = data ? Array.from(new Set(data.nodes.map((n) => n.type))).sort() : [];
  const edgeTypes = data ? Array.from(new Set(data.edges.map((e) => e.relation_type))).sort() : [];

  return (
    <div className="flex flex-col h-[calc(100vh-56px)]">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-zinc-800 bg-zinc-950 shrink-0">
        <div>
          <h1 className="text-xl font-semibold text-white">Memory Graph</h1>
          {data && (
            <p className="text-sm text-zinc-400">
              {data.nodes.length} nodes · {data.edges.length} links
            </p>
          )}
        </div>
        <Input
          className="w-64 bg-zinc-900 border-zinc-700 text-zinc-100 placeholder:text-zinc-500"
          placeholder="Search nodes..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-2 px-6 py-2 border-b border-zinc-800 bg-zinc-950 shrink-0">
        <span className="text-xs text-zinc-500 self-center">Types:</span>
        {types.map((t) => (
          <Badge
            key={t}
            variant="outline"
            className="text-xs border-zinc-700"
            style={{ color: TYPE_COLORS[t] ?? "#A0A09A" }}
          >
            {t.replace(/_/g, " ")}
          </Badge>
        ))}
        <span className="ml-4 text-xs text-zinc-500 self-center">Links:</span>
        {edgeTypes.map((e) => (
          <Badge
            key={e}
            variant="outline"
            className="text-xs border-zinc-700"
            style={{ color: EDGE_COLORS[e] ?? "#888" }}
          >
            {EDGE_LABELS[e] ?? e}
          </Badge>
        ))}
      </div>

      {/* Graph canvas */}
      <div ref={containerRef} className="flex-1 overflow-hidden relative bg-zinc-950">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center text-zinc-400">
            Loading graph…
          </div>
        )}
        {error && (
          <div className="absolute inset-0 flex items-center justify-center text-red-400">
            {error}
          </div>
        )}
        {data && (
          <ForceGraph3D
            graphData={graphData}
            width={dims.w}
            height={dims.h}
            backgroundColor="#09090b"
            nodeColor={nodeColor}
            nodeLabel={nodeLabel}
            nodeRelSize={4}
            linkColor={(link: { color?: string }) => link.color ?? "#444"}
            linkOpacity={0.4}
            linkWidth={(link: { weight?: number }) => Math.min(2, 0.5 + (link.weight ?? 1))}
            onNodeClick={handleNodeClick}
            enableNodeDrag
          />
        )}
      </div>
    </div>
  );
}
