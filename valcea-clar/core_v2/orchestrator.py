from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import orchestrator_run70 as _legacy

# RUN76 controlled compatibility boundary:
# retain the validated RUN70 orchestrator implementation as a frozen component
# for still-unmigrated stages, but make the canonical Core v2 orchestrator own
# the complete writer-consumption -> writer seam directly. The canonical writer
# stage now points at a source-neutral runtime facade; the useful ISJ writer
# remains a KEEP implementation detail behind that facade and is not retired in
# this increment. Frozen RUN70 writer-consumption and writer placeholders are
# skipped without reading or transforming their argv/output definitions.
# Historical evidence-ID namespaces stay stable deliberately so downstream
# lineage remains comparable across the migration.

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
_LEGACY_WRITER_LAYER_PLACEHOLDER_STAGES = {
    "isj_writer_deadline_consumption",
    "isj_writer_deadline_consumption_validation",
    "isj_writer",
}


def _neutralize_arg(value: str) -> str:
    """Rewrite downstream references only; canonical writer-layer stages are owned below."""
    return (
        value.replace(_OLD_VALIDATION_ARTIFACT, _NEW_VALIDATION_ARTIFACT)
        .replace(_OLD_CONSUMPTION_ARTIFACT, _NEW_CONSUMPTION_ARTIFACT)
    )


def _owned_writer_consumption_stages(workdir: Path) -> tuple[CycleStage, CycleStage]:
    """Return the canonical source-neutral consumption pair without consulting RUN70 placeholders."""
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
    """Own the canonical writer stage through the source-neutral runtime facade."""
    fact_kernel = workdir / "valcea-core-v2-isj-fact-kernel-shadow.json"
    fact_integrity = workdir / "valcea-core-v2-isj-fact-kernel-integrity-shadow.json"
    consumption = workdir / _NEW_CONSUMPTION_ARTIFACT
    validation = workdir / _NEW_VALIDATION_ARTIFACT
    article = workdir / _WRITER_ARTIFACT
    return CycleStage(
        "isj_writer",
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


def _writer_consumption_dependency_snapshot(plan: tuple[CycleStage, ...]) -> dict[str, Any]:
    by_name = {stage.name: stage for stage in plan}
    consumption = by_name["promoted_claim_writer_consumption"]
    validation = by_name["promoted_claim_writer_consumption_validation"]
    writer = by_name["isj_writer"]
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
        len(writer.argv) > 1
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
        "schema_version": "core-v2-writer-layer-runtime-dependency-shadow.v4",
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
            "Canonical writer-layer runtime passes only when Core v2 directly owns the ordered source-neutral consumption builder/validator and points the writer stage at the source-neutral promoted_claim_writer runtime facade, "
            "the facade consumes the neutral artifacts explicitly, no source-specific ISJ module or legacy writer-consumption implementation/artifact reference appears in canonical stage argv, and no publication or acceptance authority is granted. "
            "The retained ISJ writer implementation remains a KEEP implementation detail behind the facade; this proof does not claim that implementation source-neutral or retirement-eligible."
        ),
    }


def bounded_cycle_plan(workdir: Path, *, live: bool) -> tuple[CycleStage, ...]:
    legacy_plan = _LEGACY_PLAN(workdir, live=live)
    transformed: list[CycleStage] = []
    owned_consumption_stages = _owned_writer_consumption_stages(workdir)
    owned_writer = _owned_writer_stage(workdir)
    owned_chain_inserted = False

    for stage in legacy_plan:
        # Do not transform or consume the frozen writer-layer placeholder
        # definitions. They are skipped as legacy evidence only.
        if stage.name in _LEGACY_WRITER_LAYER_PLACEHOLDER_STAGES:
            continue

        # Insert the complete Core-v2-owned writer seam immediately before the
        # first downstream article-claim gate. This preserves the validated order
        # while eliminating dependence on the frozen RUN70 writer definition.
        if stage.name == "isj_article_deadline_claim_gate" and not owned_chain_inserted:
            transformed.extend((*owned_consumption_stages, owned_writer))
            owned_chain_inserted = True

        name = stage.name
        argv = [_neutralize_arg(str(arg)) for arg in stage.argv]
        output = Path(_neutralize_arg(str(stage.output))) if stage.output is not None else None
        transformed.append(CycleStage(name, tuple(argv), output))

    if not owned_chain_inserted:
        raise RuntimeError("canonical_article_claim_gate_missing_for_owned_writer_chain_insertion")

    names = [stage.name for stage in transformed]
    if len(transformed) != 42:
        raise RuntimeError(f"canonical_core_v2_stage_count_changed:{len(transformed)}")
    if "promoted_claim_writer_consumption" not in names or "promoted_claim_writer_consumption_validation" not in names:
        raise RuntimeError("source_neutral_writer_consumption_stages_missing")
    if _LEGACY_WRITER_LAYER_PLACEHOLDER_STAGES.intersection(names) != {"isj_writer"}:
        leaked = sorted(_LEGACY_WRITER_LAYER_PLACEHOLDER_STAGES.intersection(names) - {"isj_writer"})
        if leaked:
            raise RuntimeError(f"legacy_writer_layer_stage_leaked_into_canonical_runtime:{','.join(leaked)}")

    consumption_index = names.index("promoted_claim_writer_consumption")
    validation_index = names.index("promoted_claim_writer_consumption_validation")
    writer_index = names.index("isj_writer")
    gate_index = names.index("isj_article_deadline_claim_gate")
    if (consumption_index, validation_index, writer_index, gate_index) != (
        gate_index - 3,
        gate_index - 2,
        gate_index - 1,
        gate_index,
    ):
        raise RuntimeError("owned_writer_layer_stage_order_changed")

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

    writer_stage = transformed[writer_index]
    writer_argv = list(writer_stage.argv)
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
    return snapshots


# The frozen implementation resolves these globals at execution time; patch only
# the plan/snapshot seams. Publication/deploy/Meta authority remains unchanged.
_legacy.bounded_cycle_plan = bounded_cycle_plan
_legacy._persisted_runtime_snapshots = _persisted_runtime_snapshots

run_bounded_shadow_cycle = _legacy.run_bounded_shadow_cycle
main = _legacy.main


if __name__ == "__main__":
    raise SystemExit(main())
