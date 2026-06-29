"use client";

import { useCallback, useState } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { FlaskConical, Loader2, Search } from "lucide-react";
import { useI18n } from "@/hooks/useI18n";
import { getApiBaseUrl } from "@/lib/api-url";

interface SlimRecord {
  id: string;
  type: string;
  title: string;
  importance: number;
  scope: string;
  tags: string[];
  _retrieval_sources: string[];
  _vector_score: number;
}

interface ContextTrace {
  total_candidates: number;
  used_count: number;
  filtered_count: number;
  vector_hits: number;
  entity_hits: number;
  vector_avg_score: number;
  vector_max_score: number;
  cross_retrieval_count: number;
  vector_only_count: number;
  fts_only_count: number;
  retrieval_mode: string;
  vector_fallback: boolean;
}

interface ContextQuality {
  estimated_tokens: number;
  hit_rate: number;
  filter_rate: number;
  cross_retrieval_rate: number;
  vector_avg_score: number;
}

interface ContextResult {
  records: SlimRecord[];
  used_ids: string[];
  filtered_ids: string[];
  quality: ContextQuality;
  trace: ContextTrace;
  budget_chars: number;
}

const SOURCE_COLORS: Record<string, string> = {
  fts: "border-sky-700 bg-sky-500/10 text-sky-300",
  vector: "border-violet-700 bg-violet-500/10 text-violet-300",
  entity: "border-amber-700 bg-amber-500/10 text-amber-300",
  keyword: "border-zinc-600 bg-zinc-500/10 text-zinc-300",
};

function sourceClassName(source: string): string {
  return SOURCE_COLORS[source] ?? "border-zinc-600 bg-zinc-500/10 text-zinc-400";
}

export function ContextLab() {
  const { messages: t } = useI18n();
  const d = t.dashboard;
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ContextResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runTest = useCallback(async () => {
    const trimmed = query.trim();
    if (!trimmed || loading) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${getApiBaseUrl()}/api/context`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          task: trimmed,
          agent: "context-lab",
          token_budget: 2000,
          retrieval_mode: "balanced",
          prefer_atomic: true,
          include_parent: false,
        }),
      });
      if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`);
      }
      const payload = await response.json();
      const data = payload.data ?? payload;
      setResult(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Request failed");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, [query, loading]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter") {
        e.preventDefault();
        runTest();
      }
    },
    [runTest]
  );

  return (
    <Card className="border-zinc-800 bg-zinc-900">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-medium text-zinc-300">
          <FlaskConical className="h-4 w-4 text-violet-400" />
          {d.contextLabTitle}
        </CardTitle>
        <p className="text-xs text-zinc-500">{d.contextLabDescription}</p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={d.contextLabPlaceholder}
              className="pl-9 border-zinc-700 bg-zinc-800 text-zinc-200 placeholder:text-zinc-500"
            />
          </div>
          <Button
            onClick={runTest}
            disabled={loading || !query.trim()}
            variant="outline"
            className="border-violet-700/50 bg-violet-950/40 text-violet-200 hover:bg-violet-900/50 disabled:opacity-50"
          >
            {loading && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
            {loading ? d.contextLabRunning : d.contextLabRun}
          </Button>
        </div>

        {error && (
          <div className="rounded border border-red-800/50 bg-red-950/30 px-3 py-2 text-xs text-red-300">
            {error}
          </div>
        )}

        {result && result.records.length === 0 && (
          <div className="rounded border border-zinc-700 bg-zinc-800/50 px-3 py-4 text-center text-sm text-zinc-500">
            {d.contextLabNoResults}
          </div>
        )}

        {result && result.records.length > 0 && (
          <>
            {/* Recalled memories list */}
            <div className="space-y-1">
              <h3 className="text-xs font-medium text-zinc-400 mb-2">
                {d.contextLabRecords} ({result.records.length})
              </h3>
              <div className="max-h-80 space-y-1 overflow-y-auto pr-1">
                {result.records.map((record) => (
                  <div
                    key={record.id}
                    className="flex items-start gap-2 rounded bg-zinc-800 px-2.5 py-2 text-xs"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <Link
                          href={`/memory/${record.id}`}
                          className="truncate font-medium text-zinc-200 hover:text-white transition-colors"
                          title={record.title}
                        >
                          {record.title}
                        </Link>
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-1.5">
                        <Badge variant="outline" className="border-zinc-600 bg-zinc-700/50 text-zinc-400 text-[10px] px-1.5 py-0">
                          {record.type}
                        </Badge>
                        <span className="text-zinc-500">
                          {d.contextLabImportance}{" "}
                          <span className="text-zinc-300">{record.importance.toFixed(2)}</span>
                        </span>
                        {record._vector_score > 0 && (
                          <span className="text-zinc-500">
                            {d.contextLabVectorScore}{" "}
                            <span className="text-violet-300">{record._vector_score.toFixed(3)}</span>
                          </span>
                        )}
                        {record._retrieval_sources.map((src) => (
                          <Badge
                            key={src}
                            variant="outline"
                            className={`text-[10px] px-1.5 py-0 ${sourceClassName(src)}`}
                          >
                            {src}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Trace panel */}
            <div className="rounded border border-zinc-700 bg-zinc-800/50 px-3 py-2.5">
              <h3 className="text-xs font-medium text-zinc-400 mb-2">{d.contextLabTrace}</h3>
              <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs sm:grid-cols-3 lg:grid-cols-4">
                <TraceStat label={d.contextLabUsed} value={result.trace.used_count} />
                <TraceStat label={d.contextLabFiltered} value={result.trace.filtered_count} />
                <TraceStat label={d.contextLabCandidates} value={result.trace.total_candidates} />
                <TraceStat label={d.contextLabVectorAvg} value={result.quality.vector_avg_score.toFixed(3)} highlight />
                <TraceStat label={d.contextLabCrossRetrieval} value={`${(result.quality.cross_retrieval_rate * 100).toFixed(0)}%`} highlight />
                <TraceStat label={d.contextLabHitRate} value={`${(result.quality.hit_rate * 100).toFixed(0)}%`} />
                <TraceStat label={d.contextLabFilterRate} value={`${(result.quality.filter_rate * 100).toFixed(0)}%`} />
                <TraceStat label={d.contextLabTokens} value={result.quality.estimated_tokens} />
                <TraceStat label={d.contextLabVectorHits} value={result.trace.vector_hits} />
                <TraceStat label={d.contextLabEntityHits} value={result.trace.entity_hits} />
                <TraceStat label={d.contextLabFtsOnly} value={result.trace.fts_only_count} />
                <TraceStat label={d.contextLabVectorOnly} value={result.trace.vector_only_count} />
                <TraceStat label={d.contextLabMode} value={result.trace.retrieval_mode} />
                <TraceStat label={d.contextLabBudget} value={`${result.budget_chars} chars`} />
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function TraceStat({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string | number;
  highlight?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-zinc-500 truncate">{label}</span>
      <span className={`tabular-nums font-mono ${highlight ? "text-violet-300" : "text-zinc-200"}`}>
        {value}
      </span>
    </div>
  );
}
