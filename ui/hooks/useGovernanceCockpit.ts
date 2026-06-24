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
import { isActionableDecision } from "@/components/dashboard/intelligence/utils";
import type { RootState } from "@/store/store";

interface ApiErrorPayload {
  code?: string;
  message?: string;
  detail?: unknown;
}

interface ApiEnvelope<T> {
  ok?: boolean;
  data?: T;
  error?: string | ApiErrorPayload;
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
  decisionType: string;
}

interface UseGovernanceCockpitReturn extends GovernanceCockpitState {
  setReviewStatus: (status: GovernanceReviewStatus) => void;
  setDecisionType: (decisionType: string) => void;
  selectDecision: (decision: GovernanceDecision | null) => void;
  refresh: () => Promise<void>;
  applyDecision: (decisionId: string) => Promise<void>;
  rejectDecision: (decisionId: string, reason: string) => Promise<void>;
  rollbackDecision: (decisionId: string) => Promise<void>;
  applyDecisionOrThrow: (decisionId: string) => Promise<void>;
  rejectDecisionOrThrow: (decisionId: string, reason: string) => Promise<void>;
  applyBatchDecisions: (decisionIds: string[]) => Promise<number>;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "Unexpected governance cockpit error";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function extractApiErrorMessage(payload: unknown, response: Response, rawBody: string): string {
  if (isRecord(payload)) {
    const error = payload.error;
    if (typeof error === "string" && error.trim()) return error;
    if (isRecord(error) && typeof error.message === "string" && error.message.trim()) return error.message;
  }

  return rawBody.trim() || response.statusText || "Request failed";
}

function parseJsonBody<T>(rawBody: string): ApiEnvelope<T> | T | null {
  if (!rawBody) return {} as ApiEnvelope<T>;
  try {
    return JSON.parse(rawBody) as ApiEnvelope<T> | T;
  } catch {
    return null;
  }
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
  const rawBody = await response.text();
  const payload = parseJsonBody<T>(rawBody);
  if (!response.ok) {
    throw new Error(extractApiErrorMessage(payload, response, rawBody));
  }
  if (payload === null) {
    throw new Error("Response body must be valid JSON");
  }
  if (isRecord(payload) && "data" in payload) {
    return payload.data as T;
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

const RISK_PRIORITY: Record<string, number> = { high: 0, medium: 1, low: 2 };
const ACTION_PRIORITY: Record<string, number> = {
  mark_contradicted: 0,
  archive_and_merge_duplicate: 1,
  supersede: 2,
  archive_duplicate: 3,
  archive: 4,
  split: 5,
  downgrade: 6,
  promote: 7,
};

function compareDecisionsByPriority(a: GovernanceDecision, b: GovernanceDecision): number {
  const riskDelta = (RISK_PRIORITY[a.risk_level] ?? 1) - (RISK_PRIORITY[b.risk_level] ?? 1);
  if (riskDelta !== 0) return riskDelta;

  const actionDelta = (ACTION_PRIORITY[a.recommended_action] ?? 8) - (ACTION_PRIORITY[b.recommended_action] ?? 8);
  if (actionDelta !== 0) return actionDelta;

  const confidenceDelta = b.llm_confidence - a.llm_confidence;
  if (confidenceDelta !== 0) return confidenceDelta;

  return new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime();
}

function prioritizedDecisions(decisions: GovernanceDecision[], reviewStatus: GovernanceReviewStatus): GovernanceDecision[] {
  const visibleDecisions = reviewStatus === "actionable" ? decisions.filter(isActionableDecision) : decisions;
  return [...visibleDecisions].sort(compareDecisionsByPriority);
}

function reconcileSelection(current: GovernanceDecision | null, decisions: GovernanceDecision[]): GovernanceDecision | null {
  if (!decisions.length) return null;
  if (current) {
    const existing = decisions.find((decision) => decision.id === current.id);
    if (existing) return existing;
  }
  // Remove auto-selection behavior so no decision is selected by default
  return null;
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
    reviewStatus: "actionable",
    decisionType: "",
  });

  const baseUrl = useMemo(() => getApiBaseUrl(), []);

  const loadOverview = useCallback(async (signal?: AbortSignal): Promise<void> => {
    setState((current) => ({ ...current, isLoading: true, error: null }));
    try {
      const decisionUrl = appendQuery(`${baseUrl}/api/governance/decisions`, {
        review_status: state.reviewStatus,
        decision_type: state.decisionType || undefined,
      });
      const [metrics, decisions] = await Promise.all([
        fetchJson<GovernanceMetrics>(`${baseUrl}/api/governance/metrics`, { signal }),
        fetchJson<GovernanceDecision[]>(decisionUrl, { signal }),
      ]);
      const sortedDecisions = prioritizedDecisions(decisions, state.reviewStatus);
      setState((current) => ({
        ...current,
        decisions: sortedDecisions,
        metrics,
        selectedDecision: reconcileSelection(current.selectedDecision, sortedDecisions),
        isLoading: false,
        error: null,
      }));
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setState((current) => ({ ...current, isLoading: false, error: getErrorMessage(error) }));
    }
  }, [baseUrl, state.reviewStatus, state.decisionType]);

  const loadDecisionDetails = useCallback(async (decision: GovernanceDecision | null, signal?: AbortSignal): Promise<void> => {
    const memoryId = primaryMemoryId(decision);
    if (!decision || !memoryId) {
      setState((current) => ({ ...current, lineage: null, auditEvents: [], isDetailLoading: false }));
      return;
    }
    setState((current) => ({ ...current, isDetailLoading: true }));
    try {
      const fetches: [Promise<LineagePayload>, Promise<AuditEvent[]>, Promise<GovernanceDecision> | null] = [
        fetchJson<LineagePayload>(`${baseUrl}/api/lineage/${encodeURIComponent(memoryId)}?limit=100`, { signal }),
        fetchJson<AuditEvent[]>(appendQuery(`${baseUrl}/api/audit`, { memory_id: memoryId, limit: 25 }), { signal }),
        !decision.before_state?.length
          ? fetchJson<GovernanceDecision>(`${baseUrl}/api/governance/${encodeURIComponent(decision.id)}`, { signal })
          : null,
      ];
      const [lineage, auditEvents, detail] = await Promise.all(fetches);
      setState((current) => ({
        ...current,
        lineage,
        auditEvents,
        isDetailLoading: false,
        selectedDecision:
          detail && current.selectedDecision?.id === decision.id
            ? { ...current.selectedDecision, before_state: detail.before_state ?? current.selectedDecision.before_state }
            : current.selectedDecision,
      }));
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

  const setDecisionType = useCallback((decisionType: string): void => {
    setState((current) => ({ ...current, decisionType, selectedDecision: null }));
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
      throw new Error(message);
    } finally {
      setState((current) => ({ ...current, actionPendingId: null }));
    }
  }, [baseUrl, loadOverview, toast]);

  const applyDecision = useCallback(async (decisionId: string): Promise<void> => {
    await runAction(decisionId, "apply", { source_agent: "frontend" }, "Decision applied").catch(() => undefined);
  }, [runAction]);

  const rejectDecision = useCallback(async (decisionId: string, reason: string): Promise<void> => {
    await runAction(decisionId, "reject", { source_agent: "frontend", reason }, "Decision rejected").catch(() => undefined);
  }, [runAction]);

  const rollbackDecision = useCallback(async (decisionId: string): Promise<void> => {
    await runAction(decisionId, "rollback", { source_agent: "frontend" }, "Decision rolled back").catch(() => undefined);
  }, [runAction]);

  const applyDecisionOrThrow = useCallback((decisionId: string): Promise<void> =>
    runAction(decisionId, "apply", { source_agent: "frontend" }, "Decision applied"),
  [runAction]);

  const rejectDecisionOrThrow = useCallback((decisionId: string, reason: string): Promise<void> =>
    runAction(decisionId, "reject", { source_agent: "frontend", reason }, "Decision rejected"),
  [runAction]);

  const applyBatchDecisions = useCallback(async (decisionIds: string[]): Promise<number> => {
    if (!decisionIds.length) return 0;
    setState((current) => ({ ...current, actionPendingId: "batch", error: null }));
    try {
      const result = await fetchJson<{ applied_count: number }>(`${baseUrl}/api/governance/batch/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision_ids: decisionIds, source_agent: "frontend" }),
      });
      await loadOverview();
      return result.applied_count || 0;
    } catch (error: unknown) {
      const message = getErrorMessage(error);
      setState((current) => ({ ...current, error: message }));
      toast({ variant: "destructive", description: message });
      throw new Error(message);
    } finally {
      setState((current) => ({ ...current, actionPendingId: null }));
    }
  }, [baseUrl, loadOverview, toast]);

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
    setDecisionType,
    selectDecision,
    refresh,
    applyDecision,
    rejectDecision,
    rollbackDecision,
    applyDecisionOrThrow,
    rejectDecisionOrThrow,
    applyBatchDecisions,
  };
}
