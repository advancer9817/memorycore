"use client";

import React, { useEffect, useState } from "react";
import { useI18n } from "@/hooks/useI18n";
import { getApiBaseUrl } from "@/lib/api-url";
import { MemoryOperationsView } from "./MemoryOperationsView";
import {
  type CuratorRunState,
  type CuratorStatus,
  type LlmRunState,
  type MaintenanceAction,
  type MaintenanceJob,
  type MaintenanceRunState,
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
  const [maintenanceRunState, setMaintenanceRunState] = useState<MaintenanceRunState>({ state: "idle", plan: null, action: "archive" });
  const [maintenanceBusy, setMaintenanceBusy] = useState(false);
  const maintenancePollRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const maintenancePollErrorsRef = React.useRef(0);

  const selectMaintenanceAction = (action: MaintenanceAction) => {
    if (maintenanceBusy) return;
    if (maintenanceRunState.action === action) return;
    setMaintenanceRunState({ state: "idle", plan: null, action });
  };

  const fetchStatus = React.useCallback(async () => {
    const response = await fetch(`${getApiBaseUrl()}/api/v1/curator/status`);
    if (!response.ok) throw new Error(`Curator status request failed with ${response.status}`);
    const payload = await response.json();
    setStatus((payload as { data?: CuratorStatus }).data ?? (payload as CuratorStatus));
  }, []);

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

  const applyCurator = async () => {
    const started = new Date();
    setApplying(true);
    setRunState({ state: "running", startedAt: started.toISOString() });
    try {
      const response = await fetch(`${getApiBaseUrl()}/api/v1/curator/apply`, {
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
      const response = await fetch(`${getApiBaseUrl()}/api/v1/curator/llm/${jobId}`);
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
      fetch(`${getApiBaseUrl()}/api/v1/curator/llm/latest`).then((response) => response.json()).then((payload) => {
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
      const response = await fetch(`${getApiBaseUrl()}/api/v1/curator/llm`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ dry_run: true }) });
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

  const fetchMaintenancePlan = async (action: MaintenanceAction = maintenanceRunState.action ?? "archive") => {
    if (maintenanceBusy) return;
    setMaintenanceBusy(true);
    setMaintenanceRunState({ state: "planning", plan: null, action });
    try {
      const response = await fetch(`${getApiBaseUrl()}/api/v1/maintenance/plan?action=${encodeURIComponent(action)}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload?.error?.message || `Maintenance plan failed with ${response.status}`);
      setMaintenanceRunState({ state: "planReady", plan: payload, action });
    } catch (error: unknown) {
      setMaintenanceRunState({ state: "failed", plan: null, action, error: getErrorMessage(error, "Maintenance plan failed") });
    } finally {
      setMaintenanceBusy(false);
    }
  };

  const pollMaintenanceJob = React.useCallback(async (jobId: string, startedAt: number) => {
    try {
      const response = await fetch(`${getApiBaseUrl()}/api/v1/maintenance/${jobId}`);
      if (!response.ok) throw new Error(`Maintenance job request failed with ${response.status}`);
      const data = (await response.json()) as MaintenanceJob;
      maintenancePollErrorsRef.current = 0;
      if (data.status === "succeeded" || data.status === "failed") {
        const finalStatus: "succeeded" | "failed" = data.status;
        setMaintenanceRunState((previous) => ({ ...previous, state: finalStatus, jobId, startedAt, elapsedMs: Date.now() - startedAt, result: data, error: data.error || previous.error }));
        setMaintenanceBusy(false);
        return;
      }
      setMaintenanceRunState((previous) => ({ ...previous, state: "running", jobId, startedAt, result: data }));
      maintenancePollRef.current = setTimeout(() => void pollMaintenanceJob(jobId, startedAt), 2000);
    } catch (error: unknown) {
      maintenancePollErrorsRef.current += 1;
      if (maintenancePollErrorsRef.current >= 5) {
        setMaintenanceRunState((previous) => ({ ...previous, state: "failed", jobId, startedAt, elapsedMs: Date.now() - startedAt, error: getErrorMessage(error, "Maintenance job failed") }));
        setMaintenanceBusy(false);
        return;
      }
      maintenancePollRef.current = setTimeout(() => void pollMaintenanceJob(jobId, startedAt), 3000);
    }
  }, []);

  const executeMaintenance = async () => {
    const plan = maintenanceRunState.plan;
    const action = maintenanceRunState.action ?? "archive";
    if (!plan || maintenanceBusy) return;
    if (action === "clean") {
      const count = plan.clean_count ?? 0;
      if (count === 0) return;
      if (!window.confirm(messages.dashboard.maintenanceCleanConfirm(count))) return;
    }
    const startedAt = Date.now();
    setMaintenanceBusy(true);
    setMaintenanceRunState({ state: "running", plan, action, startedAt });
    try {
      const response = await fetch(`${getApiBaseUrl()}/api/v1/maintenance/execute`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ plan_token: plan.plan_token, action }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload?.error?.message || `Maintenance execute failed with ${response.status}`);
      const jobId = payload?.job_id;
      if (!jobId) throw new Error("No job_id returned from server");
      maintenancePollErrorsRef.current = 0;
      setMaintenanceRunState((previous) => ({ ...previous, state: "running", jobId, startedAt }));
      maintenancePollRef.current = setTimeout(() => void pollMaintenanceJob(jobId, startedAt), 1500);
    } catch (error: unknown) {
      const message = getErrorMessage(error, "Maintenance execute failed");
      const busyHint = messages.dashboard.maintenanceBusy;
      const staleHint = messages.dashboard.maintenanceStale;
      const isBusy = /lock|another curator|running/i.test(message);
      const isStale = /stale|plan_token/i.test(message) && !isBusy;
      setMaintenanceRunState((previous) => ({ ...previous, state: "failed", startedAt, elapsedMs: Date.now() - startedAt, error: isBusy ? busyHint : isStale ? staleHint : message }));
      setMaintenanceBusy(false);
    }
  };

  useEffect(() => {
    fetch(`${getApiBaseUrl()}/api/v1/maintenance/latest`).then((response) => response.json()).then((payload) => {
      const data = payload as MaintenanceJob;
      if (data?.status === "running" && data.job_id) {
        const startedAt = Date.now();
        setMaintenanceBusy(true);
        setMaintenanceRunState({ state: "running", jobId: data.job_id, startedAt, result: data });
        maintenancePollRef.current = setTimeout(() => void pollMaintenanceJob(data.job_id as string, startedAt), 1000);
      }
    }).catch(() => undefined);
    return () => { if (maintenancePollRef.current) clearTimeout(maintenancePollRef.current); };
  }, [pollMaintenanceJob]);

  return <MemoryOperationsView messages={messages} locale={locale} status={status} applying={applying} llmRunning={llmRunning} runState={runState} runActionsShowAll={runActionsShowAll} llmRunState={llmRunState} maintenanceRunState={maintenanceRunState} maintenanceBusy={maintenanceBusy} onApplyCurator={() => void applyCurator()} onRunLlmCurator={() => void runLlmCurator()} onShowAllActions={() => setRunActionsShowAll(true)} onGenerateMaintenancePlan={() => void fetchMaintenancePlan()} onExecuteMaintenance={() => void executeMaintenance()} onSelectMaintenanceAction={(action) => selectMaintenanceAction(action)} />;
};

export default MemoryOperationsPanel;
