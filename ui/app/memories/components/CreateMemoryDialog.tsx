"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { useState, useRef } from "react";
import { GoPlusIcon as GoPlus } from "@/components/shared/react-icons";
import { Loader2 } from "lucide-react";
import { useMemoriesApi } from "@/hooks/useMemoriesApi";
import { useToast } from "@/hooks/use-toast";
import { Textarea } from "@/components/ui/textarea";
import { useI18n } from "@/hooks/useI18n";

export function CreateMemoryDialog() {
  const { createMemory, isLoading, fetchMemories } = useMemoriesApi();
  const [open, setOpen] = useState(false);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const { messages } = useI18n();
  const { toast } = useToast();
  const t = messages.memories;

  const handleCreateMemory = async (text: string) => {
    try {
      await createMemory(text);
      toast({ description: t.createSuccess });
      setOpen(false);
      await fetchMemories();
    } catch {
      toast({ description: t.createFailure, variant: "destructive" });
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="bg-primary hover:bg-primary/90 text-white"
        >
          <GoPlus />
          {t.createButton}
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-[525px] bg-zinc-900 border-zinc-800">
        <DialogHeader>
          <DialogTitle>{t.createDialogTitle}</DialogTitle>
          <DialogDescription>
            {t.createDialogDescription}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <div className="grid gap-2">
            <Label htmlFor="memory">{t.createLabel}</Label>
            <Textarea
              ref={textRef}
              id="memory"
              placeholder={t.createPlaceholder}
              className="bg-zinc-950 border-zinc-800 min-h-[150px]"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            {t.createCancel}
          </Button>
          <Button
            disabled={isLoading}
            onClick={() => handleCreateMemory(textRef?.current?.value || "")}
          >
            {isLoading ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              t.createSave
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
