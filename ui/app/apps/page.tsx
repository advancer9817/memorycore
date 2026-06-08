"use client";

import { AppFilters } from "./components/AppFilters";
import { AppGrid } from "./components/AppGrid";
import "@/styles/animation.css";
import { useI18n } from "@/hooks/useI18n";

export default function AppsPage() {
  const { messages } = useI18n();

  return (
    <main className="flex-1 py-6">
      <div className="container">
        <div className="mb-6 animate-fade-slide-down">
          <h1 className="text-3xl font-bold tracking-tight text-white">{messages.apps.title}</h1>
          <p className="text-zinc-400 mt-1">
            {messages.apps.description}
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
