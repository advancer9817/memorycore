"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { GitBranch } from "lucide-react";
import { getApiBaseUrl } from "@/lib/api-url";
import type { GovernanceMemorySnapshot, LineagePayload } from "@/components/dashboard/intelligence/types";

interface MemoryLineageProps {
  memoryId: string;
}

function StatusBadge({ status }: { status: string | undefined }) {
  if (!status) return null;
  const isActive = status === "active";
  const isSuperseded = status === "superseded" || status === "contradicted";
  const colorClass = isActive
    ? "border-emerald-600 text-emerald-400 bg-emerald-400/10"
    : isSuperseded
    ? "border-zinc-700 text-zinc-500 bg-zinc-800/50"
    : "border-zinc-600 text-zinc-400 bg-zinc-800/50";

  return (
    <span
      className={`inline-block px-2 py-0.5 text-xs font-semibold rounded-full border ${colorClass}`}
    >
      {status}
    </span>
  );
}

interface ChainEntryProps {
  record: GovernanceMemorySnapshot;
  isRoot: boolean;
  isHead: boolean;
  isCurrent: boolean;
  isLast: boolean;
}

function ChainEntry({ record, isRoot, isHead, isCurrent, isLast }: ChainEntryProps) {
  const isSuperseded = !!record.superseded_by;
  const titleText = record.title ?? record.id ?? "Unknown";
  const snippet = record.content ? record.content.slice(0, 80) + (record.content.length > 80 ? "…" : "") : null;
  const dateText = record.created_at
    ? new Date(record.created_at).toLocaleDateString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
      })
    : null;

  return (
    <div className="relative flex gap-3">
      <div className="flex flex-col items-center">
        <div
          className={`z-10 mt-1 w-3 h-3 rounded-full border-2 flex-shrink-0 ${
            isCurrent
              ? "border-primary bg-primary"
              : isHead
              ? "border-emerald-500 bg-emerald-500"
              : "border-zinc-600 bg-zinc-800"
          }`}
        />
        {!isLast && <div className="w-[1px] flex-1 bg-zinc-700 mt-1" />}
      </div>

      <div className="pb-4 flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-1.5 mb-0.5">
          {isRoot && (
            <span className="text-xs font-semibold text-zinc-500 uppercase tracking-wide">
              Root
            </span>
          )}
          {isHead && (
            <span className="text-xs font-semibold text-emerald-500 uppercase tracking-wide">
              Current
            </span>
          )}
          <StatusBadge status={record.status} />
        </div>

        <Link
          href={`/memory/${record.id}`}
          className={`block text-sm font-medium hover:underline truncate ${
            isSuperseded ? "text-zinc-500" : isCurrent ? "text-white" : "text-zinc-300"
          }`}
        >
          {titleText}
        </Link>

        {snippet && (
          <p className="text-xs text-zinc-600 mt-0.5 line-clamp-1">{snippet}</p>
        )}

        {dateText && (
          <p className="text-xs text-zinc-600 mt-0.5">{dateText}</p>
        )}
      </div>
    </div>
  );
}

export function MemoryLineage({ memoryId }: MemoryLineageProps) {
  const [lineage, setLineage] = useState<LineagePayload | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const apiBaseUrl = getApiBaseUrl();
        const res = await fetch(`${apiBaseUrl}/api/lineage/${memoryId}`);
        if (!res.ok) return;
        const data: unknown = await res.json();
        if (data && typeof data === "object" && "memory_id" in data) {
          setLineage(data as LineagePayload);
        }
      } catch {
      } finally {
        setIsLoading(false);
      }
    };

    void load();
  }, [memoryId]);

  const chain = lineage?.chain?.length ? lineage.chain : lineage?.records ?? [];

  if (isLoading) {
    return (
      <div className="w-full max-w-md mx-auto rounded-lg overflow-hidden bg-zinc-900 border border-zinc-800 text-white p-6">
        <div className="flex items-center gap-2 mb-4">
          <GitBranch className="h-4 w-4 text-zinc-400" />
          <h2 className="font-semibold">Fact Lineage</h2>
        </div>
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="flex gap-3">
              <div className="w-3 h-3 rounded-full bg-zinc-800 flex-shrink-0 mt-1" />
              <div className="flex-1 space-y-1">
                <div className="h-3 bg-zinc-800 rounded w-3/4 animate-pulse" />
                <div className="h-2 bg-zinc-800 rounded w-1/2 animate-pulse" />
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (chain.length <= 1) {
    return (
      <div className="w-full max-w-md mx-auto rounded-lg overflow-hidden bg-zinc-900 border border-zinc-800 text-white">
        <div className="px-6 py-4 flex items-center gap-2 bg-zinc-800 border-b border-zinc-800">
          <GitBranch className="h-4 w-4 text-zinc-400" />
          <h2 className="font-semibold">Fact Lineage</h2>
        </div>
        <div className="p-6">
          <p className="text-center text-zinc-500 text-sm">No lineage data</p>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full max-w-md mx-auto rounded-lg overflow-hidden bg-zinc-900 border border-zinc-800 text-white">
      <div className="px-6 py-4 flex items-center gap-2 bg-zinc-800 border-b border-zinc-800">
        <GitBranch className="h-4 w-4 text-zinc-400" />
        <h2 className="font-semibold">Fact Lineage</h2>
      </div>
      <div className="p-6">
        {chain.map((record, index) => (
          <ChainEntry
            key={record.id ?? index}
            record={record}
            isRoot={index === 0 || record.id === lineage?.root_id}
            isHead={record.id === lineage?.current_head_id}
            isCurrent={record.id === memoryId}
            isLast={index === chain.length - 1}
          />
        ))}
      </div>
    </div>
  );
}
