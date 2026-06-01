"use client";

import React, { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Activity, Archive, Database, Play, RefreshCw, Sparkles } from "lucide-react";
import { getApiBaseUrl } from "@/lib/api-url";

type CuratorStatus = {
  stats: {
    total: number;
    by_status: Record<string, number>;
    by_type: Record<string, number>;
    never_accessed_count: number;
    link_count: number;
  };
  curator: {
    generated_at?: string;
    scanned: number;
    summary: Record<string, number>;
    planned_actions: Array<{ id: string; title?: string; action: string; reason?: string }>;
  };
  timer: Record<string, string>;
  service: Record<string, string>;
};

type CuratorRunState = {
  state: "idle" | "running" | "succeeded" | "failed";
  startedAt?: string;
  finishedAt?: string;
  elapsedMs?: number;
  summary?: Record<string, number>;
  actions?: Array<{ id: string; title?: string; action: string; reason?: string }>;
  error?: string;
};

function formatTime(value?: string) {
  if (!value || value === "n/a") return "n/a";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export const Install = () => {
  const [status, setStatus] = useState<CuratorStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [runState, setRunState] = useState<CuratorRunState>({ state: "idle" });

  const fetchStatus = async () => {
    setLoading(true);
    const response = await fetch(`${getApiBaseUrl()}/api/curator/status?limit=200`);
    const payload = await response.json();
    setStatus(payload.data);
    setLoading(false);
  };

  const applyCurator = async () => {
    const started = new Date();
    setApplying(true);
    setRunState({ state: "running", startedAt: started.toISOString() });
    try {
      const response = await fetch(`${getApiBaseUrl()}/api/curator/apply`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ limit: 500 }),
      });
      const payload = await response.json();
      if (!response.ok || payload.ok === false) {
        throw new Error(payload?.error?.message || `Curator failed with ${response.status}`);
      }
      const finished = new Date();
      setRunState({
        state: "succeeded",
        startedAt: started.toISOString(),
        finishedAt: finished.toISOString(),
        elapsedMs: finished.getTime() - started.getTime(),
        summary: payload.data?.summary || {},
        actions: payload.data?.actions || [],
      });
      await fetchStatus();
    } catch (error: any) {
      const finished = new Date();
      setRunState({
        state: "failed",
        startedAt: started.toISOString(),
        finishedAt: finished.toISOString(),
        elapsedMs: finished.getTime() - started.getTime(),
        error: error?.message || "Curator failed",
      });
    } finally {
      setApplying(false);
    }
  };

  useEffect(() => {
    fetchStatus().catch(() => setLoading(false));
  }, []);

  const summary = status?.curator.summary || {};
  const byStatus = status?.stats.by_status || {};
  const nextRun = status?.timer.NextElapseUSecRealtime;
  const lastRun = status?.service.ExecMainExitTimestamp || status?.timer.LastTriggerUSec;
  const lastResult = status?.service.Result || "unknown";

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold">Memory Operations</h2>
        <Button
          variant="outline"
          className="border-zinc-700 bg-zinc-900 hover:bg-zinc-800"
          onClick={() => fetchStatus()}
          disabled={loading}
        >
          <RefreshCw className="h-4 w-4 mr-2" />
          Refresh
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card className="bg-zinc-900 border-zinc-800">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-zinc-400 flex items-center justify-between">
              Total Memories <Database className="h-4 w-4 text-zinc-500" />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold text-white">{status?.stats.total ?? "-"}</div>
          </CardContent>
        </Card>
        <Card className="bg-zinc-900 border-zinc-800">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-zinc-400 flex items-center justify-between">
              Active <Activity className="h-4 w-4 text-zinc-500" />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold text-white">{byStatus.active ?? 0}</div>
          </CardContent>
        </Card>
        <Card className="bg-zinc-900 border-zinc-800">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-zinc-400 flex items-center justify-between">
              Candidates <Sparkles className="h-4 w-4 text-zinc-500" />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold text-white">{byStatus.candidate ?? 0}</div>
          </CardContent>
        </Card>
        <Card className="bg-zinc-900 border-zinc-800">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-zinc-400 flex items-center justify-between">
              Archived <Archive className="h-4 w-4 text-zinc-500" />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold text-white">{byStatus.archived ?? 0}</div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4">
        <Card className="bg-zinc-900 border-zinc-800">
          <CardHeader className="py-4 border-b border-zinc-800">
            <CardTitle className="text-white text-base">Curator Schedule</CardTitle>
          </CardHeader>
          <CardContent className="py-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-zinc-400">Timer</span>
              <Badge variant="outline" className="border-emerald-700 bg-emerald-500/10 text-emerald-300">
                {status?.timer.ActiveState || "unknown"}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-zinc-400">Last run</span>
              <span className="text-zinc-100">{formatTime(lastRun)}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-zinc-400">Next run</span>
              <span className="text-zinc-100">{formatTime(nextRun)}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-zinc-400">Last result</span>
              <span className="text-zinc-100">{lastResult}</span>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-zinc-900 border-zinc-800">
          <CardHeader className="py-4 border-b border-zinc-800">
            <CardTitle className="text-white text-base">Curator Dry Run</CardTitle>
          </CardHeader>
          <CardContent className="py-4 space-y-3">
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-md bg-zinc-800 px-3 py-2">
                <div className="text-zinc-500">Scanned</div>
                <div className="text-lg font-semibold">{status?.curator.scanned ?? "-"}</div>
              </div>
              <div className="rounded-md bg-zinc-800 px-3 py-2">
                <div className="text-zinc-500">Planned Actions</div>
                <div className="text-lg font-semibold">{summary.planned_actions ?? 0}</div>
              </div>
              <div className="rounded-md bg-zinc-800 px-3 py-2">
                <div className="text-zinc-500">Skill Promotions</div>
                <div className="text-lg font-semibold">{summary.skill_promotions ?? 0}</div>
              </div>
              <div className="rounded-md bg-zinc-800 px-3 py-2">
                <div className="text-zinc-500">Duplicates</div>
                <div className="text-lg font-semibold">{summary.duplicates ?? 0}</div>
              </div>
            </div>
            <Button
              className="w-full bg-primary hover:bg-primary/90"
              onClick={applyCurator}
              disabled={applying}
            >
              <Play className="h-4 w-4 mr-2" />
              {applying ? "Running curator..." : "Run Curator Now"}
            </Button>
            <div className="rounded-md border border-zinc-800 bg-zinc-950 px-3 py-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-zinc-400">Manual run</span>
                <Badge
                  variant="outline"
                  className={
                    runState.state === "succeeded"
                      ? "border-emerald-700 bg-emerald-500/10 text-emerald-300"
                      : runState.state === "failed"
                        ? "border-red-700 bg-red-500/10 text-red-300"
                        : runState.state === "running"
                          ? "border-sky-700 bg-sky-500/10 text-sky-300"
                          : "border-zinc-700 bg-zinc-800 text-zinc-300"
                  }
                >
                  {runState.state}
                </Badge>
              </div>
              {runState.startedAt && (
                <div className="mt-2 grid grid-cols-2 gap-2 text-zinc-400">
                  <div>
                    <div className="text-zinc-500">Started</div>
                    <div className="text-zinc-200">{formatTime(runState.startedAt)}</div>
                  </div>
                  <div>
                    <div className="text-zinc-500">Elapsed</div>
                    <div className="text-zinc-200">
                      {runState.elapsedMs !== undefined ? `${(runState.elapsedMs / 1000).toFixed(1)}s` : "running"}
                    </div>
                  </div>
                </div>
              )}
              {runState.summary && (
                <div className="mt-3 grid grid-cols-3 gap-2">
                  <div className="rounded bg-zinc-800 px-2 py-1">
                    <div className="text-zinc-500">Actions</div>
                    <div className="text-zinc-100 font-medium">{runState.summary.actions ?? 0}</div>
                  </div>
                  <div className="rounded bg-zinc-800 px-2 py-1">
                    <div className="text-zinc-500">Promote</div>
                    <div className="text-zinc-100 font-medium">{runState.summary.skill_promotions ?? 0}</div>
                  </div>
                  <div className="rounded bg-zinc-800 px-2 py-1">
                    <div className="text-zinc-500">Archive</div>
                    <div className="text-zinc-100 font-medium">{runState.summary.archive ?? 0}</div>
                  </div>
                </div>
              )}
              {runState.actions && runState.actions.length > 0 && (
                <div className="mt-3 space-y-2">
                  {runState.actions.slice(0, 3).map((action) => (
                    <div key={`${action.id}-${action.action}`} className="rounded bg-zinc-800 px-2 py-1">
                      <span className="text-primary">{action.action}</span>
                      <span className="text-zinc-400"> · {action.title || action.id}</span>
                    </div>
                  ))}
                </div>
              )}
              {runState.error && <div className="mt-2 text-red-300">{runState.error}</div>}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default Install;
