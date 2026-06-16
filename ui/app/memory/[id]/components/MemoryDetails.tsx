"use client";
import { MemoryActions } from "./MemoryActions";
import { ArrowLeft, Copy, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useRouter } from "next/navigation";
import { AccessLog } from "./AccessLog";
import Image from "next/image";
import Categories from "@/components/shared/categories";
import { useState } from "react";
import { useSelector } from "react-redux";
import { RootState } from "@/store/store";
import { constants } from "@/components/shared/source-app";
import { RelatedMemories } from "./RelatedMemories";
import { MemoryLineagePanel } from "@/components/dashboard/intelligence/MemoryLineagePanel";
import { useI18n } from "@/hooks/useI18n";

export function MemoryDetails() {
  const router = useRouter();
  const { messages } = useI18n();
  const memory = useSelector(
    (state: RootState) => state.memories.selectedMemory
  );
  const [copied, setCopied] = useState(false);
  const appConfig =
    constants[memory?.app_name as keyof typeof constants] || constants.default;
  const appLabel =
    constants[memory?.app_name as keyof typeof constants]?.name ||
    memory?.app_name ||
    appConfig.name;

  const handleCopy = async () => {
    if (memory?.id) {
      await navigator.clipboard.writeText(memory.id);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="container mx-auto py-6 px-4">
      <Button
        variant="ghost"
        className="mb-4 text-zinc-400 hover:text-white"
        onClick={() => router.back()}
      >
        <ArrowLeft className="h-4 w-4 mr-2" />
        {messages.memoryDetail.backToMemories}
      </Button>
      <div className="flex flex-col gap-4 w-full lg:flex-row">
        <div className="rounded-lg w-full lg:w-2/3 border h-fit pb-2 border-zinc-800 bg-zinc-900 overflow-hidden">
          <div className="">
            <div className="flex px-6 py-3 justify-between items-center mb-6 bg-zinc-800 border-b border-zinc-800">
              <div className="flex items-center gap-2">
                <h1 className="font-semibold text-white">
                  {messages.memoryDetail.memoryLabel}{" "}
                  <span className="ml-1 text-zinc-400 text-sm font-normal">
                    #{memory?.id?.slice(0, 6)}
                  </span>
                </h1>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={messages.memoryDetail.copyId}
                  className="h-4 w-4 text-zinc-400 hover:text-white -ml-[5px] mt-1"
                  onClick={handleCopy}
                >
                  {copied ? (
                    <Check className="h-3 w-3" />
                  ) : (
                    <Copy className="h-3 w-3" />
                  )}
                </Button>
              </div>
              <MemoryActions
                memoryId={memory?.id || ""}
                memoryContent={memory?.text || ""}
                memoryState={memory?.state || ""}
              />
            </div>

            <div className="px-6 py-2">
              <div className="border-l-2 border-primary pl-4 mb-6">
                <p
                  className={`${
                    memory?.state === "archived" || memory?.state === "paused"
                      ? "text-zinc-400"
                      : "text-white"
                  }`}
                >
                  {memory?.text}
                </p>
              </div>

              <div className="mt-6 pt-4 border-t border-zinc-800">
                <div className="flex justify-between items-center">
                  <div className="">
                    <Categories
                      categories={memory?.categories || []}
                      isPaused={
                        memory?.state === "archived" ||
                        memory?.state === "paused"
                      }
                    />
                  </div>
                  <div className="flex items-center gap-2 min-w-[300px] justify-end">
                    <div className="flex items-center gap-2">
                      <div className="flex items-center gap-1 bg-zinc-700 px-3 py-1 rounded-lg">
                        <span className="text-sm text-zinc-400">
                          {messages.memoryDetail.createdBy}
                        </span>
                        <div className="w-4 h-4 rounded-full bg-zinc-700 flex items-center justify-center overflow-hidden">
                          <Image
                            src={appConfig.iconImage}
                            alt={appLabel}
                            width={24}
                            height={24}
                          />
                        </div>
                        <p className="text-sm text-zinc-100 font-semibold">
                          {appLabel}
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div className="w-full lg:w-1/3 flex flex-col gap-4">
          <MemoryLineagePanel memoryId={memory?.id || ""} />
          <AccessLog memoryId={memory?.id || ""} />
          <RelatedMemories memoryId={memory?.id || ""} />
        </div>
      </div>
    </div>
  );
}
