from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence


STAGES = [
    "NF00_INTAKE",
    "NF01_CALL_INTELLIGENCE",
    "NF02_RESEARCH_PLAN",
    "NF03_EXTERNAL_EVIDENCE",
    "NF04_EVIDENCE_VALIDATION",
    "NF05_GAP_DETECTION",
    "NF06_PRIMARY_RESEARCH",
    "NF07_NEED_DISCOVERY",
    "NF08_NEED_RANKING",
    "NF09_CAUSAL_MODEL",
    "NF10_INTERVENTION_TRACEABILITY",
    "NF11_ADVERSARIAL_QA",
    "NF12_PACKAGE",
]

CHANGE_STAGE = {
    "project_input": "NF00_INTAKE",
    "call_snapshot": "NF01_CALL_INTELLIGENCE",
    "research_plan": "NF02_RESEARCH_PLAN",
    "external_source_snapshot": "NF03_EXTERNAL_EVIDENCE",
    "external_evidence": "NF03_EXTERNAL_EVIDENCE",
    "evidence_validation_rules": "NF04_EVIDENCE_VALIDATION",
    "gap_rules": "NF05_GAP_DETECTION",
    "population_snapshot": "NF06_PRIMARY_RESEARCH",
    "primary_research_plan": "NF06_PRIMARY_RESEARCH",
    "primary_research_raw": "NF06_PRIMARY_RESEARCH",
    "primary_research_aggregates": "NF06_PRIMARY_RESEARCH",
    "need_discovery_rules": "NF07_NEED_DISCOVERY",
    "ranking_rules": "NF08_NEED_RANKING",
    "causal_rules": "NF09_CAUSAL_MODEL",
    "traceability_rules": "NF10_INTERVENTION_TRACEABILITY",
    "qa_rules": "NF11_ADVERSARIAL_QA",
    "package_rules": "NF12_PACKAGE",
}


def _index(stage: str) -> int:
    if stage not in STAGES:
        raise ValueError(f"unknown Needs Factory stage: {stage}")
    return STAGES.index(stage)


def earliest_affected_stage(changed_inputs: Sequence[str]) -> str:
    if not changed_inputs:
        raise ValueError("changed_inputs cannot be empty")
    stages = []
    for item in changed_inputs:
        stage = CHANGE_STAGE.get(str(item))
        if not stage:
            raise ValueError(f"unknown resume input category: {item}")
        stages.append(stage)
    return min(stages, key=_index)


def build_resume_plan(
    previous_manifest: Mapping[str, Any],
    *,
    changed_inputs: Sequence[str],
    successor_run_id: str,
) -> Dict[str, Any]:
    restart_stage = earliest_affected_stage(changed_inputs)
    restart_index = _index(restart_stage)
    closed = [str(item) for item in (previous_manifest.get("closed_checkpoints") or [])]
    reusable = [stage for stage in closed if stage in STAGES and _index(stage) < restart_index]
    reusable.sort(key=_index)
    invalidated = STAGES[restart_index:]

    preserved_artifacts: Dict[str, str] = {}
    hashes = dict(previous_manifest.get("artifact_hashes") or {})
    for event in previous_manifest.get("events", []) or []:
        checkpoint = str(event.get("checkpoint") or "")
        path = event.get("artifact_path")
        if checkpoint in reusable and path and path in hashes:
            preserved_artifacts[str(path)] = str(hashes[path])

    plan = {
        "schema_version": "nf.resume_plan.v0.1",
        "predecessor_run_id": previous_manifest.get("run_id"),
        "successor_run_id": successor_run_id,
        "changed_inputs": sorted({str(item) for item in changed_inputs}),
        "restart_stage": restart_stage,
        "reusable_closed_checkpoints": reusable,
        "invalidated_stages": invalidated,
        "preserved_artifact_hashes": dict(sorted(preserved_artifacts.items())),
        "policy": {
            "overwrite_predecessor": False,
            "preserve_predecessor_manifest": True,
            "rerun_unaffected_checkpoints": False,
            "rollback_supported": True,
        },
    }
    return plan


def validate_resume_plan(plan: Mapping[str, Any]) -> Dict[str, Any]:
    failures = []
    predecessor = plan.get("predecessor_run_id")
    successor = plan.get("successor_run_id")
    if not predecessor or not successor:
        failures.append("missing_run_linkage")
    if predecessor == successor:
        failures.append("successor_must_be_new_version")
    restart = plan.get("restart_stage")
    if restart not in STAGES:
        failures.append("invalid_restart_stage")
        return {"valid": False, "failures": failures}
    restart_index = _index(str(restart))
    reusable = list(plan.get("reusable_closed_checkpoints") or [])
    if any(stage not in STAGES or _index(stage) >= restart_index for stage in reusable):
        failures.append("downstream_checkpoint_marked_reusable")
    expected_invalidated = STAGES[restart_index:]
    if list(plan.get("invalidated_stages") or []) != expected_invalidated:
        failures.append("invalidated_stage_set_mismatch")
    policy = plan.get("policy") or {}
    if policy.get("overwrite_predecessor") is not False:
        failures.append("predecessor_overwrite_not_forbidden")
    if policy.get("rerun_unaffected_checkpoints") is not False:
        failures.append("unaffected_rerun_not_forbidden")
    return {"valid": not failures, "failures": failures}
