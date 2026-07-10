"use client";

import { useRef, useState } from "react";
import { Download, Upload } from "lucide-react";
import { useSelector } from "react-redux";
import { useI18n } from "@/hooks/useI18n";
import { useToast } from "@/hooks/use-toast";
import type { RootState } from "@/store/store";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";

export function BackupSettings() {
  const [isUploading, setIsUploading] = useState(false);
  const [selectedFileName, setSelectedFileName] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const userId = useSelector((state: RootState) => state.profile.userId);
  const { messages } = useI18n();
  const { toast } = useToast();
  const s = messages.settings;
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "";

  const exportMemories = async () => {
    try {
      const response = await fetch(`${apiUrl}/api/v1/backup/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/zip" },
        body: JSON.stringify({ user_id: userId }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const url = window.URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "memories_export.zip";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch {
      toast({ title: s.exportFailed, variant: "destructive" });
    }
  };

  const importMemories = async () => {
    const file = fileInputRef.current?.files?.[0];
    if (!file) return;
    try {
      setIsUploading(true);
      const form = new FormData();
      form.append("file", file);
      form.append("user_id", String(userId));
      const response = await fetch(`${apiUrl}/api/v1/backup/import`, { method: "POST", body: form });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      await response.json();
      if (fileInputRef.current) fileInputRef.current.value = "";
      setSelectedFileName("");
    } catch {
      toast({ title: s.importFailed, variant: "destructive" });
    } finally {
      setIsUploading(false);
    }
  };

  return <Card>
    <CardHeader><CardTitle>{s.backupTitle}</CardTitle><CardDescription>{s.backupDescription}</CardDescription></CardHeader>
    <CardContent className="space-y-6">
      <div className="p-4 border border-zinc-800 rounded-lg space-y-2">
        <div className="text-sm font-medium">{s.exportTitle}</div><p className="text-xs text-muted-foreground">{s.exportDescription}</p>
        <Button type="button" className="bg-zinc-800 hover:bg-zinc-700" onClick={() => void exportMemories()}><Download className="h-4 w-4 mr-2" />{s.exportMemories}</Button>
      </div>
      <div className="p-4 border border-zinc-800 rounded-lg space-y-2">
        <div className="text-sm font-medium">{s.importTitle}</div><p className="text-xs text-muted-foreground">{s.importDescription}</p>
        <div className="flex items-center gap-3 flex-wrap">
          <input ref={fileInputRef} type="file" accept=".zip" className="hidden" onChange={(event) => setSelectedFileName(event.target.files?.[0]?.name || "")} />
          <Button type="button" className="bg-zinc-800 hover:bg-zinc-700" onClick={() => fileInputRef.current?.click()}><Upload className="h-4 w-4 mr-2" />{s.chooseZip}</Button>
          <span className="text-xs text-muted-foreground truncate max-w-[220px]">{selectedFileName || s.noFileSelected}</span>
          <div className="ml-auto"><Button type="button" disabled={isUploading || !selectedFileName} className="bg-primary hover:bg-primary/80 disabled:opacity-50" onClick={() => void importMemories()}>{isUploading ? s.uploading : s.import}</Button></div>
        </div>
      </div>
    </CardContent>
  </Card>;
}
