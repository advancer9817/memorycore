import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { GovernanceMemorySnapshot } from "@/components/dashboard/intelligence/types";
import { formatPercent, memoryTitle, titleCase } from "@/components/dashboard/intelligence/utils";
import type { Messages } from "@/lib/i18n/types";

interface MemorySnapshotCompareProps {
  beforeState?: GovernanceMemorySnapshot[];
  afterState?: GovernanceMemorySnapshot[];
  messages: Messages["governance"];
}

interface SnapshotColumnProps {
  title: string;
  snapshots?: GovernanceMemorySnapshot[];
  emptyText: string;
}

function SnapshotCard({ snapshot }: { snapshot: GovernanceMemorySnapshot }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/70 p-3">
      <div className="flex flex-wrap items-center gap-2">
        {snapshot.type ? <Badge variant="outline" className="border-zinc-700 text-zinc-300">{titleCase(snapshot.type)}</Badge> : null}
        {snapshot.status ? <Badge variant="outline" className="border-zinc-700 text-zinc-300">{titleCase(snapshot.status)}</Badge> : null}
      </div>
      <h4 className="mt-2 text-sm font-medium text-white">{memoryTitle(snapshot)}</h4>
      {snapshot.content ? <p className="mt-2 line-clamp-4 text-xs text-zinc-400">{snapshot.content}</p> : null}
      <div className="mt-3 grid gap-1 text-xs text-zinc-500 sm:grid-cols-2">
        <span>Importance: {formatPercent(snapshot.importance)}</span>
        <span>Confidence: {formatPercent(snapshot.confidence)}</span>
        {snapshot.id ? <span className="sm:col-span-2">ID: {snapshot.id}</span> : null}
      </div>
    </div>
  );
}

function SnapshotColumn({ title, snapshots, emptyText }: SnapshotColumnProps) {
  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium text-zinc-300">{title}</h3>
      {snapshots?.length ? snapshots.map((snapshot, index) => (
        <SnapshotCard key={snapshot.id || `${title}-${index}`} snapshot={snapshot} />
      )) : (
        <div className="rounded-lg border border-dashed border-zinc-800 p-4 text-sm text-zinc-500">{emptyText}</div>
      )}
    </div>
  );
}

export function MemorySnapshotCompare({ beforeState, afterState, messages }: MemorySnapshotCompareProps) {
  return (
    <Card className="border-zinc-800 bg-zinc-950/70">
      <CardHeader>
        <CardTitle className="text-base text-white">{messages.beforeAfter}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4 lg:grid-cols-2">
        <SnapshotColumn title={messages.beforeState} snapshots={beforeState} emptyText={messages.noSnapshot} />
        <SnapshotColumn title={messages.afterState} snapshots={afterState} emptyText={messages.noSnapshot} />
      </CardContent>
    </Card>
  );
}
