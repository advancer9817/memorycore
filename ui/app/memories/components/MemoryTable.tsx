import { HighlightText } from "@/components/shared/HighlightText";
import {
  Edit,
  MoreHorizontal,
  Trash2,
  Pause,
  Archive,
  Play,
  ArrowUp,
  ArrowDown,
  Star,
  Ban,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useToast } from "@/hooks/use-toast";
import { useMemoriesApi } from "@/hooks/useMemoriesApi";
import { useDispatch, useSelector } from "react-redux";
import { RootState } from "@/store/store";
import {
  selectMemory,
  deselectMemory,
  selectAllMemories,
  clearSelection,
} from "@/store/memoriesSlice";
import SourceApp from "@/components/shared/source-app";
import { CiCalendarIcon as CiCalendar, GoPackageIcon as GoPackage, HiMiniRectangleStackIcon as HiMiniRectangleStack, PiSwatchesIcon as PiSwatches } from "@/components/shared/react-icons";
import { useRouter, useSearchParams } from "next/navigation";
import Categories from "@/components/shared/categories";
import { useUI } from "@/hooks/useUI";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { formatDate } from "@/lib/helpers";
import { useI18n } from "@/hooks/useI18n";

export function MemoryTable() {
  const { toast } = useToast();
  const { messages, locale } = useI18n();
  const router = useRouter();
  const searchParams = useSearchParams();
  const dispatch = useDispatch();

  const currentSort = searchParams.get("sort") || "created_at";
  const currentDir = (searchParams.get("dir") || "desc") as "asc" | "desc";
  const searchQuery = searchParams.get("query") || searchParams.get("q") || "";

  const handleSortByCreatedAt = () => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("sort", "created_at");
    if (currentSort === "created_at") {
      params.set("dir", currentDir === "asc" ? "desc" : "asc");
    } else {
      params.set("dir", "desc");
    }
    params.set("page", "1");
    router.push(`?${params.toString()}`);
  };
  const selectedMemoryIds = useSelector(
    (state: RootState) => state.memories.selectedMemoryIds
  );
  const memories = useSelector((state: RootState) => state.memories.memories);

  const { deleteMemories, updateMemoryState, isLoading } = useMemoriesApi();

  const handleDeleteMemory = (id: string) => {
    deleteMemories([id]);
  };

  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      dispatch(selectAllMemories());
    } else {
      dispatch(clearSelection());
    }
  };

  const handleSelectMemory = (id: string, checked: boolean) => {
    if (checked) {
      dispatch(selectMemory(id));
    } else {
      dispatch(deselectMemory(id));
    }
  };
  const { handleOpenUpdateMemoryDialog } = useUI();

  const handleEditMemory = (memory_id: string, memory_content: string) => {
    handleOpenUpdateMemoryDialog(memory_id, memory_content);
  };

  const handleUpdateMemoryState = async (id: string, newState: string) => {
    try {
      await updateMemoryState([id], newState);
    } catch (error) {
      toast({
        title: messages.common.error,
        description: messages.memories.updateStateFailure,
        variant: "destructive",
      });
    }
  };

  const isAllSelected =
    memories.length > 0 && selectedMemoryIds.length === memories.length;
  const isPartiallySelected =
    selectedMemoryIds.length > 0 && selectedMemoryIds.length < memories.length;

  const handleMemoryClick = (id: string) => {
    router.push(`/memory/${id}`);
  };

  return (
    <TooltipProvider>
    <div className="rounded-md border h-[calc(100vh-230px)] overflow-y-auto">
      <Table className="">
        <TableHeader className="sticky top-0 z-10 bg-zinc-900">
          <TableRow className="bg-zinc-800 hover:bg-zinc-800">
            <TableHead className="w-[50px] pl-4">
              <Checkbox
                className="data-[state=checked]:border-primary border-zinc-500/50"
                checked={isAllSelected}
                aria-label={messages.common.selectAll}
                data-state={
                  isPartiallySelected
                    ? "indeterminate"
                    : isAllSelected
                    ? "checked"
                    : "unchecked"
                }
                onCheckedChange={handleSelectAll}
              />
            </TableHead>
            <TableHead className="border-zinc-700">
              <div className="flex items-center min-w-[600px]">
                <HiMiniRectangleStack className="mr-1" />
                {messages.memories.memory}
              </div>
            </TableHead>
            <TableHead className="border-zinc-700">
              <div className="flex items-center">
                <PiSwatches className="mr-1" size={15} />
                {messages.memories.categories}
              </div>
            </TableHead>
            <TableHead className="w-[140px] border-zinc-700">
              <div className="flex items-center">
                <GoPackage className="mr-1" />
                {messages.memories.sourceApp}
              </div>
            </TableHead>
            <TableHead className="w-[140px] border-zinc-700">
              <button
                onClick={handleSortByCreatedAt}
                className="flex items-center w-full justify-center gap-1 hover:text-zinc-100 transition-colors cursor-pointer"
              >
                <CiCalendar className="mr-1" size={16} />
                {messages.memories.createdOn}
                {currentSort === "created_at" ? (
                  currentDir === "asc" ? (
                    <ArrowUp className="h-3 w-3 text-primary" />
                  ) : (
                    <ArrowDown className="h-3 w-3 text-primary" />
                  )
                ) : (
                  <ArrowDown className="h-3 w-3 text-zinc-600" />
                )}
              </button>
            </TableHead>
            <TableHead className="text-right border-zinc-700">
              <span className="sr-only">{messages.common.actions}</span>
              <div className="flex justify-center" aria-hidden="true">
                <MoreHorizontal className="h-4 w-4 mr-2" />
              </div>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {memories.map((memory) => {
            const isDisabled = memory.state === "paused" || memory.state === "archived";
            return (
            <TableRow
              key={memory.id}
              className={`hover:bg-zinc-900/50 ${
                isDisabled
                  ? "text-zinc-400"
                  : ""
              } ${isLoading ? "animate-pulse opacity-50" : ""}`}
            >
              <TableCell className="pl-4">
                <Checkbox
                  className="data-[state=checked]:border-primary border-zinc-500/50"
                  checked={selectedMemoryIds.includes(memory.id)}
                  aria-label={messages.common.selectRow(memory.memory.slice(0, 40))}
                  onCheckedChange={(checked) =>
                    handleSelectMemory(memory.id, checked as boolean)
                  }
                />
              </TableCell>
              <TableCell className="">
                {isDisabled ? (
                  <Tooltip delayDuration={0}>
                    <TooltipTrigger asChild>
                      <div
                        onClick={() => handleMemoryClick(memory.id)}
                        className="font-medium text-zinc-400 cursor-pointer"
                      >
                        <HighlightText text={memory.memory} query={searchQuery} />
                      </div>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>
                        {messages.memories.disabledMemory(memory.state === "paused" ? messages.memories.pausedState : messages.memories.archivedState)}
                      </p>
                    </TooltipContent>
                  </Tooltip>
                ) : (
                  <div
                    onClick={() => handleMemoryClick(memory.id)}
                    className="font-medium text-white cursor-pointer"
                  >
                    <HighlightText text={memory.memory} query={searchQuery} />
                  </div>
                )}
              </TableCell>
              <TableCell className="">
                <div className="flex flex-wrap gap-1">
                  <Categories
                    categories={memory.categories}
                    isPaused={isDisabled}
                    concat={true}
                  />
                </div>
              </TableCell>
              <TableCell className="w-[140px] text-center">
                <SourceApp source={memory.app_name} />
              </TableCell>
              <TableCell className="w-[140px] text-center">
                {formatDate(memory.created_at, locale)}
              </TableCell>
              <TableCell className="text-right flex items-center justify-end gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 text-zinc-400 hover:text-amber-400 hover:bg-zinc-800"
                  title="加星置顶保鲜 (重要度 0.95)"
                  onClick={async () => {
                    try {
                      await fetch(`/api/v1/memories/${memory.id}`, {
                        method: "PATCH",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ importance: 0.95 }),
                      });
                      toast({ title: "已加星置顶", description: "该记忆重要度提升至 0.95 并受防衰减保护。" });
                    } catch {
                      toast({ title: "置顶失败", variant: "destructive" });
                    }
                  }}
                >
                  <Star className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className={`h-8 w-8 ${memory.state === "archived" ? "text-emerald-400" : "text-zinc-400"} hover:bg-zinc-800`}
                  title={memory.state === "archived" ? "恢复活跃" : "一键归档"}
                  onClick={() => {
                    const newState = memory.state === "active" ? "archived" : "active";
                    handleUpdateMemoryState(memory.id, newState);
                  }}
                >
                  <Archive className="h-3.5 w-3.5" />
                </Button>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      aria-label={`${messages.common.actions}: ${memory.memory.slice(0, 40)}`}
                    >
                      <MoreHorizontal className="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    align="end"
                    className="bg-zinc-900 border-zinc-800"
                  >
                    <DropdownMenuItem
                      className="cursor-pointer text-amber-500 focus:text-amber-500"
                      onClick={async () => {
                        const reason = window.prompt("请输入废弃原因或替代记忆ID:");
                        if (reason !== null) {
                          try {
                            await handleUpdateMemoryState(memory.id, "superseded");
                            toast({ title: "已标记为废弃 (Superseded)", description: reason || "已标记" });
                          } catch {
                            toast({ title: "废弃操作失败", variant: "destructive" });
                          }
                        }
                      }}
                    >
                      <Ban className="mr-2 h-4 w-4" />
                      标记废弃 (Supersede)
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      className="cursor-pointer"
                      onClick={() => {
                        const newState =
                          memory.state === "active" ? "paused" : "active";
                        handleUpdateMemoryState(memory.id, newState);
                      }}
                    >
                      {memory?.state === "active" ? (
                        <>
                          <Pause className="mr-2 h-4 w-4" />
                          {messages.memories.pause}
                        </>
                      ) : (
                        <>
                          <Play className="mr-2 h-4 w-4" />
                          {messages.memories.resume}
                        </>
                      )}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      className="cursor-pointer"
                      onClick={() => {
                        const newState =
                          memory.state === "active" ? "archived" : "active";
                        handleUpdateMemoryState(memory.id, newState);
                      }}
                    >
                      <Archive className="mr-2 h-4 w-4" />
                      {memory?.state !== "archived" ? (
                        <>{messages.memories.archive}</>
                      ) : (
                        <>{messages.memories.unarchive}</>
                      )}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      className="cursor-pointer"
                      onClick={() => handleEditMemory(memory.id, memory.memory)}
                    >
                      <Edit className="mr-2 h-4 w-4" />
                      {messages.memories.edit}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      className="cursor-pointer text-red-500 focus:text-red-500"
                      onClick={() => handleDeleteMemory(memory.id)}
                    >
                      <Trash2 className="mr-2 h-4 w-4" />
                      {messages.memories.delete}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </TableCell>
            </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
    </TooltipProvider>
  );
}
