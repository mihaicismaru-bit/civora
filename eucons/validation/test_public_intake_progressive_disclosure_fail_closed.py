#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "validation" / "validate_public_intake_progressive_disclosure.py"
CONTRACT_PATH = ROOT / "web" / "public_intake_progressive_disclosure_contract.json"
JTBD_PATH = ROOT / "web" / "jtbd_ux_contract.json"
IA_PATH = ROOT / "web" / "information_architecture.json"


def load_validator():
    spec = importlib.util.spec_from_file_location("validate_public_intake_progressive_disclosure", VALIDATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def expect_failure(validator, contract, jtbd, ia, label):
    try:
        validator.validate_data(contract, jtbd, ia)
    except validator.ValidationError:
        return
    raise AssertionError(f"fail-closed regression accepted: {label}")


def main():
    validator = load_validator()
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    jtbd = json.loads(JTBD_PATH.read_text(encoding="utf-8"))
    ia = json.loads(IA_PATH.read_text(encoding="utf-8"))
    validator.validate_data(contract, jtbd, ia)

    broken = copy.deepcopy(contract)
    broken["first_stage_policy"]["submission_enabled"] = True
    expect_failure(validator, broken, jtbd, ia, "first-stage network/submission enabled")

    broken = copy.deepcopy(contract)
    broken["boundaries"]["crm_write_enabled"] = True
    expect_failure(validator, broken, jtbd, ia, "CRM write enabled")

    broken = copy.deepcopy(contract)
    broken["boundaries"]["analytics_transport_enabled"] = True
    expect_failure(validator, broken, jtbd, ia, "analytics transport enabled")

    broken = copy.deepcopy(contract)
    broken["boundaries"]["file_upload_enabled"] = True
    expect_failure(validator, broken, jtbd, ia, "file upload enabled")

    broken = copy.deepcopy(contract)
    broken["boundaries"]["external_message_enabled"] = True
    expect_failure(validator, broken, jtbd, ia, "external message enabled")

    broken = copy.deepcopy(contract)
    broken["boundaries"]["research_crm_separation"] = False
    expect_failure(validator, broken, jtbd, ia, "research CRM separation disabled")

    broken = copy.deepcopy(contract)
    broken["first_stage_policy"]["eligibility_state"] = "ELIGIBLE"
    expect_failure(validator, broken, jtbd, ia, "eligibility assessed in first stage")

    broken = copy.deepcopy(contract)
    broken["contact_handoff"]["automatic"] = True
    expect_failure(validator, broken, jtbd, ia, "automatic contact handoff")

    broken = copy.deepcopy(contract)
    broken["journeys"][1]["allowed_first_stage_fields"].append("email")
    expect_failure(validator, broken, jtbd, ia, "contract early email field")

    broken_jtbd = copy.deepcopy(jtbd)
    broken_jtbd["journeys"][1]["first_step_fields"].append("phone")
    expect_failure(validator, contract, broken_jtbd, ia, "upstream early phone field")

    broken_jtbd = copy.deepcopy(jtbd)
    broken_jtbd["global_rules"]["progressive_data_minimization"] = False
    expect_failure(validator, contract, broken_jtbd, ia, "upstream data minimization disabled")

    broken_ia = copy.deepcopy(ia)
    for row in broken_ia["cta_destinations"]:
        if row["cta_id"] == "request_project_evaluation":
            row["path"] = "/contact/"
            break
    expect_failure(validator, contract, jtbd, broken_ia, "CTA bypasses canonical lead handoff")

    broken = copy.deepcopy(contract)
    broken["decision"]["runtime_materialization_authorized"] = True
    expect_failure(validator, broken, jtbd, ia, "policy guard authorizes runtime")

    broken = copy.deepcopy(contract)
    broken["source_bindings"]["jtbd_contract_id"] = "R04-DRIFT"
    expect_failure(validator, broken, jtbd, ia, "source contract id drift")

    print(json.dumps({"status": "PASS", "phase": "R04_PUBLIC_INTAKE", "negative_cases": 14}, ensure_ascii=False))


if __name__ == "__main__":
    main()
