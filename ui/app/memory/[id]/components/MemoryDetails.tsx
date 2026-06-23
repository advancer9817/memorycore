"use client";
import { useMemoriesApi } from "@/hooks/useMemoriesApi";
import { MemoryActions } from "./MemoryActions";
import { ArrowLeft, Copy, Check, ChevronDown, ChevronUp, CalendarClock, Calendar as CalendarIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Calendar } from "@/components/ui/calendar";
import { useRouter } from "next/navigation";
import { AccessLog } from "./AccessLog";
import Image from "next/image";
import Categories from "@/components/shared/categories";
import { useEffect, useState } from "react";
import { useSelector } from "react-redux";
import { RootState } from "@/store/store";
import { constants } from "@/components/shared/source-app";
import { RelatedMemories } from "./RelatedMemories";
import { MemoryLineage } from "./MemoryLineage";
import { cn } from "@/lib/utils";

function parseDateStr(s: string): Date | undefined {
  if (!s) return undefined;
  const d = new Date(s);
  return isNaN(d.getTime()) ? undefined : d;
}

function formatDateStr(d: Date | undefined): string {
  if (!d) return "";
  return d.toISOString().slice(0, 10);
}

function formatDisplay(s: string): string {
  if (!s) return "未设置";
  return s;
}

interface MemoryDetailsProps {
  memory_id: string;
}

export function MemoryDetails({ memory_id }: MemoryDetailsProps) {
  const router = useRouter();
  const { hasUpdates, updateValidityRange, isLoading } = useMemoriesApi();
  const memory = useSelector(
    (state: RootState) => state.memories.selectedMemory
  );
  const [copied, setCopied] = useState(false);
  const [validFrom, setValidFrom] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [validitySaved, setValiditySaved] = useState(false);
  const [validityExpanded, setValidityExpanded] = useState(false);
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

  const handleSaveValidity = async () => {
    if (!memory?.id) return;
    await updateValidityRange(memory.id, validFrom, validUntil);
    setValiditySaved(true);
    setTimeout(() => setValiditySaved(false), 2000);
  };


  useEffect(() => {
    if (memory) {
      setValidFrom((memory as any).valid_from ? (memory as any).valid_from.slice(0, 10) : "");
      setValidUntil((memory as any).valid_until ? (memory as any).valid_until.slice(0, 10) : "");
    }
  }, [memory?.id]);

  return (
    <div className="container mx-auto py-6 px-4">
      <Button
        variant="ghost"
        className="mb-4 text-zinc-400 hover:text-white"
        onClick={() => router.back()}
      >
        <ArrowLeft className="h-4 w-4 mr-2" />
        Back to Memories
      </Button>
      <div className="flex gap-4 w-full">
        <div className="rounded-lg w-2/3 border h-fit pb-2 border-zinc-800 bg-zinc-900 overflow-hidden">
          <div className="">
            <div className="flex px-6 py-3 justify-between items-center mb-6 bg-zinc-800 border-b border-zinc-800">
              <div className="flex items-center gap-2">
                <h1 className="font-semibold text-white">
                  Memory{" "}
                  <span className="ml-1 text-zinc-400 text-sm font-normal">
                    #{memory?.id?.slice(0, 6)}
                  </span>
                </h1>
                <Button
                  variant="ghost"
                  size="icon"
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
                          Created by:
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

                <div className="mt-4 pt-4 border-t border-zinc-800">
                  <button
                    className="flex items-center gap-2 w-full text-left group"
                    onClick={() => setValidityExpanded((v) => !v)}
                  >
                    <CalendarClock className="h-3.5 w-3.5 text-zinc-500" />
                    <span className="text-xs text-zinc-500 flex-1">Validity Range</span>
                    {(validFrom || validUntil) && (
                      <span className="text-xs text-zinc-400 mr-2">
                        {validFrom || "∞"} → {validUntil || "∞"}
                      </span>
                    )}
                    {validityExpanded ? (
                      <ChevronUp className="h-3.5 w-3.5 text-zinc-500" />
                    ) : (
                      <ChevronDown className="h-3.5 w-3.5 text-zinc-500" />
                    )}
                  </button>
                  {validityExpanded && (
                    <div className="flex gap-3 items-end mt-3">
                      <div className="flex-1 space-y-1">
                        <Label className="text-xs text-zinc-400">Valid From</Label>
                        <Popover>
                          <PopoverTrigger asChild>
                            <Button
                              variant="outline"
                              className={cn(
                                "w-full h-8 justify-start text-left text-sm font-normal border-zinc-700 bg-zinc-950 hover:bg-zinc-900",
                                !validFrom && "text-zinc-500"
                              )}
                            >
                              <CalendarIcon className="mr-2 h-3.5 w-3.5 text-zinc-400" />
                              {validFrom || "选择日期"}
                            </Button>
                          </PopoverTrigger>
                          <PopoverContent className="w-auto p-0 border-zinc-700 bg-zinc-900" align="start">
                            <Calendar
                              mode="single"
                              selected={parseDateStr(validFrom)}
                              onSelect={(d) => setValidFrom(formatDateStr(d))}
                              initialFocus
                            />
                          </PopoverContent>
                        </Popover>
                      </div>
                      <div className="flex-1 space-y-1">
                        <Label className="text-xs text-zinc-400">Valid Until</Label>
                        <Popover>
                          <PopoverTrigger asChild>
                            <Button
                              variant="outline"
                              className={cn(
                                "w-full h-8 justify-start text-left text-sm font-normal border-zinc-700 bg-zinc-950 hover:bg-zinc-900",
                                !validUntil && "text-zinc-500"
                              )}
                            >
                              <CalendarIcon className="mr-2 h-3.5 w-3.5 text-zinc-400" />
                              {validUntil || "选择日期"}
                            </Button>
                          </PopoverTrigger>
                          <PopoverContent className="w-auto p-0 border-zinc-700 bg-zinc-900" align="start">
                            <Calendar
                              mode="single"
                              selected={parseDateStr(validUntil)}
                              onSelect={(d) => setValidUntil(formatDateStr(d))}
                              initialFocus
                            />
                          </PopoverContent>
                        </Popover>
                      </div>
                      <Button
                        size="sm"
                        disabled={isLoading}
                        onClick={handleSaveValidity}
                        className="h-8 bg-primary hover:bg-primary/80 text-white text-xs"
                      >
                        {validitySaved ? <Check className="h-3 w-3" /> : "Save"}
                      </Button>
                    </div>
                  )}
                </div>

                {/* <div className="flex justify-end gap-2 w-full mt-2">
                <p className="text-sm font-semibold text-primary my-auto">
                    {new Date(memory.created_at).toLocaleString()}
                  </p>
                </div> */}
              </div>
            </div>
          </div>
        </div>
        <div className="w-1/3 flex flex-col gap-4">
          <AccessLog memoryId={memory?.id || ""} />
          <RelatedMemories memoryId={memory?.id || ""} />
          <MemoryLineage memoryId={memory?.id || ""} />
        </div>
      </div>
    </div>
  );
}
