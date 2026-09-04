"use client";

import { useEffect, useState } from "react";
import { AppWindow, Database, Settings2, Bot, Server } from "lucide-react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useI18n } from "@/hooks/useI18n";
import { getApiBaseUrl } from "@/lib/api-url";

type AppSummary = {
  id: string;
  name: string;
  display_name?: string;
  description?: string;
  category?: "agent" | "system" | string;
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
    <Card className="border-zinc-800 bg-zinc-900 shadow-sm">
      <CardHeader className="pb-3 border-b border-zinc-800/60">
        <CardTitle className="flex items-center justify-between text-sm font-medium text-zinc-300">
          <span className="flex items-center gap-2">
            <AppWindow className="h-4 w-4 text-sky-400" />
            <span>{t.apps.title}</span>
            <span className="text-xs text-zinc-500 font-normal">
              (授权写入与接入通道)
            </span>
          </span>
          <span className="text-xs font-normal text-zinc-500">
            {apps.length} 个接入方
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-4">
        <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2 xl:grid-cols-4">
          {apps.map((app) => {
            const isSystem = app.id === "mcore" || app.category === "system";
            const displayName = app.display_name || app.name;
            const isOnline = app.status === "online" || (app.is_active && app.status !== "offline");

            return (
              <Link
                key={app.id}
                href={`/apps/${encodeURIComponent(app.id)}`}
                className="group relative flex flex-col justify-between rounded-xl border border-zinc-800 bg-zinc-950/60 p-3.5 transition-all duration-150 hover:border-violet-500/50 hover:bg-zinc-900/90"
              >
                <div>
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-zinc-800/80 text-zinc-300 group-hover:bg-violet-600/20 group-hover:text-violet-300 transition-colors">
                        {isSystem ? (
                          <Server className="h-3.5 w-3.5 text-indigo-400" />
                        ) : (
                          <Bot className="h-3.5 w-3.5 text-sky-400" />
                        )}
                      </div>
                      <span className="truncate text-sm font-semibold text-zinc-200 group-hover:text-violet-200">
                        {displayName}
                      </span>
                    </div>

                    <div className="flex items-center gap-1.5 shrink-0">
                      <span
                        className={`h-2 w-2 rounded-full ${
                          isOnline ? "bg-emerald-500 ring-2 ring-emerald-500/20" : "bg-zinc-600"
                        }`}
                        title={isOnline ? "在线 / 活跃" : "离线 / 闲置"}
                      />
                    </div>
                  </div>

                  {app.description && (
                    <p className="mt-2 line-clamp-1 text-[11px] text-zinc-400">
                      {app.description}
                    </p>
                  )}
                </div>

                <div className="mt-3.5 border-t border-zinc-800/60 pt-2.5">
                  <div className="flex items-center justify-between text-xs text-zinc-400">
                    <span className="flex items-center gap-1.5">
                      <Database className="h-3 w-3 text-zinc-500" />
                      <span className="font-medium text-zinc-300">
                        {app.total_memories_created}
                      </span>
                      <span className="text-[11px] text-zinc-500">条记忆</span>
                    </span>

                    <span className="text-[11px] text-zinc-500">
                      召回: <strong className="text-zinc-300 font-medium">{app.total_memories_accessed}</strong>
                    </span>
                  </div>

                  <div className="mt-2 flex items-center justify-between text-[10px] text-zinc-500">
                    <span className="rounded bg-zinc-800/60 px-1.5 py-0.5 text-zinc-400 border border-zinc-800">
                      {isSystem ? "系统内置" : "Agent 客户端"}
                    </span>
                    <span className="flex items-center gap-1 text-zinc-400 opacity-0 group-hover:opacity-100 transition-opacity">
                      <Settings2 className="h-3 w-3" />
                      <span>管理</span>
                    </span>
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
