import { GovernanceDecision, GovernanceMemorySnapshot } from "./types";

export function formatGovernanceDate(value?: string | number | null): string {
  if (!value || value === "n/a") return "n/a";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "n/a";
  return date.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
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

export function decisionTitle(decision: GovernanceDecision): string {
  const findingTitle = typeof decision.finding?.title === "string" ? decision.finding.title : "";
  const firstMemory = decision.before_state?.[0] ?? decision.after_state?.[0];
  return findingTitle || memoryTitle(firstMemory) || decision.id;
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
