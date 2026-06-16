"use client";

import { Input } from "@/components/ui/input";
import type { Messages } from "@/lib/i18n/types";

const GRAPH_LIMIT_OPTIONS = [500, 1000, 2000, 5000, 10000] as const;
const GRAPH_HIGH_LIMIT_WARNING = 5000;

interface GraphTopbarProps {
  listCollapsed: boolean;
  setListCollapsed: (v: boolean | ((prev: boolean) => boolean)) => void;
  searchInput: string;
  setSearchInput: (v: string) => void;
  data: { nodes: unknown[] } | null;
  filteredNodesLength: number;
  filteredEdgesLength: number;
  highlightImportant: boolean;
  setHighlightImportant: (v: boolean | ((prev: boolean) => boolean)) => void;
  importantCount: number;
  resetAll: () => void;
  limit: number;
  setLimit: (v: number) => void;
  handleExportJson: () => void;
  messages: Messages["graph"];
}

export function GraphTopbar({
  listCollapsed,
  setListCollapsed,
  searchInput,
  setSearchInput,
  data,
  filteredNodesLength,
  filteredEdgesLength,
  highlightImportant,
  setHighlightImportant,
  importantCount,
  resetAll,
  limit,
  setLimit,
  handleExportJson,
  messages: g,
}: GraphTopbarProps) {
  return (
    <div className="flex items-center gap-3 px-4 h-12 shrink-0" style={{ borderBottom: "1px solid rgba(255,255,255,0.06)", background: "#05070c" }}>

      {/* List collapse toggle — in topbar, left of brand */}
      <button
        onClick={() => setListCollapsed(v => !v)}
        className="shrink-0 w-7 h-7 flex items-center justify-center rounded-md transition-all hover:bg-white/5"
        style={{ border: "1px solid rgba(255,255,255,0.07)", color: "#52525b", fontSize: 12 }}
        title={listCollapsed ? g.expandList : g.collapseList}
      >{listCollapsed ? "›" : "‹"}</button>

      {/* Brand */}
      <div className="flex items-center gap-2 shrink-0">
        <span className="w-1.5 h-1.5 rounded-full bg-cyan-500 animate-pulse" />
        <span className="font-mono text-xs font-bold uppercase tracking-[0.15em] text-cyan-500/70 select-none">
          NeuralGraph
        </span>
      </div>

      {/* Divider */}
      <span className="w-px h-4 bg-white/8 shrink-0" />

      {/* Search — takes remaining space, centered feel */}
      <div className="flex-1 max-w-lg mx-auto">
        <Input
          className="w-full h-8 rounded-lg text-sm text-zinc-200 placeholder:text-zinc-600"
          style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
          placeholder={g.searchPlaceholder}
          value={searchInput}
          onChange={e => setSearchInput(e.target.value)}
        />
      </div>

      {/* Divider */}
      <span className="w-px h-4 bg-white/8 shrink-0" />

      {/* Action buttons */}
      <div className="flex items-center gap-1 shrink-0">
        {data && (
          <span className="font-mono text-xs text-zinc-600 mr-2 select-none whitespace-nowrap">
            <span className="text-zinc-400">{filteredNodesLength}</span>
            <span className="text-zinc-700">/{data.nodes.length}</span>
            <span className="mx-1.5 text-zinc-800">·</span>
            <span className="text-zinc-400">{filteredEdgesLength}</span>
            <span className="text-zinc-700"> {g.links}</span>
          </span>
        )}

        <button
          onClick={() => setHighlightImportant(v => !v)}
          className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md transition-all"
          style={{
            color: highlightImportant ? "#FBBF24" : "#52525b",
            background: highlightImportant ? "rgba(251,191,36,0.08)" : "transparent",
            border: `1px solid ${highlightImportant ? "rgba(251,191,36,0.2)" : "rgba(255,255,255,0.06)"}`,
          }}
        >
          <span>★</span>
          <span className="font-mono tabular-nums">{importantCount}</span>
        </button>

        <button
          onClick={resetAll}
          className="text-xs text-zinc-500 hover:text-zinc-200 px-2.5 py-1.5 rounded-md hover:bg-white/5 transition-all"
          style={{ border: "1px solid rgba(255,255,255,0.06)" }}
        >{g.reset}</button>

        <select
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
          className="text-xs text-zinc-400 px-2 py-1.5 rounded-md transition-all"
          style={{
            background: "rgba(255,255,255,0.04)",
            border: "1px solid rgba(255,255,255,0.08)",
            color: "#a1a1aa",
            outline: "none",
          }}
          title={g.limitTitle}
        >
          {GRAPH_LIMIT_OPTIONS.map((n) => (
            <option key={n} value={n}>{n}{n >= GRAPH_HIGH_LIMIT_WARNING ? g.slowSuffix : ""}</option>
          ))}
        </select>

        {limit >= GRAPH_HIGH_LIMIT_WARNING && (
          <span className="hidden sm:inline text-[10px] text-amber-500/70 font-mono">{g.largeGraphWarning}</span>
        )}

        <button
          onClick={handleExportJson}
          className="text-xs text-zinc-500 hover:text-zinc-200 px-2.5 py-1.5 rounded-md hover:bg-white/5 transition-all"
          style={{ border: "1px solid rgba(255,255,255,0.06)" }}
        >{g.export}</button>
      </div>
    </div>
  );
}
