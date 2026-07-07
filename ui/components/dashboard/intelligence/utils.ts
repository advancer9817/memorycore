import { GovernanceDecision, GovernanceMemorySnapshot } from "./types";

export function formatGovernanceDate(value?: string | number | null, locale: "en" | "zh" = "en"): string {
  if (!value || value === "n/a") return "n/a";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "n/a";
  return date.toLocaleString(locale === "zh" ? "zh-CN" : "en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function formatPercent(value?: number): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "n/a";
  return `${Math.round(value * 100)}%`;
}

export function titleCase(value: string): string {
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function memoryTitle(memory?: GovernanceMemorySnapshot): string {
  const title = memory?.title?.trim() || memory?.content?.trim() || memory?.id || "Unknown memory";
  return title.length > 90 ? `${title.slice(0, 90)}…` : title;
}

function findingTitle(finding?: Record<string, unknown>): string {
  if (!finding) return "";
  for (const key of ["title", "newer_title", "new_title", "keep_title", "older_title", "old_title", "drop_title"]) {
    const val = finding[key];
    if (typeof val === "string" && val.trim()) return val.trim();
  }
  return "";
}

export function decisionTitle(decision: GovernanceDecision): string {
  const title = findingTitle(decision.finding);
  const firstMemory = decision.before_state?.[0] ?? decision.after_state?.[0];
  return title || memoryTitle(firstMemory) || decision.id;
}

export function decisionSummary(decision: GovernanceDecision): string {
  const reason = typeof decision.finding?.reason === "string" ? decision.finding.reason : "";
  return reason || decision.policy_reason || titleCase(decision.recommended_action);
}

export function confidenceTone(confidence: number): string {
  if (confidence > 0.8) return "border-emerald-700 bg-emerald-500/10 text-emerald-300";
  if (confidence >= 0.6) return "border-amber-700 bg-amber-500/10 text-amber-300";
  return "border-red-700 bg-red-500/10 text-red-300";
}

export function riskTone(risk: string): string {
  if (risk === "high") return "border-red-800/70 bg-red-950/35 text-red-200";
  if (risk === "low") return "border-sky-800/70 bg-sky-950/35 text-sky-200";
  return "border-amber-800/70 bg-amber-950/35 text-amber-200";
}

export function reviewStatusTone(status: string): string {
  if (status === "applied") return "border-emerald-800/70 bg-emerald-950/35 text-emerald-200";
  if (status === "auto_approved") return "border-sky-800/70 bg-sky-950/35 text-sky-200";
  if (status === "rejected") return "border-zinc-700 bg-zinc-900 text-zinc-300";
  if (status === "rolled_back") return "border-zinc-700/70 bg-zinc-800/35 text-zinc-300";
  return "border-amber-800/70 bg-amber-950/35 text-amber-200";
}

export function canApplyDecision(decision: GovernanceDecision): boolean {
  return decision.review_status === "needs_review" || decision.review_status === "auto_approved";
}

export function isActionableDecision(decision: GovernanceDecision): boolean {
  return canApplyDecision(decision) && decision.recommended_action !== "keep";
}

export function canRollbackDecision(decision: GovernanceDecision): boolean {
  return decision.review_status === "applied";
}
