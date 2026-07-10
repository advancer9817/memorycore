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

export {
  EDGE_COLORS,
  IMPORTANCE_THRESHOLD,
  GRAPH_SCENE,
  KNOWN_EDGE_TYPES,
  TYPE_BG_CLASSES,
  TYPE_COLORS,
  TYPE_TEXT_CLASSES,
} from "./graph-theme";
