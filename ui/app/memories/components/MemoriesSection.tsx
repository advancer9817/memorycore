import { useState, useEffect } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { FileStack } from "lucide-react";
import { MemoryTable } from "./MemoryTable";
import { MemoryPagination } from "./MemoryPagination";
import { CreateMemoryDialog } from "./CreateMemoryDialog";
import { PageSizeSelector } from "./PageSizeSelector";
import { useMemoriesApi } from "@/hooks/useMemoriesApi";
import { useSelector } from "react-redux";
import { RootState } from "@/store/store";
import { useRouter, useSearchParams } from "next/navigation";
import { MemoryTableSkeleton } from "@/skeleton/MemoryTableSkeleton";
import { useI18n } from "@/hooks/useI18n";

export function MemoriesSection() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { fetchMemories } = useMemoriesApi();
  const { messages } = useI18n();
  const memories = useSelector((state: RootState) => state.memories.memories);
  const refreshKey = useSelector((state: RootState) => state.memories.refreshKey);
  const [totalItems, setTotalItems] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [isLoading, setIsLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);

  const currentPage = Number(searchParams.get("page")) || 1;
  const itemsPerPage = Number(searchParams.get("size")) || 20;
  const sortColumn = searchParams.get("sort") || "created_at";
  const sortDirection = (searchParams.get("dir") || "desc") as "asc" | "desc";
  const searchQuery = searchParams.get("search") ?? "";

  useEffect(() => {
    const loadMemories = async () => {
      setIsLoading(true);
      setFetchError(null);
      try {
        const result = await fetchMemories(
          searchQuery,
          currentPage,
          itemsPerPage,
          { sortColumn, sortDirection },
          refreshKey > 0
        );
        setTotalItems(result.total);
        setTotalPages(result.pages);
      } catch {
        setFetchError(messages.memories.loadFailure);
      }
      setIsLoading(false);
    };

    loadMemories();
  }, [currentPage, itemsPerPage, sortColumn, sortDirection, searchQuery, fetchMemories, refreshKey, messages.memories.loadFailure]);

  const setCurrentPage = (page: number) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("page", page.toString());
    params.set("size", itemsPerPage.toString());
    router.push(`?${params.toString()}`);
  };

  const handlePageSizeChange = (size: number) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("page", "1");
    params.set("size", size.toString());
    router.push(`?${params.toString()}`);
  };

  if (isLoading) {
    return (
      <div className="w-full bg-transparent">
        <MemoryTableSkeleton />
        <div className="flex items-center justify-between mt-4">
          <div className="h-8 w-32 bg-zinc-800 rounded animate-pulse" />
          <div className="h-8 w-48 bg-zinc-800 rounded animate-pulse" />
          <div className="h-8 w-32 bg-zinc-800 rounded animate-pulse" />
        </div>
      </div>
    );
  }

  return (
    <div className="w-full bg-transparent">
      {fetchError && (
        <Alert variant="destructive" className="mb-4">
          <AlertDescription className="flex items-center justify-between">
            <span>{fetchError}</span>
            <Button
              size="sm"
              variant="outline"
              className="ml-4 shrink-0"
              onClick={() => {
                setFetchError(null);
                setIsLoading(true);
                fetchMemories(searchQuery, currentPage, itemsPerPage, { sortColumn, sortDirection }, true)
                  .then((r) => { setTotalItems(r.total); setTotalPages(r.pages); })
                  .catch(() => setFetchError(messages.memories.loadFailure))
                  .finally(() => setIsLoading(false));
              }}
            >
              {messages.common.retry}
            </Button>
          </AlertDescription>
        </Alert>
      )}
      <div>
        {memories.length > 0 ? (
          <>
            <MemoryTable />
            <div className="flex items-center justify-between mt-4">
              <PageSizeSelector
                pageSize={itemsPerPage}
                onPageSizeChange={handlePageSizeChange}
              />
              <div className="text-sm text-zinc-500 mr-2">
                {messages.memories.showingRange(
                  (currentPage - 1) * itemsPerPage + 1,
                  Math.min(currentPage * itemsPerPage, totalItems),
                  totalItems
                )}
              </div>
              <MemoryPagination
                currentPage={currentPage}
                totalPages={totalPages}
                setCurrentPage={setCurrentPage}
              />
            </div>
          </>
        ) : (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <div className="rounded-full bg-zinc-800 p-3 mb-4">
              <FileStack className="h-6 w-6 text-zinc-400" aria-hidden="true" />
            </div>
            <h3 className="text-lg font-medium">{messages.memories.noMemoriesFound}</h3>
            <p className="text-zinc-400 mt-1 mb-4">
              {searchQuery
                ? messages.memories.tryAdjustingFilters
                : messages.memories.createFirstMemory}
            </p>
            {searchQuery ? (
              <Button
                variant="outline"
                onClick={() => {
                  const params = new URLSearchParams(searchParams.toString());
                  params.delete("search");
                  router.push(`?${params.toString()}`);
                }}
              >
                {messages.common.clearFilters}
              </Button>
            ) : (
              <CreateMemoryDialog />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
