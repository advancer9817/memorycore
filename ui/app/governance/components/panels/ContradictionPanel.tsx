import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ContradictionFinding } from "@/components/dashboard/intelligence/types";
import { formatPercent } from "@/components/dashboard/intelligence/utils";
import type { Messages } from "@/lib/i18n/types";

interface ContradictionPanelProps {
  finding: ContradictionFinding;
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
  accent: "emerald" | "red";
  messages: Messages["governance"];
}) {
  const border = accent === "emerald" ? "border-emerald-800/60" : "border-red-800/60";
  const bg = accent === "emerald" ? "bg-emerald-950/20" : "bg-red-950/20";
  const badgeCls = accent === "emerald"
    ? "border-emerald-700 bg-emerald-500/10 text-emerald-300"
    : "border-red-700 bg-red-500/10 text-red-300";

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

export function ContradictionPanel({ finding, messages }: ContradictionPanelProps) {
  return (
    <Card className="border-zinc-800 bg-zinc-950/70">
      <CardHeader>
        <CardTitle className="text-base text-white">
          {messages.decisionTypeLabels.contradiction}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 lg:grid-cols-2">
          <MemoryCard
            label={messages.contradiction.newerMemory}
            title={finding.newer_title}
            memoryId={finding.newer_id}
            accent="emerald"
            messages={messages}
          />
          <MemoryCard
            label={messages.contradiction.olderMemory}
            title={finding.older_title}
            memoryId={finding.older_id}
            accent="red"
            messages={messages}
          />
        </div>
        {finding.reason ? (
          <div className="rounded-lg border border-zinc-800 bg-black/30 p-3">
            <p className="text-xs font-medium text-zinc-400 mb-1">{messages.contradiction.reason}</p>
            <p className="text-sm text-zinc-200">{finding.reason}</p>
          </div>
        ) : null}
        {typeof finding.score === "number" ? (
          <div className="flex items-center gap-2 text-xs text-zinc-500">
            <span>{messages.contradiction.score}:</span>
            <Badge className="border-zinc-700 bg-zinc-900 text-zinc-300">{formatPercent(finding.score)}</Badge>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
