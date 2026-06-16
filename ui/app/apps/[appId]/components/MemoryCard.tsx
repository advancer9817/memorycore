"use client";

import { useState } from "react";
import { Edit, Trash2 } from "lucide-react";
import Categories from "@/components/shared/categories";
import Link from "next/link";
import { constants } from "@/components/shared/source-app";
import Image from "next/image";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useI18n } from "@/hooks/useI18n";

interface MemoryCardProps {
  id: string;
  content: string;
  created_at: string;
  metadata?: Record<string, unknown>;
  categories?: string[];
  access_count?: number;
  app_name: string;
  state: string;
  onDelete?: (id: string) => void;
  onEdit?: (id: string) => void;
}

export function MemoryCard({
  id,
  content,
  created_at,
  metadata,
  categories,
  access_count,
  app_name,
  state,
  onDelete,
  onEdit,
}: MemoryCardProps) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const { messages, locale } = useI18n();
  const t = messages.apps;
  const td = messages.memoryDetail;

  const appConfig =
    constants[app_name as keyof typeof constants] || constants.default;
  const appLabel =
    constants[app_name as keyof typeof constants]?.name || app_name || appConfig.name;

  const formatCreatedAt = (value: string): string => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleDateString(locale === "zh" ? "zh-CN" : "en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "numeric",
    });
  };

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 overflow-hidden group">
      <div className="p-4">
        <div className="border-l-2 border-primary pl-4 mb-4">
          <p
            className={`${state !== "active" ? "text-zinc-400" : "text-white"}`}
          >
            {content}
          </p>
        </div>

        {metadata && Object.keys(metadata).length > 0 && (
          <div className="mb-4">
            <p className="text-xs text-zinc-500 uppercase mb-2">{t.metadata}</p>
            <div className="bg-zinc-800 rounded p-3 text-zinc-400">
              <pre className="whitespace-pre-wrap">
                {JSON.stringify(metadata, null, 2)}
              </pre>
            </div>
          </div>
        )}

        <div className="mb-2">
          <Categories
            categories={categories as string[]}
            isPaused={state !== "active"}
          />
        </div>

        <div className="flex justify-between items-center">
          <div className="flex items-center gap-2">
            <span className="text-zinc-400 text-sm">
              {access_count ? (
                <span className="relative top-1">
                  {t.accessedTimes(access_count)}
                </span>
              ) : (
                formatCreatedAt(created_at)
              )}
            </span>

            {state !== "active" && (
              <span className="inline-block px-3 border border-yellow-600 text-yellow-600 font-semibold text-xs rounded-full bg-yellow-400/10 backdrop-blur-sm">
                {state === "paused" ? td.statePaused : td.stateArchived}
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            {(onEdit || onDelete) && (
              <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                {onEdit && (
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t.editMemory}
                    className="h-8 w-8 text-zinc-500 hover:text-primary"
                    onClick={() => onEdit(id)}
                  >
                    <Edit className="h-4 w-4" />
                  </Button>
                )}
                {onDelete && (
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t.deleteMemory}
                    className="h-8 w-8 text-zinc-500 hover:text-red-400"
                    onClick={() => setConfirmDelete(true)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                )}
              </div>
            )}

            {!app_name && (
              <Link
                href={`/memory/${id}`}
                className="hover:cursor-pointer bg-zinc-800 hover:bg-zinc-700 flex items-center px-3 py-1 text-sm rounded-lg text-white p-0 hover:text-white"
              >
                {t.viewDetails}
              </Link>
            )}
            {app_name && (
              <div className="flex items-center gap-1 bg-zinc-700 px-3 py-1 rounded-lg">
                <span className="text-sm text-zinc-400">{t.createdBy}</span>
                <div className="w-5 h-5 rounded-full bg-zinc-700 flex items-center justify-center overflow-hidden">
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
            )}
          </div>
        </div>
      </div>

      <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <AlertDialogContent className="bg-zinc-900 border-zinc-800">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-white">{t.deleteConfirmTitle}</AlertDialogTitle>
            <AlertDialogDescription className="text-zinc-400">
              {t.deleteConfirmDescription}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="bg-zinc-800 border-zinc-700 text-zinc-300 hover:bg-zinc-700">
              {t.cancel}
            </AlertDialogCancel>
            <AlertDialogAction
              className="bg-red-600 hover:bg-red-700 text-white"
              onClick={() => {
                onDelete?.(id);
                setConfirmDelete(false);
              }}
            >
              {t.delete}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
