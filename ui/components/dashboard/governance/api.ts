"use client";

import { getApiBaseUrl } from "@/lib/api-url";
import { AuditEvent, GovernanceDecision, GovernanceMetrics } from "@/components/dashboard/intelligence/types";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const base = getApiBaseUrl();
  const res = await fetch(`${base}/api/${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export async function fetchGovernanceDecisions(
  reviewStatus?: string,
  limit = 100,
  signal?: AbortSignal,
): Promise<GovernanceDecision[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (reviewStatus) params.set("review_status", reviewStatus);
  return apiFetch<GovernanceDecision[]>(`governance/decisions?${params}`, { signal });
}

export async function fetchGovernanceMetrics(signal?: AbortSignal): Promise<GovernanceMetrics> {
  return apiFetch<GovernanceMetrics>("governance/metrics", { signal });
}

export async function fetchAuditLog(
  eventType?: string,
  limit = 50,
  signal?: AbortSignal,
): Promise<AuditEvent[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (eventType) params.set("event_type", eventType);
  return apiFetch<AuditEvent[]>(`audit?${params}`, { signal });
}
