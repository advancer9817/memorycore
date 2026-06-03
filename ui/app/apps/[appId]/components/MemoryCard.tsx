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

function formatCreatedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "numeric",
  });
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
  const appConfig =
    constants[app_name as keyof typeof constants] || constants.default;
  const appLabel =
    constants[app_name as keyof typeof constants]?.name || app_name || appConfig.name;

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden group">
      <div className="p-4">
        <div className="border-l-2 border-primary pl-4 mb-4">
          <p
            className={`${state !== "active" ? "text-muted-foreground" : "text-foreground"}`}
          >
            {content}
          </p>
        </div>

        {metadata && Object.keys(metadata).length > 0 && (
          <div className="mb-4">
            <p className="text-xs text-muted-foreground uppercase mb-2">METADATA</p>
            <div className="bg-muted rounded p-3 text-muted-foreground">
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
            <span className="text-muted-foreground text-sm">
              {access_count ? (
                <span className="relative top-1">
                  Accessed {access_count} times
                </span>
              ) : (
                formatCreatedAt(created_at)
              )}
            </span>

            {state !== "active" && (
              <span className="inline-block px-3 border border-yellow-600 text-yellow-600 font-semibold text-xs rounded-full bg-yellow-400/10 backdrop-blur-sm">
                {state === "paused" ? "Paused" : "Archived"}
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
                    className="h-8 w-8 text-muted-foreground hover:text-primary"
                    onClick={() => onEdit(id)}
                  >
                    <Edit className="h-4 w-4" />
                  </Button>
                )}
                {onDelete && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-muted-foreground hover:text-red-400"
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
                className="hover:cursor-pointer bg-muted hover:bg-muted flex items-center px-3 py-1 text-sm rounded-lg text-foreground p-0 hover:text-foreground"
              >
                View Details
              </Link>
            )}
            {app_name && (
              <div className="flex items-center gap-1 bg-zinc-700 px-3 py-1 rounded-lg">
                <span className="text-sm text-muted-foreground">Created by:</span>
                <div className="w-5 h-5 rounded-full bg-zinc-700 flex items-center justify-center overflow-hidden">
                  <Image
                    src={appConfig.iconImage}
                    alt={appLabel}
                    width={24}
                    height={24}
                  />
                </div>
                <p className="text-sm text-foreground font-semibold">
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
            <AlertDialogTitle className="text-foreground">Delete this memory?</AlertDialogTitle>
            <AlertDialogDescription className="text-muted-foreground">
              This will archive the memory. This action cannot be easily undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="bg-muted border-border text-foreground/80 hover:bg-muted">
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              className="bg-red-600 hover:bg-red-700 text-foreground"
              onClick={() => {
                onDelete?.(id);
                setConfirmDelete(false);
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
