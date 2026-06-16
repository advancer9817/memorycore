import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/hooks/useI18n";

interface MemoryPaginationProps {
  currentPage: number;
  totalPages: number;
  setCurrentPage: (page: number) => void;
}

export function MemoryPagination({
  currentPage,
  totalPages,
  setCurrentPage,
}: MemoryPaginationProps) {
  const { messages } = useI18n();

  return (
    <div className="flex items-center justify-between my-auto">
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="icon"
          aria-label={messages.common.previousPage}
          onClick={() => setCurrentPage(Math.max(currentPage - 1, 1))}
          disabled={currentPage === 1}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <div className="text-sm">
          {messages.common.page} {currentPage} {messages.common.of} {totalPages}
        </div>
        <Button
          variant="outline"
          size="icon"
          aria-label={messages.common.nextPage}
          onClick={() => setCurrentPage(Math.min(currentPage + 1, totalPages))}
          disabled={currentPage === totalPages}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
