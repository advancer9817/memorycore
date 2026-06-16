"use client";

import Link from "next/link";
import { useState } from "react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import type { AuditEvent, GovernanceDecision, LineagePayload } from "@/components/dashboard/intelligence/types";
import {
  canApplyDecision,
  decisionSummary,
  decisionTitle,
  formatGovernanceDate,
  formatPercent,
  reviewStatusTone,
  riskTone,
  titleCase,
} from "@/components/dashboard/intelligence/utils";
import type { Messages } from "@/lib/i18n/types";
import { MemorySnapshotCompare } from "./MemorySnapshotCompare";
import { DecisionOverviewPanel } from "./DecisionOverviewPanel";

interface GovernanceDecisionSheetProps {
  decision: GovernanceDecision | null;
  lineage: LineagePayload | null;
  auditEvents: AuditEvent[];
  isDetailLoading: boolean;
  actionPendingId: string | null;
  messages: Messages["governance"];
  onClose: () => void;
  onApply: (decisionId: string) => Promise<void>;
  onReject: (decisionId: string, reason: string) => Promise<void>;
}

function JsonBlock({ value }: { value: Record<string, unknown> | undefined }) {
  if (!value || !Object.keys(value).length) {
    return <div className="rounded-lg border border-dashed border-zinc-800 p-4 text-sm text-zinc-500">n/a</div>;
  }
  return (
    <pre className="max-h-64 overflow-auto rounded-lg border border-zinc-800 bg-black/40 p-3 text-xs text-zinc-300">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function LineagePanel({ lineage, messages }: { lineage: LineagePayload | null; messages: Messages["governance"] }) {
  const chain = lineage?.chain?.length ? lineage.chain : lineage?.records ?? [];
  return (
    <Card className="border-zinc-800 bg-zinc-950/70">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium text-zinc-300">{messages.lineage}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm text-zinc-400">
        {lineage ? (
          <>
            <div className="grid gap-1 text-xs text-zinc-500 sm:grid-cols-2">
              <span>{messages.root}: {lineage.root_id || messages.notAvailable}</span>
              <span>{messages.currentHead}: {lineage.current_head_id || messages.notAvailable}</span>
            </div>
            <div className="flex flex-col">
              {chain.map((record, index) => {
                const isRoot = index === 0 || record.id === lineage.root_id;
                const isHead = record.id === lineage.current_head_id;
                const isSuperseded = !!record.superseded_by;
                return (
                  <div key={record.id} className="flex flex-col">
                    <div className={`rounded-lg border p-3 ${isHead ? "border-emerald-700 bg-emerald-950/30" : "border-zinc-800 bg-zinc-950"}`}>
                      <div className="flex flex-wrap items-center gap-2">
                        {isRoot && (
                          <span className="text-xs font-semibold text-zinc-500 uppercase tracking-wide">Root</span>
                        )}
                        {isHead && (
                          <span className="text-xs font-semibold text-emerald-400 uppercase tracking-wide">Head</span>
                        )}
                        <span className={`text-sm font-medium truncate ${isSuperseded ? "text-zinc-500" : "text-white"}`}>
                          {record.title || record.id}
                        </span>
                        {record.status ? (
                          <Badge className={reviewStatusTone(record.status)}>{titleCase(record.status)}</Badge>
                        ) : null}
                      </div>
                      {record.superseded_by ? (
                        <p className="mt-1 text-xs text-zinc-500">{messages.supersededBy} {record.superseded_by}</p>
                      ) : null}
                    </div>
                    {index < chain.length - 1 && (
                      <div className="flex justify-center py-1 text-zinc-600 text-xs select-none">↓</div>
                    )}
                  </div>
                );
              })}
            </div>
          </>
        ) : (
          <div className="rounded-lg border border-dashed border-zinc-800 p-4">{messages.noLineage}</div>
        )}
      </CardContent>
    </Card>
  );
}

function AuditPanel({ auditEvents, messages }: { auditEvents: AuditEvent[]; messages: Messages["governance"] }) {
  return (
    <Card className="border-zinc-800 bg-zinc-950/70">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium text-zinc-300">{messages.auditTrail}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {auditEvents.length ? (
          auditEvents.map((event, i) => (
            <div key={event.id || `${event.event_type}-${i}`} className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span className="font-medium text-white">{event.event_type || "audit_event"}</span>
                <span className="text-xs text-zinc-500">{formatGovernanceDate(event.created_at)}</span>
              </div>
              {event.agent ? <p className="mt-1 text-xs text-zinc-500">{event.agent}</p> : null}
            </div>
          ))
        ) : (
          <div className="rounded-lg border border-dashed border-zinc-800 p-4 text-sm text-zinc-500">
            {messages.noAudit}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

interface ConfirmActionButtonProps {
  label: string;
  title: string;
  description: string;
  disabled: boolean;
  variant?: "default" | "outline" | "destructive";
  cancelLabel: string;
  onConfirm: () => Promise<void>;
}

function ConfirmActionButton({
  label, title, description, disabled, variant = "default", cancelLabel, onConfirm,
}: ConfirmActionButtonProps) {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button disabled={disabled} variant={variant} size="sm">{label}</Button>
      </AlertDialogTrigger>
      <AlertDialogContent className="border-zinc-800 bg-zinc-950 text-zinc-100">
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription className="text-zinc-400">{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel className="border-zinc-700 bg-zinc-900 text-zinc-200 hover:bg-zinc-800">
            {cancelLabel}
          </AlertDialogCancel>
          <AlertDialogAction onClick={() => void onConfirm().catch(() => undefined)}>{label}</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export function GovernanceDecisionSheet({
  decision,
  lineage,
  auditEvents,
  isDetailLoading,
  actionPendingId,
  messages,
  onClose,
  onApply,
  onReject,
}: GovernanceDecisionSheetProps) {
  const [rejectReason, setRejectReason] = useState("");

  const isPending = actionPendingId === decision?.id;
  const canApply = decision ? canApplyDecision(decision) : false;
  const showActions = canApply;
  const normalizedRejectReason = rejectReason.trim() || messages.defaultRejectReason;
  const primarySourceId = decision?.source_ids?.[0] || decision?.before_state?.[0]?.id || decision?.after_state?.[0]?.id || "";

  return (
    <Sheet open={!!decision} onOpenChange={(open) => !open && onClose()}>
      <SheetContent
        side="right"
        className="w-full overflow-y-auto border-zinc-800 bg-zinc-950 text-zinc-100 sm:max-w-2xl"
      >
        {decision && (
          <>
            <SheetHeader className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge className={reviewStatusTone(decision.review_status)}>
                  {titleCase(decision.review_status)}
                </Badge>
                <Badge className={riskTone(decision.risk_level)}>
                  {titleCase(decision.risk_level)}
                </Badge>
                <Badge variant="outline" className="border-zinc-700 text-zinc-300">
                  {messages.confidence}: {formatPercent(decision.llm_confidence)}
                </Badge>
              </div>
              <SheetTitle className="text-lg text-white">{decisionTitle(decision)}</SheetTitle>
              <p className="text-sm text-zinc-400">{decisionSummary(decision)}</p>
            </SheetHeader>

            {/* Metadata */}
            <div className="mt-4 grid gap-1 text-xs text-zinc-500 sm:grid-cols-2">
              <span>{messages.recommendedAction}: <span className="text-zinc-300">{messages.actionLabels[decision.recommended_action] ?? titleCase(decision.recommended_action)}</span></span>
              <span>{messages.created}: <span className="text-zinc-300">{formatGovernanceDate(decision.created_at)}</span></span>
              <span>{messages.policyReason}: <span className="text-zinc-300">{messages.policyReasonLabels[decision.policy_reason] ?? (decision.policy_reason || messages.notAvailable)}</span></span>
              <span className="break-all">{messages.sourceMemories}: <span className="text-zinc-300">{decision.source_ids?.join(", ") || messages.notAvailable}</span></span>
            </div>
            {primarySourceId ? (
              <div className="mt-3">
                <Button asChild variant="outline" size="sm" className="border-zinc-700 bg-zinc-900 text-zinc-200 hover:bg-zinc-800">
                  <Link href={`/memory/${encodeURIComponent(primarySourceId)}`}>{messages.openSourceMemory}</Link>
                </Button>
              </div>
            ) : null}

            {/* Actions */}
            {showActions && (
              <div className="mt-4 rounded-lg border border-zinc-800 bg-zinc-950/60 p-3 space-y-2">
                {canApply && (
                  <>
                    <label className="text-xs font-medium text-zinc-400" htmlFor="sheet-reject-reason">
                      {messages.rejectionReason}
                    </label>
                    <Textarea
                      id="sheet-reject-reason"
                      value={rejectReason}
                      onChange={(e) => setRejectReason(e.target.value)}
                      placeholder={messages.defaultRejectReason}
                      rows={2}
                      className="border-zinc-800 bg-zinc-950 text-sm text-zinc-200"
                    />
                  </>
                )}
                <div className="flex flex-wrap gap-2">
                  {canApply && (
                    <ConfirmActionButton
                      label={messages.apply}
                      title={messages.confirmApplyTitle}
                      description={messages.confirmApplyDescription(decision.id)}
                      disabled={isPending}
                      cancelLabel={messages.cancel}
                      onConfirm={() => onApply(decision.id)}
                    />
                  )}
                  {canApply && (
                    <ConfirmActionButton
                      label={messages.reject}
                      title={messages.confirmRejectTitle}
                      description={messages.confirmRejectDescription(decision.id)}
                      disabled={isPending}
                      cancelLabel={messages.cancel}
                      variant="outline"
                      onConfirm={() => onReject(decision.id, normalizedRejectReason)}
                    />
                  )}
                </div>
              </div>
            )}

            {/* Tabbed content */}
            <Tabs defaultValue="overview" className="mt-4">
              <TabsList className="bg-zinc-900/60">
                <TabsTrigger value="overview">{messages.tabOverview}</TabsTrigger>
                <TabsTrigger value="evidence">{messages.tabEvidence}</TabsTrigger>
                <TabsTrigger value="history">{messages.tabHistory}</TabsTrigger>
              </TabsList>

              <TabsContent value="overview" className="mt-3">
                <DecisionOverviewPanel decision={decision} messages={messages} />
              </TabsContent>

              <TabsContent value="evidence" className="mt-3">
                <Card className="border-zinc-800 bg-zinc-950/70">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm font-medium text-zinc-300">{messages.llmTrace}</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <JsonBlock value={decision.llm_trace} />
                    <JsonBlock value={decision.finding} />
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="history" className="mt-3 space-y-4">
                {isDetailLoading ? (
                  <div className="rounded-lg border border-zinc-800 bg-zinc-950/70 p-4 text-sm text-zinc-400">
                    {messages.loading}
                  </div>
                ) : (
                  <>
                    <LineagePanel lineage={lineage} messages={messages} />
                    <AuditPanel auditEvents={auditEvents} messages={messages} />
                  </>
                )}
              </TabsContent>
            </Tabs>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
