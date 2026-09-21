from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import orchestrator_run86 as _base

# RUN87 controlled ownership extraction:
# freeze the naturally validated RUN86 orchestrator and move the canonical
# promoted_claim_writer stage itself into a direct Core v2 definition. Preserve
# the source-neutral facade, argv/output semantics, 42-stage order, retained ISJ
# implementation behind the facade, and the no-publication/no-acceptance boundary.

CycleStage = _base.CycleStage
run_shadow = _base.run_shadow

_BASE_PLAN = _base.bounded_cycle_plan
_BASE_SNAPSHOTS = _base._persisted_runtime_snapshots

# Preserve existing test/introspection seams while RUN70/RUN81/RUN86 remain
# frozen semantic references during the controlled migration.
_LEGACY_PLAN = _base._LEGACY_PLAN
_writer_consumption_dependency_snapshot = _base._writer_consumption_dependency_snapshot
_article_truth_stage_ownership_snapshot = _base._article_truth_stage_ownership_snapshot
_promoted_claim_contract_stage_ownership_snapshot = _base._promoted_claim_contract_stage_ownership_snapshot
_owned_article_truth_stages = _base._owned_article_truth_stages
_owned_promoted_claim_contract_stages = _base._owned_promoted_claim_contract_stages
_owned_fact_kernel_stages = _base._owned_fact_kernel_stages
_fact_kernel_stage_ownership_snapshot = _base._fact_kernel_stage_ownership_snapshot
_owned_projection_stages = _base._owned_projection_stages
_promoted_claim_projection_stage_ownership_snapshot = _base._promoted_claim_projection_stage_ownership_snapshot
_owned_consumption_stages = _base._owned_consumption_stages
_promoted_claim_consumption_stage_ownership_snapshot = _base._promoted_claim_consumption_stage_ownership_snapshot

_WRITER_STAGE = "promoted_claim_writer"
_WRITER_MODULE = "valcea-clar/core_v2/promoted_claim_writer.py"
_RETAINED_WRITER_IMPLEMENTATION = "valcea-clar/core_v2/isj_writer_shadow_lane.py"
_WRITER_ARTIFACT = "valcea-core-v2-isj-article-shadow.json"
_FACT_KERNEL_ARTIFACT = "valcea-core-v2-isj-fact-kernel-shadow.json"
_FACT_KERNEL_INTEGRITY_ARTIFACT = "valcea-core-v2-isj-fact-kernel-integrity-shadow.json"
_CONSUMPTION_ARTIFACT = "valcea-core-v2-promoted-claim-writer-consumption.json"
_CONSUMPTION_VALIDATION_ARTIFACT = "valcea-core-v2-promoted-claim-writer-consumption-validation.json"


def _owned_writer_stage(workdir: Path) -> CycleStage:
    """Own the existing source-neutral writer facade without semantic change."""
    fact_kernel = workdir / _FACT_KERNEL_ARTIFACT
    fact_integrity = workdir / _FACT_KERNEL_INTEGRITY_ARTIFACT
    consumption = workdir / _CONSUMPTION_ARTIFACT
    validation = workdir / _CONSUMPTION_VALIDATION_ARTIFACT
    article = workdir / _WRITER_ARTIFACT
    return CycleStage(
        _WRITER_STAGE,
        (
            sys.executable,
            _WRITER_MODULE,
            "--fact-kernel", str(fact_kernel),
            "--fact-kernel-integrity", str(fact_integrity),
            "--writer-consumption", str(consumption),
            "--writer-consumption-validation", str(validation),
            "--output", str(article),
        ),
        article,
    )


def _writer_stage_ownership_snapshot(plan: tuple[CycleStage, ...]) -> dict[str, Any]:
    by_name = {stage.name: stage for stage in plan}
    writer = by_name[_WRITER_STAGE]
    joined = " ".join(writer.argv)
    exact = (
        writer.name == _WRITER_STAGE
        and len(writer.argv) > 1
        and writer.argv[1] == _WRITER_MODULE
        and writer.output is not None
        and writer.output.name == _WRITER_ARTIFACT
        and _FACT_KERNEL_ARTIFACT in joined
        and _FACT_KERNEL_INTEGRITY_ARTIFACT in joined
        and _CONSUMPTION_ARTIFACT in joined
        and _CONSUMPTION_VALIDATION_ARTIFACT in joined
        and "--writer-consumption" in writer.argv
        and "--writer-consumption-validation" in writer.argv
        and "--output" in writer.argv
    )
    return {
        "schema_version": "core-v2-promoted-claim-writer-stage-ownership-shadow.v1",
        "status": "PASS_SHADOW" if exact else "BLOCKED",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "canonical_stage_count": len(plan),
        "canonical_stage_ownership": "CORE_V2_ORCHESTRATOR_DIRECT_DEFINITION",
        "owned_stage": writer.name,
        "canonical_writer_module": writer.argv[1] if len(writer.argv) > 1 else None,
        "canonical_writer_artifact": writer.output.name if writer.output is not None else None,
        "frozen_run81_writer_definition_consumed": False,
        "frozen_run86_writer_stage_anchor_used_for_position_only": True,
        "source_neutral_writer_facade_retained": True,
        "retained_writer_implementation": _RETAINED_WRITER_IMPLEMENTATION,
        "retained_writer_implementation_delegated_behind_facade": True,
        "retained_writer_implementation_retirement_eligible": False,
        "stage_name_retained": True,
        "artifact_identity_retained": True,
        "lineage_inputs_retained": True,
        "retirement_eligible": False,
        "retirement_performed": False,
        "truth_rule": (
            "Core v2 directly owns the canonical promoted_claim_writer stage while preserving the naturally "
            "validated source-neutral facade, exact upstream writer-consumption lineage, article artifact and "
            "42-stage position. The retained ISJ writer stays behind the facade as a KEEP implementation detail. "
            "This extraction grants no retirement, publication or acceptance authority."
        ),
    }


def bounded_cycle_plan(workdir: Path, *, live: bool) -> tuple[CycleStage, ...]:
    base_plan = _BASE_PLAN(workdir, live=live)
    owned_writer = _owned_writer_stage(workdir)
    transformed: list[CycleStage] = []
    writer_inserted = False

    for stage in base_plan:
        if stage.name == _WRITER_STAGE and not writer_inserted:
            transformed.append(owned_writer)
            writer_inserted = True
            continue
        if stage.name == _WRITER_STAGE:
            continue
        transformed.append(stage)

    if not writer_inserted:
        raise RuntimeError("canonical_promoted_claim_writer_anchor_missing")

    names = [stage.name for stage in transformed]
    if len(transformed) != 42:
        raise RuntimeError(f"canonical_core_v2_stage_count_changed:{len(transformed)}")
    if names.count(_WRITER_STAGE) != 1:
        raise RuntimeError("canonical_promoted_claim_writer_not_unique")

    writer_index = names.index(_WRITER_STAGE)
    consumption_validation_index = names.index("promoted_claim_writer_consumption_validation")
    article_gate_index = names.index("isj_article_deadline_claim_gate")
    if writer_index != consumption_validation_index + 1:
        raise RuntimeError("canonical_promoted_claim_writer_upstream_order_changed")
    if article_gate_index != writer_index + 1:
        raise RuntimeError("canonical_promoted_claim_writer_downstream_order_changed")
    if transformed[writer_index] != _owned_writer_stage(workdir):
        raise RuntimeError("canonical_owned_promoted_claim_writer_definition_drifted")

    ownership = _writer_stage_ownership_snapshot(tuple(transformed))
    if ownership["status"] != "PASS_SHADOW":
        raise RuntimeError("promoted_claim_writer_direct_ownership_not_proven")
    if ownership["frozen_run81_writer_definition_consumed"] is not False:
        raise RuntimeError("frozen_run81_writer_definition_consumed")
    if ownership["retirement_eligible"] is not False:
        raise RuntimeError("promoted_claim_writer_retirement_must_remain_closed")

    return tuple(transformed)


def _persisted_runtime_snapshots(plan: tuple[CycleStage, ...]) -> dict[str, Any]:
    snapshots = _BASE_SNAPSHOTS(plan)
    writer = next((stage for stage in plan if stage.name == _WRITER_STAGE), None)
    if writer is not None and writer.output is not None and writer.output.is_file():
        try:
            snapshots[_WRITER_STAGE] = json.loads(writer.output.read_text(encoding="utf-8"))
        except Exception:
            snapshots[_WRITER_STAGE] = {"parse_error": True, "path": str(writer.output)}
    snapshots["promoted_claim_writer_stage_ownership"] = _writer_stage_ownership_snapshot(plan)
    return snapshots


# RUN70 executes through globals in the frozen legacy module. Patch only the
# plan/snapshot seams needed for the next controlled ownership layer.
_base.bounded_cycle_plan = bounded_cycle_plan
_base._persisted_runtime_snapshots = _persisted_runtime_snapshots
_base._base.bounded_cycle_plan = bounded_cycle_plan
_base._base._persisted_runtime_snapshots = _persisted_runtime_snapshots
_base._base._legacy.bounded_cycle_plan = bounded_cycle_plan
_base._base._legacy._persisted_runtime_snapshots = _persisted_runtime_snapshots

run_bounded_shadow_cycle = _base._base._legacy.run_bounded_shadow_cycle
main = _base._base._legacy.main


if __name__ == "__main__":
    raise SystemExit(main())
