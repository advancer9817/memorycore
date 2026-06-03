"use client";

import dynamic from "next/dynamic";
import { useEffect, useState, useRef, useCallback } from "react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { useRouter } from "next/navigation";
import { getApiBaseUrl } from "@/lib/api-url";

// Load ForceGraph2D only on client — it requires window/canvas
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

interface GraphNode {
  id: string;
  title: string;
  type: string;
  status: string;
  x?: number;
  y?: number;
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

const EDGE_STYLES: Record<string, { dash: number[] | null; color: string }> = {
  related_to: { dash: null, color: "#555" },
  supports: { dash: null, color: "#6B9E78" },
  contradicts: { dash: [4, 4], color: "#E07B8C" },
  part_of: { dash: [2, 2], color: "#666" },
  supersedes: { dash: [6, 2], color: "#DA7756" },
};

const EDGE_LABELS: Record<string, string> = {
  related_to: "related",
  supports: "supports",
  contradicts: "contradicts",
  part_of: "part of",
  supersedes: "supersedes",
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
        nodes: data.nodes.map((n) => ({ ...n })),
        links: data.edges.map((e) => ({
          source: e.source,
          target: e.target,
          relation_type: e.relation_type,
          weight: e.weight,
        })),
      }
    : { nodes: [], links: [] };

  const handleNodeClick = useCallback(
    (node: GraphNode) => router.push(`/memory/${node.id}`),
    [router]
  );

  const nodeCanvasObject = useCallback(
    (node: GraphNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const r = Math.max(4, 7 / Math.sqrt(globalScale));
      const x = node.x ?? 0;
      const y = node.y ?? 0;
      const color = TYPE_COLORS[node.type] ?? TYPE_COLORS.unknown;
      const isHit =
        search.length > 1 &&
        ((node.title ?? "").toLowerCase().includes(search.toLowerCase()) ||
          node.type.toLowerCase().includes(search.toLowerCase()));

      ctx.beginPath();
      ctx.arc(x, y, r + (isHit ? 3 : 0), 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();
      if (isHit) {
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 1.5 / globalScale;
        ctx.stroke();
      }
      if (globalScale > 0.7) {
        const fs = Math.max(9 / globalScale, 3);
        ctx.font = `${fs}px sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillStyle = "rgba(255,255,255,0.8)";
        ctx.fillText((node.title ?? node.id).slice(0, 28), x, y + r + 1);
      }
    },
    [search]
  );

  const linkCanvasObject = useCallback(
    (
      link: { source: GraphNode; target: GraphNode; relation_type: string; weight: number },
      ctx: CanvasRenderingContext2D
    ) => {
      const style = EDGE_STYLES[link.relation_type] ?? EDGE_STYLES.related_to;
      ctx.beginPath();
      ctx.setLineDash(style.dash ?? []);
      ctx.moveTo(link.source.x ?? 0, link.source.y ?? 0);
      ctx.lineTo(link.target.x ?? 0, link.target.y ?? 0);
      ctx.strokeStyle = style.color;
      ctx.lineWidth = Math.min(1.5, 0.5 + (link.weight ?? 1));
      ctx.globalAlpha = 0.5;
      ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.setLineDash([]);
    },
    []
  );

  const types = data ? Array.from(new Set(data.nodes.map((n) => n.type))).sort() : [];
  const edgeTypes = data ? Array.from(new Set(data.edges.map((e) => e.relation_type))).sort() : [];

  return (
    <div className="flex flex-col h-[calc(100vh-56px)]">
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
          className="w-64 bg-zinc-900 border-zinc-700 text-zinc-100"
          placeholder="Search nodes..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <div className="flex flex-wrap gap-2 px-6 py-2 border-b border-zinc-800 bg-zinc-950 shrink-0">
        <span className="text-xs text-zinc-500 self-center">Types:</span>
        {types.map((t) => (
          <Badge
            key={t}
            variant="outline"
            className="text-xs border-zinc-600"
            style={{ color: TYPE_COLORS[t] ?? "#A0A09A" }}
          >
            {t.replace(/_/g, " ")}
          </Badge>
        ))}
        <span className="ml-4 text-xs text-zinc-500 self-center">Links:</span>
        {edgeTypes.map((e) => (
          <Badge key={e} variant="secondary" className="text-xs bg-zinc-800 text-zinc-300">
            {EDGE_LABELS[e] ?? e}
          </Badge>
        ))}
      </div>

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
          <ForceGraph2D
            graphData={graphData}
            width={dims.w}
            height={dims.h}
            backgroundColor="#09090b"
            nodeCanvasObject={nodeCanvasObject}
            nodeCanvasObjectMode={() => "replace"}
            linkCanvasObject={linkCanvasObject}
            linkCanvasObjectMode={() => "replace"}
            onNodeClick={handleNodeClick}
            nodeLabel={(node: GraphNode) => `${node.title ?? node.id}\n[${node.type}]`}
            cooldownTicks={80}
          />
        )}
      </div>
    </div>
  );
}
