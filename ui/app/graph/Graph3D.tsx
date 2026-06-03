"use client";

import { useRef, useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { ForceGraph3D } from "react-force-graph";

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
  color?: string;
}

interface Props {
  nodes: GraphNode[];
  links: GraphLink[];
  search: string;
  width: number;
  height: number;
}

export default function Graph3D({ nodes, links, search, width, height }: Props) {
  const router = useRouter();

  const graphData = {
    nodes: nodes.map((n) => ({ ...n })),
    links: links.map((l) => ({
      ...l,
      color: EDGE_COLORS[l.relation_type] ?? EDGE_COLORS.related_to,
    })),
  };

  const highlightIds =
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

  const nodeColor = useCallback(
    (node: GraphNode) => {
      if (highlightIds) {
        return highlightIds.has(node.id)
          ? (TYPE_COLORS[node.type] ?? TYPE_COLORS.unknown)
          : "rgba(80,80,80,0.15)";
      }
      return TYPE_COLORS[node.type] ?? TYPE_COLORS.unknown;
    },
    [search]
  );

  const nodeLabel = useCallback(
    (node: GraphNode) =>
      `<div style="background:rgba(0,0,0,.85);padding:6px 10px;border-radius:6px;font-size:12px;max-width:280px">
        <b style="color:${TYPE_COLORS[node.type] ?? "#ccc"}">${node.type.replace(/_/g, " ")}</b><br/>
        ${(node.title ?? node.id).slice(0, 120)}
      </div>`,
    []
  );

  const handleNodeClick = useCallback(
    (node: GraphNode) => router.push(`/memory/${node.id}`),
    [router]
  );

  return (
    <ForceGraph3D
      graphData={graphData}
      width={width}
      height={height}
      backgroundColor="#09090b"
      nodeColor={nodeColor}
      nodeLabel={nodeLabel}
      nodeRelSize={4}
      linkColor={(link: GraphLink) => link.color ?? "#444"}
      linkOpacity={0.4}
      linkWidth={(link: GraphLink) => Math.min(2, 0.5 + (link.weight ?? 1))}
      onNodeClick={handleNodeClick}
      enableNodeDrag
    />
  );
}
