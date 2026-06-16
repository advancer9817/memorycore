import Image from "next/image";
import { useEffect, useState } from "react";
import { useMemoriesApi } from "@/hooks/useMemoriesApi";
import { constants } from "@/components/shared/source-app";
import { useSelector } from "react-redux";
import { RootState } from "@/store/store";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useI18n } from "@/hooks/useI18n";

interface AccessLogEntry {
  id: string;
  app_name: string;
  accessed_at: string;
}

interface AccessLogProps {
  memoryId: string;
}

export function AccessLog({ memoryId }: AccessLogProps) {
  const { fetchAccessLogs } = useMemoriesApi();
  const accessEntries = useSelector(
    (state: RootState) => state.memories.accessLogs
  );
  const [isLoading, setIsLoading] = useState(true);
  const { messages, locale } = useI18n();
  const t = messages.memoryDetail;

  useEffect(() => {
    const loadAccessLogs = async () => {
      try {
        await fetchAccessLogs(memoryId);
      } finally {
        setIsLoading(false);
      }
    };

    loadAccessLogs();
  }, [memoryId, fetchAccessLogs]);

  if (isLoading) {
    return (
      <div className="w-full max-w-md mx-auto rounded-lg overflow-hidden bg-zinc-900 border border-zinc-800 text-white pb-1">
        <div className="px-6 py-4 bg-zinc-800 border-b border-zinc-800">
          <div className="h-4 w-24 bg-zinc-700 rounded animate-pulse" />
        </div>
        <div className="p-6 flex items-center justify-center min-h-[80px]">
          <p className="text-center text-zinc-500">{t.accessLogLoading}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full max-w-md mx-auto rounded-lg overflow-hidden bg-zinc-900 border border-zinc-800 text-white pb-1">
      <div className="px-6 py-4 flex justify-between items-center bg-zinc-800 border-b border-zinc-800">
        <h2 className="font-semibold">{t.accessLogTitle}</h2>
      </div>

      <ScrollArea className="p-6 max-h-[450px]">
        {accessEntries.length === 0 && (
          <div className="flex items-center justify-center min-h-[80px]">
            <p className="text-center text-zinc-500">
              {t.accessLogEmpty}
            </p>
          </div>
        )}
        <ul className="space-y-8">
          {accessEntries.map((entry: AccessLogEntry, index: number) => {
            const appConfig =
              constants[entry.app_name as keyof typeof constants] ||
              constants.default;

            return (
              <li key={entry.id} className="relative flex items-start gap-4">
                <div className="relative z-10 rounded-full overflow-hidden bg-[#2a2a2a] w-8 h-8 flex items-center justify-center flex-shrink-0">
                  {appConfig.iconImage ? (
                    <Image
                      src={appConfig.iconImage}
                      alt={`${appConfig.name} icon`}
                      width={30}
                      height={30}
                      className="w-8 h-8 object-contain"
                    />
                  ) : (
                    <div className="w-8 h-8 flex items-center justify-center">
                      {appConfig.icon}
                    </div>
                  )}
                </div>

                {index < accessEntries.length - 1 && (
                  <div className="absolute left-4 top-6 bottom-0 w-[1px] h-[calc(100%+1rem)] bg-[#333333] transform -translate-x-1/2"></div>
                )}

                <div className="flex flex-col">
                  <span className="font-medium">{appConfig.name}</span>
                  <span className="text-zinc-400 text-sm">
                    {new Date(entry.accessed_at + "Z").toLocaleDateString(
                      locale === "zh" ? "zh-CN" : "en-US",
                      {
                        year: "numeric",
                        month: "short",
                        day: "numeric",
                        hour: "numeric",
                        minute: "numeric",
                      }
                    )}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      </ScrollArea>
    </div>
  );
}
