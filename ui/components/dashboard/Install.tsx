"use client";

import React, { useEffect, useState } from "react";
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

type LlmFindingCategory = "semantic_duplicates" | "contradictions" | "importance_reassessments" | "split_candidates";

type RawFinding = Record<string, unknown>;

type LlmFindingView = {
  action: string;
  reason: string;
  title?: string;
  llm_thinking?: string;
  llm_raw?: string;
  llm_prompt?: string;
  _category?: LlmFindingCategory;
  _raw?: RawFinding;
};

type LlmResultPayload = {
  summary?: Record<string, number>;
  errors?: string[];
  semantic_duplicates?: RawFinding[];
  contradictions?: RawFinding[];
  importance_reassessments?: RawFinding[];
  split_candidates?: RawFinding[];
};

type ApplyFindingState = {
  state: "idle" | "succeeded" | "failed";
  message?: string;
};

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  return fallback;
}

function getPayloadErrorMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object" && "error" in payload) {
    const error = (payload as { error?: { message?: unknown } | string }).error;
    if (typeof error === "string") return error;
    if (error?.message && typeof error.message === "string") return error.message;
  }
  return fallback;
}

function getString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
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

export const Install = () => {
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

  const [llmRunState, setLlmRunState] = useState<{
    state: "idle" | "running" | "succeeded" | "failed";
    jobId?: string;
    startedAt?: number;
    elapsedMs?: number;
    summary?: Record<string, number>;
    errors?: string[];
    error?: string;
    findings?: LlmFindingView[];
  }>({ state: "idle" });
  const [llmRunning, setLlmRunning] = useState(false);
  const [llmFindingsShowAll, setLlmFindingsShowAll] = useState(false);
  const [llmDismissedIndices, setLlmDismissedIndices] = useState<Set<number>>(new Set());
  const [acceptingAll, setAcceptingAll] = useState(false);
  const [applyFindingStates, setApplyFindingStates] = useState<Record<number, ApplyFindingState>>({});
  const [isRecovering, setIsRecovering] = useState(false);
  const llmPollRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  const LLM_JOB_KEY = "mcore_llm_curator_job";

  const _parseLlmResult = (data: LlmResultPayload) => ({
    summary: data.summary || {},
    errors: data.errors || [],
    findings: [
      ...(data.semantic_duplicates || []).map((d) => ({
        action: "archive duplicate",
        title: getString(d.drop_title),
        reason: getString(d.reason) ?? "",
        llm_thinking: getString(d.llm_thinking),
        llm_raw: getString(d.llm_raw),
        llm_prompt: getString(d.llm_prompt),
        _category: "semantic_duplicates" as const,
        _raw: d,
      })),
      ...(data.contradictions || []).map((c) => ({
        action: "mark contradicted",
        title: getString(c.older_title),
        reason: getString(c.reason) ?? "",
        llm_thinking: getString(c.llm_thinking),
        llm_raw: getString(c.llm_raw),
        llm_prompt: getString(c.llm_prompt),
        _category: "contradictions" as const,
        _raw: c,
      })),
      ...(data.importance_reassessments || [])
        .filter((r) => r.action !== "keep")
        .map((r) => ({
          action: getString(r.action) ?? "reassess",
          title: getString(r.title),
          reason: getString(r.reason) ?? "",
          llm_thinking: getString(r.llm_thinking),
          llm_raw: getString(r.llm_raw),
          llm_prompt: getString(r.llm_prompt),
          _category: "importance_reassessments" as const,
          _raw: r,
        })),
      ...(data.split_candidates || []).map((s) => ({
        action: "split",
        title: getString(s.title),
        reason: getString(s.reason) ?? "",
        llm_thinking: getString(s.llm_thinking),
        llm_raw: getString(s.llm_raw),
        llm_prompt: getString(s.llm_prompt),
        _category: "split_candidates" as const,
        _raw: s,
      })),
    ],
  });

  const _pollJob = React.useCallback(async (jobId: string, startedAt: number) => {
    try {
      const res = await fetch(`${getApiBaseUrl()}/api/curator/llm/${jobId}`);
      setIsRecovering(false);
      // Job not found (service restarted) — treat as stale, stop polling
      if (!res.ok) {
        setLlmRunState({ state: "idle" });
        setLlmRunning(false);
        localStorage.removeItem(LLM_JOB_KEY);
        return;
      }
      const payload = await res.json();
      const pollData = payload.data || payload;
      if (pollData.status === "done") {
        const result = pollData.result || pollData;
        const parsed = _parseLlmResult(result);
        setLlmRunState({
          state: "succeeded",
          jobId,
          startedAt,
          elapsedMs: Date.now() - startedAt,
          ...parsed,
        });
        setLlmRunning(false);
        localStorage.removeItem(LLM_JOB_KEY);
        fetchStatus();
      } else if (pollData.status === "error") {
        setLlmRunState({
          state: "failed",
          jobId,
          startedAt,
          elapsedMs: Date.now() - startedAt,
          error: pollData.error || "LLM Curator job failed",
        });
        setLlmRunning(false);
        localStorage.removeItem(LLM_JOB_KEY);
      } else {
        // still running — schedule next poll
        llmPollRef.current = setTimeout(() => _pollJob(jobId, startedAt), 2000);
      }
    } catch {
      setIsRecovering(false);
      llmPollRef.current = setTimeout(() => _pollJob(jobId, startedAt), 3000);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // On mount: check if a job was running before page reload
  useEffect(() => {
    const saved = localStorage.getItem(LLM_JOB_KEY);
    if (!saved) {
      // Also check the backend for a running job
      fetch(`${getApiBaseUrl()}/api/curator/llm/latest`)
        .then((r) => r.json())
        .then((p) => {
          const d = p.data || p;
          if (d.status === "running" && d.job_id) {
            const startedAt = Date.now();
            setLlmRunning(true);
            setIsRecovering(true);
            setLlmRunState({ state: "running", jobId: d.job_id, startedAt });
            localStorage.setItem(LLM_JOB_KEY, JSON.stringify({ jobId: d.job_id, startedAt }));
            llmPollRef.current = setTimeout(() => _pollJob(d.job_id, startedAt), 2000);
          }
        })
        .catch(() => {});
      return;
    }
    try {
      const { jobId, startedAt } = JSON.parse(saved);
      // If the saved job is older than 2 hours, the server has likely restarted
      // and the job no longer exists — discard it instead of showing stale state
      if (!jobId || Date.now() - startedAt > 2 * 60 * 60 * 1000) {
        localStorage.removeItem(LLM_JOB_KEY);
        return;
      }
      setLlmRunning(true);
      setIsRecovering(true);
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
    setLlmDismissedIndices(new Set());
    setLlmRunState({ state: "running", startedAt });
    try {
      const response = await fetch(`${getApiBaseUrl()}/api/curator/llm`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ dry_run: false }),
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

  const acceptAllFindings = async () => {
    const findings = llmRunState.findings ?? [];
    const visible = findings.filter((_, i) => !llmDismissedIndices.has(i));
    setAcceptingAll(true);
    const results = await Promise.allSettled(
      visible.map(async (f) => {
        if (!f._category || !f._raw) return undefined;
        const globalIdx = findings.indexOf(f);
        const response = await fetch(`${getApiBaseUrl()}/api/curator/llm/apply-single`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ category: f._category, finding: f._raw }),
        });
        const payload: ApiEnvelope<unknown> = await response.json();
        if (!response.ok || payload.ok === false) {
          throw new Error(getPayloadErrorMessage(payload, `${t.dashboard.applyError}: ${response.status}`));
        }
        return globalIdx;
      })
    );
    const accepted = new Set<number>();
    const failedStates: Record<number, ApplyFindingState> = {};
    results.forEach((result, index) => {
      const globalIdx = findings.indexOf(visible[index]);
      if (result.status === "fulfilled" && result.value !== undefined) {
        accepted.add(result.value);
        return;
      }
      failedStates[globalIdx] = {
        state: "failed",
        message: result.status === "rejected" ? getErrorMessage(result.reason, t.dashboard.applyError) : t.dashboard.applyError,
      };
    });
    setApplyFindingStates((prev) => ({ ...prev, ...failedStates }));
    setLlmDismissedIndices((prev) => new Set([...prev, ...accepted]));
    setAcceptingAll(false);
    fetchStatus();
  };

  const dismissAllFindings = () => {
    const findings = llmRunState.findings ?? [];
    setLlmDismissedIndices(new Set(findings.map((_, i) => i)));
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

      {/* Schedule bar + Operations — unified compact strip */}
      <div className="mt-4 rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-3 text-sm space-y-3">
        {/* Row 1: schedule info + buttons */}
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 w-full">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
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
            <span className="text-zinc-500 hidden sm:inline">
              {t.dashboard.scanned} <span className="text-zinc-200">{status?.curator.scanned ?? "-"}</span>
            </span>
          </div>

          <div className="flex items-center gap-2 ml-auto shrink-0">
            <Button
              onClick={applyCurator}
              disabled={applying || llmRunning}
              variant="outline"
              size="sm"
              className="h-8 border-zinc-700/50 bg-zinc-800 text-zinc-300 hover:bg-zinc-700 transition-colors"
            >
              <Play className="h-3 w-3 mr-1" />
              {applying ? t.dashboard.running : t.dashboard.runCurator}
            </Button>
            <Button
              onClick={runLlmCurator}
              disabled={applying || llmRunning}
              variant="outline"
              size="sm"
              className="h-8 border-zinc-700/50 bg-zinc-800 text-zinc-300 hover:bg-zinc-700 transition-colors"
            >
              <Sparkles className="h-3 w-3 mr-1 text-violet-400" />
              {llmRunning ? t.dashboard.analyzing : t.dashboard.runLlm}
            </Button>
          </div>
        </div>

        {/* Manual run result — only when active */}
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
                <span className="text-emerald-300 font-medium shrink-0">{action.action}</span>
                {action.title && <span className="text-zinc-400">· {action.title}</span>}
                {action.reason && <span className="text-zinc-500 ml-auto">{action.reason}</span>}
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

        {/* LLM Curator results */}
        {llmRunState.state !== "idle" && (
          <div className="border-t border-zinc-800 pt-2 text-sm space-y-2">
            {isRecovering && (
              <div className="flex items-center gap-2 text-sky-400 text-xs animate-pulse">
                <span>{t.dashboard.recoveringJob}</span>
              </div>
            )}
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
                </span>
              )}
            </div>
            {llmRunState.errors && llmRunState.errors.length > 0 && (
              <div className="space-y-1">
                {llmRunState.errors.map((e, i) => (
                  <div key={`err-${i}-${e.slice(0,16)}`} className="rounded bg-amber-950/40 border border-amber-800/40 px-2 py-1 text-xs text-amber-300">
                    ⚠ {e}
                  </div>
                ))}
              </div>
            )}
            {llmRunState.findings && llmRunState.findings.length > 0 && (() => {
              const visibleFindings = llmRunState.findings.filter((_, i) => !llmDismissedIndices.has(i));
              const displayFindings = llmFindingsShowAll ? visibleFindings : visibleFindings.slice(0, 20);
              return (
                <div className="space-y-1 max-h-96 overflow-y-auto pr-1">
                  <div className="flex gap-2 pb-1 sticky top-0 bg-zinc-900/95 z-10">
                    <button
                      onClick={acceptAllFindings}
                      disabled={acceptingAll || visibleFindings.length === 0}
                      className="rounded px-2 py-1 text-xs bg-emerald-800/60 text-emerald-300 hover:bg-emerald-700 disabled:opacity-50 transition-colors"
                    >
                      {acceptingAll ? t.dashboard.processing : t.dashboard.acceptAll(visibleFindings.length)}
                    </button>
                    <button
                      onClick={dismissAllFindings}
                      disabled={visibleFindings.length === 0}
                      className="rounded px-2 py-1 text-xs bg-zinc-700 text-zinc-400 hover:bg-red-900/60 hover:text-red-300 disabled:opacity-50 transition-colors"
                    >
                      {t.dashboard.rejectAll(visibleFindings.length)}
                    </button>
                  </div>
                  {displayFindings.map((f, displayIdx) => {
                    const globalIdx = llmRunState.findings!.indexOf(f);
                    return (
                      <LlmFinding
                        key={globalIdx}
                        finding={f}
                        applyState={applyFindingStates[globalIdx]}
                        labels={{ accept: t.dashboard.accept, reject: t.dashboard.reject, thinking: t.dashboard.thinking, raw: t.dashboard.raw, prompt: t.dashboard.prompt, applyError: t.dashboard.applyError, acceptFindingTitle: t.dashboard.acceptFindingTitle, dismissFindingTitle: t.dashboard.dismissFindingTitle }}
                        onAccept={async () => {
                          if (!f._category || !f._raw) return;
                          const response = await fetch(`${getApiBaseUrl()}/api/curator/llm/apply-single`, {
                            method: "POST",
                            headers: { "content-type": "application/json" },
                            body: JSON.stringify({ category: f._category, finding: f._raw }),
                          });
                          const payload: ApiEnvelope<unknown> = await response.json();
                          if (!response.ok || payload.ok === false) {
                            throw new Error(getPayloadErrorMessage(payload, `${t.dashboard.applyError}: ${response.status}`));
                          }
                          setApplyFindingStates((prev) => ({ ...prev, [globalIdx]: { state: "succeeded", message: t.dashboard.applySuccess } }));
                          setLlmDismissedIndices((prev) => new Set([...prev, globalIdx]));
                        }}
                        onDismiss={() => {
                          setLlmDismissedIndices((prev) => new Set([...prev, globalIdx]));
                        }}
                      />
                    );
                  })}
                  {!llmFindingsShowAll && visibleFindings.length > 20 && (
                    <button
                      onClick={() => setLlmFindingsShowAll(true)}
                      className="w-full text-center text-xs text-zinc-400 hover:text-zinc-200 py-1.5 rounded bg-zinc-800/50 hover:bg-zinc-800 transition-colors"
                    >
                      {t.dashboard.showAll(visibleFindings.length)}
                    </button>
                  )}
                </div>
              );
            })()}
            {llmRunState.error && <div className="text-red-300">{llmRunState.error}</div>}
          </div>
        )}
      </div>
    </div>
  );
};

export default Install;

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

function LlmFinding({ finding, applyState, labels, onAccept, onDismiss }: {
  finding: LlmFindingView;
  applyState?: ApplyFindingState;
  labels: { accept: string; reject: string; thinking: string; raw: string; prompt: string; applyError: string; acceptFindingTitle: string; dismissFindingTitle: string };
  onAccept?: () => Promise<void>;
  onDismiss?: () => void;
}) {
  const [expanded, setExpanded] = React.useState<null | "thinking" | "raw" | "prompt">(null);
  const [accepting, setAccepting] = React.useState(false);
  const [localApplyState, setLocalApplyState] = React.useState<ApplyFindingState>({ state: "idle" });
  const hasDetail = finding.llm_thinking || finding.llm_raw || finding.llm_prompt;

  const handleAccept = async () => {
    if (!onAccept) return;
    setAccepting(true);
    try {
      await onAccept();
      setLocalApplyState({ state: "succeeded" });
    } catch (error: unknown) {
      setLocalApplyState({ state: "failed", message: getErrorMessage(error, labels.applyError) });
    } finally {
      setAccepting(false);
    }
  };

  return (
    <div className="rounded bg-zinc-800 px-2 py-2 text-xs">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <span className="text-violet-300 font-medium">{finding.action}</span>
          {finding.title && <span className="text-zinc-400"> · {finding.title}</span>}
          {finding.reason && <div className="text-zinc-500 mt-0.5">{finding.reason}</div>}
        </div>
        <div className="flex gap-1 shrink-0 mt-0.5 items-center">
          {onAccept && (
            <button
              onClick={handleAccept}
              disabled={accepting}
              className="rounded px-1.5 py-0.5 text-[10px] transition-colors bg-emerald-800/60 text-emerald-300 hover:bg-emerald-700 disabled:opacity-50"
              title={labels.acceptFindingTitle}
            >
              {accepting ? "..." : labels.accept}
            </button>
          )}
          {onDismiss && (
            <button
              onClick={onDismiss}
              className="rounded px-1.5 py-0.5 text-[10px] transition-colors bg-zinc-700 text-zinc-400 hover:bg-red-900/60 hover:text-red-300"
              title={labels.dismissFindingTitle}
            >
              {labels.reject}
            </button>
          )}
          {hasDetail && (
            <>
              {finding.llm_thinking && (
                <button
                  onClick={() => setExpanded(expanded === "thinking" ? null : "thinking")}
                  className={`rounded px-1.5 py-0.5 text-[10px] transition-colors ${expanded === "thinking" ? "bg-sky-700 text-sky-100" : "bg-zinc-700 text-zinc-400 hover:text-zinc-200"}`}
                >
                  {labels.thinking}
                </button>
              )}
              {finding.llm_raw && (
                <button
                  onClick={() => setExpanded(expanded === "raw" ? null : "raw")}
                  className={`rounded px-1.5 py-0.5 text-[10px] transition-colors ${expanded === "raw" ? "bg-violet-700 text-violet-100" : "bg-zinc-700 text-zinc-400 hover:text-zinc-200"}`}
                >
                  {labels.raw}
                </button>
              )}
              {finding.llm_prompt && (
                <button
                  onClick={() => setExpanded(expanded === "prompt" ? null : "prompt")}
                  className={`rounded px-1.5 py-0.5 text-[10px] transition-colors ${expanded === "prompt" ? "bg-zinc-500 text-zinc-100" : "bg-zinc-700 text-zinc-400 hover:text-zinc-200"}`}
                >
                  {labels.prompt}
                </button>
              )}
            </>
          )}
        </div>
      </div>
      {(applyState?.state === "failed" || localApplyState.state === "failed") && (
        <div className="mt-2 rounded border border-red-800/50 bg-red-950/40 px-2 py-1 text-[10px] text-red-300">
          {applyState?.message || localApplyState.message || labels.applyError}
        </div>
      )}
      {expanded && (
        <pre className={`mt-2 max-h-64 overflow-auto rounded p-2 text-[10px] leading-relaxed whitespace-pre-wrap break-words ${
          expanded === "thinking" ? "bg-sky-950/50 text-sky-200 border border-sky-800/40" :
          expanded === "raw" ? "bg-violet-950/50 text-violet-200 border border-violet-800/40" :
          "bg-zinc-900 text-zinc-300 border border-zinc-700"
        }`}>
          {expanded === "thinking" ? finding.llm_thinking :
           expanded === "raw" ? finding.llm_raw :
           finding.llm_prompt}
        </pre>
      )}
    </div>
  );
}
