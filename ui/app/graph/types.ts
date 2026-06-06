export interface GraphNode {
  id: string;
  title: string;
  type: string;
  status: string;
  importance: number;
  feedback_score: number;
  injected_count: number;
  content: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  relation_type: string;
  weight: number;
}

// Scientific / Cyberpunk luminescent palette
export const TYPE_COLORS: Record<string, string> = {
  project_memory:   "#06B6D4", // cyan-500     — core knowledge structure
  feedback:         "#10B981", // emerald-500  — signal input
  user_profile:     "#3B82F6", // blue-500     — user directive
  decision:         "#FBBF24", // amber-400    — decision crystal
  environment_fact: "#8B5CF6", // violet-500   — proton purple static fact
  reference:        "#EC4899", // pink-500     — external anchor
  episodic_memory:  "#22D3EE", // cyan-400     — event memory
  skill_candidate:  "#F97316", // orange-500   — skill pointer
  timeline_event:   "#A78BFA", // violet-400   — temporal marker
  unknown:          "#64748B", // slate-500    — dust grey
};

export const EDGE_COLORS: Record<string, string> = {
  related_to:      "#3F3F46", // zinc-700   — ambient connection
  supports:        "#10B981", // emerald    — support signal
  contradicts:     "#F43F5E", // rose-500   — conflict alert
  part_of:         "#475569", // slate-600  — structural bond
  supersedes:      "#F97316", // orange-500 — override flow
  causes:          "#FBBF24", // amber-400  — causal chain
  failure_pattern: "#EF4444", // red-500    — failure marker
};

export const IMPORTANCE_THRESHOLD = 0.7;
