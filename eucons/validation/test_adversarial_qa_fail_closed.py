#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"


def load_suite():
    path = EUCONS / "adversarial" / "adversarial_suite.py"
    spec = importlib.util.spec_from_file_location("e26_adversarial_failclosed", path)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load E26 adversarial suite")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def must_fail(label: str, fn) -> None:
    try:
        fn()
    except ValueError:
        return
    raise SystemExit(f"{label}: E26 meta-guard failed open")


def main() -> None:
    suite = load_suite()
    contract = json.loads((EUCONS / "adversarial" / "adversarial_contract.json").read_text(encoding="utf-8"))

    unsafe = copy.deepcopy(contract); unsafe["production_side_effects_enabled"] = True
    must_fail("production side effects", lambda: suite.run_suite(unsafe))

    no_fail_closed = copy.deepcopy(contract); no_fail_closed["fail_closed_required"] = False
    must_fail("fail-closed disabled", lambda: suite.run_suite(no_fail_closed))

    missing_scenario = copy.deepcopy(contract); missing_scenario["required_scenarios"] = missing_scenario["required_scenarios"][:-1]
    must_fail("scenario removed", lambda: suite.run_suite(missing_scenario))

    wrong_order = copy.deepcopy(contract); wrong_order["required_scenarios"] = list(reversed(wrong_order["required_scenarios"]))
    must_fail("scenario order changed", lambda: suite.run_suite(wrong_order))

    incomplete_forbidden = copy.deepcopy(contract); incomplete_forbidden["forbidden"]["production_deployment"] = False
    must_fail("production-deployment guard removed", lambda: suite.run_suite(incomplete_forbidden))

    must_fail("repository report write", lambda: suite.assert_output_path_safe(EUCONS / "adversarial" / "unsafe-report.json"))
    suite.assert_output_path_safe(Path("/tmp/eucons-e26-adversarial.json"))

    report = suite.run_suite(contract)
    if any(row["safe_outcome"] in {"PUBLISHED", "SENT", "DEPLOYED", "PROMOTED"} for row in report["scenarios"]):
        raise SystemExit("E26 report contains forbidden success-side effect")

    print("EUCONS E26 Adversarial QA meta fail-closed: PASS")


if __name__ == "__main__":
    main()
