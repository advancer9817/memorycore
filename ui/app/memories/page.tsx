"use client";

import { useEffect } from "react";
import { MemoriesSection } from "@/app/memories/components/MemoriesSection";
import { MemoryFilters } from "@/app/memories/components/MemoryFilters";
import { useRouter, useSearchParams } from "next/navigation";
import UpdateMemory from "@/components/shared/update-memory";
import { PageShell } from "@/components/shared/PageShell";
import { useUI } from "@/hooks/useUI";

export default function MemoriesPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { updateMemoryDialog, handleCloseUpdateMemoryDialog } = useUI();
  useEffect(() => {
    if (!searchParams.has("page") || !searchParams.has("size")) {
      const params = new URLSearchParams(searchParams.toString());
      if (!searchParams.has("page")) params.set("page", "1");
      if (!searchParams.has("size")) params.set("size", "20");
      if (!searchParams.has("sort")) params.set("sort", "created_at");
      if (!searchParams.has("dir")) params.set("dir", "desc");
      router.push(`?${params.toString()}`);
    }
  }, []);

  return (
    <PageShell>
      <UpdateMemory
        memoryId={updateMemoryDialog.memoryId || ""}
        memoryContent={updateMemoryDialog.memoryContent || ""}
        open={updateMemoryDialog.isOpen}
        onOpenChange={handleCloseUpdateMemoryDialog}
      />
      <div className="pb-4 animate-fade-slide-down">
        <MemoryFilters />
      </div>
      <div className="animate-fade-slide-down delay-1">
        <MemoriesSection />
      </div>
    </PageShell>
  );
}
