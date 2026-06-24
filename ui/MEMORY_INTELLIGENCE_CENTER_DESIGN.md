# Memory Intelligence Center: Design Implementation Guide

This document outlines the design and implementation guidance for replacing the lower Memories table on the MemoryCore Dashboard with a comprehensive Memory Intelligence Center. The design adheres to the existing dark zinc/violet shadcn/ui aesthetic.

## 1. Component Hierarchy and Naming

We recommend scaffolding a new module within `components/dashboard/` to contain the Intelligence Center widgets.

```text
app/page.tsx (DashboardPage)
├── components/dashboard/MemoryOperationsPanel.tsx (Existing Operations Cards)
└── components/dashboard/intelligence/MemoryIntelligenceCenter.tsx (New Wrapper)
    ├── NeedsAttentionWidget.tsx
    ├── MemoryHealthWidget.tsx
    ├── ActivityTimelineWidget.tsx
    ├── KnowledgeGraphSnapshotWidget.tsx
    └── SourceAgentBreakdownWidget.tsx
```

## 2. Layout & Responsive Grid

The layout should use Tailwind's CSS grid. The spacing follows the project's standard (`gap-6`).

*   **Desktop (`xl`):** 3-column layout.
*   **Tablet (`md`):** 2-column layout.
*   **Mobile (default):** 1-column vertical stack.

```tsx
// MemoryIntelligenceCenter.tsx
<div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6 mt-6">
  {/* Row 1 */}
  <div className="col-span-1"><NeedsAttentionWidget /></div>
  <div className="col-span-1"><MemoryHealthWidget /></div>
  <div className="col-span-1"><SourceAgentBreakdownWidget /></div>
  
  {/* Row 2 */}
  <div className="col-span-1 md:col-span-2"><ActivityTimelineWidget /></div>
  <div className="col-span-1"><KnowledgeGraphSnapshotWidget /></div>
</div>
```

## 3. Visual Style & Palette (Dark Zinc/Violet)

Leverage the existing shadcn/ui components (`Card`, `Badge`, `Progress`, `Chart`) configured with the current Tailwind theme.

*   **Widget Container:** `bg-zinc-900 border border-zinc-800 rounded-lg shadow-sm overflow-hidden`
*   **Header Area:** `bg-zinc-900 border-b border-zinc-800 p-4 flex items-center justify-between`
*   **Typography:**
    *   Titles: `text-white text-base font-semibold tracking-tight`
    *   Subtitles/Microcopy: `text-zinc-400 text-sm`
    *   Emphasis/Values: `text-white text-2xl font-bold`
*   **Accents:** Use the primary theme color (typically `text-violet-500` or `bg-violet-500` in this app context).
*   **Badges:** 
    *   Default: `bg-zinc-800 text-zinc-300 border-zinc-700 hover:bg-zinc-700`
    *   Warning: `bg-amber-500/10 text-amber-500 border-amber-500/20`
    *   Critical: `bg-red-500/10 text-red-500 border-red-500/20`

## 4. Widget Specifications & Microcopy

### A. Needs Attention Widget
*   **Purpose:** Surface memories with conflicts, missing relationships, or those marked as stale.
*   **Microcopy:**
    *   **Title:** Needs Attention
    *   **Description:** "Memories requiring review to maintain context accuracy."
*   **Content:** A list of 3-4 actionable items (e.g., "2 Contradictions Detected", "15 Stale Memories"). Include small "Review" link buttons.

### B. Memory Health Widget
*   **Purpose:** Provide a snapshot of overall memory ecosystem quality.
*   **Microcopy:**
    *   **Title:** Memory Health
*   **Content:**
    *   Use `components/ui/progress.tsx` for visual bars.
    *   Metrics: "Atomization Score" (e.g., 85%), "Connectivity Density" (e.g., 2.4 edges/node).

### C. Activity Timeline Widget
*   **Purpose:** Display recent ingestion and read/write activity.
*   **Microcopy:**
    *   **Title:** Activity Timeline
    *   **Description:** "Memory read and write volume over the last 7 days."
*   **Content:** Bar or Area chart (via Recharts / shadcn `chart.tsx`). 
    *   X-Axis: Days.
    *   Y-Axis: Events.
    *   Series: Writes (Violet), Reads (Zinc-600).

### D. Knowledge Graph Snapshot Widget
*   **Purpose:** Highlight central entities or clusters.
*   **Microcopy:**
    *   **Title:** Graph Snapshot
    *   **Description:** "Most connected entities in your context."
*   **Content:** A list of top 3-5 tags/entities with badge counts (e.g., `user_preferences: 24`, `project_setup: 12`).

### E. Source/Agent Breakdown Widget
*   **Purpose:** Show which integrations are contributing knowledge.
*   **Microcopy:**
    *   **Title:** Sources & Agents
*   **Content:** A mini horizontal stacked bar or a donut chart. Use the existing app icons mapped in `constants` for a visual list underneath.

## 5. UI States

Consistent states ensure a polished feel across the dashboard.

### Loading State
Use existing `components/ui/skeleton.tsx`.
```tsx
<div className="bg-zinc-900 border border-zinc-800 rounded-lg">
  <div className="border-b border-zinc-800 p-4">
    <Skeleton className="h-5 w-32 bg-zinc-800 rounded" />
  </div>
  <div className="p-4 space-y-3">
    <Skeleton className="h-10 w-full bg-zinc-800 rounded" />
    <Skeleton className="h-10 w-full bg-zinc-800 rounded" />
  </div>
</div>
```

### Empty State
Use a consistent empty state across widgets if data is 0.
```tsx
<div className="flex flex-col items-center justify-center h-32 p-4 text-center">
  {/* Insert Lucide icon like Inbox or CheckCircle2 */}
  <div className="w-8 h-8 rounded-full bg-zinc-800/50 flex items-center justify-center mb-3">
    <CheckCircle2Icon className="w-4 h-4 text-zinc-500" />
  </div>
  <p className="text-zinc-400 text-sm">All clear! No pending items.</p>
</div>
```

### Error State
For failed API calls.
```tsx
<div className="flex flex-col items-center justify-center h-32 p-4 text-center">
  <AlertTriangleIcon className="w-6 h-6 text-red-500/70 mb-2" />
  <p className="text-zinc-400 text-sm mb-3">Failed to load metrics.</p>
  <Button variant="outline" size="sm" className="h-8 border-zinc-700 bg-zinc-800 text-zinc-300">
    Retry
  </Button>
</div>
```

## 6. Implementation Checklist

1.  **Remove Old Components:** In `app/page.tsx`, remove `<MemoryFilters />` and `<MemoriesSection />` (they still live on `/memories`).
2.  **Scaffold Widgets:** Create the 5 widget components in `components/dashboard/intelligence/`.
3.  **Data Fetching Hooks:** Extend `useStats.ts` or add `useIntelligenceApi.ts` to fetch the specific data needed (e.g., breakdown, timeline).
4.  **Animations:** Add `<div className="animate-fade-slide-down delay-2">` wrappers around the new Intelligence Center in `app/page.tsx` to match the entrance animation of the top cards.
