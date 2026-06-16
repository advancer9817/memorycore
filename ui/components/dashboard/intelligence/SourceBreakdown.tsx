"use client";

import { RadioTower } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useI18n } from "@/hooks/useI18n";

function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function percentage(value: number, total: number): number {
  if (total <= 0) return 0;
  return Math.min(100, Math.round((value / total) * 100));
}

function BreakdownList({ title, entries, total }: { title: string; entries: [string, number][]; total: number }) {
  return (
    <div>
      <div className="mb-2 text-xs uppercase tracking-[0.16em] text-zinc-500">{title}</div>
      <div className="space-y-2">
        {entries.length > 0 ? (
          entries.map(([label, count]) => (
            <div key={label}>
              <div className="mb-1 flex items-center justify-between text-xs">
                <span className="text-zinc-300">{titleCase(label)}</span>
                <span className="text-zinc-500">{count}</span>
              </div>
              <Progress value={percentage(count, total)} className="h-1.5 bg-zinc-800" />
            </div>
          ))
        ) : (
          <div className="rounded-lg border border-zinc-800 bg-zinc-950/40 px-3 py-2 text-xs text-zinc-500">
            No distribution data yet.
          </div>
        )}
      </div>
    </div>
  );
}

interface SourceBreakdownProps {
  typeEntries: [string, number][];
  sourceEntries: [string, number][];
  totalMemories: number;
  recentMemoriesCount: number;
  recentCount: number;
  oldCount: number;
}

export function SourceBreakdown({ typeEntries, sourceEntries, totalMemories, recentMemoriesCount, recentCount, oldCount }: SourceBreakdownProps) {
  const { messages } = useI18n();
  const t = messages.dashboard;

  return (
    <Card className="border-zinc-800 bg-zinc-900 xl:col-span-2">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between text-sm font-medium text-zinc-300">
          {t.sourceBreakdown}
          <RadioTower className="h-4 w-4 text-zinc-500" />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <BreakdownList title={t.memoryTypes} entries={typeEntries} total={totalMemories} />
        <BreakdownList title={t.recentSources} entries={sourceEntries} total={Math.max(recentMemoriesCount, 1)} />
        <div className="rounded-lg border border-zinc-800 bg-zinc-950/45 px-3 py-2 text-xs text-zinc-500">
          {t.freshSignals(recentCount, oldCount)}
        </div>
      </CardContent>
    </Card>
  );
}
