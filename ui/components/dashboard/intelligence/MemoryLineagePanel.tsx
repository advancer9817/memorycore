"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { GitBranch, Loader2 } from "lucide-react";
import { getApiBaseUrl } from "@/lib/api-url";
import { useI18n } from "@/hooks/useI18n";
import type { GovernanceMemorySnapshot, LineagePayload } from "@/components/dashboard/intelligence/types";

interface MemoryLineagePanelProps {
  memoryId: string;
}

function memoryLabel(memory?: GovernanceMemorySnapshot): string {
  const label = memory?.title?.trim() || memory?.content?.trim() || memory?.id || "Unknown";
  return label.length > 60 ? `${label.slice(0, 60)}...` : label;
}

export function MemoryLineagePanel({ memoryId }: MemoryLineagePanelProps) {
  const { messages } = useI18n();
  const t = messages.memoryDetail;
  const [lineage, setLineage] = useState<LineagePayload | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const baseUrl = useMemo(() => getApiBaseUrl(), []);

  useEffect(() => {
    if (!memoryId) return;
    const controller = new AbortController();
    async function load(): Promise<void> {
      setIsLoading(true);
      setError(null);
      try {
        const response = await fetch(
          `${baseUrl}/api/lineage/${encodeURIComponent(memoryId)}?limit=100`,
          { signal: controller.signal },
        );
        if (!response.ok) {
          if (response.status === 404) {
            setLineage(null);
            return;
          }
          throw new Error("Failed to load lineage");
        }
        const data = await response.json();
        const payload: LineagePayload = data?.data ?? data;
        setLineage(payload);
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(t.lineageError);
      } finally {
        setIsLoading(false);
      }
    }
    void load();
    return () => controller.abort();
  }, [baseUrl, memoryId, t.lineageError]);

  if (isLoading) {
    return (
      <Card className="border-zinc-800 bg-zinc-900">
        <CardContent className="flex items-center gap-2 py-4 text-sm text-zinc-400">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t.lineageLoading}
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="border-zinc-800 bg-zinc-900">
        <CardContent className="py-4 text-sm text-red-400">{error}</CardContent>
      </Card>
    );
  }

  const hasData = lineage && (lineage.records?.length > 0 || lineage.chain?.length);
  if (!hasData) {
    return (
      <Card className="border-zinc-800 bg-zinc-900">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-zinc-300">
            <GitBranch className="h-4 w-4 text-zinc-500" />
            {t.lineageTitle}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-zinc-500">{t.lineageNoData}</p>
        </CardContent>
      </Card>
    );
  }

  const chainRecords = lineage.chain ?? lineage.records ?? [];
  const links = lineage.links ?? [];

  return (
    <Card className="border-zinc-800 bg-zinc-900">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm font-medium text-zinc-300">
          <GitBranch className="h-4 w-4 text-primary/70" />
          {t.lineageTitle}
        </CardTitle>
        <p className="text-xs text-zinc-500">{t.lineageDescription}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-3">
          <div className="rounded-lg border border-zinc-800 bg-zinc-950/45 px-3 py-2">
            <div className="text-[10px] uppercase tracking-[0.16em] text-zinc-600">{t.lineageRoot}</div>
            <div className="mt-1 text-sm font-medium text-zinc-200">
              <Link href={`/memory/${lineage.root_id}`} className="hover:text-primary transition-colors">
                {lineage.root_id?.slice(0, 8)}...
              </Link>
            </div>
          </div>
          {lineage.current_head_id && (
            <div className="rounded-lg border border-zinc-800 bg-zinc-950/45 px-3 py-2">
              <div className="text-[10px] uppercase tracking-[0.16em] text-zinc-600">{t.lineageCurrentHead}</div>
              <div className="mt-1 text-sm font-medium text-zinc-200">
                <Link href={`/memory/${lineage.current_head_id}`} className="hover:text-primary transition-colors">
                  {lineage.current_head_id?.slice(0, 8)}...
                </Link>
              </div>
            </div>
          )}
        </div>

        {chainRecords.length > 0 && (
          <div>
            <div className="mb-2 text-xs uppercase tracking-[0.16em] text-zinc-500">{t.lineageChain}</div>
            <div className="space-y-1.5">
              {chainRecords.map((record, index) => {
                const isCurrent = record.id === memoryId;
                const isHead = record.id === lineage.current_head_id;
                return (
                  <div
                    key={record.id ?? index}
                    className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${
                      isCurrent
                        ? "border-primary/40 bg-primary/5 text-zinc-200"
                        : "border-zinc-800 bg-zinc-950/45 text-zinc-400"
                    }`}
                  >
                    <div className={`h-2 w-2 shrink-0 rounded-full ${isCurrent ? "bg-primary" : "bg-zinc-600"}`} />
                    <Link href={`/memory/${record.id}`} className="truncate hover:text-primary transition-colors">
                      {memoryLabel(record)}
                    </Link>
                    {isHead && (
                      <Badge variant="outline" className="ml-auto border-emerald-700 bg-emerald-500/10 text-emerald-300">
                        HEAD
                      </Badge>
                    )}
                    {record.superseded_by && (
                      <Badge variant="outline" className="ml-auto border-zinc-700 bg-zinc-900 text-zinc-400">
                        {t.lineageSupersededBy}
                      </Badge>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {links.length > 0 && (
          <div>
            <div className="mb-2 text-xs uppercase tracking-[0.16em] text-zinc-500">{t.lineageRelation}</div>
            <div className="space-y-1">
              {links.map((link, index) => (
                <div key={index} className="flex items-center gap-2 text-xs text-zinc-500">
                  <span className="font-mono text-zinc-400">{link.source_id?.slice(0, 8)}</span>
                  <span className="text-zinc-600">-&gt;</span>
                  <Badge variant="outline" className="border-zinc-700 text-zinc-400">
                    {link.relation_type ?? "related"}
                  </Badge>
                  <span className="text-zinc-600">-&gt;</span>
                  <span className="font-mono text-zinc-400">{link.target_id?.slice(0, 8)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
