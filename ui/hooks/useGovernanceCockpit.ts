"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSelector } from "react-redux";
import { useToast } from "@/hooks/use-toast";
import { getApiBaseUrl } from "@/lib/api-url";
import type {
  AuditEvent,
  GovernanceActionResult,
  GovernanceDecision,
  GovernanceMetrics,
  GovernanceReviewStatus,
  LineagePayload,
} from "@/components/dashboard/intelligence/types";
import type { RootState } from "@/store/store";

interface ApiEnvelope<T> {
  ok?: boolean;
  data?: T;
  error?: string;
}

interface GovernanceCockpitState {
  decisions: GovernanceDecision[];
  metrics: GovernanceMetrics | null;
  selectedDecision: GovernanceDecision | null;
  lineage: LineagePayload | null;
  auditEvents: AuditEvent[];
  isLoading: boolean;
  isDetailLoading: boolean;
  actionPendingId: string | null;
  error: string | null;
  reviewStatus: GovernanceReviewStatus;
}

interface UseGovernanceCockpitReturn extends GovernanceCockpitState {
  setReviewStatus: (status: GovernanceReviewStatus) => void;
  selectDecision: (decision: GovernanceDecision | null) => void;
  refresh: () => Promise<void>;
  applyDecision: (decisionId: string) => Promise<void>;
  rejectDecision: (decisionId: string, reason: string) => Promise<void>;
  rollbackDecision: (decisionId: string) => Promise<void>;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "Unexpected governance cockpit error";
}

function appendQuery(url: string, params: Record<string, string | number | undefined>): string {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      searchParams.set(key, String(value));
    }
  });
  const query = searchParams.toString();
  return query ? `${url}?${query}` : url;
}

async function readJson<T>(response: Response): Promise<T> {
  const payload = (await response.json()) as ApiEnvelope<T> | T;
  if (!response.ok) {
    const errorMessage = typeof (payload as ApiEnvelope<T>).error === "string" ? (payload as ApiEnvelope<T>).error : response.statusText;
    throw new Error(errorMessage || "Request failed");
  }
  if (typeof payload === "object" && payload !== null && "data" in payload) {
    return (payload as ApiEnvelope<T>).data as T;
  }
  return payload as T;
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  return readJson<T>(response);
}

function primaryMemoryId(decision: GovernanceDecision | null): string {
  if (!decision) return "";
  return decision.source_ids?.[0] || decision.before_state?.[0]?.id || decision.after_state?.[0]?.id || "";
}

function reconcileSelection(current: GovernanceDecision | null, decisions: GovernanceDecision[]): GovernanceDecision | null {
  if (!decisions.length) return null;
  if (current) {
    const existing = decisions.find((decision) => decision.id === current.id);
    if (existing) return existing;
  }
  return decisions.find((decision) => decision.review_status === "needs_review") ?? decisions[0];
}

export function useGovernanceCockpit(): UseGovernanceCockpitReturn {
  const { toast } = useToast();
  const governanceRefreshKey = useSelector((rootState: RootState) => rootState.ui.governanceRefreshKey);
  const [state, setState] = useState<GovernanceCockpitState>({
    decisions: [],
    metrics: null,
    selectedDecision: null,
    lineage: null,
    auditEvents: [],
    isLoading: true,
    isDetailLoading: false,
    actionPendingId: null,
    error: null,
    reviewStatus: "all",
  });

  const baseUrl = useMemo(() => getApiBaseUrl(), []);

  const loadOverview = useCallback(async (signal?: AbortSignal): Promise<void> => {
    setState((current) => ({ ...current, isLoading: true, error: null }));
    try {
      const decisionUrl = appendQuery(`${baseUrl}/api/governance/decisions`, {
        review_status: state.reviewStatus === "all" ? undefined : state.reviewStatus,
        limit: 100,
      });
      const [metrics, decisions] = await Promise.all([
        fetchJson<GovernanceMetrics>(`${baseUrl}/api/governance/metrics`, { signal }),
        fetchJson<GovernanceDecision[]>(decisionUrl, { signal }),
      ]);
      setState((current) => ({
        ...current,
        decisions,
        metrics,
        selectedDecision: reconcileSelection(current.selectedDecision, decisions),
        isLoading: false,
        error: null,
      }));
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setState((current) => ({ ...current, isLoading: false, error: getErrorMessage(error) }));
    }
  }, [baseUrl, state.reviewStatus]);

  const loadDecisionDetails = useCallback(async (decision: GovernanceDecision | null, signal?: AbortSignal): Promise<void> => {
    const memoryId = primaryMemoryId(decision);
    if (!decision || !memoryId) {
      setState((current) => ({ ...current, lineage: null, auditEvents: [], isDetailLoading: false }));
      return;
    }
    setState((current) => ({ ...current, isDetailLoading: true }));
    try {
      const [lineage, auditEvents] = await Promise.all([
        fetchJson<LineagePayload>(`${baseUrl}/api/lineage/${encodeURIComponent(memoryId)}?limit=100`, { signal }),
        fetchJson<AuditEvent[]>(appendQuery(`${baseUrl}/api/audit`, { memory_id: memoryId, limit: 25 }), { signal }),
      ]);
      setState((current) => ({ ...current, lineage, auditEvents, isDetailLoading: false }));
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setState((current) => ({
        ...current,
        lineage: null,
        auditEvents: [],
        isDetailLoading: false,
        error: getErrorMessage(error),
      }));
    }
  }, [baseUrl]);

  const refresh = useCallback(async (): Promise<void> => {
    await loadOverview();
  }, [loadOverview]);

  const selectDecision = useCallback((decision: GovernanceDecision | null): void => {
    setState((current) => ({ ...current, selectedDecision: decision }));
  }, []);

  const setReviewStatus = useCallback((reviewStatus: GovernanceReviewStatus): void => {
    setState((current) => ({ ...current, reviewStatus, selectedDecision: null }));
  }, []);

  const runAction = useCallback(async (
    decisionId: string,
    action: "apply" | "reject" | "rollback",
    body: Record<string, unknown>,
    successMessage: string,
  ): Promise<void> => {
    setState((current) => ({ ...current, actionPendingId: decisionId, error: null }));
    try {
      await fetchJson<GovernanceActionResult>(`${baseUrl}/api/governance/${encodeURIComponent(decisionId)}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      toast({ description: successMessage });
      await loadOverview();
    } catch (error: unknown) {
      const message = getErrorMessage(error);
      setState((current) => ({ ...current, error: message }));
      toast({ variant: "destructive", description: message });
    } finally {
      setState((current) => ({ ...current, actionPendingId: null }));
    }
  }, [baseUrl, loadOverview, toast]);

  const applyDecision = useCallback(async (decisionId: string): Promise<void> => {
    await runAction(decisionId, "apply", { source_agent: "frontend" }, "Decision applied");
  }, [runAction]);

  const rejectDecision = useCallback(async (decisionId: string, reason: string): Promise<void> => {
    await runAction(decisionId, "reject", { source_agent: "frontend", reason }, "Decision rejected");
  }, [runAction]);

  const rollbackDecision = useCallback(async (decisionId: string): Promise<void> => {
    await runAction(decisionId, "rollback", { source_agent: "frontend" }, "Decision rolled back");
  }, [runAction]);

  useEffect(() => {
    const controller = new AbortController();
    void loadOverview(controller.signal);
    return () => controller.abort();
  }, [governanceRefreshKey, loadOverview]);

  useEffect(() => {
    const controller = new AbortController();
    void loadDecisionDetails(state.selectedDecision, controller.signal);
    return () => controller.abort();
  }, [loadDecisionDetails, state.selectedDecision]);

  return {
    ...state,
    setReviewStatus,
    selectDecision,
    refresh,
    applyDecision,
    rejectDecision,
    rollbackDecision,
  };
}
