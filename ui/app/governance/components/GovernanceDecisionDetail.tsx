"use client";

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
import { Textarea } from "@/components/ui/textarea";
import type { AuditEvent, GovernanceDecision, LineagePayload } from "@/components/dashboard/intelligence/types";
import {
  canApplyDecision,
  canRollbackDecision,
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

interface GovernanceDecisionDetailProps {
  decision: GovernanceDecision | null;
  lineage: LineagePayload | null;
  auditEvents: AuditEvent[];
  isDetailLoading: boolean;
  actionPendingId: string | null;
  messages: Messages["governance"];
  onApply: (decisionId: string) => Promise<void>;
  onReject: (decisionId: string, reason: string) => Promise<void>;
  onRollback: (decisionId: string) => Promise<void>;
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
      <CardHeader>
        <CardTitle className="text-base text-white">{messages.lineage}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm text-zinc-400">
        {lineage ? (
          <>
            <div className="grid gap-2 text-xs text-zinc-500 sm:grid-cols-2">
              <span>{messages.root}: {lineage.root_id || "n/a"}</span>
              <span>{messages.currentHead}: {lineage.current_head_id || "n/a"}</span>
            </div>
            <div className="space-y-2">
              {chain.map((record) => (
                <div key={record.id} className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-white">{record.title || record.id}</span>
                    {record.status ? <Badge className={reviewStatusTone(record.status)}>{titleCase(record.status)}</Badge> : null}
                  </div>
                  {record.superseded_by ? <p className="mt-1 text-xs text-zinc-500">Superseded by {record.superseded_by}</p> : null}
                </div>
              ))}
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
      <CardHeader>
        <CardTitle className="text-base text-white">{messages.auditTrail}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {auditEvents.length ? auditEvents.map((event, index) => (
          <div key={event.id || `${event.event_type}-${index}`} className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="font-medium text-white">{event.event_type || "audit_event"}</span>
              <span className="text-xs text-zinc-500">{formatGovernanceDate(event.created_at)}</span>
            </div>
            {event.agent ? <p className="mt-1 text-xs text-zinc-500">{event.agent}</p> : null}
          </div>
        )) : (
          <div className="rounded-lg border border-dashed border-zinc-800 p-4 text-sm text-zinc-500">{messages.noAudit}</div>
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
  label,
  title,
  description,
  disabled,
  variant = "default",
  cancelLabel,
  onConfirm,
}: ConfirmActionButtonProps) {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button disabled={disabled} variant={variant}>{label}</Button>
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
          <AlertDialogAction onClick={() => void onConfirm()}>{label}</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export function GovernanceDecisionDetail({
  decision,
  lineage,
  auditEvents,
  isDetailLoading,
  actionPendingId,
  messages,
  onApply,
  onReject,
  onRollback,
}: GovernanceDecisionDetailProps) {
  const [rejectReason, setRejectReason] = useState("");

  if (!decision) {
    return (
      <Card className="border-zinc-800 bg-zinc-950/80">
        <CardContent className="p-8 text-sm text-zinc-400">{messages.selectDecision}</CardContent>
      </Card>
    );
  }

  const isPending = actionPendingId === decision.id;
  const normalizedRejectReason = rejectReason.trim() || messages.defaultRejectReason;

  return (
    <div className="space-y-4">
      <Card className="border-zinc-800 bg-zinc-950/80">
        <CardHeader className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge className={reviewStatusTone(decision.review_status)}>{titleCase(decision.review_status)}</Badge>
            <Badge className={riskTone(decision.risk_level)}>{titleCase(decision.risk_level)}</Badge>
            <Badge variant="outline" className="border-zinc-700 text-zinc-300">
              {messages.confidence}: {formatPercent(decision.llm_confidence)}
            </Badge>
          </div>
          <CardTitle className="text-xl text-white">{decisionTitle(decision)}</CardTitle>
          <p className="text-sm text-zinc-400">{decisionSummary(decision)}</p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 text-sm text-zinc-400 md:grid-cols-2">
            <span>{messages.recommendedAction}: {titleCase(decision.recommended_action)}</span>
            <span>{messages.created}: {formatGovernanceDate(decision.created_at)}</span>
            <span>{messages.policyReason}: {decision.policy_reason || "n/a"}</span>
            <span>{messages.sourceMemories}: {decision.source_ids?.join(", ") || "n/a"}</span>
          </div>

          <div className="flex flex-col gap-3 rounded-lg border border-zinc-800 bg-zinc-950/70 p-3">
            <label className="text-sm font-medium text-zinc-300" htmlFor="reject-reason">{messages.rejectionReason}</label>
            <Textarea
              id="reject-reason"
              value={rejectReason}
              onChange={(event) => setRejectReason(event.target.value)}
              placeholder={messages.defaultRejectReason}
              className="border-zinc-800 bg-zinc-950 text-zinc-200"
            />
            <div className="flex flex-wrap gap-2">
              {canApplyDecision(decision) ? (
                <ConfirmActionButton
                  label={messages.apply}
                  title={messages.confirmApplyTitle}
                  description={messages.confirmApplyDescription(decision.id)}
                  disabled={isPending}
                  cancelLabel={messages.cancel}
                  onConfirm={() => onApply(decision.id)}
                />
              ) : null}
              {canApplyDecision(decision) ? (
                <ConfirmActionButton
                  label={messages.reject}
                  title={messages.confirmRejectTitle}
                  description={messages.confirmRejectDescription(decision.id)}
                  disabled={isPending}
                  cancelLabel={messages.cancel}
                  variant="outline"
                  onConfirm={() => onReject(decision.id, normalizedRejectReason)}
                />
              ) : null}
              {canRollbackDecision(decision) ? (
                <ConfirmActionButton
                  label={messages.rollback}
                  title={messages.confirmRollbackTitle}
                  description={messages.confirmRollbackDescription(decision.id)}
                  disabled={isPending}
                  cancelLabel={messages.cancel}
                  variant="destructive"
                  onConfirm={() => onRollback(decision.id)}
                />
              ) : null}
            </div>
          </div>
        </CardContent>
      </Card>

      <MemorySnapshotCompare beforeState={decision.before_state} afterState={decision.after_state} messages={messages} />

      <Card className="border-zinc-800 bg-zinc-950/70">
        <CardHeader>
          <CardTitle className="text-base text-white">{messages.llmTrace}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <JsonBlock value={decision.llm_trace} />
          <JsonBlock value={decision.finding} />
        </CardContent>
      </Card>

      {isDetailLoading ? (
        <div className="rounded-lg border border-zinc-800 bg-zinc-950/70 p-4 text-sm text-zinc-400">{messages.loading}</div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          <LineagePanel lineage={lineage} messages={messages} />
          <AuditPanel auditEvents={auditEvents} messages={messages} />
        </div>
      )}
    </div>
  );
}
