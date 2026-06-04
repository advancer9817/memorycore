"use client";

import { Button } from "@/components/ui/button";
import { HiHome, HiMiniRectangleStack } from "react-icons/hi2";
import { RiApps2AddFill } from "react-icons/ri";
import { FiRefreshCcw } from "react-icons/fi";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { CreateMemoryDialog } from "@/app/memories/components/CreateMemoryDialog";
import { Settings } from "lucide-react";
import { useState, useCallback } from "react";
import { useToast } from "@/hooks/use-toast";

// Lazy refresh: only import API hooks when the refresh button is clicked.
// This avoids 4 unnecessary Redux subscriptions on every page render.
async function refreshForPath(pathname: string): Promise<void> {
  const { useMemoriesApi: _m, useAppsApi: _a, useStats: _s, useConfig: _c } = await Promise.resolve({
    useMemoriesApi: null, useAppsApi: null, useStats: null, useConfig: null,
  });
  // The actual fetch is triggered by the page's own useEffect after navigation.
  // For refresh we dynamically call the correct endpoint.
  const { getApiBaseUrl } = await import("@/lib/api-url");
  const base = getApiBaseUrl();
  const fetches: Promise<unknown>[] = [];

  if (pathname === "/") {
    fetches.push(fetch(`${base}/api/v1/stats`), fetch(`${base}/api/v1/memories/filter`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ page: 1, size: 20 }) }));
  } else if (pathname.startsWith("/memories")) {
    const sp = new URLSearchParams(window.location.search);
    fetches.push(fetch(`${base}/api/v1/memories/filter`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ page: Number(sp.get("page") || 1), size: Number(sp.get("size") || 20) }) }));
  } else if (pathname.startsWith("/apps")) {
    fetches.push(fetch(`${base}/api/v1/apps/`));
  } else if (pathname.startsWith("/settings")) {
    fetches.push(fetch(`${base}/api/v1/config`));
  } else if (pathname.startsWith("/graph")) {
    fetches.push(fetch(`${base}/api/graph`));
  }
  await Promise.allSettled(fetches);
}

export function Navbar() {
  const pathname = usePathname();
  const [isRefreshing, setIsRefreshing] = useState(false);
  const { toast } = useToast();

  const handleRefresh = useCallback(async () => {
    if (isRefreshing) return;
    setIsRefreshing(true);
    try {
      // Invalidate cache by dispatching a reset action, then reload the page data
      await refreshForPath(pathname);
      // Force page re-fetch by dispatching invalidation
      const { store } = await import("@/store/store");
      const { resetMemoriesState } = await import("@/store/memoriesSlice");
      const { resetAppsState } = await import("@/store/appsSlice");
      const { resetProfileState } = await import("@/store/profileSlice");
      store.dispatch(resetMemoriesState());
      store.dispatch(resetAppsState());
      store.dispatch(resetProfileState());
      toast({ description: "Refreshed successfully" });
    } finally {
      setIsRefreshing(false);
    }
  }, [isRefreshing, pathname, toast]);

  const isActive = (href: string) => {
    if (href === "/") return pathname === href;
    return pathname.startsWith(href.substring(0, 5));
  };

  const activeClass = "bg-zinc-800 text-white border-zinc-600";
  const inactiveClass = "text-zinc-300";

  return (
    <header className="sticky top-0 z-50 w-full border-b border-zinc-800 bg-zinc-950/95 backdrop-blur supports-[backdrop-filter]:bg-zinc-950/60">
      <div className="container flex h-14 items-center justify-between">
        <Link href="/" className="flex items-center gap-2">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo.svg" alt="MemoryCore" width={26} height={26} />
          <span className="text-xl font-medium">MemoryCore</span>
        </Link>
        <div className="flex items-center gap-2">
          <Link href="/">
            <Button
              variant="outline"
              size="sm"
              className={`flex items-center gap-2 border-none ${
                isActive("/") ? activeClass : inactiveClass
              }`}
            >
              <HiHome />
              Dashboard
            </Button>
          </Link>
          <Link href="/memories">
            <Button
              variant="outline"
              size="sm"
              className={`flex items-center gap-2 border-none ${
                isActive("/memories") ? activeClass : inactiveClass
              }`}
            >
              <HiMiniRectangleStack />
              Memories
            </Button>
          </Link>
          <Link href="/apps">
            <Button
              variant="outline"
              size="sm"
              className={`flex items-center gap-2 border-none ${
                isActive("/apps") ? activeClass : inactiveClass
              }`}
            >
              <RiApps2AddFill />
              Apps
            </Button>
          </Link>
          <Link href="/graph">
            <Button
              variant="outline"
              size="sm"
              className={`flex items-center gap-2 border-none ${
                isActive("/graph") ? activeClass : inactiveClass
              }`}
            >
              Graph
            </Button>
          </Link>
          <Link href="/settings">
            <Button
              variant="outline"
              size="sm"
              className={`flex items-center gap-2 border-none ${
                isActive("/settings") ? activeClass : inactiveClass
              }`}
            >
              <Settings />
              Settings
            </Button>
          </Link>
        </div>
        <div className="flex items-center gap-4">
          <Button
            onClick={handleRefresh}
            disabled={isRefreshing}
            variant="outline"
            size="sm"
            className="border-zinc-700/50 bg-zinc-900 hover:bg-zinc-800 disabled:opacity-60"
          >
            <FiRefreshCcw className={`transition-transform duration-500 ${isRefreshing ? "animate-spin" : ""}`} />
            {isRefreshing ? "Refreshing..." : "Refresh"}
          </Button>
          <CreateMemoryDialog />
        </div>
      </div>
    </header>
  );
}
