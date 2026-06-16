import { useEffect, useState } from "react";
import { useMemoriesApi } from "@/hooks/useMemoriesApi";
import { useSelector } from "react-redux";
import { RootState } from "@/store/store";
import { Memory } from "@/components/types";
import Categories from "@/components/shared/categories";
import Link from "next/link";
import { formatDate } from "@/lib/helpers";
import { useI18n } from "@/hooks/useI18n";

interface RelatedMemoriesProps {
  memoryId: string;
}

export function RelatedMemories({ memoryId }: RelatedMemoriesProps) {
  const { fetchRelatedMemories } = useMemoriesApi();
  const relatedMemories = useSelector(
    (state: RootState) => state.memories.relatedMemories
  );
  const [isLoading, setIsLoading] = useState(true);
  const { messages, locale } = useI18n();
  const t = messages.memoryDetail;

  useEffect(() => {
    const loadRelatedMemories = async () => {
      try {
        await fetchRelatedMemories(memoryId);
      } finally {
        setIsLoading(false);
      }
    };

    loadRelatedMemories();
  }, [memoryId, fetchRelatedMemories]);

  if (isLoading) {
    return (
      <div className="w-full max-w-2xl mx-auto rounded-lg overflow-hidden bg-zinc-900 border border-zinc-800 text-white pb-1">
        <div className="px-6 py-4 bg-zinc-800 border-b border-zinc-800">
          <div className="h-4 w-32 bg-zinc-700 rounded animate-pulse" />
        </div>
        <div className="flex items-center justify-center min-h-[80px]">
          <p className="text-center text-zinc-500">{t.relatedMemoriesLoading}</p>
        </div>
      </div>
    );
  }

  if (!relatedMemories.length) {
    return (
      <div className="w-full max-w-2xl mx-auto rounded-lg overflow-hidden bg-zinc-900 border border-zinc-800 text-white p-6">
        <p className="text-center text-zinc-500">{t.relatedMemoriesEmpty}</p>
      </div>
    );
  }

  return (
    <div className="w-full max-w-2xl mx-auto rounded-lg overflow-hidden bg-zinc-900 border border-zinc-800 text-white">
      <div className="px-6 py-4 flex justify-between items-center bg-zinc-800 border-b border-zinc-800">
        <h2 className="font-semibold">{t.relatedMemoriesTitle}</h2>
      </div>
      <div className="space-y-6 p-6">
        {relatedMemories.map((memory: Memory) => (
          <div
            key={memory.id}
            className="border-l-2 border-zinc-800 pl-6 py-1 hover:bg-zinc-700/10 transition-colors cursor-pointer"
          >
            <Link href={`/memory/${memory.id}`}>
              <h3 className="font-medium mb-3">{memory.memory}</h3>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Categories
                    categories={memory.categories}
                    isPaused={
                      memory.state === "paused" || memory.state === "archived"
                    }
                    concat={true}
                  />
                  {memory.state !== "active" && (
                    <span className="inline-block px-3 border border-yellow-600 text-yellow-600 font-semibold text-xs rounded-full bg-yellow-400/10 backdrop-blur-sm">
                      {memory.state === "paused" ? t.statePaused : t.stateArchived}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-4">
                  <div className="text-zinc-400 text-sm">
                    {formatDate(memory.created_at, locale)}
                  </div>
                </div>
              </div>
            </Link>
          </div>
        ))}
      </div>
    </div>
  );
}
