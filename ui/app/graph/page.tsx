"use client";

import dynamic from "next/dynamic";
import { useEffect, useState, useRef } from "react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { getApiBaseUrl } from "@/lib/api-url";

const ForceGraph = dynamic(() => import("./ForceGraph"), { ssr: false });

interface GraphNode {
  id: string;
  title: string;
  type: string;
  status: string;
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

export default function GraphPage() {
  const [data, setData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);

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

  const types = data ? Array.from(new Set(data.nodes.map((n) => n.type))).sort() : [];
  const edgeTypes = data ? Array.from(new Set(data.edges.map((e) => e.relation_type))).sort() : [];

  return (
    <div className="flex flex-col h-[calc(100vh-56px)]">
      <div className="flex items-center justify-between px-6 py-3 border-b border-border bg-card shrink-0">
        <div>
          <h1 className="text-xl font-semibold">Memory Graph</h1>
          {data && (
            <p className="text-sm text-muted-foreground">
              {data.nodes.length} nodes · {data.edges.length} links
            </p>
          )}
        </div>
        <Input
          className="w-64"
          placeholder="Search nodes..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-2 px-6 py-2 border-b border-border bg-background shrink-0">
        <span className="text-xs text-muted-foreground self-center">Types:</span>
        {types.map((t) => (
          <Badge
            key={t}
            variant="outline"
            className="text-xs"
            style={{ borderColor: TYPE_COLORS[t] ?? "#A0A09A", color: TYPE_COLORS[t] ?? "#A0A09A" }}
          >
            {t.replace(/_/g, " ")}
          </Badge>
        ))}
        <span className="ml-4 text-xs text-muted-foreground self-center">Links:</span>
        {edgeTypes.map((e) => (
          <Badge key={e} variant="secondary" className="text-xs">
            {EDGE_LABELS[e] ?? e}
          </Badge>
        ))}
      </div>

      <div ref={containerRef} className="flex-1 overflow-hidden relative">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center text-muted-foreground">
            Loading graph…
          </div>
        )}
        {error && (
          <div className="absolute inset-0 flex items-center justify-center text-red-300">
            {error}
          </div>
        )}
        {data && <ForceGraph data={data} searchTerm={search} />}
      </div>
    </div>
  );
}
