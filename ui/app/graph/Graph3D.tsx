"use client";

import { useRef, useEffect } from "react";
import { type GraphNode, type GraphEdge, TYPE_COLORS, EDGE_COLORS, IMPORTANCE_THRESHOLD } from "./types";

interface Props {
  nodes: GraphNode[];
  links: GraphEdge[];
  search: string;
  highlightImportant: boolean;
  selectedNodeId: string | null;
  linkedNodeIds: Set<string> | null;
  width: number;
  height: number;
  onNodeClick: (node: GraphNode) => void;
  onBackgroundClick: () => void;
}

export default function Graph3D({ nodes, links, search, highlightImportant, selectedNodeId, linkedNodeIds, width, height, onNodeClick, onBackgroundClick }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<any>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    let fg: any;

    import("3d-force-graph").then((mod) => {
      const ForceGraph3D = mod.default;
      // eslint-disable-next-line @typescript-eslint/ban-ts-comment
      // @ts-ignore — library supports both new and call invocation at runtime
      fg = ForceGraph3D()(containerRef.current!)
        .width(width)
        .height(height)
        .backgroundColor("#09090b")
        .nodeRelSize(5)
        .nodeVal((n: GraphNode) => {
          const base = 1 + (n.importance ?? 0.5) * 3;
          return Math.max(1, base);
        })
        .nodeColor((n: GraphNode) => {
          if (n.importance >= IMPORTANCE_THRESHOLD) return "#F59E0B";
          return TYPE_COLORS[n.type] ?? TYPE_COLORS.unknown;
        })
        .nodeLabel((n: GraphNode) =>
          `<div style="background:rgba(9,9,11,.92);padding:8px 12px;border-radius:8px;font-size:12px;max-width:300px;border:1px solid ${TYPE_COLORS[n.type] ?? '#555'}">
            <b style="color:${TYPE_COLORS[n.type] ?? '#ccc'}">${n.type.replace(/_/g, " ")}</b>
            ${n.importance >= IMPORTANCE_THRESHOLD ? ' <span style="color:#F59E0B">★</span>' : ''}
            <br/>${(n.title ?? n.id).slice(0, 140)}
            <br/><span style="color:#666;font-size:10px">importance ${(n.importance ?? 0).toFixed(2)} · injected ${n.injected_count ?? 0}×</span>
          </div>`
        )
        .nodeThreeObject((n: GraphNode) => {
          const THREE = (window as any).THREE;
          if (!THREE) return undefined;
          const isImportant = (n.importance ?? 0) >= IMPORTANCE_THRESHOLD;
          const color = isImportant ? 0xF59E0B : parseInt((TYPE_COLORS[n.type] ?? TYPE_COLORS.unknown).slice(1), 16);
          const size = 2 + (n.importance ?? 0.5) * 3;

          const group = new THREE.Group();

          const geo = new THREE.SphereGeometry(size, 16, 16);
          const mat = new THREE.MeshLambertMaterial({
            color,
            transparent: !isImportant,
            opacity: isImportant ? 1.0 : 0.85,
          });
          group.add(new THREE.Mesh(geo, mat));

          if (isImportant) {
            const ringGeo = new THREE.SphereGeometry(size * 1.5, 12, 12);
            const ringMat = new THREE.MeshLambertMaterial({
              color: 0xF59E0B,
              transparent: true,
              opacity: 0.15,
            });
            group.add(new THREE.Mesh(ringGeo, ringMat));
          }

          return group;
        })
        .nodeThreeObjectExtend(false)
        .linkColor((l: GraphEdge) => EDGE_COLORS[l.relation_type] ?? "#444")
        .linkOpacity(0.35)
        .linkWidth((l: GraphEdge) => Math.min(2.5, 0.4 + (l.weight ?? 1) * 0.6))
        .linkDirectionalParticles((l: GraphEdge) =>
          l.relation_type === "contradicts" || l.relation_type === "supersedes" ? 2 : 0
        )
        .linkDirectionalParticleSpeed(0.004)
        .onNodeClick((n: GraphNode) => onNodeClick(n))
        .onBackgroundClick(() => onBackgroundClick())
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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-render when filtered data changes
  useEffect(() => {
    const fg = graphRef.current;
    if (!fg) return;
    fg.graphData({
      nodes: nodes.map((n) => ({ ...n })),
      links: links.map((l) => ({ ...l })),
    });
  }, [nodes, links]);

  // Size
  useEffect(() => {
    graphRef.current?.width(width).height(height);
  }, [width, height]);

  // Node color: selected node bright blue, linked nodes keep normal color, others dim
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
      if (selectedNodeId) {
        if (n.id === selectedNodeId) return "#60A5FA"; // selected: bright blue
        if (linkedNodeIds?.has(n.id)) {
          // connected: keep normal type color
          if (highlightImportant && (n.importance ?? 0) >= IMPORTANCE_THRESHOLD) return "#F59E0B";
          return TYPE_COLORS[n.type] ?? TYPE_COLORS.unknown;
        }
        return "rgba(50,50,50,0.18)"; // unrelated: very dim
      }
      if (hitIds) {
        if (!hitIds.has(n.id)) return "rgba(60,60,60,0.12)";
      }
      if (highlightImportant && (n.importance ?? 0) >= IMPORTANCE_THRESHOLD) return "#F59E0B";
      return TYPE_COLORS[n.type] ?? TYPE_COLORS.unknown;
    });
  }, [search, highlightImportant, selectedNodeId, linkedNodeIds, nodes]);

  return <div ref={containerRef} className="w-full h-full" />;
}
