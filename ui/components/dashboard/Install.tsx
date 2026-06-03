"use client";

import React, { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Activity, Archive, Brain, Database, Play, Sparkles } from "lucide-react";
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

  const [llmRunState, setLlmRunState] = useState<{
    state: "idle" | "running" | "succeeded" | "failed";
    jobId?: string;
    startedAt?: number;
    elapsedMs?: number;
    summary?: Record<string, number>;
    errors?: string[];
    error?: string;
    findings?: Array<{
      action: string;
      reason: string;
      title?: string;
      llm_thinking?: string;
      llm_raw?: string;
      llm_prompt?: string;
    }>;
  }>({ state: "idle" });
  const [llmRunning, setLlmRunning] = useState(false);
  const llmPollRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  const LLM_JOB_KEY = "mcore_llm_curator_job";

  const _parseLlmResult = (data: any) => ({
    summary: data.summary || {},
    errors: data.errors || [],
    findings: [
      ...(data.semantic_duplicates || []).map((d: any) => ({
        action: "archive duplicate",
        title: d.drop_title,
        reason: d.reason,
        llm_thinking: d.llm_thinking,
        llm_raw: d.llm_raw,
        llm_prompt: d.llm_prompt,
      })),
      ...(data.contradictions || []).map((c: any) => ({
        action: "mark contradicted",
        title: c.older_title,
        reason: c.reason,
        llm_thinking: c.llm_thinking,
        llm_raw: c.llm_raw,
        llm_prompt: c.llm_prompt,
      })),
      ...(data.importance_reassessments || [])
        .filter((r: any) => r.action !== "keep")
        .map((r: any) => ({
          action: r.action,
          title: r.title,
          reason: r.reason,
          llm_thinking: r.llm_thinking,
          llm_raw: r.llm_raw,
          llm_prompt: r.llm_prompt,
        })),
      ...(data.split_candidates || []).map((s: any) => ({
        action: "split",
        title: s.title,
        reason: s.reason,
        llm_thinking: s.llm_thinking,
        llm_raw: s.llm_raw,
        llm_prompt: s.llm_prompt,
      })),
    ],
  });

  const _pollJob = React.useCallback(async (jobId: string, startedAt: number) => {
    try {
      const res = await fetch(`${getApiBaseUrl()}/api/curator/llm/${jobId}`);
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
        body: JSON.stringify({ dry_run: false, limit: 200 }),
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
    } catch (error: any) {
      setLlmRunState({
        state: "failed",
        startedAt,
        elapsedMs: Date.now() - startedAt,
        error: error?.message || "LLM Curator failed",
      });
      setLlmRunning(false);
      localStorage.removeItem(LLM_JOB_KEY);
    }
  };

  const summary = status?.curator.summary || {};
  const byStatus = status?.stats.by_status || {};
  const nextRun = status?.timer.NextElapseUSecRealtime;
  const lastRun = status?.service.ExecMainExitTimestamp || status?.timer.LastTriggerUSec;
  const lastResult = status?.service.Result || "unknown";

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-base font-medium text-zinc-400">Memory Operations</h2>
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

      {/* Schedule bar — compact horizontal strip */}
      <div className="mt-4 rounded-lg border border-zinc-800 bg-zinc-900 px-5 py-3 flex flex-wrap items-center gap-x-8 gap-y-2 text-sm">
        <span className="text-zinc-400 font-medium shrink-0">Curator Schedule</span>
        <div className="flex items-center gap-2">
          <span className="text-zinc-500">Timer</span>
          <Badge variant="outline" className="border-emerald-700 bg-emerald-500/10 text-emerald-300 text-xs">
            {status?.timer.ActiveState || "unknown"}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-zinc-500">Last run</span>
          <span className="text-zinc-200">{formatTime(lastRun)}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-zinc-500">Next run</span>
          <span className="text-zinc-200">{formatTime(nextRun)}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-zinc-500">Result</span>
          <span className="text-zinc-200">{lastResult}</span>
        </div>
      </div>

      {/* Operations — full width */}
      <Card className="bg-zinc-900 border-zinc-800 mt-4">
        <CardHeader className="py-4 border-b border-zinc-800">
          <CardTitle className="text-white text-base">Curator Operations</CardTitle>
        </CardHeader>
        <CardContent className="py-4 space-y-3">
          {/* Stats row */}
          <div className="grid grid-cols-4 gap-3 text-sm">
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

          {/* Action buttons */}
          <div className="flex gap-3">
            <Button
              className="flex-1 bg-primary hover:bg-primary/90"
              onClick={applyCurator}
              disabled={applying || llmRunning}
            >
              <Play className="h-4 w-4 mr-2" />
              {applying ? "Running curator..." : "Run Curator Now"}
            </Button>
            <Button
              className="flex-1 bg-violet-700 hover:bg-violet-600 text-white"
              onClick={runLlmCurator}
              disabled={applying || llmRunning}
            >
              <Brain className="h-4 w-4 mr-2" />
              {llmRunning ? "LLM 分析中..." : "Run LLM Curator"}
            </Button>
          </div>

          {/* Manual run result */}
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

          {/* LLM Curator results */}
          {llmRunState.state !== "idle" && (
            <div className="rounded-md border border-violet-800 bg-zinc-950 px-3 py-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-zinc-400">LLM analysis</span>
                <Badge
                  variant="outline"
                  className={
                    llmRunState.state === "succeeded"
                      ? "border-violet-600 bg-violet-500/10 text-violet-300"
                      : llmRunState.state === "failed"
                        ? "border-red-700 bg-red-500/10 text-red-300"
                        : "border-sky-700 bg-sky-500/10 text-sky-300"
                  }
                >
                  {llmRunState.state}
                </Badge>
              </div>
              {llmRunState.state === "running" && llmRunState.startedAt
                ? <LlmElapsedTimer startedAt={llmRunState.startedAt} />
                : llmRunState.elapsedMs !== undefined && (
                <div className="mt-1 text-zinc-500 text-xs">
                  {(llmRunState.elapsedMs / 1000).toFixed(1)}s
                </div>
              )}
              {llmRunState.summary && (
                <div className="mt-2 grid grid-cols-4 gap-2">
                  <div className="rounded bg-zinc-800 px-2 py-1">
                    <div className="text-zinc-500 text-xs">重复</div>
                    <div className="text-zinc-100 font-medium">{llmRunState.summary.semantic_duplicates ?? 0}</div>
                  </div>
                  <div className="rounded bg-zinc-800 px-2 py-1">
                    <div className="text-zinc-500 text-xs">矛盾</div>
                    <div className="text-zinc-100 font-medium">{llmRunState.summary.contradictions ?? 0}</div>
                  </div>
                  <div className="rounded bg-zinc-800 px-2 py-1">
                    <div className="text-zinc-500 text-xs">重评</div>
                    <div className="text-zinc-100 font-medium">{llmRunState.summary.importance_reassessments ?? 0}</div>
                  </div>
                  <div className="rounded bg-zinc-800 px-2 py-1">
                    <div className="text-zinc-500 text-xs">拆分</div>
                    <div className="text-zinc-100 font-medium">{llmRunState.summary.split_candidates ?? 0}</div>
                  </div>
                </div>
              )}
              {llmRunState.errors && llmRunState.errors.length > 0 && (
                <div className="mt-2 space-y-1">
                  {llmRunState.errors.map((e, i) => (
                    <div key={i} className="rounded bg-amber-950/40 border border-amber-800/40 px-2 py-1 text-xs text-amber-300">
                      ⚠ {e}
                    </div>
                  ))}
                </div>
              )}
              {llmRunState.findings && llmRunState.findings.length > 0 && (
                <div className="mt-3 space-y-1 max-h-96 overflow-y-auto pr-1">
                  {llmRunState.findings.map((f, i) => (
                    <LlmFinding key={i} finding={f} />
                  ))}
                </div>
              )}
              {llmRunState.error && <div className="mt-2 text-red-300">{llmRunState.error}</div>}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default Install;

function LlmElapsedTimer({ startedAt }: { startedAt: number }) {
  const [elapsed, setElapsed] = React.useState(Date.now() - startedAt);
  useEffect(() => {
    const id = setInterval(() => setElapsed(Date.now() - startedAt), 100);
    return () => clearInterval(id);
  }, [startedAt]);
  return (
    <div className="mt-1 text-sky-400 text-xs animate-pulse">
      运行中 {(elapsed / 1000).toFixed(1)}s…
    </div>
  );
}

function LlmFinding({ finding }: {
  finding: {
    action: string;
    reason: string;
    title?: string;
    llm_thinking?: string;
    llm_raw?: string;
    llm_prompt?: string;
  }
}) {
  const [expanded, setExpanded] = React.useState<null | "thinking" | "raw" | "prompt">(null);
  const hasDetail = finding.llm_thinking || finding.llm_raw || finding.llm_prompt;

  return (
    <div className="rounded bg-zinc-800 px-2 py-2 text-xs">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <span className="text-violet-300 font-medium">{finding.action}</span>
          {finding.title && <span className="text-zinc-400"> · {finding.title}</span>}
          {finding.reason && <div className="text-zinc-500 mt-0.5">{finding.reason}</div>}
        </div>
        {hasDetail && (
          <div className="flex gap-1 shrink-0 mt-0.5">
            {finding.llm_thinking && (
              <button
                onClick={() => setExpanded(expanded === "thinking" ? null : "thinking")}
                className={`rounded px-1.5 py-0.5 text-[10px] transition-colors ${expanded === "thinking" ? "bg-sky-700 text-sky-100" : "bg-zinc-700 text-zinc-400 hover:text-zinc-200"}`}
              >
                思考
              </button>
            )}
            {finding.llm_raw && (
              <button
                onClick={() => setExpanded(expanded === "raw" ? null : "raw")}
                className={`rounded px-1.5 py-0.5 text-[10px] transition-colors ${expanded === "raw" ? "bg-violet-700 text-violet-100" : "bg-zinc-700 text-zinc-400 hover:text-zinc-200"}`}
              >
                原话
              </button>
            )}
            {finding.llm_prompt && (
              <button
                onClick={() => setExpanded(expanded === "prompt" ? null : "prompt")}
                className={`rounded px-1.5 py-0.5 text-[10px] transition-colors ${expanded === "prompt" ? "bg-zinc-500 text-zinc-100" : "bg-zinc-700 text-zinc-400 hover:text-zinc-200"}`}
              >
                Prompt
              </button>
            )}
          </div>
        )}
      </div>
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
