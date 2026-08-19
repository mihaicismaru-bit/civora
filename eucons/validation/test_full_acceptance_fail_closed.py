#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expect_rejected(engine, contract, label: str) -> None:
    try:
        engine.validate_contract(contract)
    except ValueError:
        return
    raise SystemExit(f"E27 fail-closed mutation accepted: {label}")


def main() -> None:
    engine = load_module("e27_acceptance_fail_closed", EUCONS / "acceptance" / "full_acceptance.py")
    contract = json.loads((EUCONS / "acceptance" / "full_acceptance_contract.json").read_text(encoding="utf-8"))
    engine.validate_contract(contract)

    mutations = []
    row = copy.deepcopy(contract); row["engine_id"] = "WRONG"; mutations.append(("engine_id", row))
    row = copy.deepcopy(contract); row["production_side_effects_enabled"] = True; mutations.append(("side_effects", row))
    row = copy.deepcopy(contract); row["required_completed_phases"] = row["required_completed_phases"][:-1]; mutations.append(("prerequisites", row))
    row = copy.deepcopy(contract); row["required_analytics_events"].append("offer_sent"); mutations.append(("analytics_live_semantics", row))
    row = copy.deepcopy(contract); row["external_gates"]["linkedin"] = "OPEN"; mutations.append(("linkedin_gate", row))
    row = copy.deepcopy(contract); row["determinism"]["analytics_replay"] = False; mutations.append(("determinism", row))
    row = copy.deepcopy(contract); row["forbidden"]["real_personal_data"] = False; mutations.append(("forbidden_matrix", row))

    for label, mutated in mutations:
        expect_rejected(engine, mutated, label)

    try:
        engine.assert_output_path_safe(EUCONS / "ops" / "unsafe-e27-runtime.json")
    except ValueError:
        pass
    else:
        raise SystemExit("E27 repository runtime receipt write failed open")

    print("EUCONS E27 Full Acceptance fail-closed: PASS")


if __name__ == "__main__":
    main()
