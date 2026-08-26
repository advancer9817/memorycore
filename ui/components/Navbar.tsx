"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode, useCallback, useEffect, useState } from "react";
import { Home, Layers3, Menu, Network, RefreshCcw, Settings, UserRound } from "lucide-react";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { useI18n } from "@/hooks/useI18n";
import { useToast } from "@/hooks/use-toast";
import { getApiBaseUrl } from "@/lib/api-url";

const CreateMemoryDialog = dynamic(
  () => import("@/app/memories/components/CreateMemoryDialog").then((mod) => mod.CreateMemoryDialog),
  { ssr: false }
);

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
    fetches.push(fetch(`${base}/api/v1/stats`));
  } else if (pathname.startsWith("/memories")) {
    return;
  } else if (pathname.startsWith("/apps")) {
    fetches.push(fetch(`${base}/api/v1/apps/`));
  } else if (pathname.startsWith("/settings")) {
    fetches.push(fetch(`${base}/api/v1/config`));
  } else if (pathname.startsWith("/governance")) {
    fetches.push(fetch(`${base}/api/v1/governance/metrics`));
    fetches.push(fetch(`${base}/api/v1/governance/decisions?review_status=actionable&limit=500`));
  } else if (pathname.startsWith("/profile")) {
    fetches.push(fetch(`${base}/api/v1/profile`));
  }

  await Promise.allSettled(fetches);
}

export function Navbar() {
  const pathname = usePathname();
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [actionableCount, setActionableCount] = useState(0);
  const { messages } = useI18n();
  const { toast } = useToast();

  // 轮询 governance actionable 计数
  useEffect(() => {
    const fetchActionableCount = async () => {
      try {
        const res = await fetch(`${getApiBaseUrl()}/api/v1/governance/counts`);
        if (!res.ok) return;
        const payload = await res.json();
        const data = payload.data ?? payload;
        // actionable = total - applied - rejected - rolled_back - auto_approved
        const total = data?.total ?? 0;
        const applied = data?.applied ?? 0;
        const rejected = data?.rejected ?? 0;
        const rolledBack = data?.rolled_back ?? 0;
        const autoApproved = data?.auto_approved ?? 0;
        const actionable = Math.max(0, total - applied - rejected - rolledBack - autoApproved);
        setActionableCount(actionable);
      } catch {
        // 静默失败，badge 不是关键功能
      }
    };

    fetchActionableCount();
    // 每 60 秒轮询一次
    const interval = setInterval(fetchActionableCount, 60_000);
    return () => clearInterval(interval);
  }, [pathname]);

  const handleRefresh = useCallback(async () => {
    if (isRefreshing) return;
    setIsRefreshing(true);
    try {
      const { store } = await import("@/store/store");
      if (pathname === "/") {
        const { requestDashboardRefresh } = await import("@/store/uiSlice");
        store.dispatch(requestDashboardRefresh());
      } else if (pathname.startsWith("/memories")) {
        const { requestMemoriesRefresh } = await import("@/store/memoriesSlice");
        store.dispatch(requestMemoriesRefresh());
      } else if (pathname.startsWith("/apps")) {
        const { requestAppsRefresh } = await import("@/store/appsSlice");
        store.dispatch(requestAppsRefresh());
      } else if (pathname.startsWith("/graph")) {
        const { requestGraphRefresh } = await import("@/store/uiSlice");
        store.dispatch(requestGraphRefresh());
      } else if (pathname.startsWith("/governance")) {
        const { requestGovernanceRefresh } = await import("@/store/uiSlice");
        store.dispatch(requestGovernanceRefresh());
      } else {
        await refreshForPath(pathname);
        const { resetProfileState } = await import("@/store/profileSlice");
        store.dispatch(resetProfileState());
      }
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
    { href: "/", label: messages.nav.dashboard, icon: <Home /> },
    { href: "/memories", label: messages.nav.memories, icon: <Layers3 /> },
    { href: "/graph", label: messages.nav.graph, icon: <Network className="h-4 w-4" /> },
    { href: "/profile", label: messages.nav.profile, icon: <UserRound className="h-4 w-4" /> },
    { href: "/settings", label: messages.nav.settings, icon: <Settings className="h-4 w-4" /> },
  ];

  const activeClass = "bg-zinc-800 text-white border-zinc-600";
  const inactiveClass = "text-zinc-300";

  const renderNavButton = (item: NavItem, mobileClose?: () => void) => (
    <Link key={item.href} href={item.href} onClick={mobileClose}>
      <Button
        variant={mobileClose ? "ghost" : "outline"}
        size="sm"
        className={`flex items-center gap-2 ${mobileClose ? "w-full justify-start" : "border-none"} ${
          mobileClose
            ? isActive(item.href) ? "bg-zinc-800 text-white" : "text-zinc-400 hover:text-white"
            : isActive(item.href) ? activeClass : inactiveClass
        }`}
      >
        {item.icon}
        {item.label}
        {item.href === "/" && actionableCount > 0 && (
          <span className="ml-0.5 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-amber-500 text-amber-950 text-[10px] font-bold leading-none">
            {actionableCount > 99 ? "99+" : actionableCount}
          </span>
        )}
      </Button>
    </Link>
  );

  return (
    <header className="sticky top-0 z-50 w-full border-b border-zinc-800 bg-zinc-950/95 backdrop-blur supports-[backdrop-filter]:bg-zinc-950/60">
      <div className="container flex h-14 items-center justify-between gap-4">
        <Link href="/" className="flex shrink-0 items-center gap-2">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo.svg" alt="MemoryCore" width={26} height={26} />
          <span className="text-xl font-medium">MemoryCore</span>
        </Link>

        <nav className="hidden items-center gap-2 md:flex" aria-label="Primary">
          {navItems.map((item) => renderNavButton(item))}
        </nav>

        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetTrigger asChild className="md:hidden">
            <Button variant="ghost" size="sm" className="text-zinc-300">
              <Menu className="h-5 w-5" />
              <span className="sr-only">{messages.nav.menu}</span>
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-64 bg-zinc-950 border-zinc-800 p-0">
            <div className="flex items-center gap-2 px-4 py-4 border-b border-zinc-800">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/logo.svg" alt="MemoryCore" width={24} height={24} />
              <span className="text-lg font-medium text-white">MemoryCore</span>
            </div>
            <nav className="flex flex-col gap-1 p-2" aria-label="Mobile">
              {navItems.map((item) => renderNavButton(item, () => setMobileOpen(false)))}
            </nav>
          </SheetContent>
        </Sheet>

        <div className="flex shrink-0 items-center gap-3">
          <LanguageSwitcher />
          <Button
            onClick={handleRefresh}
            disabled={isRefreshing}
            variant="outline"
            size="sm"
            className="border-zinc-700/50 bg-zinc-900 hover:bg-zinc-800 disabled:opacity-60"
          >
            <RefreshCcw className={`transition-transform duration-500 ${isRefreshing ? "animate-spin" : ""}`} />
            {isRefreshing ? messages.nav.refreshing : messages.nav.refresh}
          </Button>
          <CreateMemoryDialog />
        </div>
      </div>
    </header>
  );
}
