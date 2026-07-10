export const TYPE_COLORS: Record<string, string> = {
  project_memory: "#06B6D4",
  feedback: "#10B981",
  user_profile: "#3B82F6",
  decision: "#FBBF24",
  environment_fact: "#8B5CF6",
  reference: "#EC4899",
  episodic_memory: "#22D3EE",
  skill_candidate: "#F97316",
  timeline_event: "#A78BFA",
  unknown: "#64748B",
};

export const EDGE_COLORS: Record<string, string> = {
  related_to: "#38BDF8",
  supports: "#10B981",
  contradicts: "#F43F5E",
  part_of: "#C084FC",
  supersedes: "#F97316",
  causes: "#FBBF24",
  failure_pattern: "#EF4444",
};

export const TYPE_TEXT_CLASSES: Record<string, string> = {
  project_memory: "text-cyan-500",
  feedback: "text-emerald-500",
  user_profile: "text-blue-500",
  decision: "text-amber-400",
  environment_fact: "text-violet-500",
  reference: "text-pink-500",
  episodic_memory: "text-cyan-400",
  skill_candidate: "text-orange-500",
  timeline_event: "text-violet-400",
  unknown: "text-slate-500",
};

export const TYPE_BG_CLASSES: Record<string, string> = {
  project_memory: "bg-cyan-500",
  feedback: "bg-emerald-500",
  user_profile: "bg-blue-500",
  decision: "bg-amber-400",
  environment_fact: "bg-violet-500",
  reference: "bg-pink-500",
  episodic_memory: "bg-cyan-400",
  skill_candidate: "bg-orange-500",
  timeline_event: "bg-violet-400",
  unknown: "bg-slate-500",
};

export const GRAPH_SCENE = {
  background: "#020408",
  important: "#FBBF24",
  selected: "#60A5FA",
  dimNode: "rgba(30,30,35,0.10)",
  hiddenNode: "rgba(30,30,35,0.08)",
  fallbackEdge: "#3F3F46",
  particle: "#9CA3AF",
  tooltipFallback: "#888888",
  tooltipMuted: "#475569",
  ambientLight: "#06B6D4",
  keyLight: "#7DD3FC",
  fillLight: "#FBBF24",
  fogDensity: 0.0015,
  maxPixelRatio: 2,
} as const;

export const IMPORTANCE_THRESHOLD = 0.7;
export const KNOWN_EDGE_TYPES = Object.keys(EDGE_COLORS);
