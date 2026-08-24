import type React from "react";
import { ArrowRight } from "lucide-react";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
} from "@/components/ui/card";

import { constants } from "@/components/shared/source-app";
import { App } from "@/store/appsSlice";
import Image from "next/image";
import Link from "next/link";
import { useI18n } from "@/hooks/useI18n";

interface AppCardProps {
  app: App;
}

export function AppCard({ app }: AppCardProps) {
  const { messages } = useI18n();
  const t = messages.apps;
  const appConfig =
    constants[app.name as keyof typeof constants] || constants.default;
  const isActive = app.is_active;

  return (
    <Card className="bg-zinc-900 text-white border-zinc-800">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-1">
          <div className="relative z-10 rounded-full overflow-hidden bg-[#2a2a2a] w-6 h-6 flex items-center justify-center flex-shrink-0">
            {appConfig.iconImage ? (
              <div className="w-6 h-6 rounded-full bg-zinc-700 flex items-center justify-center overflow-hidden">
                <Image
                  src={appConfig.iconImage}
                  alt={appConfig.name}
                  width={28}
                  height={28}
                />
              </div>
            ) : (
              <div className="w-6 h-6 flex items-center justify-center">
                {appConfig.icon}
              </div>
            )}
          </div>
          <h2 className="text-xl font-semibold">{appConfig.name}</h2>
        </div>
      </CardHeader>
      <CardContent className="pb-4 my-1">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="text-zinc-400 text-sm mb-1">{t.totalMemoriesCreated}</p>
            <p className="text-[11px] text-zinc-500 -mt-0.5 mb-1">{t.activeMemoriesHint}</p>
            <p className="text-xl font-medium">
              {app.total_memories_created.toLocaleString()} {t.memoriesUnit}
            </p>
          </div>
          <div>
            <p className="text-zinc-400 text-sm mb-1">{t.totalMemoriesAccessed}</p>
            <p className="text-xl font-medium">
              {app.total_memories_accessed.toLocaleString()} {t.memoriesUnit}
            </p>
          </div>
        </div>
      </CardContent>
      <CardFooter className="border-t border-zinc-800 p-0 px-6 py-2 flex justify-between items-center">
        <div
          className={`${
            isActive
              ? "bg-green-800 text-white hover:bg-green-500/20"
              : "bg-red-500/20 text-red-400 hover:bg-red-500/20"
          } rounded-lg px-2 py-0.5 flex items-center text-sm`}
        >
          <span className="h-2 w-2 my-auto mr-1 rounded-full inline-block bg-current"></span>
          {isActive ? t.statusActive : t.statusInactive}
        </div>
        <Link
          href={`/apps/${app.id}`}
          className="border border-zinc-700 bg-zinc-950 flex items-center px-3 py-1 text-sm rounded-lg text-white p-0 hover:bg-zinc-950/50 hover:text-white"
        >
          {t.viewDetails} <ArrowRight className="ml-2 h-4 w-4" />
        </Link>
      </CardFooter>
    </Card>
  );
}
