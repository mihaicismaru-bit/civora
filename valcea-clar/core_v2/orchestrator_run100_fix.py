from __future__ import annotations

import json
from typing import Any

import orchestrator_run100 as _base

# RUN100 correction: the lower migration modules patch RUN70's snapshot symbol
# during import, so capturing a supposedly frozen snapshot callable after those
# imports still resolves to the RUN81 42-stage contract-pair snapshotter. Build
# the 41-stage snapshots directly from the canonical plan instead.

globals().update({name: value for name, value in vars(_base).items() if not name.startswith("__")})


def _read_output(stage: Any) -> dict[str, Any] | None:
    if stage.output is None or not stage.output.is_file():
        return None
    try:
        value = json.loads(stage.output.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return value
        return {"parse_error": True, "path": str(stage.output), "reason": "non_object_json"}
    except Exception:
        return {"parse_error": True, "path": str(stage.output)}


def _persisted_runtime_snapshots(plan):
    snapshots: dict[str, Any] = {}
    # Persist every JSON stage artifact that exists. This is more observable than
    # the old bounded allow-list and does not infer truth from missing files.
    for stage in plan:
        value = _read_output(stage)
        if value is not None:
            snapshots[stage.name] = value

    snapshots["fact_kernel_stage_ownership"] = _base._fact_kernel_stage_ownership_snapshot(plan)
    snapshots["promoted_claim_projection_stage_ownership"] = _base._promoted_claim_projection_stage_ownership_snapshot(plan)
    snapshots["promoted_claim_consumption_stage_ownership"] = _base._promoted_claim_consumption_stage_ownership_snapshot(plan)
    snapshots["writer_consumption_runtime_dependency"] = _base._writer_consumption_dependency_snapshot(plan)
    snapshots["writer_stage_ownership"] = _base._writer_stage_ownership_snapshot(plan)
    snapshots["article_truth_stage_ownership"] = _base._article_truth_stage_ownership_snapshot(plan)
    snapshots["article_integrity_stage_ownership"] = _base._article_integrity_stage_ownership_snapshot(plan)
    snapshots["promoted_claim_contract_runtime_ownership"] = _base._promoted_claim_contract_stage_ownership_snapshot(plan)
    return snapshots


# Replace every live snapshot lookup seam after all lower wrappers have imported.
_base._persisted_runtime_snapshots = _persisted_runtime_snapshots
_base._base._persisted_runtime_snapshots = _persisted_runtime_snapshots
_base._base._base._persisted_runtime_snapshots = _persisted_runtime_snapshots
_base._base._base._base._persisted_runtime_snapshots = _persisted_runtime_snapshots
_base._RUN70._persisted_runtime_snapshots = _persisted_runtime_snapshots

run_bounded_shadow_cycle = _base._RUN70_ENGINE
main = _base._RUN70_MAIN


if __name__ == "__main__":
    raise SystemExit(main())
