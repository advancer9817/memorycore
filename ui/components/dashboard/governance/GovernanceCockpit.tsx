"use client";

import { useState } from "react";
import { AlertTriangle, CheckCircle2, Clock, RefreshCcw, ShieldAlert, ShieldCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { AuditEvent, GovernanceDecision, GovernanceMetrics } from "@/components/dashboard/intelligence/types";
import {
  confidenceTone,
  decisionSummary,
  decisionTitle,
  formatGovernanceDate,
  formatPercent,
  riskTone,
  titleCase,
} from "@/components/dashboard/intelligence/utils";
import { useGovernanceCockpit } from "./useGovernanceCockpit";
import { useI18n } from "@/hooks/useI18n";

// ---------------------------------------------------------------------------
// Judge Trace drawer
// ---------------------------------------------------------------------------
function JudgeTraceDrawer({
  decision,
  onClose,
  c,
  locale,
}: {
  decision: GovernanceDecision | null;
  onClose: () => void;
  c: ReturnType<typeof useI18n>["messages"]["governance"]["cockpit"];
  locale: "en" | "zh";
}) {
  void locale; // used for date formatting in parent
  const trace = decision?.llm_trace ?? {};
  return (
    <Sheet open={!!decision} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-full max-w-xl bg-zinc-900 border-zinc-700">
        <SheetHeader>
          <SheetTitle className="text-zinc-100">{c.rawJudgeTrace}</SheetTitle>
        </SheetHeader>
        <ScrollArea className="mt-4 h-[calc(100vh-120px)] pr-2">
          {decision && (
            <div className="space-y-4 text-sm">
              <Row label={c.traceDecisionId} value={decision.id} mono />
              <Row label={c.traceType} value={titleCase(decision.decision_type)} />
              <Row label={c.traceAction} value={titleCase(decision.recommended_action)} />
              <Row label={c.traceConfidence} value={`${Math.round(decision.llm_confidence * 100)}%`} />
              <Row label={c.traceRisk} value={decision.risk_level} />
              <Row label={c.traceStatus} value={decision.review_status} />
              <Row label={c.tracePolicyReason} value={decision.policy_reason} />
              {typeof trace.rationale === "string" && (
                <Section label={c.traceRationale} content={trace.rationale} />
              )}
              {typeof trace.prompt === "string" && (
                <Section label={c.tracePrompt} content={trace.prompt} mono />
              )}
              {typeof trace.response === "string" && (
                <Section label={c.traceResponse} content={trace.response} mono />
              )}
              {typeof trace.thinking === "string" && trace.thinking && (
                <Section label={c.traceThinking} content={trace.thinking} mono />
              )}
            </div>
          )}
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}

// ---------------------------------------------------------------------------
// Snapshot/Timeline drawer
// ---------------------------------------------------------------------------
function SnapshotDrawer({
  decision,
  onClose,
  c,
}: {
  decision: GovernanceDecision | null;
  onClose: () => void;
  c: ReturnType<typeof useI18n>["messages"]["governance"]["cockpit"];
}) {
  return (
    <Sheet open={!!decision} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-full max-w-2xl bg-zinc-900 border-zinc-700">
        <SheetHeader>
          <SheetTitle className="text-zinc-100">{c.beforeAfterSnapshot}</SheetTitle>
        </SheetHeader>
        <ScrollArea className="mt-4 h-[calc(100vh-120px)] pr-2">
          {decision && (
            <div className="space-y-6 text-sm">
              <SnapshotPanel label={c.beforeAfterSnapshot.split(" / ")[0]} memories={decision.before_state ?? []} noSnapshotLabel={c.noSnapshotRecorded} statusLabel={c.statusLabel} importanceLabel={c.importanceLabel} />
              <SnapshotPanel label={c.beforeAfterSnapshot.split(" / ")[1]} memories={decision.after_state ?? []} noSnapshotLabel={c.noSnapshotRecorded} statusLabel={c.statusLabel} importanceLabel={c.importanceLabel} />
            </div>
          )}
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}

// ---------------------------------------------------------------------------
// Decision card
// ---------------------------------------------------------------------------
function DecisionCard({
  decision,
  onTrace,
  onSnapshot,
  c,
  locale,
}: {
  decision: GovernanceDecision;
  onTrace: () => void;
  onSnapshot: () => void;
  c: ReturnType<typeof useI18n>["messages"]["governance"]["cockpit"];
  locale: "en" | "zh";
}) {
  return (
    <div className="rounded-lg border border-zinc-700/60 bg-zinc-800/40 p-3 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium text-zinc-100 leading-snug line-clamp-2">
          {decisionTitle(decision)}
        </p>
        <Badge
          variant="outline"
          className={`shrink-0 text-[10px] px-1.5 py-0 ${confidenceTone(decision.llm_confidence)}`}
        >
          {Math.round(decision.llm_confidence * 100)}%
        </Badge>
      </div>

      <p className="text-xs text-zinc-400 line-clamp-2">{decisionSummary(decision)}</p>

      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant="outline" className={`text-[10px] px-1.5 py-0 ${riskTone(decision.risk_level)}`}>
          {c.riskSuffix(decision.risk_level)}
        </Badge>
        <Badge variant="outline" className="text-[10px] px-1.5 py-0 border-zinc-600 text-zinc-400">
          {titleCase(decision.decision_type)}
        </Badge>
        <span className="ml-auto text-[10px] text-zinc-500">
          {formatGovernanceDate(decision.created_at, locale)}
        </span>
      </div>

      <div className="flex gap-2 pt-1">
        <Button
          size="sm"
          variant="ghost"
          className="h-6 text-[11px] px-2 text-zinc-400 hover:text-zinc-100"
          onClick={onTrace}
        >
          {c.judgeTrace}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 text-[11px] px-2 text-zinc-400 hover:text-zinc-100"
          onClick={onSnapshot}
        >
          {c.snapshot}
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Zone container
// ---------------------------------------------------------------------------
function Zone({
  title,
  icon,
  count,
  accent,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  count: number;
  accent: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col rounded-xl border border-zinc-700/50 bg-zinc-900/60 overflow-hidden">
      <div className={`flex items-center gap-2 px-4 py-3 border-b border-zinc-700/50 ${accent}`}>
        {icon}
        <span className="text-sm font-semibold">{title}</span>
        <Badge variant="secondary" className="ml-auto text-[11px] h-5 px-1.5">
          {count}
        </Badge>
      </div>
      <ScrollArea className="flex-1 max-h-72 p-3">
        <div className="space-y-2">{children}</div>
      </ScrollArea>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Health metrics zone
// ---------------------------------------------------------------------------
function MetricsZone({
  metrics,
  c,
}: {
  metrics: GovernanceMetrics | null;
  c: ReturnType<typeof useI18n>["messages"]["governance"]["cockpit"];
}) {
  if (!metrics) {
    return (
      <div className="flex flex-col rounded-xl border border-zinc-700/50 bg-zinc-900/60 overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-zinc-700/50 text-zinc-300">
          <ShieldCheck className="h-4 w-4 text-sky-400" />
          <span className="text-sm font-semibold">{c.zoneHealthMetrics}</span>
        </div>
        <div className="p-4 text-xs text-zinc-500 italic">{c.metricsUnavailable}</div>
      </div>
    );
  }

  return (
    <div className="flex flex-col rounded-xl border border-zinc-700/50 bg-zinc-900/60 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-zinc-700/50 text-zinc-300">
        <ShieldCheck className="h-4 w-4 text-sky-400" />
        <span className="text-sm font-semibold">{c.zoneHealthMetrics}</span>
        <Badge
          variant="outline"
          className={`ml-auto text-[10px] px-1.5 py-0 ${
            metrics.auto_supersede_enabled
              ? "border-emerald-700 bg-emerald-500/10 text-emerald-300"
              : "border-zinc-600 bg-zinc-800 text-zinc-400"
          }`}
        >
          {c.autoSupersede(metrics.auto_supersede_enabled)}
        </Badge>
      </div>
      <div className="grid grid-cols-2 gap-3 p-4">
        <Metric label={c.applied} value={String(metrics.applied_count)} />
        <Metric label={c.rolledBack} value={String(metrics.rolled_back_count)} warn={metrics.rolled_back_count > 0} />
        <Metric label={c.rollbackRate} value={formatPercent(metrics.rollback_rate)} warn={metrics.rollback_rate > 0.1} />
        <Metric label={c.revivalRate} value={formatPercent(metrics.revival_rate)} warn={metrics.revival_rate > 0.05} />
        <Metric label={c.reviewQueue} value={String(metrics.needs_review_count)} warn={metrics.needs_review_count > 10} />
        <Metric
          label={c.queueAge}
          value={metrics.review_queue_age_hours > 0 ? metrics.review_queue_age_hours.toFixed(1) : "—"}
          warn={metrics.review_queue_age_hours > 24}
        />
      </div>
      {Object.keys(metrics.rejection_rate_by_type).length > 0 && (
        <div className="border-t border-zinc-800 px-4 py-3">
          <p className="text-[10px] uppercase tracking-wide text-zinc-500 mb-2">{c.rejectionRateByType}</p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(metrics.rejection_rate_by_type).map(([dtype, rate]) => (
              <Badge
                key={dtype}
                variant="outline"
                className="text-[10px] px-1.5 border-zinc-700 text-zinc-400"
              >
                {titleCase(dtype)}: {formatPercent(rate)}
              </Badge>
            ))}
          </div>
        </div>
      )}
      <div className="border-t border-zinc-800 px-4 py-2">
        <p className="text-[10px] text-zinc-600">{c.policyVersionLabel(metrics.policy_version)}</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Timeline / Audit zone
// ---------------------------------------------------------------------------
function AuditZone({
  auditLog,
  c,
  locale,
}: {
  auditLog: AuditEvent[];
  c: ReturnType<typeof useI18n>["messages"]["governance"]["cockpit"];
  locale: "en" | "zh";
}) {
  return (
    <div className="flex flex-col rounded-xl border border-zinc-700/50 bg-zinc-900/60 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-zinc-700/50 text-zinc-300">
        <Clock className="h-4 w-4 text-zinc-400" />
        <span className="text-sm font-semibold">{c.zoneTimeline}</span>
        <Badge variant="secondary" className="ml-auto text-[11px] h-5 px-1.5">
          {auditLog.length}
        </Badge>
      </div>
      <ScrollArea className="flex-1 max-h-72 p-3">
        {auditLog.length === 0 ? (
          <EmptyState label={c.noAuditEvents} />
        ) : (
          <div className="space-y-1">
            {auditLog.map((event, i) => (
              <div
                key={event.id ?? i}
                className="flex items-start gap-2 text-[11px] py-1.5 border-b border-zinc-800 last:border-0"
              >
                <span className="text-zinc-500 shrink-0 w-[130px]">
                  {formatGovernanceDate(event.created_at, locale)}
                </span>
                <span className="text-zinc-400 shrink-0 font-mono">{event.event_type ?? "—"}</span>
                <span className="text-zinc-500 truncate">{event.agent ?? ""}</span>
              </div>
            ))}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function EmptyState({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-8 text-zinc-600 gap-2">
      <CheckCircle2 className="h-6 w-6" />
      <span className="text-xs">{label}</span>
    </div>
  );
}

function Row({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</p>
      <p className={`text-zinc-200 break-all ${mono ? "font-mono text-[11px]" : ""}`}>{value || "—"}</p>
    </div>
  );
}

function Section({ label, content, mono = false }: { label: string; content: string; mono?: boolean }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1">{label}</p>
      <pre
        className={`whitespace-pre-wrap break-all rounded bg-zinc-800 p-2 text-zinc-300 text-[11px] leading-relaxed ${
          mono ? "font-mono" : "font-sans"
        }`}
      >
        {content}
      </pre>
    </div>
  );
}

function SnapshotPanel({
  label,
  memories,
  noSnapshotLabel,
  statusLabel,
  importanceLabel,
}: {
  label: string;
  memories: Array<{ id?: string; title?: string; content?: string; status?: string; importance?: number }>;
  noSnapshotLabel: string;
  statusLabel: string;
  importanceLabel: string;
}) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-zinc-500 mb-2">{label}</p>
      {memories.length === 0 ? (
        <p className="text-zinc-600 text-xs italic">{noSnapshotLabel}</p>
      ) : (
        <div className="space-y-2">
          {memories.map((m, i) => (
            <div key={m.id ?? i} className="rounded bg-zinc-800 p-2 space-y-1">
              <p className="text-zinc-200 text-[11px] font-medium">{m.title || m.id}</p>
              {m.content && (
                <p className="text-zinc-400 text-[11px] line-clamp-3">{m.content}</p>
              )}
              <div className="flex gap-2 text-[10px] text-zinc-500">
                {m.status && <span>{statusLabel} {m.status}</span>}
                {typeof m.importance === "number" && <span>{importanceLabel} {m.importance}</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, warn = false }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="rounded-lg bg-zinc-800/50 p-3">
      <p className="text-[10px] text-zinc-500 uppercase tracking-wide">{label}</p>
      <p className={`text-xl font-semibold mt-0.5 ${warn ? "text-amber-400" : "text-zinc-100"}`}>
        {value}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main cockpit
// ---------------------------------------------------------------------------
export function GovernanceCockpit() {
  const { applied, needsReview, auditLog, metrics, loading, error, refresh } = useGovernanceCockpit();
  const { messages, locale } = useI18n();
  const c = messages.governance.cockpit;
  const [traceDecision, setTraceDecision] = useState<GovernanceDecision | null>(null);
  const [snapshotDecision, setSnapshotDecision] = useState<GovernanceDecision | null>(null);

  const allClear = !loading && !error && applied.length === 0 && needsReview.length === 0;
  const degraded = metrics?.degraded_warning ?? false;

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-zinc-100">{c.title}</h1>
          <p className="text-sm text-zinc-400 mt-0.5">{c.subtitle}</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={refresh}
          disabled={loading}
          className="border-zinc-700/50 bg-zinc-900 hover:bg-zinc-800 disabled:opacity-60"
        >
          <RefreshCcw className={`h-3.5 w-3.5 mr-1.5 transition-transform duration-500 ${loading ? "animate-spin" : ""}`} />
          {loading ? c.loading : c.refresh}
        </Button>
      </div>

      {/* Degraded warning */}
      {degraded && (
        <div className="flex items-start gap-3 rounded-lg border border-amber-700/60 bg-amber-950/30 px-4 py-3 text-sm text-amber-300">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <div>
            <p className="font-medium">{c.automationDegraded}</p>
            <p className="text-xs text-amber-400/80 mt-0.5">{c.automationDegradedDetail}</p>
          </div>
        </div>
      )}

      {/* Error banner */}
      {error && (
        <div className="rounded-lg border border-red-800/60 bg-red-950/30 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* All-clear empty state */}
      {allClear && (
        <div className="flex flex-col items-center justify-center py-20 gap-3 text-zinc-500">
          <CheckCircle2 className="h-10 w-10 text-emerald-500" />
          <p className="text-base font-medium text-zinc-300">{c.allClear}</p>
          <p className="text-sm">{c.allClearDetail}</p>
        </div>
      )}

      {/* Four-zone grid */}
      {!allClear && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Zone 1: Needs Review */}
          <Zone
            title={c.zoneNeedsReview}
            icon={<ShieldAlert className="h-4 w-4 text-amber-400" />}
            count={needsReview.length}
            accent="text-amber-300"
          >
            {needsReview.length === 0 ? (
              <EmptyState label={c.reviewQueueEmpty} />
            ) : (
              needsReview.map((d) => (
                <DecisionCard
                  key={d.id}
                  decision={d}
                  onTrace={() => setTraceDecision(d)}
                  onSnapshot={() => setSnapshotDecision(d)}
                  c={c}
                  locale={locale}
                />
              ))
            )}
          </Zone>

          {/* Zone 2: Auto-Applied */}
          <Zone
            title={c.zoneAutoApplied}
            icon={<CheckCircle2 className="h-4 w-4 text-emerald-400" />}
            count={applied.length}
            accent="text-emerald-300"
          >
            {applied.length === 0 ? (
              <EmptyState label={c.noAutoApplied} />
            ) : (
              applied.map((d) => (
                <DecisionCard
                  key={d.id}
                  decision={d}
                  onTrace={() => setTraceDecision(d)}
                  onSnapshot={() => setSnapshotDecision(d)}
                  c={c}
                  locale={locale}
                />
              ))
            )}
          </Zone>

          {/* Zone 3: Health Metrics */}
          <MetricsZone metrics={metrics} c={c} />

          {/* Zone 4: Timeline / Audit */}
          <AuditZone auditLog={auditLog} c={c} locale={locale} />
        </div>
      )}

      {/* Drawers */}
      <JudgeTraceDrawer decision={traceDecision} onClose={() => setTraceDecision(null)} c={c} locale={locale} />
      <SnapshotDrawer decision={snapshotDecision} onClose={() => setSnapshotDecision(null)} c={c} />
    </div>
  );
}
