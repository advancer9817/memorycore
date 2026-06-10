"""Typed governance mutation requests and deterministic validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

POLICY_VERSION = "2026-06-10.1"
VALID_ORIGINS = {"llm_curator", "rule_curator", "governance", "atomization", "mcp", "ui", "cli", "maintenance"}
VALID_RISK_LEVELS = {"low", "medium", "high"}
VALID_ACTION_TYPES = {
    "memory_update",
    "memory_insert",
    "memory_archive",
    "memory_status_update",
    "memory_importance_update",
    "memory_confidence_update",
    "memory_supersede",
    "memory_link_insert",
    "memory_link_delete",
    "governance_decision_update",
    "maintenance_cleanup",
    "no_op",
}
ROLLBACK_CAPABLE_ACTIONS = VALID_ACTION_TYPES - {"maintenance_cleanup", "no_op"}
LOW_RISK_ACTIONS = {"memory_insert", "memory_link_insert", "memory_importance_update", "memory_confidence_update", "no_op"}
MEDIUM_RISK_ACTIONS = {"memory_update", "memory_archive", "memory_status_update", "memory_supersede", "memory_link_delete", "governance_decision_update"}
HIGH_RISK_ACTIONS = {"maintenance_cleanup"}

VALID_EXECUTION_TRANSITIONS = {
    "planned": {"policy_evaluated"},
    "policy_evaluated": {"queued", "rejected", "applying"},
    "queued": {"applying", "cancelled"},
    "applying": {"applied", "apply_failed"},
    "applied": {"rolling_back"},
    "rolling_back": {"rolled_back", "rollback_failed"},
}
@dataclass(frozen=True)
class MutationContext:
    actor: str
    origin: str
    approval_kind: str = "auto_policy"
    run_id: str | None = None
    decision_id: str | None = None
    correlation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.actor:
            raise ValueError("mutation context actor is required")
        if self.origin not in VALID_ORIGINS:
            raise ValueError(f"unsupported mutation origin: {self.origin!r}")


@dataclass(frozen=True)
class MutationRequest:
    action_type: str
    target_type: str
    target_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    risk_level: str = "medium"
    confidence: float = 1.0
    rollback_required: bool = True
    idempotency_key: str = ""

    def validate(self) -> None:
        if self.action_type not in VALID_ACTION_TYPES:
            raise ValueError(f"unsupported mutation action type: {self.action_type!r}")
        if not self.target_type:
            raise ValueError("mutation target_type is required")
        generated_target_actions = {"memory_insert", "memory_link_insert", "no_op", "maintenance_cleanup"}
        if self.action_type not in generated_target_actions and not self.target_id:
            raise ValueError("mutation target_id is required")
        if self.risk_level not in VALID_RISK_LEVELS:
            raise ValueError(f"unsupported risk level: {self.risk_level!r}")
        if not isinstance(self.payload, dict):
            raise ValueError("mutation payload must be an object")
        try:
            confidence = float(self.confidence)
        except Exception as exc:
            raise ValueError("mutation confidence must be numeric") from exc
        if confidence < 0.0 or confidence > 1.0:
            raise ValueError("mutation confidence must be between 0 and 1")
        if self.rollback_required and self.action_type not in ROLLBACK_CAPABLE_ACTIONS:
            raise ValueError(f"{self.action_type} cannot require rollback")
        if self.action_type == "memory_insert":
            for field_name in ("type", "title", "content"):
                if not self.payload.get(field_name):
                    raise ValueError(f"memory_insert payload missing {field_name}")
        if self.action_type == "memory_link_insert":
            for field_name in ("source_id", "target_id", "relation_type"):
                if not self.payload.get(field_name):
                    raise ValueError(f"memory_link_insert payload missing {field_name}")

    def canonical(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "payload": self.payload,
            "risk_level": self.risk_level,
            "confidence": float(self.confidence),
            "rollback_required": bool(self.rollback_required),
            "idempotency_key": self.idempotency_key,
        }


def validate_execution_transition(current_status: str, next_status: str) -> None:
    if next_status in VALID_EXECUTION_TRANSITIONS.get(current_status, set()):
        return
    raise ValueError(f"invalid governance execution transition: {current_status} -> {next_status}")


def evaluate_mutation_policy(request: MutationRequest, context: MutationContext) -> dict[str, Any]:
    request.validate()
    context.validate()
    reasons: list[str] = []
    decision = "allowed"

    if request.action_type in HIGH_RISK_ACTIONS or request.risk_level == "high":
        decision = "queued"
        reasons.append("high_risk_requires_review")
    if request.action_type in MEDIUM_RISK_ACTIONS and request.risk_level != "low":
        decision = "queued"
        reasons.append("medium_risk_requires_safe_envelope")
    if request.confidence < 0.55:
        decision = "rejected"
        reasons.append("confidence_below_review_threshold")
    elif request.confidence < 0.90 and decision == "allowed" and request.action_type not in LOW_RISK_ACTIONS:
        decision = "queued"
        reasons.append("confidence_below_auto_threshold")
    if context.approval_kind in {"human_accept", "admin_override", "rollback", "maintenance"} and decision == "queued":
        decision = "override_allowed" if context.approval_kind == "admin_override" else "allowed"
        reasons.append(f"approved_by_{context.approval_kind}")

    return {
        "policy_decision": decision,
        "policy_reason": "; ".join(reasons) if reasons else "policy allowed reversible mutation",
        "policy_reasons": reasons,
        "policy_version": POLICY_VERSION,
    }
