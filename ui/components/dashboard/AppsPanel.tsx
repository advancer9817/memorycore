"use client";

import { useEffect, useState } from "react";
import { AppWindow, Database } from "lucide-react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useI18n } from "@/hooks/useI18n";
import { getApiBaseUrl } from "@/lib/api-url";

type AppSummary = {
  id: string;
  name: string;
  total_memories_created: number;
  total_memories_accessed: number;
  is_active: boolean;
  status: string;
  last_activity_at?: string | null;
};

export function AppsPanel() {
  const { messages: t } = useI18n();
  const [apps, setApps] = useState<AppSummary[]>([]);

  useEffect(() => {
    let active = true;
    fetch(`${getApiBaseUrl()}/api/v1/apps/?sort_by=last_activity&sort_direction=desc&page_size=100`)
      .then((response) => response.json())
      .then((payload) => {
        if (active) setApps((payload as { apps?: AppSummary[] }).apps ?? []);
      })
      .catch(() => {
        if (active) setApps([]);
      });
    return () => {
      active = false;
    };
  }, []);

  if (apps.length === 0) {
    return null;
  }

  return (
    <Card className="border-zinc-800 bg-zinc-900">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between text-sm font-medium text-zinc-300">
          <span className="flex items-center gap-2">
            <AppWindow className="h-4 w-4 text-sky-400" /> {t.apps.title}
          </span>
          <span className="text-xs font-normal text-zinc-500">{apps.length} {t.nav.apps}</span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {apps.slice(0, 12).map((app) => (
            <Link
              key={app.id}
              href={`/apps/${encodeURIComponent(app.id)}`}
              className="group rounded-lg border border-zinc-800 bg-zinc-800/50 p-3 transition-colors hover:bg-zinc-800"
            >
              <div className="flex items-center justify-between">
                <span className="truncate text-sm font-medium text-zinc-200">{app.name}</span>
                <span
                  className={`h-2 w-2 shrink-0 rounded-full ${app.status === "online" || (app.is_active && app.status !== "offline") ? "bg-emerald-500" : "bg-zinc-600"}`}
                  title={app.status}
                />
              </div>
              <div className="mt-2 flex items-center gap-4 text-xs text-zinc-500">
                <span className="flex items-center gap-1">
                  <Database className="h-3 w-3" /> {app.total_memories_created} {t.apps.memoriesUnit}
                </span>
                <span>{t.apps.totalMemoriesAccessed}: {app.total_memories_accessed}</span>
              </div>
              {app.last_activity_at && <div className="mt-1 text-[10px] text-zinc-600">{t.apps.lastAccessed} {(app.last_activity_at || "").slice(0, 16).replace("T", " ")}</div>}
            </Link>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}