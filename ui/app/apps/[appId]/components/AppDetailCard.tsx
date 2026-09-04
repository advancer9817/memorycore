import React, { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  PauseIcon,
  Loader2,
  PlayIcon,
  Settings2,
  Check,
  X,
  ExternalLink,
  Bot,
  Server,
  ShieldCheck,
} from "lucide-react";
import { useAppsApi } from "@/hooks/useAppsApi";
import { useDispatch, useSelector } from "react-redux";
import { setAppDetails, AppDetails } from "@/store/appsSlice";
import { RootState } from "@/store/store";
import { useI18n } from "@/hooks/useI18n";
import { useToast } from "@/hooks/use-toast";
import Link from "next/link";

interface SelectedApp {
  details: AppDetails | null;
}

const AppDetailCard = ({
  appId,
  selectedApp,
}: {
  appId: string;
  selectedApp: SelectedApp;
}) => {
  const { updateAppDetails, fetchAppDetails, fetchApps } = useAppsApi();
  const [isLoading, setIsLoading] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  const dispatch = useDispatch();
  const { messages, locale } = useI18n();
  const { toast } = useToast();
  const t = messages.apps;

  const details = selectedApp.details;

  // Form states for management
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");

  useEffect(() => {
    if (details) {
      setDisplayName(details.display_name || details.name || appId);
      setDescription(details.description || "");
    }
  }, [details, appId]);

  if (!details) return null;

  const isSystem = appId === "mcore" || details.category === "system";

  const handlePauseAccess = async () => {
    setIsLoading(true);
    try {
      const nextActive = !details.is_active;
      await updateAppDetails(appId, {
        is_active: nextActive,
      });
      dispatch(setAppDetails({ appId, isActive: nextActive }));
      toast({
        title: nextActive ? "已启用访问" : "已暂停访问",
        description: `写入方 [${displayName}] 状态已成功更新`,
      });
    } catch {
      toast({
        title: messages.common.error,
        description: messages.apps.accessStatus,
        variant: "destructive",
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleSaveSettings = async () => {
    setIsSaving(true);
    try {
      await updateAppDetails(appId, {
        display_name: displayName,
        description: description,
        is_active: details.is_active,
      });
      await fetchAppDetails(appId);
      await fetchApps({ forceRefresh: true });
      setIsEditing(false);
      toast({
        title: "配置已更新",
        description: `应用信息已持久化落盘`,
      });
    } catch {
      toast({
        title: messages.common.error,
        description: "更新应用配置失败",
        variant: "destructive",
      });
    } finally {
      setIsSaving(false);
    }
  };

  const formatDate = (dateStr: string | null | undefined) => {
    if (!dateStr) return t.never;
    return new Date(dateStr).toLocaleDateString(locale === "zh" ? "zh-CN" : "en-US", {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "numeric",
      minute: "numeric",
    });
  };

  const buttonText = details.is_active ? t.pauseAccess : t.unpauseAccess;

  return (
    <div className="w-full max-w-[340px] mb-6">
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden shadow-sm">
        {/* Header with identity */}
        <div className="flex items-center justify-between bg-zinc-800/80 border-b border-zinc-700/60 p-3.5">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-7 h-7 flex items-center justify-center rounded-lg bg-zinc-700/80 text-zinc-300">
              {isSystem ? (
                <Server className="w-4 h-4 text-indigo-400" />
              ) : (
                <Bot className="w-4 h-4 text-sky-400" />
              )}
            </div>
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-zinc-100 truncate">
                {displayName}
              </h2>
              <span className="text-[10px] text-zinc-400 font-mono">
                id: {appId}
              </span>
            </div>
          </div>

          <Button
            size="sm"
            variant="ghost"
            onClick={() => setIsEditing(!isEditing)}
            className="h-7 w-7 p-0 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-700/60"
            title="编辑应用配置与别名"
          >
            <Settings2 className="h-4 w-4" />
          </Button>
        </div>

        {/* Edit Form or Display View */}
        <div className="p-3.5 space-y-3.5 text-xs">
          {isEditing ? (
            <div className="space-y-3 rounded-lg bg-zinc-950/70 p-3 border border-violet-500/30">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-violet-300">
                  基本管理与属性配置
                </span>
                <button
                  onClick={() => setIsEditing(false)}
                  className="text-zinc-500 hover:text-zinc-300"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>

              <div>
                <label className="block text-[11px] text-zinc-400 mb-1">
                  显示名称 / 别名
                </label>
                <Input
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="如: Claude Code"
                  className="h-8 text-xs bg-zinc-900 border-zinc-700 text-zinc-200"
                />
              </div>

              <div>
                <label className="block text-[11px] text-zinc-400 mb-1">
                  应用定位与功能描述
                </label>
                <Textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="如: 终端编码与系统运维 Agent 通道"
                  className="min-h-[60px] text-xs bg-zinc-900 border-zinc-700 text-zinc-200"
                />
              </div>

              <div className="flex justify-end gap-2 pt-1">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setIsEditing(false)}
                  className="h-7 text-xs text-zinc-400 hover:text-zinc-200"
                >
                  取消
                </Button>
                <Button
                  size="sm"
                  onClick={handleSaveSettings}
                  disabled={isSaving}
                  className="h-7 text-xs bg-violet-600 hover:bg-violet-500 text-white flex items-center gap-1"
                >
                  {isSaving ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Check className="h-3 w-3" />
                  )}
                  保存配置
                </Button>
              </div>
            </div>
          ) : (
            description && (
              <div className="rounded-lg bg-zinc-950/50 p-2.5 border border-zinc-800/80 text-[11px] text-zinc-400">
                {description}
              </div>
            )
          )}

          {/* Status & Stats info */}
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-lg bg-zinc-800/40 p-2 border border-zinc-800/60">
              <p className="text-[10px] text-zinc-500">{t.accessStatus}</p>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    details.is_active ? "bg-emerald-500" : "bg-red-500"
                  }`}
                />
                <span
                  className={`font-semibold ${
                    details.is_active ? "text-emerald-400" : "text-red-400"
                  }`}
                >
                  {details.is_active ? t.statusActive : t.statusInactive}
                </span>
              </div>
            </div>

            <div className="rounded-lg bg-zinc-800/40 p-2 border border-zinc-800/60">
              <p className="text-[10px] text-zinc-500">分类角色</p>
              <p className="font-semibold text-zinc-300 mt-0.5">
                {isSystem ? "系统内置中枢" : "外部接入 Agent"}
              </p>
            </div>
          </div>

          <div className="space-y-2 pt-1 border-t border-zinc-800/60">
            <div className="flex justify-between items-center text-zinc-400">
              <span>{t.totalMemoriesCreated}</span>
              <span className="font-semibold text-zinc-200">
                {details.total_memories_created} 条
              </span>
            </div>

            <div className="flex justify-between items-center text-zinc-400">
              <span>{t.totalMemoriesAccessed}</span>
              <span className="font-semibold text-zinc-200">
                {details.total_memories_accessed} 次
              </span>
            </div>

            <div className="flex justify-between items-center text-zinc-400">
              <span>{t.firstAccessed}</span>
              <span className="font-medium text-zinc-300 text-[11px]">
                {formatDate(details.first_accessed)}
              </span>
            </div>

            <div className="flex justify-between items-center text-zinc-400">
              <span>{t.lastAccessed}</span>
              <span className="font-medium text-zinc-300 text-[11px]">
                {formatDate(details.last_accessed)}
              </span>
            </div>
          </div>

          <hr className="border-zinc-800/80" />

          {/* Quick Actions */}
          <div className="space-y-2">
            <Link
              href={`/memories?query=&source_agent=${encodeURIComponent(appId)}`}
              className="w-full flex items-center justify-center gap-1.5 h-8 rounded-lg bg-zinc-800 hover:bg-zinc-700/80 text-zinc-200 font-medium text-xs transition-colors border border-zinc-700/40"
            >
              <ExternalLink className="h-3.5 w-3.5 text-zinc-400" />
              <span>查看此写入方的全部记忆</span>
            </Link>

            <Button
              onClick={handlePauseAccess}
              className={`w-full flex items-center justify-center gap-1.5 h-8 text-xs font-medium border transition-colors ${
                details.is_active
                  ? "bg-zinc-900 border-zinc-700/80 text-amber-400 hover:bg-amber-950/30 hover:border-amber-500/40"
                  : "bg-emerald-600/20 border-emerald-500/40 text-emerald-300 hover:bg-emerald-600/30"
              }`}
              size="sm"
              disabled={isLoading}
            >
              {isLoading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : details.is_active ? (
                <PauseIcon className="h-3.5 w-3.5" />
              ) : (
                <PlayIcon className="h-3.5 w-3.5" />
              )}
              {buttonText}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AppDetailCard;
