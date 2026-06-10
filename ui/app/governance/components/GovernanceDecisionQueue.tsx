import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { GovernanceDecision } from "@/components/dashboard/intelligence/types";
import {
  confidenceTone,
  decisionSummary,
  decisionTitle,
  formatGovernanceDate,
  formatPercent,
  reviewStatusTone,
  riskTone,
  titleCase,
} from "@/components/dashboard/intelligence/utils";
import type { Messages } from "@/lib/i18n/types";

interface GovernanceDecisionQueueProps {
  decisions: GovernanceDecision[];
  selectedDecisionId?: string;
  messages: Messages["governance"];
  onSelect: (decision: GovernanceDecision) => void;
}

export function GovernanceDecisionQueue({
  decisions,
  selectedDecisionId,
  messages,
  onSelect,
}: GovernanceDecisionQueueProps) {
  return (
    <Card className="border-zinc-800 bg-zinc-950/80">
      <CardHeader>
        <CardTitle className="text-base text-white">{messages.decisionQueue}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {decisions.length ? decisions.map((decision) => {
          const isSelected = decision.id === selectedDecisionId;
          return (
            <Button
              key={decision.id}
              type="button"
              variant="outline"
              onClick={() => onSelect(decision)}
              className={`h-auto w-full justify-start border-zinc-800 bg-zinc-950/70 p-4 text-left hover:bg-zinc-900 ${
                isSelected ? "border-violet-500/70 bg-violet-950/20" : ""
              }`}
            >
              <span className="flex w-full flex-col gap-3">
                <span className="flex flex-wrap items-center gap-2">
                  <Badge className={reviewStatusTone(decision.review_status)}>{titleCase(decision.review_status)}</Badge>
                  <Badge className={riskTone(decision.risk_level)}>{titleCase(decision.risk_level)}</Badge>
                  <Badge className={confidenceTone(decision.llm_confidence)}>{formatPercent(decision.llm_confidence)}</Badge>
                </span>
                <span className="block text-sm font-medium text-white">{decisionTitle(decision)}</span>
                <span className="line-clamp-2 block text-xs text-zinc-400">{decisionSummary(decision)}</span>
                <span className="block text-xs text-zinc-500">{formatGovernanceDate(decision.created_at)}</span>
              </span>
            </Button>
          );
        }) : (
          <div className="rounded-lg border border-dashed border-zinc-800 p-6 text-sm text-zinc-400">
            {messages.noDecisions}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
