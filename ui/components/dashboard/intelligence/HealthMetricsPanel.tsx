"use client";

import { ShieldCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useI18n } from "@/hooks/useI18n";
import { HealthSignal } from "./helpers";

interface HealthMetricsPanelProps {
  qualityScore: number;
  healthSignals: HealthSignal[];
  t: ReturnType<typeof useI18n>["messages"]["dashboard"];
}

function scoreColor(value: number): string {
  if (value >= 80) return "text-emerald-400";
  if (value >= 60) return "text-amber-400";
  return "text-red-400";
}

function barColor(value: number): string {
  if (value >= 80) return "bg-emerald-500";
  if (value >= 60) return "bg-amber-500";
  return "bg-red-500";
}

function SignalCard({ signal }: { signal: HealthSignal }) {
  // lower-is-better signals (cleanup backlog) must be praised when LOW:
  // invert the value before feeding the shared high-is-good color scale.
  const colorValue = signal.inverted ? 100 - signal.value : signal.value;
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/50 px-3 py-2.5">
      <div className="flex items-center justify-between text-xs">
        <span className="text-zinc-400">{signal.label}</span>
        <span className={`font-mono font-medium ${scoreColor(colorValue)}`}>
          {Math.round(signal.value)}%
        </span>
      </div>
      <div className="mt-2 h-1 overflow-hidden rounded-full bg-zinc-800">
        <div
          className={`h-full rounded-full transition-all ${barColor(colorValue)}`}
          style={{ width: `${Math.min(100, Math.max(2, signal.value))}%` }}
        />
      </div>
      <p className="mt-1.5 text-[11px] text-zinc-600 truncate" title={signal.detail}>
        {signal.detail}
      </p>
    </div>
  );
}

export function HealthMetricsPanel({ qualityScore, healthSignals, t }: HealthMetricsPanelProps) {
  const circumference = 2 * Math.PI * 54;
  const dashOffset = circumference * (1 - qualityScore / 100);

  return (
    <Card className="border-zinc-800 bg-zinc-900">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between text-sm font-medium text-zinc-300">
          {t.memoryHealth}
          <ShieldCheck className="h-4 w-4 text-emerald-400" />
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start">
          {/* Score gauge */}
          <div className="flex shrink-0 flex-col items-center gap-3 lg:w-48">
            <div className="relative h-32 w-32">
              <svg viewBox="0 0 120 120" className="h-full w-full -rotate-90">
                <circle
                  cx="60" cy="60" r="54"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="6"
                  className="text-zinc-800"
                />
                <circle
                  cx="60" cy="60" r="54"
                  fill="none"
                  strokeWidth="6"
                  strokeLinecap="round"
                  strokeDasharray={circumference}
                  strokeDashoffset={dashOffset}
                  className={scoreColor(qualityScore)}
                  stroke="currentColor"
                />
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className={`text-3xl font-semibold ${scoreColor(qualityScore)}`}>
                  {qualityScore}
                </span>
              </div>
            </div>
            <Badge
              className={
                qualityScore >= 70
                  ? "border-emerald-800 bg-emerald-500/10 text-emerald-300"
                  : qualityScore >= 50
                    ? "border-amber-800 bg-amber-500/10 text-amber-300"
                    : "border-red-800 bg-red-500/10 text-red-300"
              }
              variant="outline"
            >
              {qualityScore >= 70 ? t.healthy : t.needsWork}
            </Badge>
            <p className="text-center text-[11px] leading-relaxed text-zinc-600">
              {t.healthScoreDescription}
            </p>
          </div>

          {/* Signal grid */}
          <div className="grid flex-1 grid-cols-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
            {healthSignals.map((signal) => (
              <SignalCard key={signal.label} signal={signal} />
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
