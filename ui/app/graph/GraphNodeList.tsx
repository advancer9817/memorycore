"use client";

import { useRef } from "react";
import type { Virtualizer } from "@tanstack/react-virtual";
import type { CSSProperties } from "react";
import { type GraphNode, IMPORTANCE_THRESHOLD, TYPE_BG_CLASSES } from "./types";
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
  const listStyle: CSSProperties = {
    height: `${rowVirtualizer.getTotalSize()}px`,
    width: "100%",
    position: "relative",
  };
  return (
    <>
      {/* Node list header */}
      <div className="flex shrink-0 items-center border-b border-white/[0.04] px-3 py-2">
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
        <div style={listStyle}>
          {rowVirtualizer.getVirtualItems().map((virtualRow) => {
            const node = sortedListNodes[virtualRow.index];
            const isSelected = selectedNode?.id === node.id;
            const isLinked = linked && !isSelected && linked.has(node.id);
            const rowStyle: CSSProperties = {
              transform: `translateY(${virtualRow.start}px)`,
            };
            return (
              <div
                key={node.id}
                onClick={() => handleNodeSelect(node)}
                className={`absolute left-0 right-0 top-0 cursor-pointer border-b border-l-2 border-b-white/[0.03] px-3 py-2.5 transition-all ${isSelected ? "border-l-cyan-500 bg-cyan-500/10" : isLinked ? "border-l-transparent bg-white/[0.02]" : "border-l-transparent bg-transparent"}`}
                style={rowStyle}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className={`h-2 w-2 flex-none shrink-0 rounded-full ${TYPE_BG_CLASSES[node.type] ?? TYPE_BG_CLASSES.unknown}`} />
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
