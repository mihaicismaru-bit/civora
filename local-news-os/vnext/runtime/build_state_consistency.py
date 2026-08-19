#!/usr/bin/env python3
"""Fail closed when vNext build state drifts from build-ready/acceptance evidence."""

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


def main() -> int:
    state = load(VNEXT / "VNEXT_STATE.json")
    ready = load(VNEXT / "BUILD_READY_FOR_MIGRATION.json")
    shadow = load(VNEXT / "acceptance" / "valcea-p18-shadow-latest.json")
    projection = load(VNEXT / "acceptance" / "valcea-p18-projection-latest.json")
    preflight = load(VNEXT / "acceptance" / "valcea-p18-controlled-live-preflight-latest.json")

    require(state.get("site_owns_runtime") is True, "SITE_OWNS_RUNTIME drift")
    require(state.get("core_knows_no_locality") is True, "CORE_KNOWS_NO_LOCALITY drift")
    require(state.get("production_cutover") is False, "build state must not claim cutover before P18")
    require(ready.get("status") == "BUILD_READY_FOR_MIGRATION", "build-ready contract is not ready")
    require(ready.get("production_cutover") is False, "build-ready contract must remain pre-cutover")

    phases = state.get("phases", {})
    for phase in ready.get("completed_build_phases", []):
        require(phases.get(phase, {}).get("status") == "CLOSED", f"{phase} is not CLOSED in VNEXT_STATE")

    p18 = phases.get("P18_MIGRATION_SHADOW_LIVE_SOAK_PRODUCTION_LOCK", {})
    require(shadow.get("status") == "SHADOW_MIGRATION_PASS", "shadow migration evidence is not PASS")
    require(projection.get("status") == "SHADOW_PROJECTION_PASS", "shadow projection evidence is not PASS")
    require(preflight.get("production_cutover") is False, "preflight cannot claim cutover")
    require(preflight.get("public_runtime_mutated") is False, "preflight cannot mutate public runtime")
    require(preflight.get("network_publication_attempted") is False, "preflight cannot attempt network publication")
    require(
        preflight.get("status") == "BLOCKED_EXTERNAL_RUNTIME_BINDING",
        "controlled-live preflight status changed; canonical state must be reconciled before promotion",
    )
    require(
        p18.get("status") == preflight.get("status"),
        "P18 status in VNEXT_STATE does not match controlled-live preflight",
    )
    require(p18.get("build_defect") is False, "external runtime binding must not be mislabeled as a build defect")
    require(p18.get("production_cutover") is False, "P18 state cannot claim cutover while externally blocked")
    require(state.get("acceptance_state", {}).get("build_defects_open") == [], "unexpected open build defects")

    print("LOCAL NEWS OS vNext build state consistency: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
