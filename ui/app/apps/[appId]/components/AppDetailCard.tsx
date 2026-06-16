import React, { useState } from "react";
import { Button } from "@/components/ui/button";
import { PauseIcon, Loader2, PlayIcon } from "lucide-react";
import { useAppsApi } from "@/hooks/useAppsApi";
import Image from "next/image";
import { useDispatch, useSelector } from "react-redux";
import { setAppDetails, AppDetails } from "@/store/appsSlice";
import { BiEditIcon as BiEdit } from "@/components/shared/react-icons";
import { constants } from "@/components/shared/source-app";
import { RootState } from "@/store/store";
import { useI18n } from "@/hooks/useI18n";
import { useToast } from "@/hooks/use-toast";

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
  const { updateAppDetails } = useAppsApi();
  const [isLoading, setIsLoading] = useState(false);
  const dispatch = useDispatch();
  const { messages, locale } = useI18n();
  const { toast } = useToast();
  const t = messages.apps;
  const apps = useSelector((state: RootState) => state.apps.apps);
  const currentApp = apps.find((app) => app.id === appId);
  const appConfig = currentApp
    ? constants[currentApp.name as keyof typeof constants] || constants.default
    : constants.default;

  const handlePauseAccess = async () => {
    setIsLoading(true);
    try {
      await updateAppDetails(appId, {
        is_active: !details.is_active,
      });
      dispatch(
        setAppDetails({ appId, isActive: !details.is_active })
      );
    } catch {
      toast({ title: messages.common.error, description: messages.apps.accessStatus, variant: "destructive" });
    } finally {
      setIsLoading(false);
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

  if (!selectedApp.details) return null;

  const details = selectedApp.details;
  const buttonText = details.is_active ? t.pauseAccess : t.unpauseAccess;

  return (
    <div>
      <div className="bg-zinc-900 border w-[320px] border-zinc-800 rounded-xl mb-6">
        <div className="flex items-center gap-2 mb-4 bg-zinc-800 rounded-t-xl p-3">
          <div className="w-5 h-5 flex items-center justify-center">
            {appConfig.iconImage ? (
              <div>
                <div className="w-6 h-6 rounded-full bg-zinc-700 flex items-center justify-center overflow-hidden">
                  <Image
                    src={appConfig.iconImage}
                    alt={appConfig.name}
                    width={40}
                    height={40}
                  />
                </div>
              </div>
            ) : (
              <div className="w-5 h-5 flex items-center justify-center bg-zinc-700 rounded-full">
                <BiEdit className="w-4 h-4 text-zinc-400" />
              </div>
            )}
          </div>
          <h2 className="text-md font-semibold">{appConfig.name}</h2>
        </div>

        <div className="space-y-4 p-3">
          <div>
            <p className="text-xs text-zinc-400">{t.accessStatus}</p>
            <p
              className={`font-medium ${
                details.is_active
                  ? "text-emerald-500"
                  : "text-red-500"
              }`}
            >
              {details.is_active ? t.statusActive : t.statusInactive}
            </p>
          </div>

          <div>
            <p className="text-xs text-zinc-400">{t.totalMemoriesCreated}</p>
            <p className="font-medium">
              {details.total_memories_created} {t.memoriesUnit}
            </p>
          </div>

          <div>
            <p className="text-xs text-zinc-400">{t.totalMemoriesAccessed}</p>
            <p className="font-medium">
              {details.total_memories_accessed} {t.memoriesUnit}
            </p>
          </div>

          <div>
            <p className="text-xs text-zinc-400">{t.firstAccessed}</p>
            <p className="font-medium">{formatDate(details.first_accessed)}</p>
          </div>

          <div>
            <p className="text-xs text-zinc-400">{t.lastAccessed}</p>
            <p className="font-medium">{formatDate(details.last_accessed)}</p>
          </div>

          <hr className="border-zinc-800" />

          <div className="flex gap-2 justify-end">
            <Button
              onClick={handlePauseAccess}
              className="flex bg-transparent w-[170px] bg-zinc-800 border-zinc-800 hover:bg-zinc-800 text-white"
              size="sm"
              disabled={isLoading}
            >
              {isLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : details.is_active ? (
                <PauseIcon className="h-4 w-4" />
              ) : (
                <PlayIcon className="h-4 w-4" />
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
