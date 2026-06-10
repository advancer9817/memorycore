"use client";

import { RefreshCcw } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useGovernanceCockpit } from "@/hooks/useGovernanceCockpit";
import { useI18n } from "@/hooks/useI18n";
import type { GovernanceReviewStatus } from "@/components/dashboard/intelligence/types";
import { GovernanceDecisionDetail } from "./components/GovernanceDecisionDetail";
import { GovernanceDecisionQueue } from "./components/GovernanceDecisionQueue";
import { GovernanceMetricsCards } from "./components/GovernanceMetricsCards";

const REVIEW_STATUSES: GovernanceReviewStatus[] = ["all", "needs_review", "auto_approved", "applied", "rejected", "rolled_back"];

export default function GovernancePage() {
  const { messages } = useI18n();
  const cockpit = useGovernanceCockpit();

  return (
    <main className="container mx-auto space-y-6 px-4 py-8">
      <section className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-2">
          <p className="text-sm font-medium uppercase tracking-[0.3em] text-violet-300">{messages.nav.governance}</p>
          <h1 className="text-3xl font-semibold text-white">{messages.governance.title}</h1>
          <p className="max-w-3xl text-sm text-zinc-400">{messages.governance.description}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Select value={cockpit.reviewStatus} onValueChange={(value) => cockpit.setReviewStatus(value as GovernanceReviewStatus)}>
            <SelectTrigger className="w-[190px] border-zinc-800 bg-zinc-950 text-zinc-200">
              <SelectValue aria-label={messages.common.filter} />
            </SelectTrigger>
            <SelectContent>
              {REVIEW_STATUSES.map((status) => (
                <SelectItem key={status} value={status}>{messages.governance.statusLabels[status]}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            onClick={() => void cockpit.refresh()}
            disabled={cockpit.isLoading}
            className="border-zinc-700 bg-zinc-950 text-zinc-200 hover:bg-zinc-900"
          >
            <RefreshCcw className={`mr-2 h-4 w-4 ${cockpit.isLoading ? "animate-spin" : ""}`} />
            {messages.nav.refresh}
          </Button>
        </div>
      </section>

      {cockpit.error ? (
        <Alert className="border-red-800 bg-red-950/30 text-red-200">
          <AlertDescription>{cockpit.error}</AlertDescription>
        </Alert>
      ) : null}

      <GovernanceMetricsCards metrics={cockpit.metrics} messages={messages.governance} />

      <section className="grid gap-6 xl:grid-cols-[minmax(320px,420px)_1fr]">
        <GovernanceDecisionQueue
          decisions={cockpit.decisions}
          selectedDecisionId={cockpit.selectedDecision?.id}
          messages={messages.governance}
          onSelect={cockpit.selectDecision}
        />
        <GovernanceDecisionDetail
          decision={cockpit.selectedDecision}
          lineage={cockpit.lineage}
          auditEvents={cockpit.auditEvents}
          isDetailLoading={cockpit.isDetailLoading}
          actionPendingId={cockpit.actionPendingId}
          messages={messages.governance}
          onApply={cockpit.applyDecision}
          onReject={cockpit.rejectDecision}
          onRollback={cockpit.rollbackDecision}
        />
      </section>
    </main>
  );
}
