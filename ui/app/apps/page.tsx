"use client";

import { AppFilters } from "./components/AppFilters";
import { AppGrid } from "./components/AppGrid";
import "@/styles/animation.css";

export default function AppsPage() {
  return (
    <main className="flex-1 py-6">
      <div className="container">
        <div className="mb-6 animate-fade-slide-down">
          <h1 className="text-3xl font-bold tracking-tight">Agents & Clients</h1>
          <p className="text-muted-foreground mt-1">
            Monitor memory producers, client activity, and per-agent recall surfaces.
          </p>
        </div>
        <div className="mt-1 pb-4 animate-fade-slide-down">
          <AppFilters />
        </div>
        <div className="animate-fade-slide-down delay-1">
          <AppGrid />
        </div>
      </div>
    </main>
  );
}
