"use client";

import { useEffect, useReducer, useRef } from "react";
import { AuditEvent, GovernanceDecision, GovernanceMetrics } from "@/components/dashboard/intelligence/types";
import { fetchAuditLog, fetchGovernanceDecisions, fetchGovernanceMetrics } from "./api";

interface CockpitState {
  applied: GovernanceDecision[];
  needsReview: GovernanceDecision[];
  auditLog: AuditEvent[];
  metrics: GovernanceMetrics | null;
  loading: boolean;
  error: string | null;
}

type Action =
  | { type: "loading" }
  | {
      type: "loaded";
      applied: GovernanceDecision[];
      needsReview: GovernanceDecision[];
      auditLog: AuditEvent[];
      metrics: GovernanceMetrics | null;
    }
  | { type: "error"; message: string };

function reducer(state: CockpitState, action: Action): CockpitState {
  switch (action.type) {
    case "loading":
      return { ...state, loading: true, error: null };
    case "loaded":
      return {
        ...state,
        loading: false,
        applied: action.applied,
        needsReview: action.needsReview,
        auditLog: action.auditLog,
        metrics: action.metrics,
      };
    case "error":
      return { ...state, loading: false, error: action.message };
  }
}

const INITIAL: CockpitState = {
  applied: [],
  needsReview: [],
  auditLog: [],
  metrics: null,
  loading: true,
  error: null,
};

export function useGovernanceCockpit() {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const abortRef = useRef<AbortController | null>(null);

  const load = () => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    dispatch({ type: "loading" });

    Promise.all([
      fetchGovernanceDecisions("applied", 100, ctrl.signal),
      fetchGovernanceDecisions("needs_review", 100, ctrl.signal),
      fetchAuditLog(undefined, 50, ctrl.signal),
      fetchGovernanceMetrics(ctrl.signal).catch(() => null),
    ])
      .then(([applied, needsReview, auditLog, metrics]) => {
        if (ctrl.signal.aborted) return;
        dispatch({ type: "loaded", applied, needsReview, auditLog, metrics });
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        dispatch({ type: "error", message: err instanceof Error ? err.message : String(err) });
      });
  };

  useEffect(() => {
    load();
    return () => abortRef.current?.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { ...state, refresh: load };
}
