"use client";

import { useEffect, useState } from "react";
import { Archive, DatabaseBackup, History } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useI18n } from "@/hooks/useI18n";
import { getApiBaseUrl } from "@/lib/api-url";

type MaintenanceJob = {
  job_id?: string | null;
  plan_token?: string;
  kind?: string;
  action?: string;
  status?: string;
  created_at?: string;
  finished_at?: string;
  summary?: Record<string, number>;
  backup_path?: string | null;
  error?: string | null;
};

export function MaintenanceHistory() {
  const { messages: t } = useI18n();
  const [job, setJob] = useState<MaintenanceJob | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    fetch(`${getApiBaseUrl()}/api/v1/maintenance/latest`)
      .then((response) => response.json())
      .then((payload) => {
        if (!active) return;
        const data = (payload as { data?: MaintenanceJob }).data ?? (payload as MaintenanceJob);
        setJob(data && data.status !== "none" ? data : null);
      })
      .catch(() => {
        if (active) setJob(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <Card className="border-zinc-800 bg-zinc-900 animate-fade-slide-down">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-medium text-zinc-300">
          <History className="h-4 w-4 text-violet-400" /> {t.settings.recentMaintenance}
        </CardTitle>
        <CardDescription>{t.settings.recentMaintenanceDescription}</CardDescription>
      </CardHeader>
      <CardContent className="text-sm">
        {loading ? (
          <div className="py-3 text-xs text-zinc-500">{t.settings.loading}</div>
        ) : job ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Badge
                variant="outline"
                className={
                  job.status === "succeeded"
                    ? "border-emerald-700 bg-emerald-500/10 text-emerald-300 text-xs"
                    : job.status === "failed"
                      ? "border-red-700 bg-red-500/10 text-red-300 text-xs"
                      : "border-sky-700 bg-sky-500/10 text-sky-300 text-xs"
                }
              >
                {job.status}
              </Badge>
              <span className="text-zinc-300">{job.kind ?? job.action ?? "maintenance"}</span>
              <span className="text-zinc-500 text-xs">
                {job.created_at ? new Date(job.created_at).toLocaleString("zh-CN", { hour12: false }) : ""}
              </span>
            </div>
            {job.summary && Object.keys(job.summary).length > 0 && (
              <div className="text-xs text-zinc-400">
                {Object.entries(job.summary)
                  .filter(([, value]) => Number(value) > 0)
                  .map(([key, value]) => (
                    <span key={key} className="mr-3 inline-flex items-center gap-1">
                      <Archive className="h-3 w-3 text-zinc-500" /> {key}: <b className="text-zinc-200">{String(value)}</b>
                    </span>
                  ))}
              </div>
            )}
            {job.backup_path && (
              <div className="flex items-center gap-1.5 text-xs text-zinc-500">
                <DatabaseBackup className="h-3 w-3 text-emerald-400" />
                <span className="truncate">{job.backup_path}</span>
              </div>
            )}
            {job.error && <div className="text-xs text-red-300">{job.error}</div>}
          </div>
        ) : (
          <div className="py-3 text-xs text-zinc-500">
            {t.settings.noMaintenanceJobs} — {t.settings.noMaintenanceJobsDetail}
          </div>
        )}
      </CardContent>
    </Card>
  );
}