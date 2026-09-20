from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import orchestrator_run70 as _legacy

# RUN71 controlled compatibility boundary:
# retain the validated RUN70 orchestrator implementation as a frozen component,
# but make the canonical 42-stage runtime use the source-neutral writer-consumption
# builder/validator and neutral artifact names. Historical evidence-ID namespaces
# stay unchanged deliberately so downstream lineage remains stable.

CycleStage = _legacy.CycleStage
run_shadow = _legacy.run_shadow

_LEGACY_PLAN = _legacy.bounded_cycle_plan
_LEGACY_SNAPSHOTS = _legacy._persisted_runtime_snapshots

_OLD_CONSUMPTION_ARTIFACT = "valcea-core-v2-isj-writer-deadline-consumption.json"
_NEW_CONSUMPTION_ARTIFACT = "valcea-core-v2-promoted-claim-writer-consumption.json"
_OLD_VALIDATION_ARTIFACT = "valcea-core-v2-isj-writer-deadline-consumption-validation.json"
_NEW_VALIDATION_ARTIFACT = "valcea-core-v2-promoted-claim-writer-consumption-validation.json"


def _neutralize_arg(value: str) -> str:
    return (
        value.replace(_OLD_VALIDATION_ARTIFACT, _NEW_VALIDATION_ARTIFACT)
        .replace(_OLD_CONSUMPTION_ARTIFACT, _NEW_CONSUMPTION_ARTIFACT)
    )


def bounded_cycle_plan(workdir: Path, *, live: bool) -> tuple[CycleStage, ...]:
    plan = _LEGACY_PLAN(workdir, live=live)
    transformed: list[CycleStage] = []
    for stage in plan:
        name = stage.name
        argv = [_neutralize_arg(str(arg)) for arg in stage.argv]
        output = Path(_neutralize_arg(str(stage.output))) if stage.output is not None else None

        if name == "isj_writer_deadline_consumption":
            name = "promoted_claim_writer_consumption"
            argv[1] = "valcea-clar/core_v2/promoted_claim_writer_consumption.py"
        elif name == "isj_writer_deadline_consumption_validation":
            name = "promoted_claim_writer_consumption_validation"
            argv[1] = "valcea-clar/core_v2/validate_promoted_claim_writer_consumption_runtime.py"

        transformed.append(CycleStage(name, tuple(argv), output))

    names = [stage.name for stage in transformed]
    if len(transformed) != 42:
        raise RuntimeError(f"canonical_core_v2_stage_count_changed:{len(transformed)}")
    if "promoted_claim_writer_consumption" not in names or "promoted_claim_writer_consumption_validation" not in names:
        raise RuntimeError("source_neutral_writer_consumption_stages_missing")
    if "isj_writer_deadline_consumption" in names or "isj_writer_deadline_consumption_validation" in names:
        raise RuntimeError("legacy_writer_consumption_stage_leaked_into_canonical_runtime")
    for stage in transformed:
        joined = "\n".join(stage.argv)
        if _OLD_CONSUMPTION_ARTIFACT in joined or _OLD_VALIDATION_ARTIFACT in joined:
            raise RuntimeError(f"legacy_writer_consumption_artifact_leaked:{stage.name}")
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
    return snapshots


# The frozen implementation resolves these globals at execution time; patch only
# the plan/snapshot seams. Publication/deploy/Meta authority remains unchanged.
_legacy.bounded_cycle_plan = bounded_cycle_plan
_legacy._persisted_runtime_snapshots = _persisted_runtime_snapshots

run_bounded_shadow_cycle = _legacy.run_bounded_shadow_cycle
main = _legacy.main


if __name__ == "__main__":
    raise SystemExit(main())
