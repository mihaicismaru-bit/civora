#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / "eucons" / "ops" / "github_automation.py"


def load_engine():
    spec = importlib.util.spec_from_file_location("eucons_github_automation", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load E22 automation helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    engine = load_engine()

    reconciled = engine.reconcile()
    if reconciled["status"] != "PASS" or reconciled["canonical_state_mutated"] is not False:
        raise SystemExit("E22 canonical reconciliation must pass read-only on current state")
    health = engine.health_check()
    if health["status"] != "PASS" or health["external_side_effects"] is not False:
        raise SystemExit("E22 canonical health must pass with production gates closed")
    scheduled = engine.scheduler_receipt("2026-08-19T10:00:00Z")
    if scheduled["status"] != "PASS" or scheduled["external_publication"] is not False or scheduled["provider_credentials_used"] is not False:
        raise SystemExit("E22 scheduler must remain credential-free and non-publishing")

    with tempfile.TemporaryDirectory() as td:
        temp = Path(td)
        empty_build = temp / "empty-build"
        empty_build.mkdir()
        try:
            engine.directory_manifest(empty_build)
        except ValueError:
            pass
        else:
            raise SystemExit("E22 empty build must fail closed")

        original_checkpoint = engine.CHECKPOINT_PATH
        original_health = engine.HEALTH_PATH
        checkpoint = json.loads(original_checkpoint.read_text(encoding="utf-8"))
        checkpoint["completed_phases"] = checkpoint["completed_phases"] + [checkpoint["current_phase"]]
        bad_checkpoint = temp / "checkpoint.json"
        bad_checkpoint.write_text(json.dumps(checkpoint), encoding="utf-8")
        engine.CHECKPOINT_PATH = bad_checkpoint
        try:
            result = engine.reconcile()
            if result["status"] != "FAIL" or "CURRENT_PHASE_ALREADY_COMPLETED" not in result["critical_failures"]:
                raise SystemExit("E22 phase/checkpoint contradiction did not fail closed")
        finally:
            engine.CHECKPOINT_PATH = original_checkpoint

        health_data = json.loads(original_health.read_text(encoding="utf-8"))
        health_data["checks"]["linkedin_direct_publication"] = "ACTIVE"
        bad_health = temp / "health.json"
        bad_health.write_text(json.dumps(health_data), encoding="utf-8")
        engine.HEALTH_PATH = bad_health
        try:
            result = engine.health_check()
            if result["status"] != "FAIL" or not result["open_or_missing_production_gates"]:
                raise SystemExit("E22 open production gate did not fail closed")
        finally:
            engine.HEALTH_PATH = original_health

    print("EUCONS E22 GitHub Automation fail-closed: PASS")


if __name__ == "__main__":
    main()
