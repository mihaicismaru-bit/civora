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
INBOUND_PATH = ROOT / "leads" / "inbound_runtime_contract.json"


def load_validator():
    spec = importlib.util.spec_from_file_location("validate_public_intake_progressive_disclosure", VALIDATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def expect_failure(validator, contract, jtbd, ia, inbound, label):
    try:
        validator.validate_data(contract, jtbd, ia, inbound)
    except validator.ValidationError:
        return
    raise AssertionError(f"fail-closed regression accepted: {label}")


def main():
    validator = load_validator()
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    jtbd = json.loads(JTBD_PATH.read_text(encoding="utf-8"))
    ia = json.loads(IA_PATH.read_text(encoding="utf-8"))
    inbound = json.loads(INBOUND_PATH.read_text(encoding="utf-8"))
    validator.validate_data(contract, jtbd, ia, inbound)

    cases = []

    broken = copy.deepcopy(contract); broken["profile_stage_policy"]["production_collection_allowed"] = True
    cases.append((broken, jtbd, ia, inbound, "guard production collection"))
    broken = copy.deepcopy(contract); broken["profile_stage_policy"]["eligibility_state"] = "ELIGIBLE"
    cases.append((broken, jtbd, ia, inbound, "PROFILE eligibility assessed"))
    broken = copy.deepcopy(contract); broken["profile_stage_policy"]["contact_details_allowed"] = True
    cases.append((broken, jtbd, ia, inbound, "PROFILE contact allowed"))
    broken = copy.deepcopy(contract); broken["journeys"][1]["allowed_profile_fields"].append("email")
    cases.append((broken, jtbd, ia, inbound, "guard early email"))
    broken = copy.deepcopy(contract); broken["runtime_boundaries"]["repository_pii_writes_forbidden"] = False
    cases.append((broken, jtbd, ia, inbound, "repository PII writes"))
    broken = copy.deepcopy(contract); broken["runtime_boundaries"]["telemetry_production_transport_enabled"] = True
    cases.append((broken, jtbd, ia, inbound, "production telemetry"))
    broken = copy.deepcopy(contract); broken["runtime_boundaries"]["research_crm_separation"] = False
    cases.append((broken, jtbd, ia, inbound, "research CRM separation"))
    broken = copy.deepcopy(contract); broken["decision"]["production_activation_authorized"] = True
    cases.append((broken, jtbd, ia, inbound, "guard authorizes production"))

    broken_jtbd = copy.deepcopy(jtbd); broken_jtbd["journeys"][1]["first_step_fields"].append("phone")
    cases.append((contract, broken_jtbd, ia, inbound, "R04 early phone"))
    broken_jtbd = copy.deepcopy(jtbd); broken_jtbd["global_rules"]["progressive_data_minimization"] = False
    cases.append((contract, broken_jtbd, ia, inbound, "R04 minimization disabled"))

    broken_inbound = copy.deepcopy(inbound); broken_inbound["request_contract"]["contact_before_contact_step_forbidden"] = False
    cases.append((contract, jtbd, ia, broken_inbound, "R05 early contact enabled"))
    broken_inbound = copy.deepcopy(inbound); broken_inbound["production_collection_enabled"] = True
    cases.append((contract, jtbd, ia, broken_inbound, "R05 production collection enabled"))
    broken_inbound = copy.deepcopy(inbound); broken_inbound["public_form_contract"]["endpoint"]["production_binding_enabled"] = True
    cases.append((contract, jtbd, ia, broken_inbound, "R05 production endpoint bound"))
    broken_inbound = copy.deepcopy(inbound); broken_inbound["telemetry"]["raw_contact_forbidden"] = False
    cases.append((contract, jtbd, ia, broken_inbound, "R05 telemetry raw contact"))

    for args in cases:
        expect_failure(validator, *args)

    print(json.dumps({"status": "PASS", "phase": "R04_PUBLIC_INTAKE_GUARD", "negative_cases": len(cases)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
