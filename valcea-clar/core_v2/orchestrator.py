from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import orchestrator_run94 as _base

# RUN95 controlled canonical article-integrity switch:
# freeze the naturally validated RUN94 surface and replace only the canonical
# isj_article_integrity stage implementation with the source-neutral Core v2
# facade. Preserve the stage name, argv/output semantics, exact 42-stage order,
# article evidence namespace, retained verifier as an independent regression
# component, and the no-authority publication/acceptance boundary.

CycleStage = _base.CycleStage
run_shadow = _base.run_shadow

_BASE_PLAN = _base.bounded_cycle_plan
_BASE_SNAPSHOTS = _base._persisted_runtime_snapshots

# Preserve established migration introspection seams.
_LEGACY_PLAN = _base._LEGACY_PLAN
_writer_consumption_dependency_snapshot = _base._writer_consumption_dependency_snapshot
_promoted_claim_contract_stage_ownership_snapshot = _base._promoted_claim_contract_stage_ownership_snapshot
_owned_article_truth_stages = _base._owned_article_truth_stages
_owned_promoted_claim_contract_stages = _base._owned_promoted_claim_contract_stages
_owned_fact_kernel_stages = _base._owned_fact_kernel_stages
_fact_kernel_stage_ownership_snapshot = _base._fact_kernel_stage_ownership_snapshot
_owned_projection_stages = _base._owned_projection_stages
_promoted_claim_projection_stage_ownership_snapshot = _base._promoted_claim_projection_stage_ownership_snapshot
_owned_consumption_stages = _base._owned_consumption_stages
_promoted_claim_consumption_stage_ownership_snapshot = _base._promoted_claim_consumption_stage_ownership_snapshot
_writer_stage_ownership_snapshot = _base._writer_stage_ownership_snapshot
_owned_writer_stage = _base._owned_writer_stage
_owned_article_truth_switch_stages = _base._owned_article_truth_switch_stages

_WRITER_STAGE = "promoted_claim_writer"
_ARTICLE_GATE_STAGE = "isj_article_deadline_claim_gate"
_ARTICLE_VALIDATION_STAGE = "isj_article_deadline_claim_validation"
_ARTICLE_INTEGRITY_STAGE = "isj_article_integrity"
_ARTICLE_TRUTH_MODULE = "valcea-clar/core_v2/promoted_claim_article_truth.py"
_ARTICLE_INTEGRITY_MODULE = "valcea-clar/core_v2/promoted_claim_article_integrity.py"
_RETAINED_ARTICLE_GATE_IMPLEMENTATION = "valcea-clar/core_v2/isj_article_deadline_claim_gate.py"
_RETAINED_ARTICLE_VALIDATOR_IMPLEMENTATION = "valcea-clar/core_v2/validate_isj_article_deadline_claim_gate.py"
_RETAINED_ARTICLE_INTEGRITY_IMPLEMENTATION = "valcea-clar/core_v2/isj_article_integrity.py"
_FACT_KERNEL_ARTIFACT = "valcea-core-v2-isj-fact-kernel-shadow.json"
_FACT_KERNEL_INTEGRITY_ARTIFACT = "valcea-core-v2-isj-fact-kernel-integrity-shadow.json"
_WRITER_ARTIFACT = "valcea-core-v2-isj-article-shadow.json"
_ARTICLE_GATE_ARTIFACT = "valcea-core-v2-isj-article-deadline-claim.json"
_ARTICLE_VALIDATION_ARTIFACT = "valcea-core-v2-isj-article-deadline-claim-validation.json"
_ARTICLE_INTEGRITY_ARTIFACT = "valcea-core-v2-isj-article-integrity-shadow.json"


def _owned_article_integrity_switch_stage(workdir: Path) -> CycleStage:
    """Bind the canonical integrity stage one-for-one to the neutral facade."""
    fact_kernel = workdir / _FACT_KERNEL_ARTIFACT
    fact_integrity = workdir / _FACT_KERNEL_INTEGRITY_ARTIFACT
    article = workdir / _WRITER_ARTIFACT
    integrity = workdir / _ARTICLE_INTEGRITY_ARTIFACT
    return CycleStage(
        _ARTICLE_INTEGRITY_STAGE,
        (
            sys.executable,
            _ARTICLE_INTEGRITY_MODULE,
            "--fact-kernel", str(fact_kernel),
            "--fact-kernel-integrity", str(fact_integrity),
            "--article", str(article),
            "--output", str(integrity),
        ),
        integrity,
    )


def _article_truth_stage_ownership_snapshot(plan: tuple[CycleStage, ...]) -> dict[str, Any]:
    by_name = {stage.name: stage for stage in plan}
    writer = by_name[_WRITER_STAGE]
    gate = by_name[_ARTICLE_GATE_STAGE]
    validation = by_name[_ARTICLE_VALIDATION_STAGE]
    integrity = by_name[_ARTICLE_INTEGRITY_STAGE]
    names = [stage.name for stage in plan]
    writer_index = names.index(_WRITER_STAGE)
    gate_index = names.index(_ARTICLE_GATE_STAGE)
    validation_index = names.index(_ARTICLE_VALIDATION_STAGE)
    integrity_index = names.index(_ARTICLE_INTEGRITY_STAGE)
    joined = "\n".join(" ".join(stage.argv) for stage in (gate, validation, integrity))
    exact = (
        len(plan) == 42
        and len(gate.argv) > 3 and gate.argv[1] == _ARTICLE_TRUTH_MODULE
        and gate.argv[2:4] == ("--mode", "gate")
        and len(validation.argv) > 3 and validation.argv[1] == _ARTICLE_TRUTH_MODULE
        and validation.argv[2:4] == ("--mode", "validate")
        and len(integrity.argv) > 1 and integrity.argv[1] == _ARTICLE_INTEGRITY_MODULE
        and gate.output is not None and gate.output.name == _ARTICLE_GATE_ARTIFACT
        and validation.output is not None and validation.output.name == _ARTICLE_VALIDATION_ARTIFACT
        and integrity.output is not None and integrity.output.name == _ARTICLE_INTEGRITY_ARTIFACT
        and gate_index == writer_index + 1
        and validation_index == gate_index + 1
        and integrity_index == validation_index + 1
        and "--fact-kernel" in integrity.argv
        and "--fact-kernel-integrity" in integrity.argv
        and "--article" in integrity.argv
        and "--output" in integrity.argv
        and _RETAINED_ARTICLE_GATE_IMPLEMENTATION not in joined
        and _RETAINED_ARTICLE_VALIDATOR_IMPLEMENTATION not in joined
        and _RETAINED_ARTICLE_INTEGRITY_IMPLEMENTATION not in joined
    )
    return {
        "schema_version": "core-v2-article-truth-stage-ownership-shadow.v3",
        "status": "PASS_SHADOW" if exact else "BLOCKED",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "canonical_stage_count": len(plan),
        "canonical_stage_ownership": "CORE_V2_ORCHESTRATOR_DIRECT_DEFINITION",
        "owned_stages": [gate.name, validation.name, integrity.name],
        "source_neutral_article_truth_cli": _ARTICLE_TRUTH_MODULE,
        "source_neutral_article_integrity_cli": _ARTICLE_INTEGRITY_MODULE,
        "canonical_gate_mode": "gate",
        "canonical_validation_mode": "validate",
        "canonical_article_truth_runtime_switched": True,
        "canonical_article_integrity_runtime_switched": True,
        "canonical_stage_definitions_switched": True,
        "retained_gate_implementation": _RETAINED_ARTICLE_GATE_IMPLEMENTATION,
        "retained_validator_implementation": _RETAINED_ARTICLE_VALIDATOR_IMPLEMENTATION,
        "retained_integrity_implementation": _RETAINED_ARTICLE_INTEGRITY_IMPLEMENTATION,
        "retained_implementations_regression_only": True,
        "retained_implementations_runtime_dependency": False,
        "retained_implementations_retirement_eligible": False,
        "source_specific_truth_stage_names_retained": True,
        "artifact_identities_retained": True,
        "lineage_inputs_retained": True,
        "canonical_order_writer_gate_validation_integrity_preserved": True,
        "retirement_eligible": False,
        "retirement_performed": False,
        "retirement_authority": "NONE",
        "truth_rule": (
            "Core v2 binds the canonical writer->article-truth gate->validation->integrity chain to source-neutral "
            "facades without changing stage names, artifacts, lineage or the 42-stage order. The retained ISJ gate, "
            "validator and integrity verifier remain KEEP regression components only. The switch grants no publication, "
            "acceptance, merge, deploy, cutover or retirement authority."
        ),
    }


def _article_integrity_stage_ownership_snapshot(plan: tuple[CycleStage, ...]) -> dict[str, Any]:
    by_name = {stage.name: stage for stage in plan}
    integrity = by_name[_ARTICLE_INTEGRITY_STAGE]
    joined = " ".join(integrity.argv)
    exact = (
        len(plan) == 42
        and integrity.name == _ARTICLE_INTEGRITY_STAGE
        and len(integrity.argv) > 1
        and integrity.argv[1] == _ARTICLE_INTEGRITY_MODULE
        and integrity.output is not None
        and integrity.output.name == _ARTICLE_INTEGRITY_ARTIFACT
        and _FACT_KERNEL_ARTIFACT in joined
        and _FACT_KERNEL_INTEGRITY_ARTIFACT in joined
        and _WRITER_ARTIFACT in joined
        and "--fact-kernel" in integrity.argv
        and "--fact-kernel-integrity" in integrity.argv
        and "--article" in integrity.argv
        and "--output" in integrity.argv
        and _RETAINED_ARTICLE_INTEGRITY_IMPLEMENTATION not in joined
    )
    return {
        "schema_version": "core-v2-promoted-claim-article-integrity-stage-ownership-shadow.v1",
        "status": "PASS_SHADOW" if exact else "BLOCKED",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "canonical_stage_count": len(plan),
        "canonical_stage_name": integrity.name,
        "canonical_integrity_module": integrity.argv[1] if len(integrity.argv) > 1 else None,
        "canonical_integrity_artifact": integrity.output.name if integrity.output is not None else None,
        "canonical_runtime_switched": True,
        "source_neutral_facade_present_in_canonical_plan": True,
        "retained_integrity_implementation": _RETAINED_ARTICLE_INTEGRITY_IMPLEMENTATION,
        "retained_integrity_runtime_dependency": False,
        "retained_integrity_regression_component": True,
        "retained_integrity_retirement_eligible": False,
        "stage_name_retained": True,
        "artifact_identity_retained": True,
        "lineage_inputs_retained": True,
        "retirement_eligible": False,
        "retirement_performed": False,
        "retirement_authority": "NONE",
    }


def bounded_cycle_plan(workdir: Path, *, live: bool) -> tuple[CycleStage, ...]:
    base_plan = _BASE_PLAN(workdir, live=live)
    owned_integrity = _owned_article_integrity_switch_stage(workdir)
    transformed: list[CycleStage] = []
    integrity_inserted = False

    for stage in base_plan:
        if stage.name == _ARTICLE_INTEGRITY_STAGE and not integrity_inserted:
            transformed.append(owned_integrity)
            integrity_inserted = True
            continue
        if stage.name == _ARTICLE_INTEGRITY_STAGE:
            continue
        transformed.append(stage)

    if not integrity_inserted:
        raise RuntimeError("canonical_article_integrity_anchor_missing")

    names = [stage.name for stage in transformed]
    if len(transformed) != 42:
        raise RuntimeError(f"canonical_core_v2_stage_count_changed:{len(transformed)}")
    for name in (_WRITER_STAGE, _ARTICLE_GATE_STAGE, _ARTICLE_VALIDATION_STAGE, _ARTICLE_INTEGRITY_STAGE):
        if names.count(name) != 1:
            raise RuntimeError(f"canonical_stage_not_unique:{name}")

    writer_index = names.index(_WRITER_STAGE)
    gate_index = names.index(_ARTICLE_GATE_STAGE)
    validation_index = names.index(_ARTICLE_VALIDATION_STAGE)
    integrity_index = names.index(_ARTICLE_INTEGRITY_STAGE)
    if (gate_index, validation_index, integrity_index) != (writer_index + 1, writer_index + 2, writer_index + 3):
        raise RuntimeError("canonical_writer_gate_validation_integrity_order_changed")
    if transformed[integrity_index] != _owned_article_integrity_switch_stage(workdir):
        raise RuntimeError("canonical_source_neutral_article_integrity_definition_drifted")

    article_ownership = _article_truth_stage_ownership_snapshot(tuple(transformed))
    if article_ownership["status"] != "PASS_SHADOW":
        raise RuntimeError("source_neutral_article_truth_integrity_switch_not_proven")
    if article_ownership["retirement_eligible"] is not False:
        raise RuntimeError("article_truth_integrity_retirement_must_remain_closed")
    if article_ownership["publication_authority"] != "NONE" or article_ownership["acceptance_ready"] is not False:
        raise RuntimeError("article_truth_integrity_switch_authority_boundary_changed")

    integrity_ownership = _article_integrity_stage_ownership_snapshot(tuple(transformed))
    if integrity_ownership["status"] != "PASS_SHADOW":
        raise RuntimeError("source_neutral_article_integrity_switch_not_proven")
    if integrity_ownership["retained_integrity_runtime_dependency"] is not False:
        raise RuntimeError("retained_article_integrity_runtime_dependency_not_closed")
    if integrity_ownership["retained_integrity_retirement_eligible"] is not False:
        raise RuntimeError("retained_article_integrity_retirement_must_remain_closed")

    return tuple(transformed)


def _persisted_runtime_snapshots(plan: tuple[CycleStage, ...]) -> dict[str, Any]:
    snapshots = _BASE_SNAPSHOTS(plan)
    integrity = next((stage for stage in plan if stage.name == _ARTICLE_INTEGRITY_STAGE), None)
    if integrity is not None and integrity.output is not None and integrity.output.is_file():
        try:
            snapshots[_ARTICLE_INTEGRITY_STAGE] = json.loads(integrity.output.read_text(encoding="utf-8"))
        except Exception:
            snapshots[_ARTICLE_INTEGRITY_STAGE] = {"parse_error": True, "path": str(integrity.output)}
    snapshots["article_truth_stage_ownership"] = _article_truth_stage_ownership_snapshot(plan)
    snapshots["article_integrity_stage_ownership"] = _article_integrity_stage_ownership_snapshot(plan)
    return snapshots


# RUN94 ultimately delegates execution to the frozen RUN70 engine. Patch only
# the plan/snapshot seams needed for this one-for-one integrity switch.
_base.bounded_cycle_plan = bounded_cycle_plan
_base._persisted_runtime_snapshots = _persisted_runtime_snapshots
_base._base.bounded_cycle_plan = bounded_cycle_plan
_base._base._persisted_runtime_snapshots = _persisted_runtime_snapshots
_base._base._base.bounded_cycle_plan = bounded_cycle_plan
_base._base._base._persisted_runtime_snapshots = _persisted_runtime_snapshots
_base._base._base._legacy.bounded_cycle_plan = bounded_cycle_plan
_base._base._base._legacy._persisted_runtime_snapshots = _persisted_runtime_snapshots

run_bounded_shadow_cycle = _base._base._base._legacy.run_bounded_shadow_cycle
main = _base._base._base._legacy.main


if __name__ == "__main__":
    raise SystemExit(main())
