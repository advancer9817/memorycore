"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Activity, ArrowRight, Database, Radio, Users } from "lucide-react";
import Image from "next/image";
import { useSelector } from "react-redux";
import { RootState } from "@/store/store";
import { useAppsApi } from "@/hooks/useAppsApi";
import { constants } from "@/components/shared/source-app";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { AppCardSkeleton } from "@/skeleton/AppCardSkeleton";

function formatActivity(value?: string) {
  if (!value) return "Never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusClass(status?: string) {
  if (status === "online") return "border-emerald-700 bg-emerald-500/10 text-emerald-300";
  if (status === "idle") return "border-yellow-700 bg-yellow-500/10 text-yellow-300";
  if (status === "busy") return "border-sky-700 bg-sky-500/10 text-sky-300";
  return "border-zinc-700 bg-zinc-800 text-zinc-300";
}

export function AppGrid() {
  const router = useRouter();
  const { fetchApps, isLoading } = useAppsApi();
  const apps = useSelector((state: RootState) => state.apps.apps);
  const filters = useSelector((state: RootState) => state.apps.filters);

  useEffect(() => {
    fetchApps({
      name: filters.searchQuery,
      is_active: filters.isActive === "all" ? undefined : filters.isActive,
      sort_by: filters.sortBy,
      sort_direction: filters.sortDirection,
      page_size: 100,
    });
  }, [fetchApps, filters]);

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <AppCardSkeleton key={i} />
          ))}
        </div>
      </div>
    );
  }

  const totalMemories = apps.reduce((sum, app) => sum + app.total_memories_created, 0);
  const activeAgents = apps.filter((app) => app.is_active).length;
  const lastActivity = apps
    .map((app) => app.last_activity_at || "")
    .filter(Boolean)
    .sort()
    .at(-1);

  const summary = [
    { label: "Connected Agents", value: apps.length, icon: Users },
    { label: "Active Agents", value: activeAgents, icon: Radio },
    { label: "Total Memories", value: totalMemories, icon: Database },
    { label: "Last Activity", value: formatActivity(lastActivity), icon: Activity },
  ];

  if (apps.length === 0) {
    return (
      <div className="text-center text-zinc-500 py-8">
        No agents or clients found matching your filters
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {summary.map((item) => (
          <Card key={item.label} className="bg-zinc-900 text-white border-zinc-800">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-zinc-400">{item.label}</CardTitle>
              <item.icon className="h-4 w-4 text-zinc-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-semibold text-white">{item.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card className="bg-zinc-900 text-white border-zinc-800">
        <CardHeader className="border-b border-zinc-800 px-4 py-3">
          <CardTitle className="text-base font-semibold">Agent Activity</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow className="border-zinc-800 hover:bg-transparent">
                <TableHead className="text-zinc-400">Agent / Client</TableHead>
                <TableHead className="text-zinc-400">Status</TableHead>
                <TableHead className="text-right text-zinc-400">Memories</TableHead>
                <TableHead className="text-zinc-400">Last Activity</TableHead>
                <TableHead className="text-right text-zinc-400">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {apps.map((app) => {
                const appConfig = constants[app.name as keyof typeof constants] || constants.default;
                const appLabel = constants[app.name as keyof typeof constants]?.name || app.name;
                return (
                  <TableRow
                    key={app.id}
                    className="border-zinc-800 hover:bg-zinc-800/60 cursor-pointer"
                    onClick={() => router.push(`/apps/${app.id}`)}
                  >
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-full bg-zinc-800 flex items-center justify-center overflow-hidden">
                          <Image src={appConfig.iconImage} alt={appLabel} width={32} height={32} />
                        </div>
                        <div>
                          <div className="font-medium text-zinc-100">{appLabel}</div>
                          <div className="text-xs text-zinc-500">{app.id}</div>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className={statusClass(app.status)}>
                        {app.status || (app.is_active ? "active" : "unknown")}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right font-medium">
                      {app.total_memories_created.toLocaleString()}
                    </TableCell>
                    <TableCell className="text-zinc-400">
                      {formatActivity(app.last_activity_at || app.last_seen_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <span className="inline-flex items-center text-sm text-primary">
                        Details <ArrowRight className="ml-2 h-4 w-4" />
                      </span>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
