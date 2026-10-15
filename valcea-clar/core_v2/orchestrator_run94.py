from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import orchestrator_run86 as _base

# RUN92 controlled canonical article-truth switch:
# freeze the naturally validated RUN91 surface and switch only the two canonical
# article claim gate/validation stages to the source-neutral Core v2 CLI.
# Preserve stage names, argv/output semantics, 42-stage order, evidence identity,
# retained ISJ implementations as regression components, and the no-authority
# publication/acceptance boundary.

CycleStage = _base.CycleStage
run_shadow = _base.run_shadow

_BASE_PLAN = _base.bounded_cycle_plan
_BASE_SNAPSHOTS = _base._persisted_runtime_snapshots

# Preserve existing test/introspection seams while RUN70/RUN81/RUN86 remain
# frozen semantic references during the controlled migration.
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

_WRITER_STAGE = "promoted_claim_writer"
_WRITER_MODULE = "valcea-clar/core_v2/promoted_claim_writer.py"
_RETAINED_WRITER_IMPLEMENTATION = "valcea-clar/core_v2/isj_writer_shadow_lane.py"
_WRITER_ARTIFACT = "valcea-core-v2-isj-article-shadow.json"
_FACT_KERNEL_ARTIFACT = "valcea-core-v2-isj-fact-kernel-shadow.json"
_FACT_KERNEL_INTEGRITY_ARTIFACT = "valcea-core-v2-isj-fact-kernel-integrity-shadow.json"
_CONSUMPTION_ARTIFACT = "valcea-core-v2-promoted-claim-writer-consumption.json"
_CONSUMPTION_VALIDATION_ARTIFACT = "valcea-core-v2-promoted-claim-writer-consumption-validation.json"

_ARTICLE_GATE_STAGE = "isj_article_deadline_claim_gate"
_ARTICLE_VALIDATION_STAGE = "isj_article_deadline_claim_validation"
_ARTICLE_INTEGRITY_STAGE = "isj_article_integrity"
_ARTICLE_TRUTH_MODULE = "valcea-clar/core_v2/promoted_claim_article_truth.py"
_RETAINED_ARTICLE_GATE_IMPLEMENTATION = "valcea-clar/core_v2/isj_article_deadline_claim_gate.py"
_RETAINED_ARTICLE_VALIDATOR_IMPLEMENTATION = "valcea-clar/core_v2/validate_isj_article_deadline_claim_gate.py"
_ARTICLE_INTEGRITY_MODULE = "valcea-clar/core_v2/isj_article_integrity.py"
_ARTICLE_GATE_ARTIFACT = "valcea-core-v2-isj-article-deadline-claim.json"
_ARTICLE_VALIDATION_ARTIFACT = "valcea-core-v2-isj-article-deadline-claim-validation.json"
_ARTICLE_INTEGRITY_ARTIFACT = "valcea-core-v2-isj-article-integrity-shadow.json"


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


def _owned_article_truth_switch_stages(workdir: Path) -> tuple[CycleStage, CycleStage]:
    """Bind the existing canonical gate/validation names to the neutral CLI."""
    fact_kernel = workdir / _FACT_KERNEL_ARTIFACT
    fact_integrity = workdir / _FACT_KERNEL_INTEGRITY_ARTIFACT
    consumption = workdir / _CONSUMPTION_ARTIFACT
    consumption_validation = workdir / _CONSUMPTION_VALIDATION_ARTIFACT
    article = workdir / _WRITER_ARTIFACT
    gate = workdir / _ARTICLE_GATE_ARTIFACT
    validation = workdir / _ARTICLE_VALIDATION_ARTIFACT
    return (
        CycleStage(
            _ARTICLE_GATE_STAGE,
            (
                sys.executable,
                _ARTICLE_TRUTH_MODULE,
                "--mode", "gate",
                "--fact-kernel", str(fact_kernel),
                "--fact-kernel-integrity", str(fact_integrity),
                "--writer-consumption", str(consumption),
                "--writer-consumption-validation", str(consumption_validation),
                "--article", str(article),
                "--output", str(gate),
            ),
            gate,
        ),
        CycleStage(
            _ARTICLE_VALIDATION_STAGE,
            (
                sys.executable,
                _ARTICLE_TRUTH_MODULE,
                "--mode", "validate",
                "--fact-kernel", str(fact_kernel),
                "--fact-kernel-integrity", str(fact_integrity),
                "--writer-consumption", str(consumption),
                "--writer-consumption-validation", str(consumption_validation),
                "--article", str(article),
                "--gate", str(gate),
                "--prove-tamper",
                "--output", str(validation),
            ),
            validation,
        ),
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


def _article_truth_stage_ownership_snapshot(plan: tuple[CycleStage, ...]) -> dict[str, Any]:
    by_name = {stage.name: stage for stage in plan}
    gate = by_name[_ARTICLE_GATE_STAGE]
    validation = by_name[_ARTICLE_VALIDATION_STAGE]
    integrity = by_name[_ARTICLE_INTEGRITY_STAGE]
    joined = "\n".join(" ".join(stage.argv) for stage in (gate, validation))
    names = [stage.name for stage in plan]
    writer_index = names.index(_WRITER_STAGE)
    gate_index = names.index(_ARTICLE_GATE_STAGE)
    validation_index = names.index(_ARTICLE_VALIDATION_STAGE)
    integrity_index = names.index(_ARTICLE_INTEGRITY_STAGE)
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
        and "--writer-consumption" in gate.argv
        and "--writer-consumption-validation" in gate.argv
        and "--writer-consumption" in validation.argv
        and "--writer-consumption-validation" in validation.argv
        and _CONSUMPTION_ARTIFACT in joined
        and _CONSUMPTION_VALIDATION_ARTIFACT in joined
        and "--gate" in validation.argv
        and str(gate.output) in validation.argv
        and "--prove-tamper" in validation.argv
        and gate_index == writer_index + 1
        and validation_index == gate_index + 1
        and integrity_index == validation_index + 1
        and _RETAINED_ARTICLE_GATE_IMPLEMENTATION not in joined
        and _RETAINED_ARTICLE_VALIDATOR_IMPLEMENTATION not in joined
    )
    return {
        "schema_version": "core-v2-article-truth-stage-ownership-shadow.v2",
        "status": "PASS_SHADOW" if exact else "BLOCKED",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "canonical_stage_count": len(plan),
        "canonical_stage_ownership": "CORE_V2_ORCHESTRATOR_DIRECT_DEFINITION",
        "owned_stages": [gate.name, validation.name, integrity.name],
        "source_neutral_article_truth_cli": _ARTICLE_TRUTH_MODULE,
        "canonical_gate_mode": "gate",
        "canonical_validation_mode": "validate",
        "canonical_runtime_switched": True,
        "canonical_stage_definitions_switched": True,
        "frozen_run70_article_truth_placeholder_definitions_consumed": False,
        "frozen_run81_article_truth_definitions_consumed": False,
        "retained_gate_implementation": _RETAINED_ARTICLE_GATE_IMPLEMENTATION,
        "retained_validator_implementation": _RETAINED_ARTICLE_VALIDATOR_IMPLEMENTATION,
        "source_specific_truth_modules_retained": True,
        "source_specific_truth_modules_runtime_dependency": False,
        "source_specific_truth_stage_names_retained": True,
        "artifact_identities_retained": True,
        "lineage_inputs_retained": True,
        "canonical_order_writer_gate_validation_integrity_preserved": True,
        "retained_implementations_regression_only": True,
        "retained_implementations_retirement_eligible": False,
        "retirement_eligible": False,
        "retirement_performed": False,
        "retirement_authority": "NONE",
        "truth_rule": (
            "Core v2 now binds the existing canonical article claim-gate and validation stage names one-for-one "
            "to the source-neutral promoted_claim_article_truth CLI while preserving their exact artifact identities, "
            "upstream lineage and writer->gate->validation->integrity order. The retained ISJ gate and validator remain "
            "KEEP regression implementations and are not runtime dependencies or retirement candidates. The switch grants "
            "no publication, acceptance, merge, deploy or retirement authority."
        ),
    }


def bounded_cycle_plan(workdir: Path, *, live: bool) -> tuple[CycleStage, ...]:
    base_plan = _BASE_PLAN(workdir, live=live)
    owned_writer = _owned_writer_stage(workdir)
    owned_gate, owned_validation = _owned_article_truth_switch_stages(workdir)
    transformed: list[CycleStage] = []
    writer_inserted = False
    gate_inserted = False
    validation_inserted = False

    for stage in base_plan:
        if stage.name == _WRITER_STAGE and not writer_inserted:
            transformed.append(owned_writer)
            writer_inserted = True
            continue
        if stage.name == _WRITER_STAGE:
            continue
        if stage.name == _ARTICLE_GATE_STAGE and not gate_inserted:
            transformed.append(owned_gate)
            gate_inserted = True
            continue
        if stage.name == _ARTICLE_GATE_STAGE:
            continue
        if stage.name == _ARTICLE_VALIDATION_STAGE and not validation_inserted:
            transformed.append(owned_validation)
            validation_inserted = True
            continue
        if stage.name == _ARTICLE_VALIDATION_STAGE:
            continue
        transformed.append(stage)

    if not writer_inserted:
        raise RuntimeError("canonical_promoted_claim_writer_anchor_missing")
    if not gate_inserted or not validation_inserted:
        raise RuntimeError("canonical_article_truth_anchor_missing")

    names = [stage.name for stage in transformed]
    if len(transformed) != 42:
        raise RuntimeError(f"canonical_core_v2_stage_count_changed:{len(transformed)}")
    for name in (_WRITER_STAGE, _ARTICLE_GATE_STAGE, _ARTICLE_VALIDATION_STAGE, _ARTICLE_INTEGRITY_STAGE):
        if names.count(name) != 1:
            raise RuntimeError(f"canonical_stage_not_unique:{name}")

    writer_index = names.index(_WRITER_STAGE)
    consumption_validation_index = names.index("promoted_claim_writer_consumption_validation")
    gate_index = names.index(_ARTICLE_GATE_STAGE)
    validation_index = names.index(_ARTICLE_VALIDATION_STAGE)
    integrity_index = names.index(_ARTICLE_INTEGRITY_STAGE)
    if writer_index != consumption_validation_index + 1:
        raise RuntimeError("canonical_promoted_claim_writer_upstream_order_changed")
    if (gate_index, validation_index, integrity_index) != (writer_index + 1, writer_index + 2, writer_index + 3):
        raise RuntimeError("canonical_article_truth_order_changed")
    if transformed[writer_index] != _owned_writer_stage(workdir):
        raise RuntimeError("canonical_owned_promoted_claim_writer_definition_drifted")
    if (transformed[gate_index], transformed[validation_index]) != _owned_article_truth_switch_stages(workdir):
        raise RuntimeError("canonical_source_neutral_article_truth_definition_drifted")

    integrity = transformed[integrity_index]
    if len(integrity.argv) < 2 or integrity.argv[1] != _ARTICLE_INTEGRITY_MODULE:
        raise RuntimeError("canonical_article_integrity_module_changed")
    if integrity.output is None or integrity.output.name != _ARTICLE_INTEGRITY_ARTIFACT:
        raise RuntimeError("canonical_article_integrity_artifact_changed")

    ownership = _writer_stage_ownership_snapshot(tuple(transformed))
    if ownership["status"] != "PASS_SHADOW":
        raise RuntimeError("promoted_claim_writer_direct_ownership_not_proven")
    if ownership["frozen_run81_writer_definition_consumed"] is not False:
        raise RuntimeError("frozen_run81_writer_definition_consumed")
    if ownership["retirement_eligible"] is not False:
        raise RuntimeError("promoted_claim_writer_retirement_must_remain_closed")

    article_ownership = _article_truth_stage_ownership_snapshot(tuple(transformed))
    if article_ownership["status"] != "PASS_SHADOW":
        raise RuntimeError("source_neutral_article_truth_switch_not_proven")
    if article_ownership["frozen_run81_article_truth_definitions_consumed"] is not False:
        raise RuntimeError("frozen_run81_article_truth_definition_consumed")
    if article_ownership["retirement_eligible"] is not False:
        raise RuntimeError("article_truth_retirement_must_remain_closed")
    if article_ownership["publication_authority"] != "NONE" or article_ownership["acceptance_ready"] is not False:
        raise RuntimeError("article_truth_switch_authority_boundary_changed")

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
    # RUN81's ownership snapshot intentionally describes its frozen ISJ-bound
    # definitions. Replace that telemetry key after the controlled one-for-one
    # switch so persisted state reflects the actual canonical plan.
    snapshots["article_truth_stage_ownership"] = _article_truth_stage_ownership_snapshot(plan)
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
