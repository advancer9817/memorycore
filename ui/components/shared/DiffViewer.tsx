import React from "react";

interface DiffViewerProps {
  oldText: string;
  newText: string;
  oldTitle?: string;
  newTitle?: string;
}

export function DiffViewer({
  oldText,
  newText,
  oldTitle = "原记忆 (已废弃/冲突)",
  newTitle = "当前生效新记忆",
}: DiffViewerProps) {
  // Simple token/word-level LCS diff
  const oldWords = oldText.split(/(\s+|[，。！？、；：])/).filter(Boolean);
  const newWords = newText.split(/(\s+|[，。！？、；：])/).filter(Boolean);

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-4 space-y-3 text-xs">
      <div className="flex items-center justify-between border-b border-zinc-800/80 pb-2">
        <span className="font-semibold text-zinc-300">知识演化版本比对 (Version Diff)</span>
        <span className="text-[11px] text-zinc-500">双向溯源对比</span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="space-y-1.5 rounded-md border border-rose-950/40 bg-rose-950/10 p-3">
          <div className="font-medium text-rose-300 flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-rose-500" />
            {oldTitle}
          </div>
          <div className="text-zinc-400 leading-relaxed whitespace-pre-wrap font-sans">
            {oldText || "（空）"}
          </div>
        </div>
        <div className="space-y-1.5 rounded-md border border-emerald-950/40 bg-emerald-950/10 p-3">
          <div className="font-medium text-emerald-300 flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            {newTitle}
          </div>
          <div className="text-zinc-200 leading-relaxed whitespace-pre-wrap font-sans">
            {newText || "（空）"}
          </div>
        </div>
      </div>
    </div>
  );
}
