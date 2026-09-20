from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import orchestrator_run70 as _legacy

# RUN73 controlled compatibility boundary:
# retain the validated RUN70 orchestrator implementation as a frozen component
# for the still-unmigrated stages, but make the canonical orchestrator own the
# source-neutral writer-consumption stage definitions directly. The frozen RUN70
# writer-consumption placeholders are filtered out without reading or transforming
# their argv/output definitions. Historical evidence-ID namespaces stay unchanged
# deliberately so downstream lineage remains stable.
#
# Source-specific ISJ writer-consumption modules may remain in the repository only
# as independent regression evidence; they are not a canonical runtime dependency.

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
_SOURCE_SPECIFIC_PLACEHOLDER_STAGES = {
    "isj_writer_deadline_consumption",
    "isj_writer_deadline_consumption_validation",
}


def _neutralize_arg(value: str) -> str:
    """Rewrite downstream references only; canonical neutral stages are owned below."""
    return (
        value.replace(_OLD_VALIDATION_ARTIFACT, _NEW_VALIDATION_ARTIFACT)
        .replace(_OLD_CONSUMPTION_ARTIFACT, _NEW_CONSUMPTION_ARTIFACT)
    )


def _owned_writer_consumption_stages(workdir: Path) -> tuple[CycleStage, CycleStage]:
    """Return the two canonical source-neutral stages without consulting RUN70 placeholders."""
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


def _writer_consumption_dependency_snapshot(plan: tuple[CycleStage, ...]) -> dict[str, Any]:
    by_name = {stage.name: stage for stage in plan}
    consumption = by_name["promoted_claim_writer_consumption"]
    validation = by_name["promoted_claim_writer_consumption_validation"]
    joined = "\n".join(" ".join(stage.argv) for stage in plan)
    legacy_refs = [
        token
        for token in (
            _OLD_CONSUMPTION_MODULE,
            _OLD_VALIDATION_MODULE,
            _OLD_CONSUMPTION_ARTIFACT,
            _OLD_VALIDATION_ARTIFACT,
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
    no_dependency = not legacy_refs and exact_neutral_paths
    return {
        "schema_version": "core-v2-writer-consumption-runtime-dependency-shadow.v2",
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
        "source_specific_placeholder_stage_dependency": False,
        "source_specific_runtime_references": legacy_refs,
        "source_specific_runtime_dependency": not no_dependency,
        "source_specific_regression_only": True,
        "source_specific_retirement_eligible": no_dependency,
        "source_specific_retirement_performed": False,
        "compatibility_identity_namespace_retained": True,
        "truth_rule": (
            "Canonical writer-consumption runtime is retirement-eligible only when Core v2 directly owns the ordered source-neutral builder and validator stages, "
            "references their artifacts exactly, contains no source-specific ISJ writer-consumption implementation/artifact reference, and grants no publication or acceptance authority."
        ),
    }


def bounded_cycle_plan(workdir: Path, *, live: bool) -> tuple[CycleStage, ...]:
    legacy_plan = _LEGACY_PLAN(workdir, live=live)
    transformed: list[CycleStage] = []
    owned_stages = _owned_writer_consumption_stages(workdir)
    owned_inserted = False

    for stage in legacy_plan:
        # Do not transform or consume the frozen source-specific placeholder
        # definitions. They are skipped as legacy evidence only.
        if stage.name in _SOURCE_SPECIFIC_PLACEHOLDER_STAGES:
            continue

        if stage.name == "isj_writer" and not owned_inserted:
            transformed.extend(owned_stages)
            owned_inserted = True

        name = stage.name
        argv = [_neutralize_arg(str(arg)) for arg in stage.argv]
        output = Path(_neutralize_arg(str(stage.output))) if stage.output is not None else None

        if name == "isj_writer":
            # Eliminate the hidden legacy filename auto-discovery dependency. The
            # writer consumes the canonical neutral pair explicitly; writer code
            # itself remains a kept/reused component in this increment.
            argv.extend([
                "--writer-consumption", str(workdir / _NEW_CONSUMPTION_ARTIFACT),
                "--writer-consumption-validation", str(workdir / _NEW_VALIDATION_ARTIFACT),
            ])

        transformed.append(CycleStage(name, tuple(argv), output))

    if not owned_inserted:
        raise RuntimeError("canonical_writer_stage_missing_for_owned_consumption_insertion")

    names = [stage.name for stage in transformed]
    if len(transformed) != 42:
        raise RuntimeError(f"canonical_core_v2_stage_count_changed:{len(transformed)}")
    if "promoted_claim_writer_consumption" not in names or "promoted_claim_writer_consumption_validation" not in names:
        raise RuntimeError("source_neutral_writer_consumption_stages_missing")
    if _SOURCE_SPECIFIC_PLACEHOLDER_STAGES.intersection(names):
        raise RuntimeError("legacy_writer_consumption_stage_leaked_into_canonical_runtime")

    # The two owned stages must be adjacent and immediately precede the writer,
    # preserving the validated golden-path ordering without consulting placeholders.
    consumption_index = names.index("promoted_claim_writer_consumption")
    validation_index = names.index("promoted_claim_writer_consumption_validation")
    writer_index = names.index("isj_writer")
    if (consumption_index, validation_index, writer_index) != (
        writer_index - 2,
        writer_index - 1,
        writer_index,
    ):
        raise RuntimeError("owned_writer_consumption_stage_order_changed")

    for stage in transformed:
        joined = "\n".join(stage.argv)
        if _OLD_CONSUMPTION_ARTIFACT in joined or _OLD_VALIDATION_ARTIFACT in joined:
            raise RuntimeError(f"legacy_writer_consumption_artifact_leaked:{stage.name}")
        if _OLD_CONSUMPTION_MODULE in joined or _OLD_VALIDATION_MODULE in joined:
            raise RuntimeError(f"legacy_writer_consumption_implementation_leaked:{stage.name}")

    expected_owned = _owned_writer_consumption_stages(workdir)
    actual_owned = (transformed[consumption_index], transformed[validation_index])
    if actual_owned != expected_owned:
        raise RuntimeError("canonical_owned_writer_consumption_definition_drifted")

    writer_stage = transformed[writer_index]
    writer_argv = list(writer_stage.argv)
    for flag, expected in (
        ("--writer-consumption", str(workdir / _NEW_CONSUMPTION_ARTIFACT)),
        ("--writer-consumption-validation", str(workdir / _NEW_VALIDATION_ARTIFACT)),
    ):
        if flag not in writer_argv or writer_argv[writer_argv.index(flag) + 1] != expected:
            raise RuntimeError(f"writer_not_explicitly_bound_to_neutral_consumption:{flag}")

    dependency = _writer_consumption_dependency_snapshot(tuple(transformed))
    if dependency["status"] != "PASS_SHADOW" or dependency["source_specific_runtime_dependency"] is not False:
        raise RuntimeError("source_specific_writer_consumption_runtime_dependency_detected")
    if dependency["source_specific_placeholder_stage_dependency"] is not False:
        raise RuntimeError("source_specific_writer_consumption_placeholder_dependency_detected")
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
