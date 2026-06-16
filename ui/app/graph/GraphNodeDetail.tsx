"use client";

import { Button } from "@/components/ui/button";
import { type GraphNode, TYPE_COLORS, IMPORTANCE_THRESHOLD } from "./types";
import type { Messages } from "@/lib/i18n/types";

interface GraphNodeDetailProps {
  selectedNode: GraphNode;
  fullContent: string | null;
  isEditing: boolean;
  editImportance: number;
  editStatus: string;
  setEditImportance: (v: number) => void;
  setEditStatus: (v: string) => void;
  setIsEditing: (v: boolean) => void;
  setSelectedNode: (v: GraphNode | null) => void;
  onSave: () => void;
  filteredNodes: GraphNode[];
  linked: Set<string> | null;
  handleNodeSelect: (node: GraphNode) => void;
  messages: Messages["graph"];
}

export function GraphNodeDetail({
  selectedNode,
  fullContent,
  isEditing,
  editImportance,
  editStatus,
  setEditImportance,
  setEditStatus,
  setIsEditing,
  setSelectedNode,
  onSave,
  filteredNodes,
  linked,
  handleNodeSelect,
  messages: g,
}: GraphNodeDetailProps) {
  return (
    <div className="flex-1 flex flex-col overflow-hidden" style={{ background: "rgba(3,5,10,0.95)", backdropFilter: "blur(16px)", borderLeft: "1px solid rgba(255,255,255,0.06)" }}>

      {/* Detail header */}
      <div className="px-4 py-4 shrink-0" style={{ borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
        <div className="flex items-start justify-between gap-2 mb-3">
          <div className="min-w-0 flex-1">
            <p className="text-[10px] font-mono uppercase tracking-[0.12em] mb-1" style={{ color: TYPE_COLORS[selectedNode.type] ?? "#64748B" }}>
              {selectedNode.type.replace(/_/g, " ")}
            </p>
            <h2 className="text-sm font-semibold text-zinc-100 leading-snug">{selectedNode.title}</h2>
          </div>
          <div className="flex items-center gap-1 shrink-0 mt-0.5">
            {!isEditing && (
              <button onClick={() => setIsEditing(true)}
                className="text-xs text-zinc-600 hover:text-zinc-300 px-2 py-1 rounded transition-all"
                style={{ border: "1px solid rgba(255,255,255,0.07)" }}>
                {g.edit}
              </button>
            )}
            <button onClick={() => setSelectedNode(null)}
              className="text-zinc-600 hover:text-zinc-200 w-7 h-7 flex items-center justify-center rounded text-base transition-all hover:bg-white/5">×</button>
          </div>
        </div>

        {/* Importance bar */}
        <div className="flex items-center gap-3">
          <div className="flex-1 h-1 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.06)" }}>
            <div className="h-full rounded-full transition-all" style={{ width: `${selectedNode.importance * 100}%`, background: selectedNode.importance >= IMPORTANCE_THRESHOLD ? "#FBBF24" : TYPE_COLORS[selectedNode.type] ?? "#06B6D4" }} />
          </div>
          <span className="font-mono text-xs text-zinc-500 tabular-nums shrink-0 w-9 text-right">{(selectedNode.importance * 100).toFixed(0)}%</span>
        </div>
      </div>

      {/* Detail body */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-5">
        {isEditing ? (
          <div className="space-y-4">
            <div>
              <label className="text-[10px] text-zinc-600 block mb-2 font-mono uppercase tracking-widest">{g.importance(editImportance)}</label>
              <input type="range" min="0" max="1" step="0.1" value={editImportance} onChange={e => setEditImportance(parseFloat(e.target.value))} className="w-full accent-cyan-500" />
            </div>
            <div>
              <label className="text-[10px] text-zinc-600 block mb-2 font-mono uppercase tracking-widest">{g.statusLabel}</label>
              <select value={editStatus} onChange={e => setEditStatus(e.target.value)}
                className="w-full text-sm rounded-lg px-3 py-2"
                style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.1)", color: "#d4d4d8" }}>
                {["active", "candidate", "stale", "archived"].map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div className="flex gap-2">
              <Button size="sm" className="flex-1 h-8 text-xs bg-cyan-600 hover:bg-cyan-700 text-white border-0"
                onClick={onSave}>{g.save}</Button>
              <Button size="sm" variant="outline" className="flex-1 h-8 text-xs border-white/10 text-zinc-400" onClick={() => setIsEditing(false)}>{g.cancel}</Button>
            </div>
          </div>
        ) : (
          <>
            {/* Content */}
            <div>
              <p className="text-[10px] font-mono uppercase tracking-widest text-zinc-700 mb-2">{g.content}</p>
              <p className="text-sm text-zinc-300 leading-relaxed whitespace-pre-wrap break-words">
                {fullContent ?? selectedNode.content ?? g.loadingContent}
              </p>
            </div>

            {/* Stats */}
            <div className="grid grid-cols-3 gap-2">
              {[
                [g.feedback, selectedNode.feedback_score >= 0 ? `+${selectedNode.feedback_score.toFixed(1)}` : selectedNode.feedback_score.toFixed(1)],
                [g.injected, `${selectedNode.injected_count}×`],
                [g.statusLabel, selectedNode.status],
              ].map(([label, value]) => (
                <div key={label} className="rounded-lg px-3 py-2.5" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)" }}>
                  <div className="text-[10px] text-zinc-600 font-mono uppercase tracking-wider">{label}</div>
                  <div className="text-sm text-zinc-200 font-medium mt-1">{value}</div>
                </div>
              ))}
            </div>

            {/* Related nodes */}
            {linked && linked.size > 1 && (
              <div>
                <p className="text-[10px] font-mono uppercase tracking-widest text-zinc-700 mb-2">{g.related} ({linked.size - 1})</p>
                <div className="space-y-0.5">
                  {filteredNodes.filter(n => linked.has(n.id) && n.id !== selectedNode.id).slice(0, 8).map(n => (
                    <button key={n.id} onClick={() => handleNodeSelect(n)}
                      className="w-full text-left px-2 py-2 rounded-lg flex items-center gap-2 transition-colors hover:bg-white/4"
                      style={{ border: "1px solid transparent" }}
                      onMouseEnter={e => (e.currentTarget.style.borderColor = "rgba(255,255,255,0.06)")}
                      onMouseLeave={e => (e.currentTarget.style.borderColor = "transparent")}
                    >
                      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: TYPE_COLORS[n.type] ?? "#64748B" }} />
                      <span className="text-xs text-zinc-400 truncate">{n.title}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
