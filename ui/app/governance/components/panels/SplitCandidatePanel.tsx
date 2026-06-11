import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { SplitCandidateFinding } from "@/components/dashboard/intelligence/types";
import type { Messages } from "@/lib/i18n/types";

interface SplitCandidatePanelProps {
  finding: SplitCandidateFinding;
  messages: Messages["governance"];
}

export function SplitCandidatePanel({ finding, messages }: SplitCandidatePanelProps) {
  const subs = finding.sub_memories ?? [];

  return (
    <Card className="border-zinc-800 bg-zinc-950/70">
      <CardHeader>
        <CardTitle className="text-base text-white">
          {messages.decisionTypeLabels.split_candidate}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded-lg border border-violet-800/60 bg-violet-950/20 p-4 space-y-2">
          <Badge className="border-violet-700 bg-violet-500/10 text-violet-300">
            {messages.splitCandidate.originalMemory}
          </Badge>
          <h4 className="text-sm font-medium text-white line-clamp-3">
            {finding.title || messages.notAvailable}
          </h4>
          <p className="text-xs text-zinc-500 break-all">{messages.idLabel}: {finding.id}</p>
        </div>

        {subs.length > 0 ? (
          <div className="space-y-2">
            <p className="text-xs font-medium text-zinc-400">
              {messages.splitCandidate.proposedSubMemories} ({subs.length})
            </p>
            {subs.map((sub, i) => (
              <div key={`sub-${i}`} className="rounded-lg border border-zinc-800 bg-zinc-950 p-3 space-y-1">
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className="border-zinc-700 text-zinc-400 text-xs">
                    #{i + 1}
                  </Badge>
                  <span className="text-sm font-medium text-white line-clamp-2">{sub.title}</span>
                </div>
                {sub.content ? (
                  <p className="text-xs text-zinc-400 line-clamp-3 pl-8">{sub.content}</p>
                ) : null}
              </div>
            ))}
          </div>
        ) : null}

        {finding.reason ? (
          <div className="rounded-lg border border-zinc-800 bg-black/30 p-3">
            <p className="text-xs font-medium text-zinc-400 mb-1">{messages.splitCandidate.reason}</p>
            <p className="text-sm text-zinc-200">{finding.reason}</p>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
