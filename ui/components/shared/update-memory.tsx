"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { useRef } from "react";
import { Loader2 } from "lucide-react";
import { useMemoriesApi } from "@/hooks/useMemoriesApi";
import { useToast } from "@/hooks/use-toast";
import { Textarea } from "@/components/ui/textarea";
import { usePathname } from "next/navigation";
import { useI18n } from "@/hooks/useI18n";

interface UpdateMemoryProps {
  memoryId: string;
  memoryContent: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const UpdateMemory = ({
  memoryId,
  memoryContent,
  open,
  onOpenChange,
}: UpdateMemoryProps) => {
  const { updateMemory, isLoading, fetchMemories, fetchMemoryById } =
    useMemoriesApi();
  const textRef = useRef<HTMLTextAreaElement>(null);
  const pathname = usePathname();
  const { messages } = useI18n();
  const { toast } = useToast();
  const t = messages.memories;

  const handleUpdateMemory = async (text: string) => {
    try {
      await updateMemory(memoryId, text);
      toast({ description: t.updateSuccess });
      onOpenChange(false);
      if (pathname.includes("memories")) {
        await fetchMemories();
      } else {
        await fetchMemoryById(memoryId);
      }
    } catch {
      toast({ description: t.updateFailure, variant: "destructive" });
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[525px] bg-zinc-900 border-zinc-800 z-50">
        <DialogHeader>
          <DialogTitle>{t.updateDialogTitle}</DialogTitle>
          <DialogDescription>{t.updateDialogDescription}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <div className="grid gap-2">
            <Label htmlFor="memory">{t.createLabel}</Label>
            <Textarea
              ref={textRef}
              id="memory"
              className="bg-zinc-950 border-zinc-800 min-h-[150px]"
              defaultValue={memoryContent}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t.createCancel}
          </Button>
          <Button
            className="w-[140px]"
            disabled={isLoading}
            onClick={() => handleUpdateMemory(textRef?.current?.value || "")}
          >
            {isLoading ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              t.updateButton
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default UpdateMemory;
