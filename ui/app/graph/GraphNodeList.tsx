"use client";

import { useRef } from "react";
import type { Virtualizer } from "@tanstack/react-virtual";
import { type GraphNode, TYPE_COLORS, IMPORTANCE_THRESHOLD } from "./types";
import type { Messages } from "@/lib/i18n/types";

interface GraphNodeListProps {
  sortedListNodes: GraphNode[];
  selectedNode: GraphNode | null;
  linked: Set<string> | null;
  listScrollRef: React.RefObject<HTMLDivElement | null>;
  rowVirtualizer: Virtualizer<HTMLDivElement, Element>;
  handleNodeSelect: (node: GraphNode) => void;
  messages: Messages["graph"];
}

export function GraphNodeList({
  sortedListNodes,
  selectedNode,
  linked,
  listScrollRef,
  rowVirtualizer,
  handleNodeSelect,
  messages: g,
}: GraphNodeListProps) {
  return (
    <>
      {/* Node list header */}
      <div className="px-3 py-2 shrink-0 flex items-center" style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
        <span className="font-mono text-[10px] text-zinc-600 uppercase tracking-widest">
          {g.nodesHeading} <span className="text-zinc-400">{sortedListNodes.length}</span>
        </span>
      </div>

      <div ref={listScrollRef} className="flex-1 overflow-y-auto">
        {sortedListNodes.length === 0 && (
          <div className="px-3 py-8 text-center text-xs text-zinc-700 font-mono">
            {g.noMatchingNodes}<br />
            <span className="text-zinc-800">{g.adjustFilters}</span>
          </div>
        )}
        <div
          style={{
            height: `${rowVirtualizer.getTotalSize()}px`,
            width: "100%",
            position: "relative",
          }}
        >
          {rowVirtualizer.getVirtualItems().map((virtualRow) => {
            const node = sortedListNodes[virtualRow.index];
            const color = TYPE_COLORS[node.type] ?? "#64748B";
            const isSelected = selectedNode?.id === node.id;
            const isLinked = linked && !isSelected && linked.has(node.id);
            return (
              <div
                key={node.id}
                onClick={() => handleNodeSelect(node)}
                className="px-3 py-2.5 cursor-pointer transition-all absolute top-0 left-0 right-0"
                style={{
                  transform: `translateY(${virtualRow.start}px)`,
                  borderBottom: "1px solid rgba(255,255,255,0.03)",
                  borderLeft: isSelected ? `2px solid ${color}` : "2px solid transparent",
                  background: isSelected ? `${color}10` : isLinked ? "rgba(255,255,255,0.02)" : "transparent",
                }}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="w-2 h-2 rounded-full shrink-0 flex-none" style={{ background: color }} />
                  <p className="text-sm text-zinc-200 leading-tight truncate flex-1 min-w-0">{node.title}</p>
                  {node.importance >= IMPORTANCE_THRESHOLD && <span className="text-amber-400 text-xs shrink-0">★</span>}
                  <span className="text-xs text-zinc-500 shrink-0 font-mono tabular-nums">{node.importance.toFixed(2)}</span>
                </div>
                <div className="ml-4 mt-0.5 text-xs text-zinc-700">{node.type.replace(/_/g, " ")}</div>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
