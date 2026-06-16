"use client";

import { ShieldCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useI18n } from "@/hooks/useI18n";
import { HealthSignal } from "./helpers";
import { MetricBar } from "./Primitives";

interface HealthMetricsPanelProps {
  qualityScore: number;
  healthSignals: HealthSignal[];
  t: ReturnType<typeof useI18n>["messages"]["dashboard"];
}

export function HealthMetricsPanel({ qualityScore, healthSignals, t }: HealthMetricsPanelProps) {
  return (
    <Card className="border-zinc-800 bg-zinc-900 xl:col-span-2">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between text-sm font-medium text-zinc-300">
          {t.memoryHealth}
          <ShieldCheck className="h-4 w-4 text-emerald-400" />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded-xl border border-zinc-800 bg-zinc-950/55 p-4">
          <div className="flex items-end justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-zinc-500">{t.governanceScore}</p>
              <div className="mt-2 text-3xl font-semibold text-white">{qualityScore}</div>
            </div>
            <Badge
              className={
                qualityScore >= 70
                  ? "border-emerald-700 bg-emerald-500/10 text-emerald-300"
                  : "border-amber-700 bg-amber-500/10 text-amber-300"
              }
              variant="outline"
            >
              {qualityScore >= 70 ? t.healthy : t.needsWork}
            </Badge>
          </div>
          <Progress value={qualityScore} className="mt-4 h-2 bg-zinc-800" />
          <p className="mt-2 text-xs leading-relaxed text-zinc-500">{t.healthScoreDescription}</p>
        </div>
        {healthSignals.map((signal) => (
          <MetricBar key={signal.label} label={signal.label} value={signal.value} detail={signal.detail} />
        ))}
      </CardContent>
    </Card>
  );
}
