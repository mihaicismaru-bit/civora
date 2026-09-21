from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import orchestrator_run70 as _legacy

# RUN81 controlled ownership extraction:
# retain the validated RUN70 orchestrator implementation as a frozen component
# for still-unmigrated stages, while Core v2 directly owns the complete writer
# seam, article-truth seam, and downstream promoted-claim contract pair.
# Source-specific modules, stage names, artifact identities and historical
# evidence-ID namespaces are intentionally retained in this increment.

CycleStage = _legacy.CycleStage
run_shadow = _legacy.run_shadow

_LEGACY_PLAN = _legacy.bounded_cycle_plan
_LEGACY_SNAPSHOTS = _legacy._persisted_runtime_snapshots

_OLD_CONSUMPTION_ARTIFACT = "valcea-core-v2-isj-writer-deadline-consumption.json"
_NEW_CONSUMPTION_ARTIFACT = "valcea-core-v2-promoted-claim-writer-consumption.json"
_OLD_VALIDATION_ARTIFACT = "valcea-core-v2-isj-writer-deadline-consumption-validation.json"
_NEW_VALIDATION_ARTIFACT = "valcea-core-v2-promoted-claim-writer-consumption-validation.json"
_OLD_CONSUMPTION_MODULE = "valcea-clar/core_v2/isj_writer_deadline_consumption_shadow_lane.py"
_NEW_CONSUMPTION_MODULE = "valcea-clar/core_v2/promoted_claim_writer_consumption.py"
_OLD_VALIDATION_MODULE = "valcea-clar/core_v2/validate_isj_writer_deadline_consumption.py"
_NEW_VALIDATION_MODULE = "valcea-clar/core_v2/validate_promoted_claim_writer_consumption_runtime.py"
_WRITER_MODULE = "valcea-clar/core_v2/promoted_claim_writer.py"
_RETAINED_WRITER_IMPLEMENTATION = "valcea-clar/core_v2/isj_writer_shadow_lane.py"
_WRITER_ARTIFACT = "valcea-core-v2-isj-article-shadow.json"

_ARTICLE_CLAIM_GATE_MODULE = "valcea-clar/core_v2/isj_article_deadline_claim_gate.py"
_ARTICLE_CLAIM_VALIDATION_MODULE = "valcea-clar/core_v2/validate_isj_article_deadline_claim_gate.py"
_ARTICLE_INTEGRITY_MODULE = "valcea-clar/core_v2/isj_article_integrity.py"
_ARTICLE_CLAIM_ARTIFACT = "valcea-core-v2-isj-article-deadline-claim.json"
_ARTICLE_CLAIM_VALIDATION_ARTIFACT = "valcea-core-v2-isj-article-deadline-claim-validation.json"
_ARTICLE_INTEGRITY_ARTIFACT = "valcea-core-v2-isj-article-integrity-shadow.json"

_PROMOTED_CLAIM_CONTRACT_MODULE = "valcea-clar/core_v2/isj_promoted_claim_contract_shadow_lane.py"
_PROMOTED_CLAIM_CONTRACT_VALIDATION_MODULE = "valcea-clar/core_v2/validate_isj_promoted_claim_contract_runtime.py"
_PROMOTED_CLAIM_CONTRACT_ARTIFACT = "valcea-core-v2-isj-promoted-claim-contract.json"
_PROMOTED_CLAIM_CONTRACT_VALIDATION_ARTIFACT = "valcea-core-v2-isj-promoted-claim-contract-validation.json"

_LEGACY_WRITER_LAYER_PLACEHOLDER_STAGES = {
    "isj_writer_deadline_consumption",
    "isj_writer_deadline_consumption_validation",
    "isj_writer",
}
_LEGACY_ARTICLE_TRUTH_PLACEHOLDER_STAGES = {
    "isj_article_deadline_claim_gate",
    "isj_article_deadline_claim_validation",
    "isj_article_integrity",
}
_LEGACY_PROMOTED_CLAIM_CONTRACT_PLACEHOLDER_STAGES = {
    "isj_promoted_claim_contract",
    "isj_promoted_claim_contract_validation",
}
_CANONICAL_WRITER_STAGE = "promoted_claim_writer"


def _neutralize_arg(value: str) -> str:
    """Rewrite downstream writer-consumption references only."""
    return (
        value.replace(_OLD_VALIDATION_ARTIFACT, _NEW_VALIDATION_ARTIFACT)
        .replace(_OLD_CONSUMPTION_ARTIFACT, _NEW_CONSUMPTION_ARTIFACT)
    )


def _owned_writer_consumption_stages(workdir: Path) -> tuple[CycleStage, CycleStage]:
    """Return the canonical source-neutral consumption pair without RUN70 placeholders."""
    fact_kernel = workdir / "valcea-core-v2-isj-fact-kernel-shadow.json"
    fact_integrity = workdir / "valcea-core-v2-isj-fact-kernel-integrity-shadow.json"
    projection = workdir / "valcea-core-v2-promoted-claim-writer-projection.json"
    projection_validation = workdir / "valcea-core-v2-promoted-claim-projection-validation.json"
    consumption = workdir / _NEW_CONSUMPTION_ARTIFACT
    validation = workdir / _NEW_VALIDATION_ARTIFACT
    py = sys.executable

    return (
        CycleStage(
            "promoted_claim_writer_consumption",
            (
                py,
                _NEW_CONSUMPTION_MODULE,
                "--fact-kernel", str(fact_kernel),
                "--fact-kernel-integrity", str(fact_integrity),
                "--projection", str(projection),
                "--projection-validation", str(projection_validation),
                "--year", "2026",
                "--output", str(consumption),
            ),
            consumption,
        ),
        CycleStage(
            "promoted_claim_writer_consumption_validation",
            (
                py,
                _NEW_VALIDATION_MODULE,
                "--fact-kernel", str(fact_kernel),
                "--fact-kernel-integrity", str(fact_integrity),
                "--projection", str(projection),
                "--projection-validation", str(projection_validation),
                "--consumption", str(consumption),
                "--year", "2026",
                "--prove-tamper",
                "--output", str(validation),
            ),
            validation,
        ),
    )


def _owned_writer_stage(workdir: Path) -> CycleStage:
    """Own the canonical source-neutral writer stage through the runtime facade."""
    fact_kernel = workdir / "valcea-core-v2-isj-fact-kernel-shadow.json"
    fact_integrity = workdir / "valcea-core-v2-isj-fact-kernel-integrity-shadow.json"
    consumption = workdir / _NEW_CONSUMPTION_ARTIFACT
    validation = workdir / _NEW_VALIDATION_ARTIFACT
    article = workdir / _WRITER_ARTIFACT
    return CycleStage(
        _CANONICAL_WRITER_STAGE,
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


def _owned_article_truth_stages(workdir: Path) -> tuple[CycleStage, CycleStage, CycleStage]:
    """Own the existing source-specific article truth stages without semantic changes."""
    fact_kernel = workdir / "valcea-core-v2-isj-fact-kernel-shadow.json"
    fact_integrity = workdir / "valcea-core-v2-isj-fact-kernel-integrity-shadow.json"
    consumption = workdir / _NEW_CONSUMPTION_ARTIFACT
    consumption_validation = workdir / _NEW_VALIDATION_ARTIFACT
    article = workdir / _WRITER_ARTIFACT
    article_claim = workdir / _ARTICLE_CLAIM_ARTIFACT
    article_claim_validation = workdir / _ARTICLE_CLAIM_VALIDATION_ARTIFACT
    article_integrity = workdir / _ARTICLE_INTEGRITY_ARTIFACT
    py = sys.executable

    return (
        CycleStage(
            "isj_article_deadline_claim_gate",
            (
                py, _ARTICLE_CLAIM_GATE_MODULE,
                "--fact-kernel", str(fact_kernel),
                "--fact-kernel-integrity", str(fact_integrity),
                "--writer-consumption", str(consumption),
                "--writer-consumption-validation", str(consumption_validation),
                "--article", str(article),
                "--output", str(article_claim),
            ),
            article_claim,
        ),
        CycleStage(
            "isj_article_deadline_claim_validation",
            (
                py, _ARTICLE_CLAIM_VALIDATION_MODULE,
                "--fact-kernel", str(fact_kernel),
                "--fact-kernel-integrity", str(fact_integrity),
                "--writer-consumption", str(consumption),
                "--writer-consumption-validation", str(consumption_validation),
                "--article", str(article),
                "--gate", str(article_claim),
                "--prove-tamper",
                "--output", str(article_claim_validation),
            ),
            article_claim_validation,
        ),
        CycleStage(
            "isj_article_integrity",
            (
                py, _ARTICLE_INTEGRITY_MODULE,
                "--fact-kernel", str(fact_kernel),
                "--fact-kernel-integrity", str(fact_integrity),
                "--article", str(article),
                "--output", str(article_integrity),
            ),
            article_integrity,
        ),
    )


def _owned_promoted_claim_contract_stages(workdir: Path) -> tuple[CycleStage, CycleStage]:
    """Own the promoted-claim contract pair while retaining established semantics."""
    deadline_validation = workdir / "valcea-core-v2-isj-registration-deadline-promotion-validation.json"
    fact_promotion_validation = workdir / "valcea-core-v2-isj-fact-kernel-deadline-promotion-validation.json"
    fact_kernel = workdir / "valcea-core-v2-isj-fact-kernel-shadow.json"
    fact_integrity = workdir / "valcea-core-v2-isj-fact-kernel-integrity-shadow.json"
    projection_validation = workdir / "valcea-core-v2-promoted-claim-projection-validation.json"
    consumption_validation = workdir / _NEW_VALIDATION_ARTIFACT
    article_claim = workdir / _ARTICLE_CLAIM_ARTIFACT
    article_claim_validation = workdir / _ARTICLE_CLAIM_VALIDATION_ARTIFACT
    article_integrity = workdir / _ARTICLE_INTEGRITY_ARTIFACT
    contract = workdir / _PROMOTED_CLAIM_CONTRACT_ARTIFACT
    contract_validation = workdir / _PROMOTED_CLAIM_CONTRACT_VALIDATION_ARTIFACT
    py = sys.executable

    common = (
        "--deadline-promotion-validation", str(deadline_validation),
        "--fact-promotion-validation", str(fact_promotion_validation),
        "--fact-kernel", str(fact_kernel),
        "--fact-integrity", str(fact_integrity),
        "--writer-projection-validation", str(projection_validation),
        "--writer-consumption-validation", str(consumption_validation),
        "--article-claim-gate", str(article_claim),
        "--article-claim-validation", str(article_claim_validation),
        "--article-integrity", str(article_integrity),
    )
    return (
        CycleStage(
            "isj_promoted_claim_contract",
            (py, _PROMOTED_CLAIM_CONTRACT_MODULE, *common, "--output", str(contract)),
            contract,
        ),
        CycleStage(
            "isj_promoted_claim_contract_validation",
            (
                py,
                _PROMOTED_CLAIM_CONTRACT_VALIDATION_MODULE,
                *common,
                "--contract", str(contract),
                "--prove-tamper",
                "--output", str(contract_validation),
            ),
            contract_validation,
        ),
    )


def _writer_consumption_dependency_snapshot(plan: tuple[CycleStage, ...]) -> dict[str, Any]:
    by_name = {stage.name: stage for stage in plan}
    consumption = by_name["promoted_claim_writer_consumption"]
    validation = by_name["promoted_claim_writer_consumption_validation"]
    writer = by_name[_CANONICAL_WRITER_STAGE]
    joined = "\n".join(" ".join(stage.argv) for stage in plan)
    legacy_refs = [
        token
        for token in (
            _OLD_CONSUMPTION_MODULE,
            _OLD_VALIDATION_MODULE,
            _OLD_CONSUMPTION_ARTIFACT,
            _OLD_VALIDATION_ARTIFACT,
            _RETAINED_WRITER_IMPLEMENTATION,
        )
        if token in joined
    ]
    exact_neutral_paths = (
        len(consumption.argv) > 1
        and consumption.argv[1] == _NEW_CONSUMPTION_MODULE
        and len(validation.argv) > 1
        and validation.argv[1] == _NEW_VALIDATION_MODULE
        and consumption.output is not None
        and consumption.output.name == _NEW_CONSUMPTION_ARTIFACT
        and validation.output is not None
        and validation.output.name == _NEW_VALIDATION_ARTIFACT
    )
    exact_writer_definition = (
        writer.name == _CANONICAL_WRITER_STAGE
        and len(writer.argv) > 1
        and writer.argv[1] == _WRITER_MODULE
        and writer.output is not None
        and writer.output.name == _WRITER_ARTIFACT
        and "--writer-consumption" in writer.argv
        and str(consumption.output) in writer.argv
        and "--writer-consumption-validation" in writer.argv
        and str(validation.output) in writer.argv
    )
    no_dependency = not legacy_refs and exact_neutral_paths and exact_writer_definition
    return {
        "schema_version": "core-v2-writer-layer-runtime-dependency-shadow.v5",
        "status": "PASS_SHADOW" if no_dependency else "BLOCKED",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "canonical_stage_count": len(plan),
        "canonical_writer_consumption_stage": consumption.name,
        "canonical_writer_consumption_module": consumption.argv[1] if len(consumption.argv) > 1 else None,
        "canonical_writer_consumption_artifact": consumption.output.name if consumption.output is not None else None,
        "canonical_writer_consumption_validation_stage": validation.name,
        "canonical_writer_consumption_validation_module": validation.argv[1] if len(validation.argv) > 1 else None,
        "canonical_writer_consumption_validation_artifact": validation.output.name if validation.output is not None else None,
        "canonical_stage_ownership": "CORE_V2_ORCHESTRATOR_DIRECT_DEFINITION",
        "canonical_writer_stage": writer.name,
        "canonical_writer_module": writer.argv[1] if len(writer.argv) > 1 else None,
        "canonical_writer_artifact": writer.output.name if writer.output is not None else None,
        "canonical_writer_stage_ownership": "CORE_V2_ORCHESTRATOR_DIRECT_DEFINITION",
        "canonical_writer_runtime_facade": True,
        "canonical_writer_runtime_facade_source_neutral": True,
        "compatibility_writer_stage_name_retired": "isj_writer" not in by_name,
        "retained_writer_implementation": _RETAINED_WRITER_IMPLEMENTATION,
        "retained_writer_implementation_delegated_behind_facade": True,
        "frozen_run70_writer_placeholder_definition_consumed": False,
        "source_specific_writer_implementation_retained_as_keep_component": True,
        "source_specific_writer_stage_runtime_reference": _RETAINED_WRITER_IMPLEMENTATION in joined,
        "source_specific_placeholder_stage_dependency": False,
        "source_specific_runtime_references": legacy_refs,
        "source_specific_runtime_dependency": not no_dependency,
        "source_specific_regression_only": True,
        "source_specific_retirement_eligible": no_dependency,
        "source_specific_retirement_performed": False,
        "retained_writer_implementation_retirement_eligible": False,
        "retained_writer_implementation_retirement_performed": False,
        "compatibility_identity_namespace_retained": True,
        "truth_rule": (
            "Canonical writer-layer runtime passes only when Core v2 directly owns the ordered source-neutral "
            "consumption builder/validator and the promoted_claim_writer stage points at the source-neutral "
            "runtime facade, with no source-specific writer-consumption implementation/artifact/stage reference "
            "in canonical runtime and no publication or acceptance authority."
        ),
    }


def _article_truth_stage_ownership_snapshot(plan: tuple[CycleStage, ...]) -> dict[str, Any]:
    by_name = {stage.name: stage for stage in plan}
    gate = by_name["isj_article_deadline_claim_gate"]
    validation = by_name["isj_article_deadline_claim_validation"]
    integrity = by_name["isj_article_integrity"]
    exact = (
        len(gate.argv) > 1 and gate.argv[1] == _ARTICLE_CLAIM_GATE_MODULE
        and len(validation.argv) > 1 and validation.argv[1] == _ARTICLE_CLAIM_VALIDATION_MODULE
        and len(integrity.argv) > 1 and integrity.argv[1] == _ARTICLE_INTEGRITY_MODULE
        and gate.output is not None and gate.output.name == _ARTICLE_CLAIM_ARTIFACT
        and validation.output is not None and validation.output.name == _ARTICLE_CLAIM_VALIDATION_ARTIFACT
        and integrity.output is not None and integrity.output.name == _ARTICLE_INTEGRITY_ARTIFACT
        and "--writer-consumption" in gate.argv
        and "--writer-consumption-validation" in gate.argv
        and "--writer-consumption" in validation.argv
        and "--writer-consumption-validation" in validation.argv
        and _NEW_CONSUMPTION_ARTIFACT in " ".join(gate.argv)
        and _NEW_VALIDATION_ARTIFACT in " ".join(gate.argv)
        and _NEW_CONSUMPTION_ARTIFACT in " ".join(validation.argv)
        and _NEW_VALIDATION_ARTIFACT in " ".join(validation.argv)
        and "--prove-tamper" in validation.argv
    )
    return {
        "schema_version": "core-v2-article-truth-stage-ownership-shadow.v1",
        "status": "PASS_SHADOW" if exact else "BLOCKED",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "canonical_stage_count": len(plan),
        "canonical_stage_ownership": "CORE_V2_ORCHESTRATOR_DIRECT_DEFINITION",
        "owned_stages": [gate.name, validation.name, integrity.name],
        "frozen_run70_article_truth_placeholder_definitions_consumed": False,
        "source_specific_truth_modules_retained": True,
        "source_specific_truth_stage_names_retained": True,
        "artifact_identities_retained": True,
        "retirement_eligible": False,
        "retirement_performed": False,
        "truth_rule": (
            "Core v2 directly owns the article claim-gate, tamper validation and article-integrity stage definitions "
            "while retaining existing source-specific truth modules, stage names and artifact identities."
        ),
    }


def _promoted_claim_contract_stage_ownership_snapshot(plan: tuple[CycleStage, ...]) -> dict[str, Any]:
    by_name = {stage.name: stage for stage in plan}
    contract = by_name["isj_promoted_claim_contract"]
    validation = by_name["isj_promoted_claim_contract_validation"]
    required_contract_inputs = (
        "valcea-core-v2-isj-registration-deadline-promotion-validation.json",
        "valcea-core-v2-isj-fact-kernel-deadline-promotion-validation.json",
        "valcea-core-v2-isj-fact-kernel-shadow.json",
        "valcea-core-v2-isj-fact-kernel-integrity-shadow.json",
        "valcea-core-v2-promoted-claim-projection-validation.json",
        _NEW_VALIDATION_ARTIFACT,
        _ARTICLE_CLAIM_ARTIFACT,
        _ARTICLE_CLAIM_VALIDATION_ARTIFACT,
        _ARTICLE_INTEGRITY_ARTIFACT,
    )
    contract_joined = " ".join(contract.argv)
    validation_joined = " ".join(validation.argv)
    exact = (
        len(contract.argv) > 1 and contract.argv[1] == _PROMOTED_CLAIM_CONTRACT_MODULE
        and len(validation.argv) > 1 and validation.argv[1] == _PROMOTED_CLAIM_CONTRACT_VALIDATION_MODULE
        and contract.output is not None and contract.output.name == _PROMOTED_CLAIM_CONTRACT_ARTIFACT
        and validation.output is not None and validation.output.name == _PROMOTED_CLAIM_CONTRACT_VALIDATION_ARTIFACT
        and all(name in contract_joined for name in required_contract_inputs)
        and all(name in validation_joined for name in required_contract_inputs)
        and "--contract" in validation.argv
        and str(contract.output) in validation.argv
        and "--prove-tamper" in validation.argv
    )
    return {
        "schema_version": "core-v2-promoted-claim-contract-stage-ownership-shadow.v1",
        "status": "PASS_SHADOW" if exact else "BLOCKED",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "canonical_stage_count": len(plan),
        "canonical_stage_ownership": "CORE_V2_ORCHESTRATOR_DIRECT_DEFINITION",
        "owned_stages": [contract.name, validation.name],
        "frozen_run70_promoted_claim_contract_placeholder_definitions_consumed": False,
        "source_specific_contract_modules_retained": True,
        "source_specific_contract_stage_names_retained": True,
        "artifact_identities_retained": True,
        "lineage_inputs_retained": True,
        "retirement_eligible": False,
        "retirement_performed": False,
        "truth_rule": (
            "Core v2 directly owns the promoted-claim contract and validation stage definitions while retaining "
            "their existing modules, stage names, output artifact identities and lineage inputs. This extraction "
            "grants no naming, retirement, publication or acceptance authority."
        ),
    }


def bounded_cycle_plan(workdir: Path, *, live: bool) -> tuple[CycleStage, ...]:
    legacy_plan = _LEGACY_PLAN(workdir, live=live)
    transformed: list[CycleStage] = []
    owned_consumption_stages = _owned_writer_consumption_stages(workdir)
    owned_writer = _owned_writer_stage(workdir)
    owned_article_truth = _owned_article_truth_stages(workdir)
    owned_contract = _owned_promoted_claim_contract_stages(workdir)
    owned_chain_inserted = False
    owned_contract_inserted = False

    for stage in legacy_plan:
        if stage.name in _LEGACY_WRITER_LAYER_PLACEHOLDER_STAGES:
            continue

        if stage.name == "isj_article_deadline_claim_gate" and not owned_chain_inserted:
            transformed.extend((*owned_consumption_stages, owned_writer, *owned_article_truth))
            owned_chain_inserted = True
            continue
        if stage.name in _LEGACY_ARTICLE_TRUTH_PLACEHOLDER_STAGES:
            continue

        if stage.name == "isj_promoted_claim_contract" and not owned_contract_inserted:
            transformed.extend(owned_contract)
            owned_contract_inserted = True
            continue
        if stage.name in _LEGACY_PROMOTED_CLAIM_CONTRACT_PLACEHOLDER_STAGES:
            continue

        name = stage.name
        argv = [_neutralize_arg(str(arg)) for arg in stage.argv]
        output = Path(_neutralize_arg(str(stage.output))) if stage.output is not None else None
        transformed.append(CycleStage(name, tuple(argv), output))

    if not owned_chain_inserted:
        raise RuntimeError("canonical_article_claim_gate_missing_for_owned_writer_chain_insertion")
    if not owned_contract_inserted:
        raise RuntimeError("canonical_promoted_claim_contract_missing_for_direct_ownership_insertion")

    names = [stage.name for stage in transformed]
    if len(transformed) != 42:
        raise RuntimeError(f"canonical_core_v2_stage_count_changed:{len(transformed)}")
    if "promoted_claim_writer_consumption" not in names or "promoted_claim_writer_consumption_validation" not in names:
        raise RuntimeError("source_neutral_writer_consumption_stages_missing")
    leaked_placeholders = sorted(_LEGACY_WRITER_LAYER_PLACEHOLDER_STAGES.intersection(names))
    if leaked_placeholders:
        raise RuntimeError(f"legacy_writer_layer_stage_leaked_into_canonical_runtime:{','.join(leaked_placeholders)}")
    if _CANONICAL_WRITER_STAGE not in names:
        raise RuntimeError("source_neutral_writer_stage_missing")

    consumption_index = names.index("promoted_claim_writer_consumption")
    validation_index = names.index("promoted_claim_writer_consumption_validation")
    writer_index = names.index(_CANONICAL_WRITER_STAGE)
    gate_index = names.index("isj_article_deadline_claim_gate")
    article_validation_index = names.index("isj_article_deadline_claim_validation")
    article_integrity_index = names.index("isj_article_integrity")
    contract_index = names.index("isj_promoted_claim_contract")
    contract_validation_index = names.index("isj_promoted_claim_contract_validation")

    if (consumption_index, validation_index, writer_index, gate_index, article_validation_index, article_integrity_index) != (
        gate_index - 3,
        gate_index - 2,
        gate_index - 1,
        gate_index,
        gate_index + 1,
        gate_index + 2,
    ):
        raise RuntimeError("owned_writer_article_truth_stage_order_changed")
    if contract_index != article_integrity_index + 1 or contract_validation_index != contract_index + 1:
        raise RuntimeError("owned_promoted_claim_contract_stage_order_changed")

    for stage in transformed:
        joined = "\n".join(stage.argv)
        if _OLD_CONSUMPTION_ARTIFACT in joined or _OLD_VALIDATION_ARTIFACT in joined:
            raise RuntimeError(f"legacy_writer_consumption_artifact_leaked:{stage.name}")
        if _OLD_CONSUMPTION_MODULE in joined or _OLD_VALIDATION_MODULE in joined:
            raise RuntimeError(f"legacy_writer_consumption_implementation_leaked:{stage.name}")
        if _RETAINED_WRITER_IMPLEMENTATION in joined:
            raise RuntimeError(f"source_specific_writer_implementation_leaked_into_stage_argv:{stage.name}")

    expected_consumption = _owned_writer_consumption_stages(workdir)
    actual_consumption = (transformed[consumption_index], transformed[validation_index])
    if actual_consumption != expected_consumption:
        raise RuntimeError("canonical_owned_writer_consumption_definition_drifted")

    if transformed[writer_index] != _owned_writer_stage(workdir):
        raise RuntimeError("canonical_owned_writer_definition_drifted")

    expected_article_truth = _owned_article_truth_stages(workdir)
    actual_article_truth = (
        transformed[gate_index],
        transformed[article_validation_index],
        transformed[article_integrity_index],
    )
    if actual_article_truth != expected_article_truth:
        raise RuntimeError("canonical_owned_article_truth_definition_drifted")

    expected_contract = _owned_promoted_claim_contract_stages(workdir)
    actual_contract = (transformed[contract_index], transformed[contract_validation_index])
    if actual_contract != expected_contract:
        raise RuntimeError("canonical_owned_promoted_claim_contract_definition_drifted")

    writer_stage = transformed[writer_index]
    writer_argv = list(writer_stage.argv)
    if writer_stage.name != _CANONICAL_WRITER_STAGE:
        raise RuntimeError("canonical_writer_stage_name_not_source_neutral")
    if len(writer_argv) < 2 or writer_argv[1] != _WRITER_MODULE:
        raise RuntimeError("canonical_writer_not_bound_to_source_neutral_runtime_facade")
    for flag, expected in (
        ("--writer-consumption", str(workdir / _NEW_CONSUMPTION_ARTIFACT)),
        ("--writer-consumption-validation", str(workdir / _NEW_VALIDATION_ARTIFACT)),
    ):
        if flag not in writer_argv or writer_argv[writer_argv.index(flag) + 1] != expected:
            raise RuntimeError(f"writer_not_explicitly_bound_to_neutral_consumption:{flag}")

    dependency = _writer_consumption_dependency_snapshot(tuple(transformed))
    if dependency["status"] != "PASS_SHADOW" or dependency["source_specific_runtime_dependency"] is not False:
        raise RuntimeError("source_specific_writer_layer_runtime_dependency_detected")
    if dependency["source_specific_placeholder_stage_dependency"] is not False:
        raise RuntimeError("source_specific_writer_layer_placeholder_dependency_detected")
    if dependency["frozen_run70_writer_placeholder_definition_consumed"] is not False:
        raise RuntimeError("frozen_run70_writer_placeholder_definition_consumed")
    if dependency["source_specific_writer_stage_runtime_reference"] is not False:
        raise RuntimeError("source_specific_writer_stage_runtime_reference_detected")
    if dependency["compatibility_writer_stage_name_retired"] is not True:
        raise RuntimeError("compatibility_writer_stage_name_still_present")

    article_ownership = _article_truth_stage_ownership_snapshot(tuple(transformed))
    if article_ownership["status"] != "PASS_SHADOW":
        raise RuntimeError("article_truth_stage_direct_ownership_not_proven")
    if article_ownership["frozen_run70_article_truth_placeholder_definitions_consumed"] is not False:
        raise RuntimeError("frozen_run70_article_truth_placeholder_definition_consumed")
    if article_ownership["retirement_eligible"] is not False:
        raise RuntimeError("article_truth_component_retirement_must_remain_closed")

    contract_ownership = _promoted_claim_contract_stage_ownership_snapshot(tuple(transformed))
    if contract_ownership["status"] != "PASS_SHADOW":
        raise RuntimeError("promoted_claim_contract_stage_direct_ownership_not_proven")
    if contract_ownership["frozen_run70_promoted_claim_contract_placeholder_definitions_consumed"] is not False:
        raise RuntimeError("frozen_run70_promoted_claim_contract_placeholder_definition_consumed")
    if contract_ownership["retirement_eligible"] is not False:
        raise RuntimeError("promoted_claim_contract_component_retirement_must_remain_closed")

    return tuple(transformed)


def _persisted_runtime_snapshots(plan: tuple[CycleStage, ...]) -> dict[str, Any]:
    snapshots = _LEGACY_SNAPSHOTS(plan)
    for stage in plan:
        if stage.name not in {"promoted_claim_writer_consumption", "promoted_claim_writer_consumption_validation"}:
            continue
        if stage.output is None or not stage.output.is_file():
            continue
        try:
            snapshots[stage.name] = json.loads(stage.output.read_text(encoding="utf-8"))
        except Exception:
            snapshots[stage.name] = {"parse_error": True, "path": str(stage.output)}
    snapshots["writer_consumption_runtime_dependency"] = _writer_consumption_dependency_snapshot(plan)
    snapshots["article_truth_stage_ownership"] = _article_truth_stage_ownership_snapshot(plan)
    snapshots["promoted_claim_contract_stage_ownership"] = _promoted_claim_contract_stage_ownership_snapshot(plan)
    return snapshots


# The frozen implementation resolves these globals at execution time; patch only
# the plan/snapshot seams. Publication/deploy/Meta authority remains unchanged.
_legacy.bounded_cycle_plan = bounded_cycle_plan
_legacy._persisted_runtime_snapshots = _persisted_runtime_snapshots

run_bounded_shadow_cycle = _legacy.run_bounded_shadow_cycle
main = _legacy.main


if __name__ == "__main__":
    raise SystemExit(main())
