from __future__ import annotations

from typing import Any, Dict, Mapping

from .engine import NeedsFactoryValidationError, sha256_json
from .package import build_narrative_ready_pack


PRODUCT_MODES = {
    "NEEDS_ANALYSIS": {
        "require_causal_validation": False,
        "require_intervention_traceability": False,
        "activities_may_create_needs": False,
        "indicators_may_create_needs": False,
        "purpose": "Standalone needs analysis based on evidence and target-group research.",
    },
    "PROPOSAL_SUPPORT": {
        "require_causal_validation": True,
        "require_intervention_traceability": True,
        "activities_may_create_needs": False,
        "indicators_may_create_needs": False,
        "purpose": "Downstream proposal support after needs have already been established independently.",
    },
}


def product_policy(mode: str) -> Dict[str, Any]:
    if mode not in PRODUCT_MODES:
        raise NeedsFactoryValidationError(f"unknown product mode: {mode}")
    return dict(PRODUCT_MODES[mode])


def build_product_narrative_pack(
    mode: str,
    project_input: Mapping[str, Any],
    ranked_needs: Mapping[str, Any],
    needs_by_id: Mapping[str, Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    causal_validation: Mapping[str, Any] | None,
    traceability_validation: Mapping[str, Any] | None,
    release_gate: Mapping[str, Any],
) -> Dict[str, Any]:
    policy = product_policy(mode)
    if mode == "PROPOSAL_SUPPORT":
        pack = build_narrative_ready_pack(
            project_input,
            ranked_needs,
            needs_by_id,
            evidence_by_id,
            causal_validation or {"valid": False},
            traceability_validation or {"valid": False},
            release_gate,
        )
    else:
        causal = dict(causal_validation or {})
        trace = dict(traceability_validation or {})
        if not causal.get("valid"):
            causal = {
                "valid": True,
                "mode": "NOT_REQUIRED_FOR_NEEDS_ANALYSIS",
                "failures": [],
                "warnings": [{
                    "warning": "causal_model_not_required_for_standalone_needs_analysis",
                    "node_id": None,
                }],
            }
        if not trace.get("valid"):
            trace = {
                "valid": True,
                "mode": "NOT_REQUIRED_FOR_NEEDS_ANALYSIS",
                "failures": [],
                "coverage": {},
            }
        pack = build_narrative_ready_pack(
            project_input,
            ranked_needs,
            needs_by_id,
            evidence_by_id,
            causal,
            trace,
            release_gate,
        )
    pack["product_mode"] = mode
    pack["product_mode_policy"] = policy
    pack["solution_leakage_guard"] = {
        "activities_may_create_needs": False,
        "indicators_may_create_needs": False,
        "intervention_traceability_is_downstream": mode == "NEEDS_ANALYSIS",
    }
    pack.pop("pack_sha256", None)
    pack["pack_sha256"] = sha256_json(pack)
    return pack


def validate_mode_inputs(
    mode: str,
    *,
    has_activity_plan: bool,
    has_indicator_plan: bool,
    need_count: int,
) -> Dict[str, Any]:
    policy = product_policy(mode)
    failures = []
    warnings = []
    if need_count <= 0:
        failures.append("no_validated_needs")
    if mode == "NEEDS_ANALYSIS":
        if has_activity_plan:
            warnings.append("activity_plan_present_but_not_used_to_create_needs")
        if has_indicator_plan:
            warnings.append("indicator_plan_present_but_not_used_to_create_needs")
    return {
        "valid": not failures,
        "mode": mode,
        "failures": failures,
        "warnings": warnings,
        "policy": policy,
    }
