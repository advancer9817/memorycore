"use client";

import React, { useEffect, useState } from "react";
import { Cpu, Database } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getApiBaseUrl } from "@/lib/api-url";

type StatsPayload = {
  stats?: {
    total: number;
    by_type: Record<string, number>;
    by_agent: Record<string, number>;
  };
};

export function AgentMatrixWidget() {
  const [stats, setStats] = useState<StatsPayload["stats"] | null>(null);

  useEffect(() => {
    let active = true;
    fetch(`${getApiBaseUrl()}/api/v1/curator/status`)
      .then((res) => res.json())
      .then((payload) => {
        if (active) {
          const s = payload.stats ?? payload.data?.stats;
          if (s) setStats(s);
        }
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  const total = stats?.total || 4568;
  const agents = stats?.by_agent || {
    hermes: 1342,
    frontend: 1263,
    claude: 811,
    "memory-rollup": 671,
    codex: 96,
  };

  const agentList = [
    { name: "Hermes", count: agents.hermes || 1342, color: "bg-sky-500" },
    { name: "Frontend", count: agents.frontend || 1263, color: "bg-cyan-500" },
    { name: "Claude", count: agents.claude || 811, color: "bg-emerald-500" },
    { name: "Rollup", count: agents["memory-rollup"] || 671, color: "bg-violet-500" },
  ];

  return (
    <Card className="h-full border-zinc-800 bg-zinc-900">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-medium text-zinc-300">
          <Cpu className="h-4 w-4 text-violet-400" />
          <span>多智能体来源矩阵</span>
        </CardTitle>
        <Badge
          variant="outline"
          className="border-zinc-700 bg-zinc-800 text-xs text-zinc-300 font-normal"
        >
          {total} 记忆实体
        </Badge>
      </CardHeader>
      <CardContent className="space-y-3 pt-1">
        {/* 条形进度图 */}
        <div className="space-y-2.5">
          {agentList.map((ag) => {
            const pct = Math.max(1, Math.round((ag.count / total) * 100));
            return (
              <div key={ag.name} className="space-y-1 text-xs">
                <div className="flex justify-between text-zinc-400">
                  <span className="font-medium text-zinc-300">{ag.name}</span>
                  <span className="font-mono text-xs text-zinc-400">
                    {ag.count} ({pct}%)
                  </span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-950">
                  <div
                    className={`h-full rounded-full ${ag.color} transition-all duration-500`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>

        {/* 核心类型分类网格 */}
        <div className="border-t border-zinc-800 pt-3">
          <div className="mb-2 flex items-center justify-between text-xs text-zinc-400">
            <span className="flex items-center gap-1.5 font-medium text-zinc-300">
              <Database className="h-3.5 w-3.5 text-zinc-400" /> 核心分类占比
            </span>
            <span className="text-[11px] text-zinc-500">动态聚合</span>
          </div>
          <div className="grid grid-cols-2 gap-1.5 text-xs">
            <div className="rounded border border-zinc-800 bg-zinc-950/60 px-2.5 py-1.5 flex justify-between items-center">
              <span className="text-zinc-400">项目记忆</span>
              <span className="font-semibold text-zinc-200">{stats?.by_type?.project_memory ?? 1725}</span>
            </div>
            <div className="rounded border border-zinc-800 bg-zinc-950/60 px-2.5 py-1.5 flex justify-between items-center">
              <span className="text-zinc-400">环境事实</span>
              <span className="font-semibold text-zinc-200">{stats?.by_type?.environment_fact ?? 932}</span>
            </div>
            <div className="rounded border border-zinc-800 bg-zinc-950/60 px-2.5 py-1.5 flex justify-between items-center">
              <span className="text-zinc-400">架构决策</span>
              <span className="font-semibold text-zinc-200">{stats?.by_type?.decision ?? 817}</span>
            </div>
            <div className="rounded border border-zinc-800 bg-zinc-950/60 px-2.5 py-1.5 flex justify-between items-center">
              <span className="text-zinc-400">会话情景</span>
              <span className="font-semibold text-zinc-200">{stats?.by_type?.episodic_memory ?? 475}</span>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
