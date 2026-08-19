#!/usr/bin/env python3
"""Fail closed when vNext build state drifts from build-ready/acceptance evidence.

Generic runtime code never names a locality. Instance-specific acceptance
receipts are referenced by VNEXT_STATE and resolved under the repository root.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VNEXT = ROOT / "local-news-os" / "vnext"


def load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def load_state_reference(state: dict, key: str) -> dict:
    acceptance = state.get("acceptance_state")
    require(isinstance(acceptance, dict), "acceptance_state must be an object")
    raw = acceptance.get(key)
    require(isinstance(raw, str) and raw, f"acceptance_state.{key} reference is required")
    relative = Path(raw)
    require(not relative.is_absolute() and ".." not in relative.parts, f"unsafe acceptance reference: {key}")
    resolved = (ROOT / relative).resolve()
    root = ROOT.resolve()
    require(root in resolved.parents, f"acceptance reference escapes repository: {key}")
    require(resolved.is_file(), f"acceptance evidence missing: {key}")
    return load(resolved)


def main() -> int:
    state = load(VNEXT / "VNEXT_STATE.json")
    ready = load(VNEXT / "BUILD_READY_FOR_MIGRATION.json")
    shadow = load_state_reference(state, "shadow_migration")
    projection = load_state_reference(state, "shadow_projection")
    preflight = load_state_reference(state, "controlled_live_preflight")

    require(state.get("site_owns_runtime") is True, "SITE_OWNS_RUNTIME drift")
    require(state.get("core_knows_no_locality") is True, "CORE_KNOWS_NO_LOCALITY drift")
    require(state.get("production_cutover") is False, "build state must not claim cutover before P18")
    require(ready.get("status") == "BUILD_READY_FOR_MIGRATION", "build-ready contract is not ready")
    require(ready.get("production_cutover") is False, "build-ready contract must remain pre-cutover")

    phases = state.get("phases", {})
    for phase in ready.get("completed_build_phases", []):
        require(phases.get(phase, {}).get("status") == "CLOSED", f"{phase} is not CLOSED in VNEXT_STATE")

    p18 = phases.get("P18_MIGRATION_SHADOW_LIVE_SOAK_PRODUCTION_LOCK", {})
    acceptance = state.get("acceptance_state", {})
    require(shadow.get("status") == acceptance.get("shadow_migration_status"), "shadow migration state/evidence mismatch")
    require(projection.get("status") == acceptance.get("shadow_projection_status"), "shadow projection state/evidence mismatch")
    require(preflight.get("status") == acceptance.get("controlled_live_status"), "controlled-live state/evidence mismatch")
    require(preflight.get("production_cutover") is False, "preflight cannot claim cutover")
    require(preflight.get("public_runtime_mutated") is False, "preflight cannot mutate public runtime")
    require(preflight.get("network_publication_attempted") is False, "preflight cannot attempt network publication")
    require(
        p18.get("status") == preflight.get("status"),
        "P18 status in VNEXT_STATE does not match controlled-live preflight",
    )
    require(p18.get("production_cutover") is False, "P18 state cannot claim cutover while not promoted")
    build_defects = acceptance.get("build_defects_open")
    require(isinstance(build_defects, list), "build_defects_open must be a list")
    require(p18.get("build_defect") is bool(build_defects), "P18 build_defect flag does not match build_defects_open")

    print("LOCAL NEWS OS vNext build state consistency: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
