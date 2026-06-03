import { Button } from "@/components/ui/button";
import { Pencil, Archive, Trash, Pause, Play, ChevronDown } from "lucide-react";
import { useUI } from "@/hooks/useUI";
import { useMemoriesApi } from "@/hooks/useMemoriesApi";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";

interface MemoryActionsProps {
  memoryId: string;
  memoryContent: string;
  memoryState: string;
}

export function MemoryActions({
  memoryId,
  memoryContent,
  memoryState,
}: MemoryActionsProps) {
  const { handleOpenUpdateMemoryDialog } = useUI();
  const { updateMemoryState, isLoading } = useMemoriesApi();

  const handleEdit = () => {
    handleOpenUpdateMemoryDialog(memoryId, memoryContent);
  };

  const handleStateChange = (newState: string) => {
    updateMemoryState([memoryId], newState);
  };

  const getStateLabel = () => {
    switch (memoryState) {
      case "archived":
        return "Archived";
      case "paused":
        return "Paused";
      default:
        return "Active";
    }
  };

  const getStateIcon = () => {
    switch (memoryState) {
      case "archived":
        return <Archive className="h-3 w-3 mr-2" />;
      case "paused":
        return <Pause className="h-3 w-3 mr-2" />;
      default:
        return <Play className="h-3 w-3 mr-2" />;
    }
  };

  return (
    <div className="flex gap-2">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            disabled={isLoading}
            variant="outline"
            size="sm"
            className="shadow-md bg-card border border-zinc-500/50 hover:bg-background text-muted-foreground"
          >
            <span className="font-semibold">{getStateLabel()}</span>
            <ChevronDown className="h-3 w-3 mt-1 -ml-1" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent className="w-40 bg-zinc-900 border-zinc-800 text-foreground">
          <DropdownMenuLabel>Change State</DropdownMenuLabel>
          <DropdownMenuSeparator className="bg-muted" />
          <DropdownMenuItem
            onClick={() => handleStateChange("active")}
            className="cursor-pointer flex items-center"
            disabled={memoryState === "active"}
          >
            <Play className="h-3 w-3 mr-2" />
            <span className="font-semibold">Active</span>
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => handleStateChange("paused")}
            className="cursor-pointer flex items-center"
            disabled={memoryState === "paused"}
          >
            <Pause className="h-3 w-3 mr-2" />
            <span className="font-semibold">Pause</span>
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => handleStateChange("archived")}
            className="cursor-pointer flex items-center"
            disabled={memoryState === "archived"}
          >
            <Archive className="h-3 w-3 mr-2" />
            <span className="font-semibold">Archive</span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Button
        disabled={isLoading}
        variant="outline"
        size="sm"
        onClick={handleEdit}
        className="shadow-md bg-card border border-zinc-500/50 hover:bg-background text-muted-foreground"
      >
        <Pencil className="h-3 w-3 -mr-1" />
        <span className="font-semibold">Edit</span>
      </Button>
    </div>
  );
}
