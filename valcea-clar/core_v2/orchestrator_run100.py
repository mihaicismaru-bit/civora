from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import orchestrator_run94 as _base

# RUN100 controlled runtime shrink:
# - retain the naturally validated RUN94 migration surface;
# - keep the source-neutral article-integrity facade introduced after RUN94;
# - remove ONLY isj_promoted_claim_contract_validation from runtime execution;
# - retain that validator as CI-only regression coverage;
# - do not insert the external auditor in this same increment.

CycleStage = _base.CycleStage
run_shadow = _base.run_shadow

_BASE_PLAN = _base.bounded_cycle_plan

# Capture the frozen RUN70 snapshot/engine seams before patching them. RUN81's
# snapshot helper assumes the validation stage is present, so it must not be
# called with the post-extraction 41-stage plan.
_RUN70 = _base._base._base._legacy
_RUN70_SNAPSHOTS = _RUN70._persisted_runtime_snapshots
_RUN70_ENGINE = _RUN70.run_bounded_shadow_cycle
_RUN70_MAIN = _RUN70.main

# Preserve established migration/test exports.
_LEGACY_PLAN = _base._LEGACY_PLAN
_writer_consumption_dependency_snapshot = _base._writer_consumption_dependency_snapshot
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

_CONTRACT_STAGE = "isj_promoted_claim_contract"
_CONTRACT_VALIDATION_STAGE = "isj_promoted_claim_contract_validation"
_CONTRACT_MODULE = "valcea-clar/core_v2/isj_promoted_claim_contract_shadow_lane.py"
_CONTRACT_VALIDATION_MODULE = "valcea-clar/core_v2/validate_isj_promoted_claim_contract_runtime.py"
_CONTRACT_ARTIFACT = "valcea-core-v2-isj-promoted-claim-contract.json"
_CONTRACT_VALIDATION_ARTIFACT = "valcea-core-v2-isj-promoted-claim-contract-validation.json"
_EXTERNAL_AUDIT_STAGE = "core_v2_external_audit"


def _owned_article_integrity_switch_stage(workdir: Path) -> CycleStage:
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
        len(plan) == 41
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
        and _RETAINED_ARTICLE_GATE_IMPLEMENTATION not in joined
        and _RETAINED_ARTICLE_VALIDATOR_IMPLEMENTATION not in joined
        and _RETAINED_ARTICLE_INTEGRITY_IMPLEMENTATION not in joined
    )
    return {
        "schema_version": "core-v2-article-truth-stage-ownership-shadow.v4",
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
    }


def _article_integrity_stage_ownership_snapshot(plan: tuple[CycleStage, ...]) -> dict[str, Any]:
    by_name = {stage.name: stage for stage in plan}
    integrity = by_name[_ARTICLE_INTEGRITY_STAGE]
    joined = " ".join(integrity.argv)
    exact = (
        len(plan) == 41
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
        "schema_version": "core-v2-promoted-claim-article-integrity-stage-ownership-shadow.v2",
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


def _promoted_claim_contract_stage_ownership_snapshot(plan: tuple[CycleStage, ...]) -> dict[str, Any]:
    by_name = {stage.name: stage for stage in plan}
    contract = by_name.get(_CONTRACT_STAGE)
    names = [stage.name for stage in plan]
    joined = "\n".join(" ".join(stage.argv) for stage in plan)
    exact = (
        len(plan) == 41
        and contract is not None
        and names.count(_CONTRACT_STAGE) == 1
        and _CONTRACT_VALIDATION_STAGE not in by_name
        and len(contract.argv) > 1
        and contract.argv[1] == _CONTRACT_MODULE
        and contract.output is not None
        and contract.output.name == _CONTRACT_ARTIFACT
        and _CONTRACT_VALIDATION_MODULE not in joined
        and _CONTRACT_VALIDATION_ARTIFACT not in joined
        and _EXTERNAL_AUDIT_STAGE not in by_name
    )
    return {
        "schema_version": "core-v2-promoted-claim-contract-runtime-ownership-shadow.v2",
        "status": "PASS_SHADOW" if exact else "BLOCKED",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "canonical_stage_count": len(plan),
        "canonical_contract_stage": _CONTRACT_STAGE,
        "canonical_contract_module": contract.argv[1] if contract is not None and len(contract.argv) > 1 else None,
        "canonical_contract_artifact": contract.output.name if contract is not None and contract.output is not None else None,
        "runtime_validation_stage_present": _CONTRACT_VALIDATION_STAGE in by_name,
        "runtime_validation_module_present": _CONTRACT_VALIDATION_MODULE in joined,
        "runtime_validation_artifact_referenced": _CONTRACT_VALIDATION_ARTIFACT in joined,
        "ci_only_validation_stage": _CONTRACT_VALIDATION_STAGE,
        "ci_only_validation_module": _CONTRACT_VALIDATION_MODULE,
        "ci_only_validation_artifact": _CONTRACT_VALIDATION_ARTIFACT,
        "runtime_extraction_performed": True,
        "ci_only_regression_retained": True,
        "external_auditor_inserted": False,
        "retirement_eligible": False,
        "retirement_performed": False,
        "retirement_authority": "NONE",
        "cutover_authority": "NONE",
        "truth_rule": (
            "The promoted-claim contract remains a canonical runtime truth artifact, while its deterministic validator is "
            "removed from runtime execution and retained as CI-only regression coverage. The validation artifact must not "
            "be consumed by any runtime stage. This controlled extraction grants no publication, acceptance, cutover or "
            "retirement authority and does not insert the external auditor."
        ),
    }


def bounded_cycle_plan(workdir: Path, *, live: bool) -> tuple[CycleStage, ...]:
    base_plan = _BASE_PLAN(workdir, live=live)
    owned_integrity = _owned_article_integrity_switch_stage(workdir)
    transformed: list[CycleStage] = []
    integrity_inserted = False
    extracted_validation_count = 0

    for stage in base_plan:
        if stage.name == _ARTICLE_INTEGRITY_STAGE and not integrity_inserted:
            transformed.append(owned_integrity)
            integrity_inserted = True
            continue
        if stage.name == _ARTICLE_INTEGRITY_STAGE:
            continue
        if stage.name == _CONTRACT_VALIDATION_STAGE:
            extracted_validation_count += 1
            continue
        transformed.append(stage)

    if not integrity_inserted:
        raise RuntimeError("canonical_article_integrity_anchor_missing")
    if extracted_validation_count != 1:
        raise RuntimeError(f"canonical_contract_validation_extraction_count_changed:{extracted_validation_count}")

    names = [stage.name for stage in transformed]
    if len(transformed) != 41:
        raise RuntimeError(f"canonical_core_v2_stage_count_changed:{len(transformed)}")
    if _CONTRACT_VALIDATION_STAGE in names:
        raise RuntimeError("ci_only_contract_validation_leaked_into_runtime")
    if _EXTERNAL_AUDIT_STAGE in names:
        raise RuntimeError("external_auditor_inserted_during_validation_extraction")
    for name in (_WRITER_STAGE, _ARTICLE_GATE_STAGE, _ARTICLE_VALIDATION_STAGE, _ARTICLE_INTEGRITY_STAGE, _CONTRACT_STAGE):
        if names.count(name) != 1:
            raise RuntimeError(f"canonical_stage_not_unique:{name}")

    writer_index = names.index(_WRITER_STAGE)
    gate_index = names.index(_ARTICLE_GATE_STAGE)
    validation_index = names.index(_ARTICLE_VALIDATION_STAGE)
    integrity_index = names.index(_ARTICLE_INTEGRITY_STAGE)
    contract_index = names.index(_CONTRACT_STAGE)
    site_ledger_index = names.index("site_verified_article_ledger")
    if (gate_index, validation_index, integrity_index) != (writer_index + 1, writer_index + 2, writer_index + 3):
        raise RuntimeError("canonical_writer_gate_validation_integrity_order_changed")
    if contract_index != integrity_index + 1:
        raise RuntimeError("canonical_promoted_claim_contract_order_changed")
    if site_ledger_index != contract_index + 1:
        raise RuntimeError("canonical_post_contract_order_changed_after_ci_extraction")
    if transformed[-1].name != "shadow_site_package":
        raise RuntimeError("canonical_terminal_stage_changed")
    if transformed[integrity_index] != _owned_article_integrity_switch_stage(workdir):
        raise RuntimeError("canonical_source_neutral_article_integrity_definition_drifted")

    joined = "\n".join(" ".join(stage.argv) for stage in transformed)
    if _CONTRACT_VALIDATION_MODULE in joined or _CONTRACT_VALIDATION_ARTIFACT in joined:
        raise RuntimeError("ci_only_contract_validation_runtime_reference_detected")

    article_ownership = _article_truth_stage_ownership_snapshot(tuple(transformed))
    if article_ownership["status"] != "PASS_SHADOW":
        raise RuntimeError("source_neutral_article_truth_integrity_switch_not_proven")
    integrity_ownership = _article_integrity_stage_ownership_snapshot(tuple(transformed))
    if integrity_ownership["status"] != "PASS_SHADOW":
        raise RuntimeError("source_neutral_article_integrity_switch_not_proven")
    contract_ownership = _promoted_claim_contract_stage_ownership_snapshot(tuple(transformed))
    if contract_ownership["status"] != "PASS_SHADOW":
        raise RuntimeError("promoted_claim_contract_validation_ci_extraction_not_proven")

    return tuple(transformed)


def _read_stage_output(snapshots: dict[str, Any], stage: CycleStage) -> None:
    if stage.output is None or not stage.output.is_file():
        return
    try:
        snapshots[stage.name] = json.loads(stage.output.read_text(encoding="utf-8"))
    except Exception:
        snapshots[stage.name] = {"parse_error": True, "path": str(stage.output)}


def _persisted_runtime_snapshots(plan: tuple[CycleStage, ...]) -> dict[str, Any]:
    # RUN70's collector tolerates absent stages. Layer migration-owned snapshots
    # back on top without invoking RUN81's 42-stage contract-pair assumptions.
    snapshots = _RUN70_SNAPSHOTS(plan)
    migration_stage_names = {
        "isj_fact_kernel", "isj_fact_kernel_integrity",
        "promoted_claim_writer_projection", "promoted_claim_projection_validation",
        "promoted_claim_writer_consumption", "promoted_claim_writer_consumption_validation",
        _WRITER_STAGE, _ARTICLE_GATE_STAGE, _ARTICLE_VALIDATION_STAGE,
        _ARTICLE_INTEGRITY_STAGE, _CONTRACT_STAGE,
    }
    for stage in plan:
        if stage.name in migration_stage_names:
            _read_stage_output(snapshots, stage)

    snapshots["fact_kernel_stage_ownership"] = _fact_kernel_stage_ownership_snapshot(plan)
    snapshots["promoted_claim_projection_stage_ownership"] = _promoted_claim_projection_stage_ownership_snapshot(plan)
    snapshots["promoted_claim_consumption_stage_ownership"] = _promoted_claim_consumption_stage_ownership_snapshot(plan)
    snapshots["writer_consumption_runtime_dependency"] = _writer_consumption_dependency_snapshot(plan)
    snapshots["writer_stage_ownership"] = _writer_stage_ownership_snapshot(plan)
    snapshots["article_truth_stage_ownership"] = _article_truth_stage_ownership_snapshot(plan)
    snapshots["article_integrity_stage_ownership"] = _article_integrity_stage_ownership_snapshot(plan)
    snapshots["promoted_claim_contract_runtime_ownership"] = _promoted_claim_contract_stage_ownership_snapshot(plan)
    return snapshots


# The execution engine is still the frozen RUN70 sequential engine. Patch only
# its plan/snapshot resolution path; no merge/deploy/site/social-write authority
# is introduced.
_base.bounded_cycle_plan = bounded_cycle_plan
_base._persisted_runtime_snapshots = _persisted_runtime_snapshots
_base._base.bounded_cycle_plan = bounded_cycle_plan
_base._base._persisted_runtime_snapshots = _persisted_runtime_snapshots
_base._base._base.bounded_cycle_plan = bounded_cycle_plan
_base._base._base._persisted_runtime_snapshots = _persisted_runtime_snapshots
_RUN70.bounded_cycle_plan = bounded_cycle_plan
_RUN70._persisted_runtime_snapshots = _persisted_runtime_snapshots

run_bounded_shadow_cycle = _RUN70_ENGINE
main = _RUN70_MAIN


if __name__ == "__main__":
    raise SystemExit(main())
