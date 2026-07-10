"use client";

import React, { useEffect, useState } from "react";
import { useI18n } from "@/hooks/useI18n";
import { getApiBaseUrl } from "@/lib/api-url";
import { MemoryOperationsView } from "./MemoryOperationsView";
import {
  type CuratorRunState,
  type CuratorStatus,
  type LlmRunState,
  getErrorMessage,
} from "./memory-operations-types";

const LLM_JOB_KEY = "mcore_llm_curator_job";

export const MemoryOperationsPanel = () => {
  const { messages, locale } = useI18n();
  const [status, setStatus] = useState<CuratorStatus | null>(null);
  const [applying, setApplying] = useState(false);
  const [runState, setRunState] = useState<CuratorRunState>({ state: "idle" });
  const [runActionsShowAll, setRunActionsShowAll] = useState(false);
  const [llmRunState, setLlmRunState] = useState<LlmRunState>({ state: "idle" });
  const [llmRunning, setLlmRunning] = useState(false);
  const llmPollRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchStatus = React.useCallback(async () => {
    const response = await fetch(`${getApiBaseUrl()}/api/curator/status`);
    if (!response.ok) throw new Error(`Curator status request failed with ${response.status}`);
    const payload = await response.json();
    setStatus(payload.data);
  }, []);

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

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
      if (!response.ok || payload.ok === false) throw new Error(payload?.error?.message || `Curator failed with ${response.status}`);
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

  const pollJob = React.useCallback(async (jobId: string, startedAt: number) => {
    try {
      const response = await fetch(`${getApiBaseUrl()}/api/curator/llm/${jobId}`);
      if (!response.ok) {
        setLlmRunState({ state: "idle" });
        setLlmRunning(false);
        localStorage.removeItem(LLM_JOB_KEY);
        return;
      }
      const payload = await response.json();
      const data = payload.data || payload;
      if (data.status === "done" || data.status === "succeeded") {
        setLlmRunState({ state: "succeeded", jobId, startedAt, elapsedMs: Date.now() - startedAt, summary: data.summary || data.result?.summary || {}, errors: data.errors || data.result?.errors || [], progress: data.progress });
        setLlmRunning(false);
        localStorage.removeItem(LLM_JOB_KEY);
        void fetchStatus();
      } else if (data.status === "error" || data.status === "failed") {
        setLlmRunState({ state: "failed", jobId, startedAt, elapsedMs: Date.now() - startedAt, summary: data.summary, progress: data.progress, errors: data.errors, error: data.error || (Array.isArray(data.errors) ? data.errors.join("; ") : "LLM Curator job failed") });
        setLlmRunning(false);
        localStorage.removeItem(LLM_JOB_KEY);
      } else {
        setLlmRunState((previous) => ({ ...previous, state: "running", jobId, startedAt, summary: data.summary || previous.summary, progress: data.progress || previous.progress, errors: data.errors || previous.errors }));
        llmPollRef.current = setTimeout(() => void pollJob(jobId, startedAt), 3000);
      }
    } catch {
      llmPollRef.current = setTimeout(() => void pollJob(jobId, startedAt), 3000);
    }
  }, [fetchStatus]);

  useEffect(() => {
    const saved = localStorage.getItem(LLM_JOB_KEY);
    if (!saved) {
      fetch(`${getApiBaseUrl()}/api/curator/llm/latest`).then((response) => response.json()).then((payload) => {
        const data = payload.data || payload;
        if (data.status === "running" && data.job_id) {
          const startedAt = Date.now();
          setLlmRunning(true);
          setLlmRunState({ state: "running", jobId: data.job_id, startedAt, summary: data.summary || {}, progress: data.progress || {} });
          localStorage.setItem(LLM_JOB_KEY, JSON.stringify({ jobId: data.job_id, startedAt }));
          llmPollRef.current = setTimeout(() => void pollJob(data.job_id, startedAt), 2000);
        }
      }).catch(() => undefined);
    } else {
      try {
        const { jobId, startedAt } = JSON.parse(saved);
        if (!jobId || Date.now() - startedAt > 2 * 60 * 60 * 1000) localStorage.removeItem(LLM_JOB_KEY);
        else {
          setLlmRunning(true);
          setLlmRunState({ state: "running", jobId, startedAt });
          llmPollRef.current = setTimeout(() => void pollJob(jobId, startedAt), 500);
        }
      } catch {
        localStorage.removeItem(LLM_JOB_KEY);
      }
    }
    return () => { if (llmPollRef.current) clearTimeout(llmPollRef.current); };
  }, [pollJob]);

  const runLlmCurator = async () => {
    if (llmRunning) return;
    const startedAt = Date.now();
    setLlmRunning(true);
    setLlmRunState({ state: "running", startedAt });
    try {
      const response = await fetch(`${getApiBaseUrl()}/api/curator/llm`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ dry_run: true }) });
      const payload = await response.json();
      if (!response.ok || payload.ok === false) throw new Error(payload?.error?.message || `LLM Curator failed with ${response.status}`);
      const jobId = (payload.data || payload)?.job_id;
      if (!jobId) throw new Error("No job_id returned from server");
      localStorage.setItem(LLM_JOB_KEY, JSON.stringify({ jobId, startedAt }));
      setLlmRunState({ state: "running", jobId, startedAt });
      llmPollRef.current = setTimeout(() => void pollJob(jobId, startedAt), 2000);
    } catch (error: unknown) {
      setLlmRunState({ state: "failed", startedAt, elapsedMs: Date.now() - startedAt, error: getErrorMessage(error, "LLM Curator failed") });
      setLlmRunning(false);
      localStorage.removeItem(LLM_JOB_KEY);
    }
  };

  return <MemoryOperationsView messages={messages} locale={locale} status={status} applying={applying} llmRunning={llmRunning} runState={runState} runActionsShowAll={runActionsShowAll} llmRunState={llmRunState} onApplyCurator={() => void applyCurator()} onRunLlmCurator={() => void runLlmCurator()} onShowAllActions={() => setRunActionsShowAll(true)} />;
};

export default MemoryOperationsPanel;
