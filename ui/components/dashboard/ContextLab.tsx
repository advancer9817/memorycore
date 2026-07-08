"use client";

import React, { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { FlaskConical, Loader2, Search } from "lucide-react";
import { getApiBaseUrl } from "@/lib/api-url";
import { useI18n } from "@/hooks/useI18n";

interface ContextLabItem {
  rank: number;
  id: string;
  title: string;
  content: string;
  type: string;
  importance: number;
  rank_score: number;
  retrieval_sources: string[];
  vector_score: number;
}

interface ContextLabTrace {
  total_candidates: number;
  used_count: number;
  filtered_count: number;
  vector_hits: number;
  entity_hits: number;
  vector_avg_score: number;
  retrieval_mode: string;
  hit_rate: number;
  cross_retrieval_rate: number;
}

interface ContextLabResult {
  items: ContextLabItem[];
  trace: ContextLabTrace;
}

const SOURCE_COLORS: Record<string, string> = {
  fts: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  vector: "bg-purple-500/20 text-purple-400 border-purple-500/30",
  entity: "bg-green-500/20 text-green-400 border-green-500/30",
  keyword: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
};

export function ContextLab() {
  const { messages } = useI18n();
  const t = messages.dashboard;
  const [query, setQuery] = useState("");
  const [tokenBudget, setTokenBudget] = useState(2000);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ContextLabResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleTest() {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${getApiBaseUrl()}/api/v1/context/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.trim(), token_budget: tokenBudget }),
      });
      const data = await res.json();
      if (data.items) {
        setResult(data);
      } else if (data.error) {
        setError(typeof data.error === "string" ? data.error : data.error.message || "Request failed");
      } else {
        setResult(data);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Network error");
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !loading) {
      handleTest();
    }
  }

  return (
    <Card className="bg-zinc-900 border-zinc-800">
      <CardHeader className="pb-3">
        <CardTitle className="text-lg font-semibold flex items-center gap-2">
          <FlaskConical className="h-5 w-5 text-purple-400" />
          {t.contextLabTitle}
          <Badge variant="outline" className="text-xs ml-2 border-purple-500/30 text-purple-400">
            {t.contextLabBadge}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2 items-center">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-white/40" />
            <Input
              className="bg-zinc-800 border-zinc-700 text-zinc-200 placeholder:text-zinc-500 pl-9"
              placeholder={t.contextLabPlaceholder}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
            />
          </div>
          <Input
            className="bg-zinc-800 border-zinc-700 text-zinc-200 w-24 text-center"
            type="number"
            min={500}
            max={8000}
            value={tokenBudget}
            onChange={(e) => setTokenBudget(Number(e.target.value) || 2000)}
            title="Token budget"
          />
          <Button
            onClick={handleTest}
            disabled={loading || !query.trim()}
            className="bg-zinc-700 hover:bg-zinc-600 text-zinc-200 border border-zinc-600"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : t.contextLabTest}
          </Button>
        </div>

        {error && (
          <div className="text-red-400 text-sm bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
            {error}
          </div>
        )}

        {result && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/10 text-white/50 text-left">
                    <th className="py-2 px-2 w-10">{t.contextLabTableRank}</th>
                    <th className="py-2 px-2">{t.contextLabTableTitle}</th>
                    <th className="py-2 px-2 w-28">{t.contextLabTableType}</th>
                    <th className="py-2 px-2 w-20 text-right">{t.contextLabTableImportance}</th>
                    <th className="py-2 px-2 w-24 text-right">{t.contextLabTableVecScore}</th>
                    <th className="py-2 px-2 w-36">{t.contextLabTableSources}</th>
                  </tr>
                </thead>
                <tbody>
                  {result.items.map((item) => (
                    <tr key={item.id} className="border-b border-white/5 hover:bg-white/5 transition-colors">
                      <td className="py-2 px-2 text-white/40 font-mono">{item.rank}</td>
                      <td className="py-2 px-2">
                        <div className="font-medium text-white/90 truncate max-w-xs" title={item.title}>
                          {item.title}
                        </div>
                        {item.content && (
                          <div className="text-white/30 text-xs truncate max-w-xs mt-0.5" title={item.content}>
                            {item.content}
                          </div>
                        )}
                      </td>
                      <td className="py-2 px-2">
                        <Badge variant="outline" className="text-xs border-white/20 text-white/60">
                          {item.type}
                        </Badge>
                      </td>
                      <td className="py-2 px-2 text-right font-mono text-white/70">
                        {item.importance.toFixed(2)}
                      </td>
                      <td className="py-2 px-2 text-right font-mono text-white/70">
                        {item.vector_score > 0 ? item.vector_score.toFixed(4) : "-"}
                      </td>
                      <td className="py-2 px-2">
                        <div className="flex gap-1 flex-wrap">
                          {item.retrieval_sources.map((src) => (
                            <Badge
                              key={src}
                              variant="outline"
                              className={`text-xs ${SOURCE_COLORS[src] || "border-white/20 text-white/50"}`}
                            >
                              {src}
                            </Badge>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {result.items.length === 0 && (
                    <tr>
                      <td colSpan={6} className="py-6 text-center text-white/30">
                        {t.contextLabNoResults}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2">
              <TraceStat label="Candidates" value={result.trace.total_candidates} />
              <TraceStat label="Returned" value={result.trace.used_count} />
              <TraceStat label="Hit Rate" value={`${(result.trace.hit_rate * 100).toFixed(1)}%`} />
              <TraceStat label="Vector Hits" value={result.trace.vector_hits} />
              <TraceStat label="Entity Hits" value={result.trace.entity_hits} />
              <TraceStat label="Vec Avg Score" value={result.trace.vector_avg_score.toFixed(3)} />
              <TraceStat label="Cross Retrieval" value={`${(result.trace.cross_retrieval_rate * 100).toFixed(1)}%`} />
              <TraceStat label="Mode" value={result.trace.retrieval_mode} />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function TraceStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-white/5 rounded-lg px-3 py-2 border border-white/5">
      <div className="text-white/40 text-xs">{label}</div>
      <div className="text-white/90 font-mono text-sm mt-0.5">{String(value)}</div>
    </div>
  );
}
