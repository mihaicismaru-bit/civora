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


def expect_handoff_rejected(engine, handoff, contract, label: str) -> None:
    try:
        engine.validate_handoff_document(handoff, contract)
    except ValueError:
        return
    raise SystemExit(f"E28 handoff fail-closed mutation accepted: {label}")


def main() -> None:
    engine = load_module("e28_closed_dev_fail_closed", EUCONS / "acceptance" / "closed_dev.py")
    contract = json.loads((EUCONS / "acceptance" / "closed_dev_contract.json").read_text(encoding="utf-8"))
    handoff = json.loads((EUCONS / "deployment" / "external_handoff_manifest.json").read_text(encoding="utf-8"))
    engine.validate_contract(contract)

    verified = engine.validate_handoff_document(handoff, contract)
    if verified.get("validated") != 1 or verified.get("pending") != 3:
        raise SystemExit(f"E28 real E29 handoff progression not reconciled: {verified}")

    mutations = []
    row = copy.deepcopy(contract); row["engine_id"] = "WRONG"; mutations.append(("engine_id", row))
    row = copy.deepcopy(contract); row["target_state"] = "PRODUCTION_READY"; mutations.append(("premature_terminal_state", row))
    row = copy.deepcopy(contract); row["production_side_effects_enabled"] = True; mutations.append(("side_effects", row))
    row = copy.deepcopy(contract); row["required_completed_phases"] = row["required_completed_phases"][:-1]; mutations.append(("receipt_chain", row))
    row = copy.deepcopy(contract); row["external_handoff"]["allowed_ids"].append("manual_code_fix"); mutations.append(("external_scope", row))
    row = copy.deepcopy(contract); row["external_handoff"]["owner_development_actions_required"] = True; mutations.append(("deferred_dev", row))
    row = copy.deepcopy(contract); row["external_handoff"]["allowed_states"] = ["OWNER_AUTHORIZATION_REQUIRED", "DONE"]; mutations.append(("handoff_state_contract", row))
    row = copy.deepcopy(contract); row["external_handoff"]["validated_receipt_statuses"] = ["PASS_ANYTHING"]; mutations.append(("receipt_status_contract", row))

    for label, mutated in mutations:
        expect_rejected(engine, mutated, label)

    bad = copy.deepcopy(handoff)
    bad["allowed_external_actions"][0]["state"] = "DONE"
    expect_handoff_rejected(engine, bad, contract, "unknown_validated_state")

    bad = copy.deepcopy(handoff)
    bad["allowed_external_actions"][0].pop("validation_receipt", None)
    expect_handoff_rejected(engine, bad, contract, "validated_missing_receipt")

    bad = copy.deepcopy(handoff)
    bad["allowed_external_actions"][0]["owner_action"] = "NOT_DONE"
    expect_handoff_rejected(engine, bad, contract, "validated_owner_not_completed")

    bad = copy.deepcopy(handoff)
    bad["allowed_external_actions"][0]["validation_receipt"] = "../../etc/passwd"
    expect_handoff_rejected(engine, bad, contract, "validated_receipt_path_escape")

    bad = copy.deepcopy(handoff)
    bad["allowed_external_actions"][0]["secrets_in_repository"] = True
    expect_handoff_rejected(engine, bad, contract, "validated_secret_leak")

    bad = copy.deepcopy(handoff)
    bad["allowed_external_actions"][1]["owner_action"] = "COMPLETED"
    expect_handoff_rejected(engine, bad, contract, "pending_claims_completion")

    bad = copy.deepcopy(handoff)
    bad["allowed_external_actions"][1]["validation_receipt"] = "eucons/ops/receipts/E29_HOSTING_API_ACTIVATION.json"
    expect_handoff_rejected(engine, bad, contract, "pending_claims_receipt")

    try:
        engine.assert_output_path_safe(EUCONS / "ops" / "unsafe-e28-runtime.json")
    except ValueError:
        pass
    else:
        raise SystemExit("E28 repository runtime output failed open")

    print("EUCONS E28 CLOSED-DEV fail-closed: PASS")


if __name__ == "__main__":
    main()
