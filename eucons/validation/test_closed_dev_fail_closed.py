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
    raise SystemExit(f"E28 fail-closed mutation accepted: {label}")


def main() -> None:
    engine = load_module("e28_closed_dev_fail_closed", EUCONS / "acceptance" / "closed_dev.py")
    contract = json.loads((EUCONS / "acceptance" / "closed_dev_contract.json").read_text(encoding="utf-8"))
    engine.validate_contract(contract)

    mutations = []
    row = copy.deepcopy(contract); row["engine_id"] = "WRONG"; mutations.append(("engine_id", row))
    row = copy.deepcopy(contract); row["target_state"] = "PRODUCTION_READY"; mutations.append(("premature_terminal_state", row))
    row = copy.deepcopy(contract); row["production_side_effects_enabled"] = True; mutations.append(("side_effects", row))
    row = copy.deepcopy(contract); row["required_completed_phases"] = row["required_completed_phases"][:-1]; mutations.append(("receipt_chain", row))
    row = copy.deepcopy(contract); row["external_handoff"]["allowed_ids"].append("manual_code_fix"); mutations.append(("external_scope", row))
    row = copy.deepcopy(contract); row["external_handoff"]["owner_development_actions_required"] = True; mutations.append(("deferred_dev", row))

    for label, mutated in mutations:
        expect_rejected(engine, mutated, label)

    try:
        engine.assert_output_path_safe(EUCONS / "ops" / "unsafe-e28-runtime.json")
    except ValueError:
        pass
    else:
        raise SystemExit("E28 repository runtime output failed open")

    print("EUCONS E28 CLOSED-DEV fail-closed: PASS")


if __name__ == "__main__":
    main()
