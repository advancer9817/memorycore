"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Activity, Archive, Brain, Database, Play, Sparkles } from "lucide-react";
import { useI18n } from "@/hooks/useI18n";
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
  llm_curator?: {
    last_run_at?: string;
    last_result?: string;
    summary?: Record<string, number>;
    errors?: string[];
    latest_job?: {
      status?: string;
      job_id?: string | null;
    };
  };
  timer: Record<string, string>;
  service: Record<string, string>;
  schedules?: {
    rule_curator?: Record<string, string>;
    llm_curator?: Record<string, string>;
  };
};

type ApiEnvelope<T> = {
  ok?: boolean;
  data?: T;
  error?: { message?: string } | string;
};

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  return fallback;
}

function ellipsize(value: string | undefined, maxChars: number): string | undefined {
  if (!value) return value;
  const chars = Array.from(value);
  if (chars.length <= maxChars) return value;
  return `${chars.slice(0, Math.max(0, maxChars - 3)).join("")}...`;
}

type CuratorRunState = {
  state: "idle" | "running" | "succeeded" | "failed";
  startedAt?: string;
  finishedAt?: string;
  elapsedMs?: number;
  summary?: Record<string, number>;
  actions?: Array<{ id: string; title?: string; action: string; reason?: string }>;
  error?: string;
};

type LlmRunState = {
  state: "idle" | "running" | "succeeded" | "failed";
  jobId?: string;
  startedAt?: number;
  elapsedMs?: number;
  summary?: Record<string, number>;
  progress?: { stage?: string; batch_index?: number };
  errors?: string[];
  error?: string;
};

function formatTime(value?: string, locale: "en" | "zh" = "en") {
  if (!value || value === "n/a") return "n/a";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(locale === "zh" ? "zh-CN" : "en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export const MemoryOperationsPanel = () => {
  const { messages: t, locale } = useI18n();
  const [status, setStatus] = useState<CuratorStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [runState, setRunState] = useState<CuratorRunState>({ state: "idle" });
  const [runActionsShowAll, setRunActionsShowAll] = useState(false);

  const fetchStatus = async () => {
    setLoading(true);
    try {
      const response = await fetch(`${getApiBaseUrl()}/api/curator/status`);
      if (!response.ok) {
        throw new Error(`Curator status request failed with ${response.status}`);
      }
      const payload = await response.json();
      setStatus(payload.data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
  }, []);

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
    } catch (error: unknown) {
      const finished = new Date();
      setRunState({
        state: "failed",
        startedAt: started.toISOString(),
        finishedAt: finished.toISOString(),
        elapsedMs: finished.getTime() - started.getTime(),
        error: getErrorMessage(error, "Curator failed"),
      });
    } finally {
      setApplying(false);
    }
  };

  const [llmRunState, setLlmRunState] = useState<LlmRunState>({ state: "idle" });
  const [llmRunning, setLlmRunning] = useState(false);
  const llmPollRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  const LLM_JOB_KEY = "mcore_llm_curator_job";

  const _pollJob = React.useCallback(async (jobId: string, startedAt: number) => {
    try {
      const res = await fetch(`${getApiBaseUrl()}/api/curator/llm/${jobId}`);
      if (!res.ok) {
        setLlmRunState({ state: "idle" });
        setLlmRunning(false);
        localStorage.removeItem(LLM_JOB_KEY);
        return;
      }
      const payload = await res.json();
      const pollData = payload.data || payload;
      if (pollData.status === "done" || pollData.status === "succeeded") {
        setLlmRunState({
          state: "succeeded",
          jobId,
          startedAt,
          elapsedMs: Date.now() - startedAt,
          summary: pollData.summary || pollData.result?.summary || {},
          errors: pollData.errors || pollData.result?.errors || [],
          progress: pollData.progress,
        });
        setLlmRunning(false);
        localStorage.removeItem(LLM_JOB_KEY);
        fetchStatus();
      } else if (pollData.status === "error" || pollData.status === "failed") {
        setLlmRunState({
          state: "failed",
          jobId,
          startedAt,
          elapsedMs: Date.now() - startedAt,
          summary: pollData.summary,
          progress: pollData.progress,
          errors: pollData.errors,
          error: pollData.error || (Array.isArray(pollData.errors) ? pollData.errors.join("; ") : "LLM Curator job failed"),
        });
        setLlmRunning(false);
        localStorage.removeItem(LLM_JOB_KEY);
      } else {
        setLlmRunState((prev) => ({
          ...prev,
          state: "running",
          jobId,
          startedAt,
          summary: pollData.summary || prev.summary,
          progress: pollData.progress || prev.progress,
          errors: pollData.errors || prev.errors,
        }));
        llmPollRef.current = setTimeout(() => _pollJob(jobId, startedAt), 3000);
      }
    } catch {
      llmPollRef.current = setTimeout(() => _pollJob(jobId, startedAt), 3000);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const saved = localStorage.getItem(LLM_JOB_KEY);
    if (!saved) {
      fetch(`${getApiBaseUrl()}/api/curator/llm/latest`)
        .then((r) => r.json())
        .then((p) => {
          const d = p.data || p;
          if (d.status === "running" && d.job_id) {
            const startedAt = Date.now();
            setLlmRunning(true);
            setLlmRunState({ state: "running", jobId: d.job_id, startedAt, summary: d.summary || {}, progress: d.progress || {} });
            localStorage.setItem(LLM_JOB_KEY, JSON.stringify({ jobId: d.job_id, startedAt }));
            llmPollRef.current = setTimeout(() => _pollJob(d.job_id, startedAt), 2000);
          }
        })
        .catch(() => {});
      return;
    }
    try {
      const { jobId, startedAt } = JSON.parse(saved);
      if (!jobId || Date.now() - startedAt > 2 * 60 * 60 * 1000) {
        localStorage.removeItem(LLM_JOB_KEY);
        return;
      }
      setLlmRunning(true);
      setLlmRunState({ state: "running", jobId, startedAt });
      llmPollRef.current = setTimeout(() => _pollJob(jobId, startedAt), 500);
    } catch {
      localStorage.removeItem(LLM_JOB_KEY);
    }
    return () => {
      if (llmPollRef.current) clearTimeout(llmPollRef.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runLlmCurator = async () => {
    if (llmRunning) return;
    const startedAt = Date.now();
    setLlmRunning(true);
    setLlmRunState({ state: "running", startedAt });
    try {
      const response = await fetch(`${getApiBaseUrl()}/api/curator/llm`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ dry_run: true }),
      });
      const payload = await response.json();
      if (!response.ok || payload.ok === false) {
        throw new Error(payload?.error?.message || `LLM Curator failed with ${response.status}`);
      }
      const initData = payload.data || payload;
      const jobId = initData?.job_id;
      if (!jobId) throw new Error("No job_id returned from server");
      localStorage.setItem(LLM_JOB_KEY, JSON.stringify({ jobId, startedAt }));
      setLlmRunState({ state: "running", jobId, startedAt });
      llmPollRef.current = setTimeout(() => _pollJob(jobId, startedAt), 2000);
    } catch (error: unknown) {
      setLlmRunState({
        state: "failed",
        startedAt,
        elapsedMs: Date.now() - startedAt,
        error: getErrorMessage(error, "LLM Curator failed"),
      });
      setLlmRunning(false);
      localStorage.removeItem(LLM_JOB_KEY);
    }
  };

  const summary = status?.curator.summary || {};
  const byStatus = status?.stats.by_status || {};
  const nextRun = status?.timer.NextElapseUSecRealtime;
  const lastRun = status?.schedules?.rule_curator?.last_run_at || status?.service.ExecMainExitTimestamp || status?.timer.LastTriggerUSec;
  const llmLastRun = status?.llm_curator?.last_run_at || status?.schedules?.llm_curator?.last_run_at;
  const lastResult = status?.service.Result || "unknown";
  const llmLastResult = status?.llm_curator?.last_result || "unknown";

  return (
    <div id="memory-operations">
      <div className="mb-6">
        <h2 className="text-base font-medium text-zinc-400">{t.dashboard.operations}</h2>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card className="bg-zinc-900 border-zinc-800">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-zinc-400 flex items-center justify-between">
              {t.dashboard.totalMemories} <Database className="h-4 w-4 text-zinc-500" />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold text-white">{status?.stats.total ?? "-"}</div>
          </CardContent>
        </Card>
        <Card className="bg-zinc-900 border-zinc-800">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-zinc-400 flex items-center justify-between">
              {t.dashboard.active} <Activity className="h-4 w-4 text-zinc-500" />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold text-white">{byStatus.active ?? 0}</div>
          </CardContent>
        </Card>
        <Card className="bg-zinc-900 border-zinc-800">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-zinc-400 flex items-center justify-between">
              {t.dashboard.candidates} <Sparkles className="h-4 w-4 text-zinc-500" />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold text-white">{byStatus.candidate ?? 0}</div>
          </CardContent>
        </Card>
        <Card className="bg-zinc-900 border-zinc-800">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-zinc-400 flex items-center justify-between">
              {t.dashboard.archived} <Archive className="h-4 w-4 text-zinc-500" />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold text-white">{byStatus.archived ?? 0}</div>
          </CardContent>
        </Card>
      </div>

      {/* Schedule bar + Operations */}
      <div className="mt-4 rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-3 text-sm space-y-2">
        <div className="flex items-center gap-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 min-w-0 flex-1 text-xs">
            <Badge variant="outline" className="border-emerald-700 bg-emerald-500/10 text-emerald-300 text-xs shrink-0">
              {t.dashboard.scheduled} · {status?.timer.ActiveState || t.dashboard.unknown}
            </Badge>
            <span className="text-zinc-500">
              {t.dashboard.ruleLast} <span className="text-zinc-200">{formatTime(lastRun, locale)}</span>
            </span>
            <span className="text-zinc-500">
              {t.dashboard.llmLast} <span className="text-zinc-200">{formatTime(llmLastRun, locale)}</span>
            </span>
            <span className="text-zinc-500">
              {t.dashboard.next} <span className="text-zinc-200">{formatTime(nextRun, locale)}</span>
            </span>
            <span className="text-zinc-500">
              {t.dashboard.result} <span className="text-zinc-200">{lastResult}</span>
              <span className="text-zinc-600"> / </span>
              <span className="text-violet-300">LLM {llmLastResult}</span>
            </span>
            <span className="text-zinc-500 hidden lg:inline">
              {t.dashboard.scanned} <span className="text-zinc-200">{status?.curator.scanned ?? "-"}</span>
            </span>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Button
              onClick={applyCurator}
              disabled={applying || llmRunning}
              variant="outline"
              size="sm"
              className="h-7 text-xs border-zinc-700/50 bg-zinc-800 text-zinc-300 hover:bg-zinc-700 transition-colors"
            >
              <Play className="h-3 w-3 mr-1" />
              {applying ? t.dashboard.running : t.dashboard.runCurator}
            </Button>
            <Button
              onClick={runLlmCurator}
              disabled={applying || llmRunning}
              variant="outline"
              size="sm"
              className="h-7 text-xs border-zinc-700/50 bg-zinc-800 text-zinc-300 hover:bg-zinc-700 transition-colors"
            >
              <Sparkles className="h-3 w-3 mr-1 text-violet-400" />
              {llmRunning ? t.dashboard.analyzing : t.dashboard.runLlm}
            </Button>
          </div>
        </div>

        {/* Manual run result */}
        {runState.state !== "idle" && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-zinc-800 pt-2">
            <span className="text-zinc-500">{t.dashboard.manualRun}</span>
            <Badge
              variant="outline"
              className={
                runState.state === "succeeded"
                  ? "border-emerald-700 bg-emerald-500/10 text-emerald-300 text-xs"
                  : runState.state === "failed"
                    ? "border-red-700 bg-red-500/10 text-red-300 text-xs"
                    : "border-sky-700 bg-sky-500/10 text-sky-300 text-xs"
              }
            >
              {runState.state}
            </Badge>
            {runState.startedAt && (
              <span className="text-zinc-500">
                {formatTime(runState.startedAt, locale)}
                {runState.elapsedMs !== undefined && (
                  <span className="ml-2 text-zinc-400">{(runState.elapsedMs / 1000).toFixed(1)}s</span>
                )}
              </span>
            )}
            {runState.summary && (
              <span className="text-zinc-500 ml-2">
                {t.dashboard.actions} <span className="text-zinc-200">{runState.summary.actions ?? 0}</span>
                {" · "}{t.dashboard.promote} <span className="text-zinc-200">{runState.summary.skill_promotions ?? 0}</span>
                {" · "}{t.dashboard.archive} <span className="text-zinc-200">{runState.summary.archive ?? 0}</span>
              </span>
            )}
            {runState.error && <span className="text-red-300 ml-2">{runState.error}</span>}
          </div>
        )}
        {runState.actions && runState.actions.length > 0 && (
          <div className="flex flex-col gap-1 border-t border-zinc-800 pt-2">
            {(runActionsShowAll ? runState.actions : runState.actions.slice(0, 3)).map((action, i) => (
              <div key={action.id ?? i} className="rounded bg-zinc-800 px-2 py-1.5 text-xs flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <div className="truncate whitespace-nowrap" title={[action.action, action.title].filter(Boolean).join(" · ")}>
                    <span className="text-emerald-300 font-medium shrink-0">
                      {ellipsize(action.action, 54)}
                    </span>
                    {action.title && <span className="text-zinc-400"> · {ellipsize(action.title, 72)}</span>}
                  </div>
                  {action.reason && (
                    <div className="truncate whitespace-nowrap text-zinc-500 mt-0.5" title={action.reason}>
                      {ellipsize(action.reason, 120)}
                    </div>
                  )}
                </div>
                {action.id && (
                  <Link href={`/memory/${action.id}`} className="rounded px-1.5 py-0.5 text-[10px] transition-colors bg-zinc-700/50 text-zinc-400 hover:text-zinc-200 shrink-0">
                    {t.common?.details ?? "详情"}
                  </Link>
                )}
              </div>
            ))}
            {!runActionsShowAll && runState.actions.length > 3 && (
              <button
                onClick={() => setRunActionsShowAll(true)}
                className="w-full text-center text-xs text-zinc-400 hover:text-zinc-200 py-1.5 rounded bg-zinc-800/50 hover:bg-zinc-800 transition-colors"
              >
                {t.dashboard.showAll(runState.actions.length)}
              </button>
            )}
          </div>
        )}

        {/* LLM Curator summary */}
        {llmRunState.state !== "idle" && (
          <div className="border-t border-zinc-800 pt-2 text-sm space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-zinc-500">{t.dashboard.llmAnalysis}</span>
              <Badge
                variant="outline"
                className={
                  llmRunState.state === "succeeded"
                    ? "border-violet-600 bg-violet-500/10 text-violet-300 text-xs"
                    : llmRunState.state === "failed"
                      ? "border-red-700 bg-red-500/10 text-red-300 text-xs"
                      : "border-sky-700 bg-sky-500/10 text-sky-300 text-xs"
                }
              >
                {llmRunState.state}
              </Badge>
              {llmRunState.state === "running" && llmRunState.startedAt
                ? <LlmElapsedTimer startedAt={llmRunState.startedAt} />
                : llmRunState.elapsedMs !== undefined && (
                  <span className="text-zinc-500 text-xs">{(llmRunState.elapsedMs / 1000).toFixed(1)}s</span>
                )}
              {llmRunState.summary && (
                <span className="text-zinc-500 text-xs ml-1">
                  {t.dashboard.duplicates} <span className="text-zinc-200">{llmRunState.summary.semantic_duplicates ?? 0}</span>
                  {" · "}{t.dashboard.contradictions} <span className="text-zinc-200">{llmRunState.summary.contradictions ?? 0}</span>
                  {" · "}{t.dashboard.reassessments} <span className="text-zinc-200">{llmRunState.summary.importance_reassessments ?? 0}</span>
                  {" · "}{t.dashboard.splits} <span className="text-zinc-200">{llmRunState.summary.split_candidates ?? 0}</span>
                  {llmRunState.progress?.stage && (
                    <span className="text-zinc-500 text-xs ml-1">
                      stage <span className="text-zinc-200">{llmRunState.progress.stage}</span>
                      {llmRunState.progress.batch_index !== undefined && <span> · batch <span className="text-zinc-200">{llmRunState.progress.batch_index}</span></span>}
                    </span>
                  )}
                </span>
              )}
            </div>
            {llmRunState.errors && llmRunState.errors.length > 0 && (
              <div className="space-y-1">
                {llmRunState.errors.map((e, i) => (
                  <div key={`err-${i}-${e.slice(0,16)}`} className="rounded bg-amber-950/40 border border-amber-800/40 px-2 py-1 text-xs text-amber-300">
                    {e}
                  </div>
                ))}
              </div>
            )}
            {llmRunState.error && <div className="text-red-300">{llmRunState.error}</div>}
          </div>
        )}
      </div>
    </div>
  );
};

export default MemoryOperationsPanel;

function LlmElapsedTimer({ startedAt }: { startedAt: number }) {
  const { messages } = useI18n();
  const [elapsed, setElapsed] = React.useState(Date.now() - startedAt);
  useEffect(() => {
    const id = setInterval(() => setElapsed(Date.now() - startedAt), 100);
    return () => clearInterval(id);
  }, [startedAt]);
  return (
    <div className="mt-1 text-sky-400 text-xs animate-pulse">
      {messages.dashboard.llmElapsed((elapsed / 1000).toFixed(1))}
    </div>
  );
}
