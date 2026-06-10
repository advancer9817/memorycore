"use client";

import { useState, useCallback } from "react";
import { RefreshCcw } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useGovernanceCockpit } from "@/hooks/useGovernanceCockpit";
import { useI18n } from "@/hooks/useI18n";
import { useToast } from "@/hooks/use-toast";
import type { GovernanceReviewStatus } from "@/components/dashboard/intelligence/types";
import { GovernanceDecisionSheet } from "./components/GovernanceDecisionSheet";
import { GovernanceTable } from "./components/GovernanceTable";
import { GovernanceMetricsCards } from "./components/GovernanceMetricsCards";

const REVIEW_STATUSES: GovernanceReviewStatus[] = [
  "all", "needs_review", "auto_approved", "applied", "rejected", "rolled_back",
];

const PAGE_SIZE = 20;

export default function GovernancePage() {
  const { messages } = useI18n();
  const { toast } = useToast();
  const cockpit = useGovernanceCockpit();

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(0);
  const [batchPending, setBatchPending] = useState(false);

  const totalPages = Math.max(1, Math.ceil(cockpit.decisions.length / PAGE_SIZE));
  const paginated = cockpit.decisions.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    setSelectedIds((prev) => {
      const pageIds = paginated.map((d) => d.id);
      const allSelected = pageIds.every((id) => prev.has(id));
      const next = new Set(prev);
      if (allSelected) {
        pageIds.forEach((id) => next.delete(id));
      } else {
        pageIds.forEach((id) => next.add(id));
      }
      return next;
    });
  }, [paginated]);

  const runBatch = useCallback(async (action: "apply" | "reject") => {
    const ids = Array.from(selectedIds);
    if (!ids.length) return;
    setBatchPending(true);
    let successCount = 0;
    const reason = messages.governance.defaultRejectReason;
    for (const id of ids) {
      try {
        if (action === "apply") {
          await cockpit.applyDecision(id);
        } else {
          await cockpit.rejectDecision(id, reason);
        }
        successCount++;
      } catch {
        // individual failures handled by the hook's toast
      }
    }
    setBatchPending(false);
    setSelectedIds(new Set());
    if (successCount > 0) {
      const actionLabel = action === "apply" ? messages.governance.apply : messages.governance.reject;
      toast({ description: messages.governance.batchSuccess(successCount, actionLabel) });
    }
    await cockpit.refresh();
  }, [selectedIds, cockpit, messages.governance, toast]);

  return (
    <div className="text-white py-6">
      <div className="container">
        {/* Header */}
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-1">
            <p className="text-xs font-medium uppercase tracking-[0.3em] text-violet-300">
              {messages.nav.governance}
            </p>
            <h1 className="text-2xl font-semibold">{messages.governance.title}</h1>
            <p className="text-sm text-zinc-500">{messages.governance.description}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {selectedIds.size > 0 && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" className="border-zinc-700/50 bg-zinc-900 hover:bg-zinc-800">
                    {messages.common.actions} ({messages.governance.selected(selectedIds.size)})
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="bg-zinc-900 border-zinc-800">
                  <DropdownMenuItem
                    disabled={batchPending}
                    onClick={() => void runBatch("apply")}
                  >
                    {messages.governance.batchApply}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    disabled={batchPending}
                    onClick={() => void runBatch("reject")}
                    className="text-red-500 focus:text-red-500"
                  >
                    {messages.governance.batchReject}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
            <Select
              value={cockpit.reviewStatus}
              onValueChange={(v) => {
                cockpit.setReviewStatus(v as GovernanceReviewStatus);
                setPage(0);
                setSelectedIds(new Set());
              }}
            >
              <SelectTrigger className="w-[170px] border-zinc-700/50 bg-zinc-900 text-zinc-200">
                <SelectValue aria-label={messages.common.filter} />
              </SelectTrigger>
              <SelectContent>
                {REVIEW_STATUSES.map((s) => (
                  <SelectItem key={s} value={s}>{messages.governance.statusLabels[s]}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              variant="outline"
              onClick={() => void cockpit.refresh()}
              disabled={cockpit.isLoading}
              className="border-zinc-700/50 bg-zinc-900 text-zinc-200 hover:bg-zinc-800"
            >
              <RefreshCcw className={`mr-2 h-4 w-4 ${cockpit.isLoading ? "animate-spin" : ""}`} />
              {messages.nav.refresh}
            </Button>
          </div>
        </div>

        {cockpit.error && (
          <Alert className="mt-4 border-red-800 bg-red-950/30 text-red-200">
            <AlertDescription>{cockpit.error}</AlertDescription>
          </Alert>
        )}

        {/* Metrics */}
        <div className="mt-6">
          <GovernanceMetricsCards metrics={cockpit.metrics} messages={messages.governance} />
        </div>

        {/* Table */}
        <div className="mt-6">
          <GovernanceTable
            decisions={paginated}
            selectedIds={selectedIds}
            onToggleSelect={toggleSelect}
            onToggleSelectAll={toggleSelectAll}
            onRowClick={cockpit.selectDecision}
            messages={messages.governance}
            isLoading={cockpit.isLoading}
          />
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="mt-4 flex items-center justify-between">
            <div className="text-sm text-zinc-500">
              {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, cockpit.decisions.length)} / {cockpit.decisions.length}
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page === 0}
                onClick={() => setPage((p) => p - 1)}
                className="border-zinc-700/50 bg-zinc-900 text-zinc-200"
              >
                {messages.governance.previousPage}
              </Button>
              <span className="text-sm text-zinc-500">{page + 1} / {totalPages}</span>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= totalPages - 1}
                onClick={() => setPage((p) => p + 1)}
                className="border-zinc-700/50 bg-zinc-900 text-zinc-200"
              >
                {messages.governance.nextPage}
              </Button>
            </div>
          </div>
        )}

        {/* Detail Sheet */}
        <GovernanceDecisionSheet
          decision={cockpit.selectedDecision}
          lineage={cockpit.lineage}
          auditEvents={cockpit.auditEvents}
          isDetailLoading={cockpit.isDetailLoading}
          actionPendingId={cockpit.actionPendingId}
          messages={messages.governance}
          onClose={() => cockpit.selectDecision(null)}
          onApply={cockpit.applyDecision}
          onReject={cockpit.rejectDecision}
          onRollback={cockpit.rollbackDecision}
        />
      </div>
    </div>
  );
}
