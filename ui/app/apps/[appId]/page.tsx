"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useSelector } from "react-redux";
import { RootState } from "@/store/store";
import { useAppsApi } from "@/hooks/useAppsApi";
import { useMemoriesApi } from "@/hooks/useMemoriesApi";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { MemoryCard } from "./components/MemoryCard";
import AppDetailCard from "./components/AppDetailCard";
import "@/styles/animation.css";
import NotFound from "@/app/not-found";
import { AppDetailCardSkeleton } from "@/skeleton/AppDetailCardSkeleton";
import { MemoryCardSkeleton } from "@/skeleton/MemoryCardSkeleton";
import { useUI } from "@/hooks/useUI";
import UpdateMemory from "@/components/shared/update-memory";

export default function AppDetailsPage() {
  const params = useParams();
  const router = useRouter();
  const appId = params.appId as string;
  const [activeTab, setActiveTab] = useState("created");
  const { fetchAppDetails, fetchAppMemories, fetchAppAccessedMemories, fetchApps } = useAppsApi();
  const { deleteMemories } = useMemoriesApi();
  const { updateMemoryDialog, handleOpenUpdateMemoryDialog, handleCloseUpdateMemoryDialog } = useUI();
  const selectedApp = useSelector((state: RootState) => state.apps.selectedApp);

  useEffect(() => { fetchApps({}); }, [fetchApps]);
  useEffect(() => {
    if (appId) {
      Promise.all([fetchAppDetails(appId), fetchAppMemories(appId), fetchAppAccessedMemories(appId)]).catch(() => {});
    }
  }, [appId, fetchAppDetails, fetchAppMemories, fetchAppAccessedMemories]);

  const handleDelete = async (memoryId: string) => {
    await deleteMemories([memoryId]);
    await fetchAppMemories(appId);
    await fetchAppDetails(appId);
    const updatedApps = await fetchApps({});
    if (updatedApps.apps.every((app) => app.id !== appId)) {
      router.push("/apps");
    }
  };

  const handleEdit = (memoryId: string) => {
    const memory = selectedApp.memories.created.items.find((m) => m.id === memoryId);
    if (memory) {
      handleOpenUpdateMemoryDialog(memoryId, memory.content);
    }
  };

  if (selectedApp.error) return <NotFound message={selectedApp.error} title="Error loading app details" />;
  if (!selectedApp.details) return (
    <div className="flex-1 py-6 text-foreground"><div className="container flex justify-between">
      <div className="flex-1 p-4 max-w-4xl animate-fade-slide-down"><div className="mb-6">
        <div className="h-10 w-64 bg-muted rounded animate-pulse mb-6" />
        <div className="space-y-6">{[...Array(3)].map((_, i) => <MemoryCardSkeleton key={i} />)}</div>
      </div></div>
      <div className="p-14 animate-fade-slide-down delay-2"><AppDetailCardSkeleton /></div>
    </div></div>
  );

  return (
    <div className="flex-1 py-6 text-foreground"><div className="container flex justify-between">
      <div className="flex-1 p-4 max-w-4xl animate-fade-slide-down">
        <Tabs defaultValue="created" className="mb-6" onValueChange={setActiveTab}>
          <TabsList className="bg-transparent border-b border-border rounded-none w-full justify-start gap-8 p-0">
            <TabsTrigger value="created" className={`px-0 pb-2 rounded-none data-[state=active]:border-b-2 data-[state=active]:border-primary data-[state=active]:shadow-none ${activeTab === "created" ? "text-foreground" : "text-muted-foreground"}`}>Created ({selectedApp.memories.created.total})</TabsTrigger>
            <TabsTrigger value="accessed" className={`px-0 pb-2 rounded-none data-[state=active]:border-b-2 data-[state=active]:border-primary data-[state=active]:shadow-none ${activeTab === "accessed" ? "text-foreground" : "text-muted-foreground"}`}>Accessed ({selectedApp.memories.accessed.total})</TabsTrigger>
          </TabsList>
          <TabsContent value="created" className="mt-6 space-y-6 animate-fade-slide-down delay-1">
            {selectedApp.memories.created.loading ? <div className="space-y-4">{[...Array(3)].map((_, i) => <MemoryCardSkeleton key={i} />)}</div>
              : selectedApp.memories.created.items.map((m) => <MemoryCard key={m.id + m.created_at} id={m.id} content={m.content} created_at={m.created_at} metadata={m.metadata_} categories={m.categories} app_name={m.app_name} state={m.state} onDelete={handleDelete} onEdit={handleEdit} />)}
          </TabsContent>
          <TabsContent value="accessed" className="mt-6 space-y-6 animate-fade-slide-down delay-1">
            {selectedApp.memories.accessed.loading ? <div className="space-y-4">{[...Array(3)].map((_, i) => <MemoryCardSkeleton key={i} />)}</div>
              : selectedApp.memories.accessed.items.map((a) => <div key={a.memory.id} className="relative"><MemoryCard id={a.memory.id} content={a.memory.content} created_at={a.memory.created_at} metadata={a.memory.metadata_} categories={a.memory.categories} access_count={a.access_count} app_name={a.memory.app_name} state={a.memory.state} onDelete={handleDelete} /></div>)}
          </TabsContent>
        </Tabs>
      </div>
      <div className="p-14 animate-fade-slide-down delay-2"><AppDetailCard appId={appId} selectedApp={selectedApp} /></div>
    </div>
    <UpdateMemory memoryId={updateMemoryDialog.memoryId || ""} memoryContent={updateMemoryDialog.memoryContent || ""} open={updateMemoryDialog.isOpen} onOpenChange={handleCloseUpdateMemoryDialog} />
    </div>
  );
}
