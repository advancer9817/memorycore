export interface GraphNode {
  id: string;
  title: string;
  type: string;
  status: string;
  importance: number;
  feedback_score: number;
  injected_count: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  relation_type: string;
  weight: number;
}

export const TYPE_COLORS: Record<string, string> = {
  project_memory: "#DA7756",
  feedback: "#6B9E78",
  user_profile: "#5B8DD9",
  decision: "#C4A35A",
  environment_fact: "#9B72CF",
  reference: "#E07B8C",
  episodic_memory: "#7DBDCF",
  skill_candidate: "#D4854E",
  timeline_event: "#E8A44E",
  unknown: "#A0A09A",
};

export const EDGE_COLORS: Record<string, string> = {
  related_to: "#444",
  supports: "#6B9E78",
  contradicts: "#E07B8C",
  part_of: "#555",
  supersedes: "#DA7756",
  causes: "#C4A35A",
  failure_pattern: "#E07B8C",
};

export const IMPORTANCE_THRESHOLD = 0.7;
