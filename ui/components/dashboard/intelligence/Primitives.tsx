"use client";

import Link from "next/link";
import { ReactNode } from "react";
import { ArrowRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useI18n } from "@/hooks/useI18n";
import { formatNumber, percentage, titleCase, TrendPoint } from "./helpers";

export function SectionHeader() {
  const { messages } = useI18n();
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h2 className="text-base font-medium text-zinc-300">{messages.dashboard.intelligenceTitle}</h2>
        <p className="mt-1 max-w-3xl text-sm text-zinc-500">
          {messages.dashboard.intelligenceDescription}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button asChild variant="outline" size="sm" className="w-fit border-zinc-700/50 bg-zinc-900 text-zinc-300 hover:bg-zinc-800">
          <Link href="/memories">
            {messages.dashboard.openMemories}
            <ArrowRight className="h-4 w-4" />
          </Link>
        </Button>
      </div>
    </div>
  );
}

export function TrendTile({ point }: { point: TrendPoint }) {
  const toneClass =
    point.tone === "danger"
      ? "text-red-300 bg-red-950/30 border-red-900/60"
      : point.tone === "warn"
        ? "text-amber-300 bg-amber-950/30 border-amber-900/60"
        : "text-emerald-300 bg-emerald-950/30 border-emerald-900/60";
  return (
    <div className={`rounded-xl border p-3 ${toneClass}`}>
      <div className="text-xs uppercase tracking-[0.16em] text-current/70">{point.label}</div>
      <div className="mt-2 text-2xl font-semibold">{formatNumber(point.value)}</div>
      <p className="mt-1 text-xs leading-relaxed text-current/75">{point.detail}</p>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-black/20">
        <div className="h-full rounded-full bg-current" style={{ width: `${Math.min(100, Math.max(8, point.value))}%` }} />
      </div>
    </div>
  );
}

export function MetricBar({ label, value, detail }: { label: string; value: number; detail: string }) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between text-xs">
        <span className="text-zinc-400">{label}</span>
        <span className="text-zinc-500">{detail}</span>
      </div>
      <Progress value={value} className="h-1.5 bg-zinc-800" />
    </div>
  );
}

export function GraphMetric({ icon, label, value }: { icon: ReactNode; label: string; value: number }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-950/55 p-3">
      <div className="flex items-center justify-between text-zinc-500">
        <span className="text-xs">{label}</span>
        {icon}
      </div>
      <div className="mt-2 text-xl font-semibold text-white">{formatNumber(value)}</div>
    </div>
  );
}

export function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/45 px-3 py-2">
      <div className="text-[10px] uppercase tracking-[0.16em] text-zinc-600">{label}</div>
      <div className="mt-1 text-sm font-medium text-zinc-200">{value}</div>
    </div>
  );
}

export function TimelineItem({
  icon,
  title,
  detail,
  time,
}: {
  icon: ReactNode;
  title: string;
  detail: string;
  time: string;
}) {
  return (
    <div className="flex gap-3 rounded-xl border border-zinc-800 bg-zinc-950/45 p-3">
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-zinc-700 bg-zinc-900 text-zinc-400">
        {icon}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-medium text-zinc-200">{title}</p>
          <span className="text-xs text-zinc-500">{time}</span>
        </div>
        <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-zinc-500">{detail}</p>
      </div>
    </div>
  );
}

export function BreakdownList({
  title,
  entries,
  total,
}: {
  title: string;
  entries: [string, number][];
  total: number;
}) {
  const { messages } = useI18n();
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
            {messages.dashboard.noDistribution}
          </div>
        )}
      </div>
    </div>
  );
}

export function MemoryIntelligenceSkeleton() {
  return (
    <section className="space-y-4">
      <SectionHeader />
      {/* Health panel skeleton */}
      <Card className="border-zinc-800 bg-zinc-900">
        <CardHeader>
          <div className="h-4 w-28 animate-pulse rounded bg-zinc-800" />
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-5 lg:flex-row lg:items-start">
            <div className="flex shrink-0 flex-col items-center gap-3 lg:w-48">
              <div className="h-32 w-32 animate-pulse rounded-full bg-zinc-800/60" />
              <div className="h-5 w-16 animate-pulse rounded bg-zinc-800" />
            </div>
            <div className="grid flex-1 grid-cols-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
              {[0, 1, 2, 3, 4].map((i) => (
                <div key={i} className="h-20 animate-pulse rounded-lg bg-zinc-800/50" />
              ))}
            </div>
          </div>
        </CardContent>
      </Card>
      {/* Activity + Breakdown skeleton */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <Card className="border-zinc-800 bg-zinc-900 xl:col-span-3">
          <CardHeader>
            <div className="h-4 w-32 animate-pulse rounded bg-zinc-800" />
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="h-16 animate-pulse rounded bg-zinc-800/60" />
            <div className="h-16 animate-pulse rounded bg-zinc-800/50" />
            <div className="h-16 animate-pulse rounded bg-zinc-800/40" />
          </CardContent>
        </Card>
        <Card className="border-zinc-800 bg-zinc-900 xl:col-span-2">
          <CardHeader>
            <div className="h-4 w-28 animate-pulse rounded bg-zinc-800" />
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="h-12 animate-pulse rounded bg-zinc-800/60" />
            <div className="h-12 animate-pulse rounded bg-zinc-800/50" />
            <div className="h-12 animate-pulse rounded bg-zinc-800/40" />
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
