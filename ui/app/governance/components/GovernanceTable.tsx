"use client";

import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { GovernanceDecision } from "@/components/dashboard/intelligence/types";
import {
  confidenceTone,
  decisionSummary,
  decisionTitle,
  formatGovernanceDate,
  formatPercent,
  isActionableDecision,
  reviewStatusTone,
  riskTone,
  titleCase,
} from "@/components/dashboard/intelligence/utils";
import type { Messages } from "@/lib/i18n/types";

interface GovernanceTableProps {
  decisions: GovernanceDecision[];
  selectedIds: Set<string>;
  onToggleSelect: (id: string) => void;
  onToggleSelectAll: () => void;
  onRowClick: (decision: GovernanceDecision) => void;
  messages: Messages["governance"];
  isLoading: boolean;
}

export function GovernanceTable({
  decisions,
  selectedIds,
  onToggleSelect,
  onToggleSelectAll,
  onRowClick,
  messages,
  isLoading,
}: GovernanceTableProps) {
  const selectableDecisions = decisions.filter(isActionableDecision);
  const isAllSelected = selectableDecisions.length > 0 && selectableDecisions.every((d) => selectedIds.has(d.id));
  const isPartial = selectableDecisions.some((d) => selectedIds.has(d.id)) && !isAllSelected;

  return (
    <div className="rounded-md border border-zinc-800">
      <Table>
        <TableHeader>
          <TableRow className="bg-zinc-800 hover:bg-zinc-800">
            <TableHead className="w-[50px] pl-4">
              <Checkbox
                className="data-[state=checked]:border-primary border-zinc-500/50"
                checked={isAllSelected}
                data-state={isPartial ? "indeterminate" : isAllSelected ? "checked" : "unchecked"}
                onCheckedChange={onToggleSelectAll}
                disabled={!selectableDecisions.length}
              />
            </TableHead>
            <TableHead className="min-w-[400px]">{messages.decisionQueue}</TableHead>
            <TableHead className="w-[120px]">{messages.riskLevel}</TableHead>
            <TableHead className="w-[100px]">{messages.confidence}</TableHead>
            <TableHead className="w-[120px]">{messages.recommendedAction}</TableHead>
            <TableHead className="w-[140px]">{messages.created}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading && !decisions.length ? (
            Array.from({ length: 5 }).map((_, i) => (
              <TableRow key={`skel-${i}`}>
                <TableCell colSpan={6} className="h-16">
                  <div className="h-4 w-full animate-pulse rounded bg-zinc-800" />
                </TableCell>
              </TableRow>
            ))
          ) : !decisions.length ? (
            <TableRow>
              <TableCell colSpan={6} className="py-8 text-center text-sm text-zinc-500">
                {messages.noDecisions}
              </TableCell>
            </TableRow>
          ) : (
            decisions.map((decision) => {
              const isSelectable = isActionableDecision(decision);
              return (
              <TableRow
                key={decision.id}
                className={`hover:bg-zinc-900/50 ${isLoading ? "animate-pulse opacity-50" : ""}`}
              >
                <TableCell className="pl-4" onClick={(e) => e.stopPropagation()}>
                  <Checkbox
                    className="data-[state=checked]:border-primary border-zinc-500/50"
                    checked={selectedIds.has(decision.id)}
                    onCheckedChange={() => onToggleSelect(decision.id)}
                    disabled={!isSelectable}
                  />
                </TableCell>
                <TableCell>
                  <button
                    type="button"
                    className="block w-full text-left"
                    onClick={() => onRowClick(decision)}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <Badge className={reviewStatusTone(decision.review_status)}>
                        {titleCase(decision.review_status)}
                      </Badge>
                    </div>
                    <div className="font-medium text-white cursor-pointer line-clamp-2">
                      {decisionTitle(decision)}
                    </div>
                    <div className="text-xs text-zinc-500 line-clamp-1 mt-0.5">
                      {decisionSummary(decision)}
                    </div>
                  </button>
                </TableCell>
                <TableCell>
                  <Badge className={riskTone(decision.risk_level)}>
                    {titleCase(decision.risk_level)}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Badge className={confidenceTone(decision.llm_confidence)}>
                    {formatPercent(decision.llm_confidence)}
                  </Badge>
                </TableCell>
                <TableCell className="text-sm text-zinc-400">
                  {titleCase(decision.recommended_action)}
                </TableCell>
                <TableCell className="text-sm text-zinc-500">
                  {formatGovernanceDate(decision.created_at)}
                </TableCell>
              </TableRow>
              );
            })
          )}
        </TableBody>
      </Table>
    </div>
  );
}
