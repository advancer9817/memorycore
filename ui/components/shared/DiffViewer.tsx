import React, { useMemo } from "react";
import Link from "next/link";
import { ArrowRight, History } from "lucide-react";

interface DiffViewerProps {
  oldText: string;
  newText: string;
  oldTitle?: string;
  newTitle?: string;
  oldId?: string;
  newId?: string;
}

type DiffToken = {
  text: string;
  type: "unchanged" | "added" | "removed";
};

function lcsDiff(oldStr: string, newStr: string): { aDiff: DiffToken[]; bDiff: DiffToken[] } {
  if (!oldStr && !newStr) return { aDiff: [], bDiff: [] };
  if (!oldStr) return { aDiff: [], bDiff: [{ text: newStr, type: "added" }] };
  if (!newStr) return { aDiff: [{ text: oldStr, type: "removed" }], bDiff: [] };

  const tokenize = (s: string) => s.match(/[\w\d]+|[^\w\d\s]|\s+/gu) || [s];
  const a = tokenize(oldStr);
  const b = tokenize(newStr);
  const m = a.length, n = b.length;

  // Fallback for extremely large texts to avoid high computation in render
  if (m * n > 250000) {
    return {
      aDiff: [{ text: oldStr, type: "removed" }],
      bDiff: [{ text: newStr, type: "added" }],
    };
  }

  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (a[i - 1] === b[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
  }

  let i = m;
  let j = n;
  const aDiff: DiffToken[] = [];
  const bDiff: DiffToken[] = [];

  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && a[i - 1] === b[j - 1]) {
      aDiff.unshift({ text: a[i - 1], type: "unchanged" });
      bDiff.unshift({ text: b[j - 1], type: "unchanged" });
      i--;
      j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      bDiff.unshift({ text: b[j - 1], type: "added" });
      j--;
    } else {
      aDiff.unshift({ text: a[i - 1], type: "removed" });
      i--;
    }
  }

  return { aDiff, bDiff };
}

export function DiffViewer({
  oldText,
  newText,
  oldTitle = "原记忆 (已废弃/变更前)",
  newTitle = "当前生效新记忆",
  oldId,
  newId,
}: DiffViewerProps) {
  const { aDiff, bDiff } = useMemo(() => lcsDiff(oldText, newText), [oldText, newText]);

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/80 p-4 space-y-3 text-xs shadow-sm">
      <div className="flex items-center justify-between border-b border-zinc-800/80 pb-2.5">
        <div className="flex items-center gap-1.5 font-semibold text-zinc-200">
          <History className="h-4 w-4 text-violet-400" />
          <span>知识演化版本比对 (Version Diff)</span>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-zinc-400">
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-rose-500/40 border border-rose-500" /> 移除
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-emerald-500/40 border border-emerald-500" /> 新增
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
        {/* 左栏：原条目 */}
        <div className="flex flex-col rounded-md border border-rose-950/40 bg-rose-950/10 p-3">
          <div className="flex items-center justify-between pb-2 border-b border-rose-900/20">
            <span className="font-medium text-rose-300 flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-rose-500" />
              {oldTitle}
            </span>
            {oldId && (
              <Link
                href={`/memory/${oldId}`}
                className="text-[11px] text-rose-400 hover:text-rose-300 hover:underline flex items-center gap-0.5"
              >
                查看原条目 <ArrowRight className="h-2.5 w-2.5" />
              </Link>
            )}
          </div>
          <div className="mt-2 text-zinc-300 leading-relaxed font-sans text-xs flex-1">
            {aDiff.length > 0 ? (
              aDiff.map((tok, idx) => (
                <span
                  key={idx}
                  className={
                    tok.type === "removed"
                      ? "bg-rose-500/25 text-rose-200 line-through rounded-sm px-0.5"
                      : "text-zinc-400"
                  }
                >
                  {tok.text}
                </span>
              ))
            ) : (
              <span className="text-zinc-600">（无旧版本内容）</span>
            )}
          </div>
        </div>

        {/* 右栏：新条目 */}
        <div className="flex flex-col rounded-md border border-emerald-950/40 bg-emerald-950/10 p-3">
          <div className="flex items-center justify-between pb-2 border-b border-emerald-900/20">
            <span className="font-medium text-emerald-300 flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              {newTitle}
            </span>
            {newId && (
              <Link
                href={`/memory/${newId}`}
                className="text-[11px] text-emerald-400 hover:text-emerald-300 hover:underline flex items-center gap-0.5"
              >
                查看新条目 <ArrowRight className="h-2.5 w-2.5" />
              </Link>
            )}
          </div>
          <div className="mt-2 text-zinc-200 leading-relaxed font-sans text-xs flex-1">
            {bDiff.length > 0 ? (
              bDiff.map((tok, idx) => (
                <span
                  key={idx}
                  className={
                    tok.type === "added"
                      ? "bg-emerald-500/25 text-emerald-200 font-medium rounded-sm px-0.5"
                      : "text-zinc-200"
                  }
                >
                  {tok.text}
                </span>
              ))
            ) : (
              <span className="text-zinc-600">（无新版本内容）</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
