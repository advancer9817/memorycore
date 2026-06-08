"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode, useCallback, useState } from "react";
import { Settings } from "lucide-react";
import { CreateMemoryDialog } from "@/app/memories/components/CreateMemoryDialog";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { Button } from "@/components/ui/button";
import {
  FiRefreshCcwIcon as FiRefreshCcw,
  HiHomeIcon as HiHome,
  HiMiniRectangleStackIcon as HiMiniRectangleStack,
  RiApps2AddFillIcon as RiApps2AddFill,
} from "@/components/shared/react-icons";
import { useI18n } from "@/hooks/useI18n";
import { useToast } from "@/hooks/use-toast";

interface NavItem {
  href: string;
  label: string;
  icon: ReactNode;
}

async function refreshForPath(pathname: string): Promise<void> {
  const { getApiBaseUrl } = await import("@/lib/api-url");
  const base = getApiBaseUrl();
  const fetches: Promise<unknown>[] = [];

  if (pathname === "/") {
    fetches.push(
      fetch(`${base}/api/v1/stats`),
      fetch(`${base}/api/v1/memories/filter`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ page: 1, size: 20 }),
      })
    );
  } else if (pathname.startsWith("/memories")) {
    const sp = new URLSearchParams(window.location.search);
    fetches.push(
      fetch(`${base}/api/v1/memories/filter`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          page: Number(sp.get("page") || 1),
          size: Number(sp.get("size") || 20),
        }),
      })
    );
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
  const { messages } = useI18n();
  const { toast } = useToast();

  const handleRefresh = useCallback(async () => {
    if (isRefreshing) return;
    setIsRefreshing(true);
    try {
      await refreshForPath(pathname);
      const { store } = await import("@/store/store");
      const { resetMemoriesState } = await import("@/store/memoriesSlice");
      const { resetAppsState } = await import("@/store/appsSlice");
      const { resetProfileState } = await import("@/store/profileSlice");
      store.dispatch(resetMemoriesState());
      store.dispatch(resetAppsState());
      store.dispatch(resetProfileState());
      toast({ description: messages.nav.refreshed });
    } finally {
      setIsRefreshing(false);
    }
  }, [isRefreshing, messages.nav.refreshed, pathname, toast]);

  const isActive = (href: string): boolean => {
    if (href === "/") return pathname === href;
    return pathname.startsWith(href);
  };

  const navItems: NavItem[] = [
    { href: "/", label: messages.nav.dashboard, icon: <HiHome /> },
    { href: "/memories", label: messages.nav.memories, icon: <HiMiniRectangleStack /> },
    { href: "/apps", label: messages.nav.apps, icon: <RiApps2AddFill /> },
    { href: "/graph", label: messages.nav.graph, icon: null },
    { href: "/settings", label: messages.nav.settings, icon: <Settings className="h-4 w-4" /> },
  ];

  const activeClass = "bg-zinc-800 text-white border-zinc-600";
  const inactiveClass = "text-zinc-300";

  return (
    <header className="sticky top-0 z-50 w-full border-b border-zinc-800 bg-zinc-950/95 backdrop-blur supports-[backdrop-filter]:bg-zinc-950/60">
      <div className="container flex h-14 items-center justify-between gap-4">
        <Link href="/" className="flex shrink-0 items-center gap-2">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo.svg" alt="MemoryCore" width={26} height={26} />
          <span className="text-xl font-medium">MemoryCore</span>
        </Link>

        <nav className="hidden items-center gap-2 md:flex" aria-label="Primary">
          {navItems.map((item) => (
            <Link key={item.href} href={item.href}>
              <Button
                variant="outline"
                size="sm"
                className={`flex items-center gap-2 border-none ${
                  isActive(item.href) ? activeClass : inactiveClass
                }`}
              >
                {item.icon}
                {item.label}
              </Button>
            </Link>
          ))}
        </nav>

        <div className="flex shrink-0 items-center gap-3">
          <LanguageSwitcher />
          <Button
            onClick={handleRefresh}
            disabled={isRefreshing}
            variant="outline"
            size="sm"
            className="border-zinc-700/50 bg-zinc-900 hover:bg-zinc-800 disabled:opacity-60"
          >
            <FiRefreshCcw className={`transition-transform duration-500 ${isRefreshing ? "animate-spin" : ""}`} />
            {isRefreshing ? messages.nav.refreshing : messages.nav.refresh}
          </Button>
          <CreateMemoryDialog />
        </div>
      </div>
    </header>
  );
}
