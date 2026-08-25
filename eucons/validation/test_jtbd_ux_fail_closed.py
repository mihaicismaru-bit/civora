#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "validation" / "validate_jtbd_ux.py"
CONTRACT_PATH = ROOT / "web" / "jtbd_ux_contract.json"


def load_validator():
    spec = importlib.util.spec_from_file_location("validate_jtbd_ux", VALIDATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def expect_failure(validator, data, label):
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "contract.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        try:
            validator.validate(path)
        except validator.ValidationError:
            return
        raise AssertionError(f"fail-closed regression accepted: {label}")


def main():
    validator = load_validator()
    canonical = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    validator.validate(CONTRACT_PATH)

    broken = copy.deepcopy(canonical)
    broken["journeys"][0]["job_ids"].append("JTBD-NOT-REAL")
    expect_failure(validator, broken, "unknown demand job")

    broken = copy.deepcopy(canonical)
    broken["journeys"][0]["service_ids"] = ["project_recovery_and_corrections"]
    expect_failure(validator, broken, "service unrelated to selected jobs")

    broken = copy.deepcopy(canonical)
    broken["journeys"][1]["cta_id"] = "autonomous_send"
    expect_failure(validator, broken, "unknown CTA")

    broken = copy.deepcopy(canonical)
    broken["journeys"][2]["path"] = broken["journeys"][0]["path"]
    expect_failure(validator, broken, "duplicate path")

    broken = copy.deepcopy(canonical)
    broken["global_rules"]["inferred_eligibility_forbidden"] = False
    expect_failure(validator, broken, "inferred eligibility enabled")

    broken = copy.deepcopy(canonical)
    broken["journeys"][3]["boundary"] = "Finanțarea este garantată."
    expect_failure(validator, broken, "guarantee claim")

    broken = copy.deepcopy(canonical)
    broken["accessibility_acceptance"]["minimum_touch_target_px"] = 32
    expect_failure(validator, broken, "undersized touch target")

    print(json.dumps({"status": "PASS", "phase": "R04", "negative_cases": 7}, ensure_ascii=False))


if __name__ == "__main__":
    main()
