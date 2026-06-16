"use client";

import { ReactNode } from "react";
import { Activity, CheckCircle2, Clock3, Workflow } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useI18n } from "@/hooks/useI18n";

interface CurationTimelineProps {
  curatorGeneratedAt?: string;
  curatorScanned?: number;
  totalMemories: number;
  serviceResult?: string;
  recentMemoryTitle: string;
  recentMemoryTime: string;
  timerNextElapse?: string;
  timerActiveState?: string;
}

function formatDate(value?: string | number, locale: "en" | "zh" = "en"): string {
  if (!value || value === "n/a") return "n/a";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "n/a";
  return date.toLocaleString(locale === "zh" ? "zh-CN" : "en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function TimelineItem({ icon, title, detail, time }: { icon: ReactNode; title: string; detail: string; time: string }) {
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

export function CurationTimeline({
  curatorGeneratedAt,
  curatorScanned,
  totalMemories,
  serviceResult,
  recentMemoryTitle,
  recentMemoryTime,
  timerNextElapse,
  timerActiveState,
}: CurationTimelineProps) {
  const { messages, locale } = useI18n();
  const t = messages.dashboard;

  return (
    <Card className="border-zinc-800 bg-zinc-900 xl:col-span-3">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between text-sm font-medium text-zinc-300">
          {t.curationActivity}
          <Clock3 className="h-4 w-4 text-zinc-500" />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <TimelineItem
          icon={<Workflow className="h-4 w-4" />}
          title={t.curatorScanCompleted}
          detail={t.curatorScanDetail(curatorScanned ?? totalMemories, serviceResult ?? t.unknown)}
          time={formatDate(curatorGeneratedAt, locale)}
        />
        <TimelineItem
          icon={<Activity className="h-4 w-4" />}
          title={t.recentMemorySignal}
          detail={recentMemoryTitle}
          time={recentMemoryTime}
        />
        <TimelineItem
          icon={<CheckCircle2 className="h-4 w-4" />}
          title={t.backgroundSchedule}
          detail={t.backgroundScheduleNextRun(formatDate(timerNextElapse, locale))}
          time={timerActiveState ?? t.unknown}
        />
      </CardContent>
    </Card>
  );
}
