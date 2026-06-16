"use client";

import { TYPE_COLORS, EDGE_COLORS } from "./types";
import type { Messages } from "@/lib/i18n/types";

interface GraphFilterPanelProps {
  allTypes: string[];
  allEdgeTypes: string[];
  activeTypes: Set<string>;
  activeEdgeTypes: Set<string>;
  activeStatus: string;
  filtersOpen: boolean;
  setFiltersOpen: (open: boolean | ((prev: boolean) => boolean)) => void;
  toggleType: (t: string) => void;
  toggleEdgeType: (t: string) => void;
  setActiveStatus: (status: string) => void;
  messages: Messages["graph"];
}

export function GraphFilterPanel({
  allTypes,
  allEdgeTypes,
  activeTypes,
  activeEdgeTypes,
  activeStatus,
  filtersOpen,
  setFiltersOpen,
  toggleType,
  toggleEdgeType,
  setActiveStatus,
  messages: g,
}: GraphFilterPanelProps) {
  return (
    <div className="shrink-0" style={{ borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
      <button
        onClick={() => setFiltersOpen(v => !v)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-mono uppercase tracking-widest transition-colors hover:bg-white/3"
        style={{ color: filtersOpen ? "#06B6D4" : "#52525b" }}
      >
        <span className="flex items-center gap-1.5">
          <span style={{ fontSize: 9 }}>{filtersOpen ? "▾" : "▸"}</span>
          {g.filter}
          {/* Active filter badge */}
          {(activeTypes.size < allTypes.length || activeEdgeTypes.size < allEdgeTypes.length || activeStatus !== "all") && (
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-500" />
          )}
        </span>
      </button>

      {filtersOpen && (
        <div className="px-3 pb-3 space-y-3">
          {/* Type filters */}
          <div>
            <p className="text-[10px] font-mono text-zinc-700 uppercase tracking-widest mb-1.5">{g.nodeTypes}</p>
            <div className="flex flex-wrap gap-1">
              {allTypes.map(t => {
                const active = activeTypes.has(t);
                const color = TYPE_COLORS[t] ?? "#64748B";
                return (
                  <button key={t} type="button" onClick={() => toggleType(t)}
                    className="flex items-center gap-1 rounded px-1.5 py-0.5 text-xs transition-all"
                    style={{ color: active ? color : "#52525b", background: active ? `${color}15` : "rgba(255,255,255,0.03)", border: `1px solid ${active ? `${color}30` : "rgba(255,255,255,0.06)"}` }}
                  >
                    <span className="w-1 h-1 rounded-full shrink-0" style={{ background: active ? color : "#3f3f46" }} />
                    {t.replace(/_/g, " ")}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Edge type filters */}
          <div>
            <p className="text-[10px] font-mono text-zinc-700 uppercase tracking-widest mb-1.5">{g.edgeTypes}</p>
            <div className="flex flex-wrap gap-1">
              {allEdgeTypes.map(e => {
                const active = activeEdgeTypes.has(e);
                const color = EDGE_COLORS[e] ?? "#64748B";
                return (
                  <button key={e} type="button" onClick={() => toggleEdgeType(e)}
                    className="flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium transition-all"
                    style={{
                      color: active ? color : "#52525b",
                      background: active ? `${color}24` : "rgba(255,255,255,0.03)",
                      border: `1px solid ${active ? `${color}70` : "rgba(255,255,255,0.06)"}`,
                      boxShadow: active ? `0 0 10px ${color}22, inset 0 0 8px ${color}14` : "none",
                    }}
                  >
                    <span
                      className="w-1.5 h-1.5 rounded-full shrink-0"
                      style={{ background: active ? color : "#3f3f46", boxShadow: active ? `0 0 8px ${color}` : "none" }}
                    />
                    {e.replace(/_/g, " ")}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Status filter */}
          <div>
            <p className="text-[10px] font-mono text-zinc-700 uppercase tracking-widest mb-1.5">{g.status}</p>
            <div className="flex gap-1">
              {(["all", "active", "candidate", "stale", "archived", "contradicted"] as const).map(s => (
                <button key={s} type="button" onClick={() => setActiveStatus(s)}
                  className="rounded px-2 py-0.5 text-xs transition-all"
                  style={{
                    color: activeStatus === s ? "#60A5FA" : "#52525b",
                    background: activeStatus === s ? "rgba(96,165,250,0.1)" : "rgba(255,255,255,0.03)",
                    border: `1px solid ${activeStatus === s ? "rgba(96,165,250,0.25)" : "rgba(255,255,255,0.06)"}`,
                  }}
                >{s}</button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
