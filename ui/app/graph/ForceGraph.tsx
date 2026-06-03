"use client";

import { useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { ForceGraph2D } from "react-force-graph";

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
  related_to: { dash: null, color: "#C8C0B4" },
  supports: { dash: null, color: "#6B9E78" },
  contradicts: { dash: [4, 4], color: "#E07B8C" },
  part_of: { dash: [2, 2], color: "#A0A09A" },
  supersedes: { dash: [6, 2], color: "#DA7756" },
};

function nodeColor(node: GraphNode): string {
  return TYPE_COLORS[node.type] ?? TYPE_COLORS.unknown;
}

interface ForceGraphProps {
  data: GraphData;
  searchTerm: string;
}

export default function ForceGraph({ data, searchTerm }: ForceGraphProps) {
  const router = useRouter();
  const fgRef = useRef<unknown>(undefined);
  const containerRef = useRef<HTMLDivElement>(null);

  const graphData = {
    nodes: data.nodes.map((n) => ({ ...n })),
    links: data.edges.map((e) => ({
      source: e.source,
      target: e.target,
      relation_type: e.relation_type,
      weight: e.weight,
    })),
  };

  const handleNodeClick = useCallback(
    (node: GraphNode) => {
      router.push(`/memory/${node.id}`);
    },
    [router]
  );

  const nodeCanvasObject = useCallback(
    (node: GraphNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const label = node.title || node.id;
      const fontSize = Math.max(10 / globalScale, 3);
      const r = Math.max(5, 8 / Math.sqrt(globalScale));
      const x = node.x ?? 0;
      const y = node.y ?? 0;
      const isHighlighted =
        searchTerm.length > 1 &&
        (node.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
          node.type.toLowerCase().includes(searchTerm.toLowerCase()));

      ctx.beginPath();
      ctx.arc(x, y, r + (isHighlighted ? 3 : 0), 0, 2 * Math.PI);
      ctx.fillStyle = nodeColor(node);
      ctx.fill();

      if (isHighlighted) {
        ctx.strokeStyle = "#DA7756";
        ctx.lineWidth = 2 / globalScale;
        ctx.stroke();
      }

      if (globalScale > 0.8) {
        ctx.font = `${fontSize}px Inter, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillStyle = "#2D2B28";
        ctx.fillText(label.slice(0, 30), x, y + r + 2);
      }
    },
    [searchTerm]
  );

  const linkCanvasObject = useCallback(
    (
      link: { source: GraphNode; target: GraphNode; relation_type: string; weight: number },
      ctx: CanvasRenderingContext2D
    ) => {
      const style = EDGE_STYLES[link.relation_type] ?? EDGE_STYLES.related_to;
      const src = link.source;
      const tgt = link.target;
      const sx = src.x ?? 0;
      const sy = src.y ?? 0;
      const tx = tgt.x ?? 0;
      const ty = tgt.y ?? 0;

      ctx.beginPath();
      if (style.dash) {
        ctx.setLineDash(style.dash);
      } else {
        ctx.setLineDash([]);
      }
      ctx.moveTo(sx, sy);
      ctx.lineTo(tx, ty);
      ctx.strokeStyle = style.color;
      ctx.lineWidth = Math.min(1.5, 0.5 + link.weight);
      ctx.globalAlpha = 0.6;
      ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.setLineDash([]);
    },
    []
  );

  const width = containerRef.current?.clientWidth ?? 900;
  const height = containerRef.current?.clientHeight ?? 600;

  return (
    <div ref={containerRef} className="w-full h-full">
      <ForceGraph2D
        ref={fgRef}
        graphData={graphData}
        width={width}
        height={height}
        backgroundColor="#F5F0E8"
        nodeCanvasObject={nodeCanvasObject}
        nodeCanvasObjectMode={() => "replace"}
        linkCanvasObject={linkCanvasObject}
        linkCanvasObjectMode={() => "replace"}
        onNodeClick={handleNodeClick}
        nodeLabel={(node: GraphNode) => `${node.title}\n${node.type}`}
        enableZoomInteraction
        enablePanInteraction
        cooldownTicks={100}
      />
    </div>
  );
}
