import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { SemanticDuplicateFinding } from "@/components/dashboard/intelligence/types";
import { formatPercent } from "@/components/dashboard/intelligence/utils";
import type { Messages } from "@/lib/i18n/types";

interface SemanticDuplicatePanelProps {
  finding: SemanticDuplicateFinding;
  messages: Messages["governance"];
}

function MemoryCard({
  label,
  title,
  memoryId,
  accent,
  messages,
}: {
  label: string;
  title?: string;
  memoryId: string;
  accent: "emerald" | "amber";
  messages: Messages["governance"];
}) {
  const border = accent === "emerald" ? "border-emerald-800/60" : "border-amber-800/60";
  const bg = accent === "emerald" ? "bg-emerald-950/20" : "bg-amber-950/20";
  const badgeCls = accent === "emerald"
    ? "border-emerald-700 bg-emerald-500/10 text-emerald-300"
    : "border-amber-700 bg-amber-500/10 text-amber-300";

  return (
    <div className={`rounded-lg border ${border} ${bg} p-4 space-y-2`}>
      <Badge className={badgeCls}>{label}</Badge>
      <h4 className="text-sm font-medium text-white line-clamp-3">
        {title || messages.notAvailable}
      </h4>
      <p className="text-xs text-zinc-500 break-all">{messages.idLabel}: {memoryId}</p>
    </div>
  );
}

export function SemanticDuplicatePanel({ finding, messages }: SemanticDuplicatePanelProps) {
  return (
    <Card className="border-zinc-800 bg-zinc-950/70">
      <CardHeader>
        <CardTitle className="text-base text-white">
          {messages.decisionTypeLabels.semantic_duplicate}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 lg:grid-cols-2">
          <MemoryCard
            label={messages.semanticDuplicate.keepMemory}
            title={finding.keep_title}
            memoryId={finding.keep_id}
            accent="emerald"
            messages={messages}
          />
          <MemoryCard
            label={messages.semanticDuplicate.dropMemory}
            title={finding.drop_title}
            memoryId={finding.drop_id}
            accent="amber"
            messages={messages}
          />
        </div>
        {finding.merge_info ? (
          <div className="rounded-lg border border-zinc-800 bg-black/30 p-3">
            <p className="text-xs font-medium text-zinc-400 mb-1">{messages.semanticDuplicate.mergeInfo}</p>
            <p className="text-sm text-zinc-200">{finding.merge_info}</p>
          </div>
        ) : null}
        {finding.reason ? (
          <div className="rounded-lg border border-zinc-800 bg-black/30 p-3">
            <p className="text-xs font-medium text-zinc-400 mb-1">{messages.semanticDuplicate.reason}</p>
            <p className="text-sm text-zinc-200">{finding.reason}</p>
          </div>
        ) : null}
        {typeof finding.score === "number" ? (
          <div className="flex items-center gap-2 text-xs text-zinc-500">
            <span>{messages.semanticDuplicate.score}:</span>
            <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{formatPercent(finding.score)}</Badge>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
