import type {
  ContradictionFinding,
  GovernanceDecision,
  ImportanceReassessmentFinding,
  SemanticDuplicateFinding,
  SplitCandidateFinding,
} from "@/components/dashboard/intelligence/types";
import type { Messages } from "@/lib/i18n/types";
import { MemorySnapshotCompare } from "./MemorySnapshotCompare";
import {
  ContradictionPanel,
  ImportanceReassessmentPanel,
  SemanticDuplicatePanel,
  SplitCandidatePanel,
} from "./panels";

interface DecisionOverviewPanelProps {
  decision: GovernanceDecision;
  messages: Messages["governance"];
}

export function DecisionOverviewPanel({ decision, messages }: DecisionOverviewPanelProps) {
  const finding = decision.finding;

  switch (decision.decision_type) {
    case "contradiction":
      return <ContradictionPanel finding={finding as unknown as ContradictionFinding} messages={messages} />;
    case "semantic_duplicate":
      return <SemanticDuplicatePanel finding={finding as unknown as SemanticDuplicateFinding} messages={messages} />;
    case "importance_reassessment":
      return <ImportanceReassessmentPanel finding={finding as unknown as ImportanceReassessmentFinding} messages={messages} />;
    case "split_candidate":
      return <SplitCandidatePanel finding={finding as unknown as SplitCandidateFinding} messages={messages} />;
    default:
      return (
        <MemorySnapshotCompare
          beforeState={decision.before_state}
          afterState={decision.after_state}
          messages={messages}
        />
      );
  }
}
