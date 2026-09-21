from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import orchestrator_run81 as _base

# RUN83 controlled ownership extraction:
# keep the naturally validated RUN81 plan as a frozen migration baseline while
# Core v2 directly owns both the fact-kernel pair and the already-owned
# promoted-claim writer projection pair. Runtime semantics, source-specific
# modules, stage names, artifacts, evidence namespaces, stage count and
# publication/acceptance authority remain unchanged.

CycleStage = _base.CycleStage
run_shadow = _base.run_shadow

_BASE_PLAN = _base.bounded_cycle_plan
_BASE_SNAPSHOTS = _base._persisted_runtime_snapshots

# Backwards-compatible test/introspection exports retained while RUN70 remains
# the frozen semantic reference for already-proven writer/article seams.
_LEGACY_PLAN = _base._LEGACY_PLAN
_writer_consumption_dependency_snapshot = _base._writer_consumption_dependency_snapshot
_article_truth_stage_ownership_snapshot = _base._article_truth_stage_ownership_snapshot
_promoted_claim_contract_stage_ownership_snapshot = _base._promoted_claim_contract_stage_ownership_snapshot
_owned_article_truth_stages = _base._owned_article_truth_stages
_owned_promoted_claim_contract_stages = _base._owned_promoted_claim_contract_stages

_FACT_KERNEL_MODULE = "valcea-clar/core_v2/isj_fact_kernel_shadow_lane.py"
_FACT_KERNEL_INTEGRITY_MODULE = "valcea-clar/core_v2/isj_fact_kernel_integrity.py"
_FACT_KERNEL_ARTIFACT = "valcea-core-v2-isj-fact-kernel-shadow.json"
_FACT_KERNEL_INTEGRITY_ARTIFACT = "valcea-core-v2-isj-fact-kernel-integrity-shadow.json"
_FACT_KERNEL_STAGES = {
    "isj_fact_kernel",
    "isj_fact_kernel_integrity",
}

_PROJECTION_MODULE = "valcea-clar/core_v2/promoted_claim_writer_projection.py"
_PROJECTION_VALIDATION_MODULE = "valcea-clar/core_v2/validate_promoted_claim_projection_runtime.py"
_PROJECTION_ARTIFACT = "valcea-core-v2-promoted-claim-writer-projection.json"
_PROJECTION_VALIDATION_ARTIFACT = "valcea-core-v2-promoted-claim-projection-validation.json"
_PROJECTION_STAGES = {
    "promoted_claim_writer_projection",
    "promoted_claim_projection_validation",
}


def _owned_fact_kernel_stages(workdir: Path) -> tuple[CycleStage, CycleStage]:
    """Own the retained truth-bound fact-kernel pair without semantic change."""
    materiality = workdir / "valcea-core-v2-isj-field-materiality-shadow.json"
    fields = workdir / "valcea-core-v2-isj-field-evidence-shadow.json"
    calendar_fields = workdir / "valcea-core-v2-isj-calendar-field-evidence-shadow.json"
    fact_kernel = workdir / _FACT_KERNEL_ARTIFACT
    integrity = workdir / _FACT_KERNEL_INTEGRITY_ARTIFACT
    py = sys.executable
    return (
        CycleStage(
            "isj_fact_kernel",
            (
                py,
                _FACT_KERNEL_MODULE,
                "--materiality", str(materiality),
                "--fields", str(fields),
                "--calendar-fields", str(calendar_fields),
                "--output", str(fact_kernel),
            ),
            fact_kernel,
        ),
        CycleStage(
            "isj_fact_kernel_integrity",
            (
                py,
                _FACT_KERNEL_INTEGRITY_MODULE,
                "--fact-kernel", str(fact_kernel),
                "--output", str(integrity),
            ),
            integrity,
        ),
    )


def _fact_kernel_stage_ownership_snapshot(plan: tuple[CycleStage, ...]) -> dict[str, Any]:
    by_name = {stage.name: stage for stage in plan}
    fact_kernel = by_name["isj_fact_kernel"]
    integrity = by_name["isj_fact_kernel_integrity"]
    fact_joined = " ".join(fact_kernel.argv)
    integrity_joined = " ".join(integrity.argv)
    required_inputs = (
        "valcea-core-v2-isj-field-materiality-shadow.json",
        "valcea-core-v2-isj-field-evidence-shadow.json",
        "valcea-core-v2-isj-calendar-field-evidence-shadow.json",
    )
    exact = (
        len(fact_kernel.argv) > 1
        and fact_kernel.argv[1] == _FACT_KERNEL_MODULE
        and len(integrity.argv) > 1
        and integrity.argv[1] == _FACT_KERNEL_INTEGRITY_MODULE
        and fact_kernel.output is not None
        and fact_kernel.output.name == _FACT_KERNEL_ARTIFACT
        and integrity.output is not None
        and integrity.output.name == _FACT_KERNEL_INTEGRITY_ARTIFACT
        and all(name in fact_joined for name in required_inputs)
        and "--fact-kernel" in integrity.argv
        and str(fact_kernel.output) in integrity.argv
        and str(fact_kernel.output) in integrity_joined
    )
    return {
        "schema_version": "core-v2-fact-kernel-stage-ownership-shadow.v1",
        "status": "PASS_SHADOW" if exact else "BLOCKED",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "canonical_stage_count": len(plan),
        "canonical_stage_ownership": "CORE_V2_ORCHESTRATOR_DIRECT_DEFINITION",
        "owned_stages": [fact_kernel.name, integrity.name],
        "canonical_fact_kernel_module": fact_kernel.argv[1] if len(fact_kernel.argv) > 1 else None,
        "canonical_fact_kernel_integrity_module": integrity.argv[1] if len(integrity.argv) > 1 else None,
        "canonical_fact_kernel_artifact": fact_kernel.output.name if fact_kernel.output is not None else None,
        "canonical_fact_kernel_integrity_artifact": integrity.output.name if integrity.output is not None else None,
        "frozen_run81_fact_kernel_definitions_consumed": False,
        "frozen_fact_kernel_stage_anchor_used_for_position_only": True,
        "source_specific_fact_kernel_modules_retained": True,
        "stage_names_retained": True,
        "artifact_identities_retained": True,
        "lineage_inputs_retained": True,
        "retirement_eligible": False,
        "retirement_performed": False,
        "truth_rule": (
            "Core v2 directly owns the retained ISJ fact-kernel and integrity definitions while preserving the "
            "naturally validated source-specific modules, stage names, artifacts and lineage. This extraction "
            "grants no retirement, publication or acceptance authority."
        ),
    }


def _owned_projection_stages(workdir: Path) -> tuple[CycleStage, CycleStage]:
    """Own the source-neutral projection pair without changing RUN81 semantics."""
    fact_kernel = workdir / _FACT_KERNEL_ARTIFACT
    fact_integrity = workdir / _FACT_KERNEL_INTEGRITY_ARTIFACT
    projection = workdir / _PROJECTION_ARTIFACT
    validation = workdir / _PROJECTION_VALIDATION_ARTIFACT
    py = sys.executable
    return (
        CycleStage(
            "promoted_claim_writer_projection",
            (
                py,
                _PROJECTION_MODULE,
                "--fact-kernel", str(fact_kernel),
                "--fact-kernel-integrity", str(fact_integrity),
                "--year", "2026",
                "--output", str(projection),
            ),
            projection,
        ),
        CycleStage(
            "promoted_claim_projection_validation",
            (
                py,
                _PROJECTION_VALIDATION_MODULE,
                "--fact-kernel", str(fact_kernel),
                "--fact-kernel-integrity", str(fact_integrity),
                "--projection", str(projection),
                "--year", "2026",
                "--prove-tamper",
                "--output", str(validation),
            ),
            validation,
        ),
    )


def _promoted_claim_projection_stage_ownership_snapshot(plan: tuple[CycleStage, ...]) -> dict[str, Any]:
    by_name = {stage.name: stage for stage in plan}
    projection = by_name["promoted_claim_writer_projection"]
    validation = by_name["promoted_claim_projection_validation"]
    projection_joined = " ".join(projection.argv)
    validation_joined = " ".join(validation.argv)
    required_inputs = (
        _FACT_KERNEL_ARTIFACT,
        _FACT_KERNEL_INTEGRITY_ARTIFACT,
    )
    exact = (
        len(projection.argv) > 1
        and projection.argv[1] == _PROJECTION_MODULE
        and len(validation.argv) > 1
        and validation.argv[1] == _PROJECTION_VALIDATION_MODULE
        and projection.output is not None
        and projection.output.name == _PROJECTION_ARTIFACT
        and validation.output is not None
        and validation.output.name == _PROJECTION_VALIDATION_ARTIFACT
        and all(name in projection_joined for name in required_inputs)
        and all(name in validation_joined for name in required_inputs)
        and "--projection" in validation.argv
        and str(projection.output) in validation.argv
        and "--year" in projection.argv
        and "2026" in projection.argv
        and "--year" in validation.argv
        and "2026" in validation.argv
        and "--prove-tamper" in validation.argv
    )
    return {
        "schema_version": "core-v2-promoted-claim-projection-stage-ownership-shadow.v1",
        "status": "PASS_SHADOW" if exact else "BLOCKED",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "canonical_stage_count": len(plan),
        "canonical_stage_ownership": "CORE_V2_ORCHESTRATOR_DIRECT_DEFINITION",
        "owned_stages": [projection.name, validation.name],
        "canonical_projection_module": projection.argv[1] if len(projection.argv) > 1 else None,
        "canonical_projection_validation_module": validation.argv[1] if len(validation.argv) > 1 else None,
        "canonical_projection_artifact": projection.output.name if projection.output is not None else None,
        "canonical_projection_validation_artifact": validation.output.name if validation.output is not None else None,
        "frozen_run81_projection_definitions_consumed": False,
        "frozen_projection_stage_anchor_used_for_position_only": True,
        "source_neutral_projection_modules_retained": True,
        "stage_names_retained": True,
        "artifact_identities_retained": True,
        "lineage_inputs_retained": True,
        "tamper_validation_retained": "--prove-tamper" in validation.argv,
        "retirement_eligible": False,
        "retirement_performed": False,
        "truth_rule": (
            "Core v2 directly owns the promoted-claim writer projection and validation definitions while preserving "
            "the naturally validated RUN81 semantics, source-neutral modules, stage names, artifacts, lineage and "
            "fail-closed tamper validation. This extraction grants no retirement, publication or acceptance authority."
        ),
    }


def bounded_cycle_plan(workdir: Path, *, live: bool) -> tuple[CycleStage, ...]:
    base_plan = _BASE_PLAN(workdir, live=live)
    owned_fact_kernel = _owned_fact_kernel_stages(workdir)
    owned_projection = _owned_projection_stages(workdir)
    transformed: list[CycleStage] = []
    fact_inserted = False
    projection_inserted = False

    for stage in base_plan:
        if stage.name == "isj_fact_kernel" and not fact_inserted:
            transformed.extend(owned_fact_kernel)
            fact_inserted = True
            continue
        if stage.name in _FACT_KERNEL_STAGES:
            continue
        if stage.name == "promoted_claim_writer_projection" and not projection_inserted:
            transformed.extend(owned_projection)
            projection_inserted = True
            continue
        if stage.name in _PROJECTION_STAGES:
            continue
        transformed.append(stage)

    if not fact_inserted:
        raise RuntimeError("canonical_fact_kernel_anchor_missing")
    if not projection_inserted:
        raise RuntimeError("canonical_promoted_claim_projection_anchor_missing")

    names = [stage.name for stage in transformed]
    if len(transformed) != 42:
        raise RuntimeError(f"canonical_core_v2_stage_count_changed:{len(transformed)}")
    if names.count("isj_fact_kernel") != 1 or names.count("isj_fact_kernel_integrity") != 1:
        raise RuntimeError("canonical_fact_kernel_pair_not_unique")
    if names.count("promoted_claim_writer_projection") != 1 or names.count("promoted_claim_projection_validation") != 1:
        raise RuntimeError("canonical_promoted_claim_projection_pair_not_unique")

    fact_index = names.index("isj_fact_kernel")
    fact_integrity_index = names.index("isj_fact_kernel_integrity")
    projection_index = names.index("promoted_claim_writer_projection")
    validation_index = names.index("promoted_claim_projection_validation")
    consumption_index = names.index("promoted_claim_writer_consumption")
    fact_promotion_validation_index = names.index("isj_fact_kernel_deadline_promotion_validation")
    if fact_index != fact_promotion_validation_index + 1:
        raise RuntimeError("canonical_fact_kernel_anchor_order_changed")
    if fact_integrity_index != fact_index + 1 or projection_index != fact_integrity_index + 1:
        raise RuntimeError("canonical_fact_kernel_projection_order_changed")
    if validation_index != projection_index + 1 or consumption_index != validation_index + 1:
        raise RuntimeError("canonical_promoted_claim_projection_order_changed")

    actual_fact_kernel = (transformed[fact_index], transformed[fact_integrity_index])
    if actual_fact_kernel != _owned_fact_kernel_stages(workdir):
        raise RuntimeError("canonical_owned_fact_kernel_definition_drifted")
    actual_projection = (transformed[projection_index], transformed[validation_index])
    if actual_projection != _owned_projection_stages(workdir):
        raise RuntimeError("canonical_owned_promoted_claim_projection_definition_drifted")

    fact_ownership = _fact_kernel_stage_ownership_snapshot(tuple(transformed))
    if fact_ownership["status"] != "PASS_SHADOW":
        raise RuntimeError("fact_kernel_direct_ownership_not_proven")
    if fact_ownership["frozen_run81_fact_kernel_definitions_consumed"] is not False:
        raise RuntimeError("frozen_run81_fact_kernel_definition_consumed")
    if fact_ownership["retirement_eligible"] is not False:
        raise RuntimeError("fact_kernel_retirement_must_remain_closed")

    projection_ownership = _promoted_claim_projection_stage_ownership_snapshot(tuple(transformed))
    if projection_ownership["status"] != "PASS_SHADOW":
        raise RuntimeError("promoted_claim_projection_direct_ownership_not_proven")
    if projection_ownership["frozen_run81_projection_definitions_consumed"] is not False:
        raise RuntimeError("frozen_run81_projection_definition_consumed")
    if projection_ownership["retirement_eligible"] is not False:
        raise RuntimeError("promoted_claim_projection_retirement_must_remain_closed")

    return tuple(transformed)


def _persisted_runtime_snapshots(plan: tuple[CycleStage, ...]) -> dict[str, Any]:
    snapshots = _BASE_SNAPSHOTS(plan)
    for stage in plan:
        if stage.name not in (_FACT_KERNEL_STAGES | _PROJECTION_STAGES):
            continue
        if stage.output is None or not stage.output.is_file():
            continue
        try:
            snapshots[stage.name] = json.loads(stage.output.read_text(encoding="utf-8"))
        except Exception:
            snapshots[stage.name] = {"parse_error": True, "path": str(stage.output)}
    snapshots["fact_kernel_stage_ownership"] = _fact_kernel_stage_ownership_snapshot(plan)
    snapshots["promoted_claim_projection_stage_ownership"] = _promoted_claim_projection_stage_ownership_snapshot(plan)
    return snapshots


# RUN81 ultimately delegates execution to the frozen RUN70 engine, which
# resolves these plan/snapshot globals at execution time. Patch only those
# seams; merge/deploy/site/social-write authority remains unchanged.
_base.bounded_cycle_plan = bounded_cycle_plan
_base._persisted_runtime_snapshots = _persisted_runtime_snapshots
_base._legacy.bounded_cycle_plan = bounded_cycle_plan
_base._legacy._persisted_runtime_snapshots = _persisted_runtime_snapshots

run_bounded_shadow_cycle = _base._legacy.run_bounded_shadow_cycle
main = _base._legacy.main


if __name__ == "__main__":
    raise SystemExit(main())
