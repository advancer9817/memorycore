"use client";

import { RadioTower } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useI18n } from "@/hooks/useI18n";
import { BreakdownList } from "./Primitives";

interface SourceBreakdownPanelProps {
  typeEntries: [string, number][];
  sourceEntries: [string, number][];
  totalMemories: number;
  recentMemoriesCount: number;
  recentCount: number;
  oldCount: number;
  t: ReturnType<typeof useI18n>["messages"]["dashboard"];
}

export function SourceBreakdownPanel({
  typeEntries,
  sourceEntries,
  totalMemories,
  recentMemoriesCount,
  recentCount,
  oldCount,
  t,
}: SourceBreakdownPanelProps) {
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
        <BreakdownList
          title={t.recentSources}
          entries={sourceEntries}
          total={Math.max(recentMemoriesCount, 1)}
        />
        <div className="rounded-lg border border-zinc-800 bg-zinc-950/45 px-3 py-2 text-xs text-zinc-500">
          {t.freshSignals(recentCount, oldCount)}
        </div>
      </CardContent>
    </Card>
  );
}
