import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ImportanceReassessmentFinding } from "@/components/dashboard/intelligence/types";
import { formatPercent } from "@/components/dashboard/intelligence/utils";
import type { Messages } from "@/lib/i18n/types";

interface ImportanceReassessmentPanelProps {
  finding: ImportanceReassessmentFinding;
  messages: Messages["governance"];
}

export function ImportanceReassessmentPanel({ finding, messages }: ImportanceReassessmentPanelProps) {
  const oldVal = finding.old_importance;
  const newVal = finding.new_importance;
  const isDowngrade = typeof oldVal === "number" && typeof newVal === "number" && newVal < oldVal;
  const arrowColor = isDowngrade ? "text-amber-400" : "text-emerald-400";

  return (
    <Card className="border-zinc-800 bg-zinc-950/70">
      <CardHeader>
        <CardTitle className="text-base text-white">
          {messages.decisionTypeLabels.importance_reassessment}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-4 space-y-2">
          <p className="text-xs font-medium text-zinc-400">{messages.importanceReassessment.memory}</p>
          <h4 className="text-sm font-medium text-white line-clamp-3">
            {finding.title || messages.notAvailable}
          </h4>
          <p className="text-xs text-zinc-500 break-all">{messages.idLabel}: {finding.id}</p>
        </div>

        <div className="flex items-center justify-center gap-4 py-2">
          <div className="text-center">
            <p className="text-xs text-zinc-500 mb-1">{messages.importanceReassessment.currentImportance}</p>
            <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300 text-lg px-3 py-1">
              {typeof oldVal === "number" ? formatPercent(oldVal) : messages.notAvailable}
            </Badge>
          </div>
          <span className={`text-2xl font-bold ${arrowColor}`}>&rarr;</span>
          <div className="text-center">
            <p className="text-xs text-zinc-500 mb-1">{messages.importanceReassessment.newImportance}</p>
            <Badge className={`text-lg px-3 py-1 ${isDowngrade
              ? "border-amber-700 bg-amber-500/10 text-amber-300"
              : "border-emerald-700 bg-emerald-500/10 text-emerald-300"
            }`}>
              {typeof newVal === "number" ? formatPercent(newVal) : messages.notAvailable}
            </Badge>
          </div>
        </div>

        {finding.reason ? (
          <div className="rounded-lg border border-zinc-800 bg-black/30 p-3">
            <p className="text-xs font-medium text-zinc-400 mb-1">{messages.importanceReassessment.reason}</p>
            <p className="text-sm text-zinc-200">{finding.reason}</p>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
