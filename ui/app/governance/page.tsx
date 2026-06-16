"use client";

import { useState, useCallback, useEffect, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { CheckCheck, Loader2 } from "lucide-react";
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
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useGovernanceCockpit } from "@/hooks/useGovernanceCockpit";
import { useI18n } from "@/hooks/useI18n";
import { useToast } from "@/hooks/use-toast";
import type { GovernanceReviewStatus } from "@/components/dashboard/intelligence/types";
import { isActionableDecision } from "@/components/dashboard/intelligence/utils";
import { GovernanceDecisionSheet } from "./components/GovernanceDecisionSheet";
import { GovernanceTable } from "./components/GovernanceTable";
import { GovernanceMetricsCards } from "./components/GovernanceMetricsCards";

const REVIEW_STATUSES: GovernanceReviewStatus[] = [
  "all", "needs_review", "actionable", "auto_approved", "applied", "rejected", "rolled_back",
];

interface DecisionTypeFilter {
  value: string;
  labelKey: "filterAll" | "filterContradictions" | "filterDuplicates" | "filterReassessments" | "filterSplits";
}

const DECISION_TYPE_FILTERS: DecisionTypeFilter[] = [
  { value: "", labelKey: "filterAll" },
  { value: "contradiction", labelKey: "filterContradictions" },
  { value: "semantic_duplicate", labelKey: "filterDuplicates" },
  { value: "importance_reassessment", labelKey: "filterReassessments" },
  { value: "split_candidate", labelKey: "filterSplits" },
];

const PAGE_SIZE = 20;

function GovernancePageInner() {
  const { messages } = useI18n();
  const { toast } = useToast();
  const cockpit = useGovernanceCockpit();
  const searchParams = useSearchParams();

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(0);
  const [batchPending, setBatchPending] = useState(false);
  const [jumpValue, setJumpValue] = useState("1");

  useEffect(() => {
    const initialType = searchParams.get("type") ?? "";
    cockpit.setDecisionType(initialType);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const totalPages = Math.max(1, Math.ceil(cockpit.decisions.length / PAGE_SIZE));
  const paginated = cockpit.decisions.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  useEffect(() => {
    const clampedPage = Math.min(page, Math.max(0, totalPages - 1));
    if (clampedPage !== page) setPage(clampedPage);
  }, [page, totalPages]);

  useEffect(() => {
    setJumpValue(String(page + 1));
  }, [page]);

  const allActionableCount = cockpit.decisions.filter(isActionableDecision).length;

  const handleJump = useCallback(() => {
    const n = parseInt(jumpValue, 10);
    if (Number.isFinite(n)) {
      setPage(Math.max(0, Math.min(n - 1, totalPages - 1)));
    }
  }, [jumpValue, totalPages]);

  const toggleSelect = useCallback((id: string) => {
    const decision = cockpit.decisions.find((item) => item.id === id);
    if (!decision || !isActionableDecision(decision)) return;
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, [cockpit.decisions]);

  const toggleSelectAll = useCallback(() => {
    setSelectedIds((prev) => {
      const pageIds = paginated.filter(isActionableDecision).map((d) => d.id);
      const allSelected = pageIds.length > 0 && pageIds.every((id) => prev.has(id));
      const next = new Set(prev);
      if (allSelected) {
        pageIds.forEach((id) => next.delete(id));
      } else {
        pageIds.forEach((id) => next.add(id));
      }
      return next;
    });
  }, [paginated]);

  const runBatch = useCallback(async (ids: string[], action: "apply" | "reject") => {
    if (!ids.length) return 0;
    if (action === "apply") {
      try {
        return await cockpit.applyBatchDecisions(ids);
      } catch {
        return 0;
      }
    }

    let successCount = 0;
    const reason = messages.governance.defaultRejectReason;
    for (const id of ids) {
      try {
        await cockpit.rejectDecisionOrThrow(id, reason);
        successCount++;
      } catch {
        // individual failures handled by the hook's toast
      }
    }
    return successCount;
  }, [cockpit, messages.governance.defaultRejectReason]);

  const runSelectedBatch = useCallback(async (action: "apply" | "reject") => {
    const ids = Array.from(selectedIds);
    if (!ids.length) return;
    setBatchPending(true);
    const successCount = await runBatch(ids, action);
    setBatchPending(false);
    setSelectedIds(new Set());
    if (successCount > 0) {
      const actionLabel = action === "apply" ? messages.governance.apply : messages.governance.reject;
      toast({ description: messages.governance.batchSuccess(successCount, actionLabel) });
    }
    await cockpit.refresh();
  }, [selectedIds, runBatch, messages.governance, toast, cockpit]);

  const runApproveAll = useCallback(async () => {
    const ids = cockpit.decisions.filter(isActionableDecision).map((d) => d.id);
    if (!ids.length) return;
    setBatchPending(true);
    const successCount = await runBatch(ids, "apply");
    setBatchPending(false);
    setSelectedIds(new Set());
    if (successCount > 0) {
      toast({ description: messages.governance.batchSuccess(successCount, messages.governance.apply) });
    }
    await cockpit.refresh();
  }, [cockpit, runBatch, messages.governance, toast]);

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

          {/* Controls */}
          <div className="flex flex-wrap items-center justify-end gap-2">
            {/* Filters group — always on one line */}
            <div className="flex shrink-0 items-center gap-2">
              {/* Decision type filter pills */}
              <div className="flex items-center gap-1 rounded-lg border border-zinc-800 p-1">
                {DECISION_TYPE_FILTERS.map((filter) => (
                  <button
                    key={filter.value}
                    type="button"
                    onClick={() => {
                      cockpit.setDecisionType(filter.value);
                      setPage(0);
                      setSelectedIds(new Set());
                    }}
                    className={`rounded-md px-2 py-1 text-xs transition-colors ${
                      cockpit.decisionType === filter.value
                        ? "bg-zinc-700 text-white"
                        : "bg-zinc-900 text-zinc-400 hover:bg-zinc-800"
                    }`}
                  >
                    {messages.governance[filter.labelKey]}
                  </button>
                ))}
              </div>

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
            </div>

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
                    onClick={(e) => { e.preventDefault(); void runSelectedBatch("apply"); }}
                  >
                    {batchPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    {batchPending ? messages.common.saving : messages.governance.batchApply}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    disabled={batchPending}
                    onClick={(e) => { e.preventDefault(); void runSelectedBatch("reject"); }}
                    className="text-red-500 focus:text-red-500"
                  >
                    {batchPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    {batchPending ? messages.common.saving : messages.governance.batchReject}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}

            {allActionableCount > 0 && (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    variant="outline"
                    disabled={batchPending}
                    className="border-violet-700/50 bg-violet-950/40 text-violet-200 hover:bg-violet-900/50"
                  >
                    <CheckCheck className="mr-2 h-4 w-4" />
                    {messages.governance.approveAll(allActionableCount)}
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent className="border-zinc-800 bg-zinc-950 text-zinc-100">
                  <AlertDialogHeader>
                    <AlertDialogTitle>{messages.governance.confirmApproveAllTitle}</AlertDialogTitle>
                    <AlertDialogDescription className="text-zinc-400">
                      {messages.governance.confirmApproveAllDescription(allActionableCount)}
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel className="border-zinc-700 bg-zinc-900 text-zinc-200 hover:bg-zinc-800" disabled={batchPending}>
                      {messages.governance.cancel}
                    </AlertDialogCancel>
                    <AlertDialogAction onClick={(e) => { e.preventDefault(); void runApproveAll(); }} disabled={batchPending}>
                      {batchPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                      {batchPending ? messages.common.saving : messages.governance.apply}
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
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
              <Input
                type="number"
                min={1}
                max={totalPages}
                value={jumpValue}
                onChange={(e) => setJumpValue(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleJump(); }}
                aria-label={messages.governance.jumpToPage}
                className="w-16 border-zinc-700/50 bg-zinc-900 text-center text-sm text-zinc-200"
              />
              <Button
                variant="outline"
                size="sm"
                onClick={handleJump}
                className="border-zinc-700/50 bg-zinc-900 text-zinc-200"
              >
                {messages.governance.goButton}
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
        />
      </div>
    </div>
  );
}

export default function GovernancePage() {
  return (
    <Suspense>
      <GovernancePageInner />
    </Suspense>
  );
}
