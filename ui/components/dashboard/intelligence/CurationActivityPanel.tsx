"use client";

import { Activity, CheckCircle2, Clock3, Workflow } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useI18n } from "@/hooks/useI18n";
import { CuratorStatusPayload, MemoryApiItem, formatDate, getMemoryTitle } from "./helpers";
import { TimelineItem } from "./Primitives";

interface CurationActivityPanelProps {
  curatorStatus: CuratorStatusPayload | null;
  recentMemories: MemoryApiItem[];
  totalMemories: number;
  t: ReturnType<typeof useI18n>["messages"]["dashboard"];
}

export function CurationActivityPanel({
  curatorStatus,
  recentMemories,
  totalMemories,
  t,
}: CurationActivityPanelProps) {
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
          title={t.curationCuratorScan}
          detail={t.curationCuratorScanDetail(curatorStatus?.curator?.scanned ?? totalMemories, curatorStatus?.service?.Result ?? t.unknown)}
          time={formatDate(curatorStatus?.curator?.generated_at)}
        />
        <TimelineItem
          icon={<Activity className="h-4 w-4" />}
          title={t.curationRecentSignal}
          detail={getMemoryTitle(recentMemories[0])}
          time={formatDate(recentMemories[0]?.created_at)}
        />
        <TimelineItem
          icon={<CheckCircle2 className="h-4 w-4" />}
          title={t.curationBackgroundSchedule}
          detail={t.curationNextRun(formatDate(curatorStatus?.timer?.NextElapseUSecRealtime))}
          time={curatorStatus?.timer?.ActiveState ?? t.unknown}
        />
      </CardContent>
    </Card>
  );
}
