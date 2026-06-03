"use client";

import { useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";

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

const EDGE_COLORS: Record<string, string> = {
  related_to: "#444",
  supports: "#6B9E78",
  contradicts: "#E07B8C",
  part_of: "#555",
  supersedes: "#DA7756",
};

interface GraphNode {
  id: string;
  title: string;
  type: string;
  x?: number;
  y?: number;
  z?: number;
}

interface GraphLink {
  source: string;
  target: string;
  relation_type: string;
  weight: number;
}

interface Props {
  nodes: GraphNode[];
  links: GraphLink[];
  search: string;
  width: number;
  height: number;
}

export default function Graph3D({ nodes, links, search, width, height }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<any>(null);
  const router = useRouter();

  useEffect(() => {
    if (!containerRef.current) return;

    let fg: any;

    import("3d-force-graph").then((mod) => {
      const ForceGraph3D = mod.default;
      fg = ForceGraph3D()(containerRef.current!)
        .width(width)
        .height(height)
        .backgroundColor("#09090b")
        .nodeColor((n: GraphNode) => TYPE_COLORS[n.type] ?? TYPE_COLORS.unknown)
        .nodeRelSize(4)
        .nodeLabel((n: GraphNode) =>
          `<div style="background:rgba(0,0,0,.85);padding:6px 10px;border-radius:6px;font-size:12px;max-width:280px">
            <b style="color:${TYPE_COLORS[n.type] ?? "#ccc"}">${n.type.replace(/_/g, " ")}</b><br/>
            ${(n.title ?? n.id).slice(0, 120)}
          </div>`
        )
        .linkColor((l: GraphLink) => EDGE_COLORS[l.relation_type] ?? "#444")
        .linkOpacity(0.4)
        .linkWidth((l: GraphLink) => Math.min(2, 0.5 + (l.weight ?? 1)))
        .onNodeClick((n: GraphNode) => router.push(`/memory/${n.id}`))
        .graphData({
          nodes: nodes.map((n) => ({ ...n })),
          links: links.map((l) => ({ ...l })),
        });

      graphRef.current = fg;
    });

    return () => {
      fg?._destructor?.();
      if (containerRef.current) containerRef.current.innerHTML = "";
    };
  }, []);

  // Update size
  useEffect(() => {
    graphRef.current?.width(width).height(height);
  }, [width, height]);

  // Update highlight on search change
  useEffect(() => {
    const fg = graphRef.current;
    if (!fg) return;
    const hitIds =
      search.length > 1
        ? new Set(
            nodes
              .filter(
                (n) =>
                  (n.title ?? "").toLowerCase().includes(search.toLowerCase()) ||
                  n.type.toLowerCase().includes(search.toLowerCase())
              )
              .map((n) => n.id)
          )
        : null;

    fg.nodeColor((n: GraphNode) => {
      if (hitIds) {
        return hitIds.has(n.id)
          ? (TYPE_COLORS[n.type] ?? TYPE_COLORS.unknown)
          : "rgba(80,80,80,0.15)";
      }
      return TYPE_COLORS[n.type] ?? TYPE_COLORS.unknown;
    });
  }, [search, nodes]);

  return <div ref={containerRef} className="w-full h-full" />;
}
