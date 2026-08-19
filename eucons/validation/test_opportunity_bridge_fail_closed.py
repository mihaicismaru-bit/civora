#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
CONTRACT_PATH = EUCONS / "opportunities" / "bridge_contract.json"


def load_bridge():
    path = EUCONS / "opportunities" / "build_projection.py"
    spec = importlib.util.spec_from_file_location("eucons_opportunity_bridge_tests", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def verified_item(item_id: str, *, state="PUBLISHABLE", decision="ALLOW_VERIFIED_FACTS"):
    return {
        "id": item_id,
        "title": f"Opportunity {item_id}",
        "programme": "Programme",
        "code": "CODE",
        "status": "OPEN",
        "publicationState": state,
        "materialFacts": {
            "status": "OPEN",
            "deadline": {"closes_at": "2026-09-30T12:00:00+03:00"},
            "budget": {"total_eur": 1000000},
            "unverified_internal_note": "must never project",
        },
        "verifiedFactClasses": ["status", "deadline"],
        "verificationEvidence": [{
            "evidenceId": f"EV-{item_id}",
            "sourceTier": "T1",
            "sourceUrl": "https://example.invalid/official",
            "observedAt": "2026-08-19T08:00:00Z",
            "supportedFactClasses": ["status", "deadline"],
        }],
        "publicationDecision": {"decision": decision, "reasonCodes": ["VERIFIED_FACTS_ONLY"]},
    }


def source_payload():
    return {
        "schemaVersion": 4,
        "asOf": "2026-08-19T09:00:00Z",
        "policy": {
            "unverifiedMaterialFactsVisible": False,
            "verificationProvenanceVisible": True,
            "integrityGate": "STRICT_FAIL_CLOSED",
        },
        "opportunities": [
            verified_item("good"),
            verified_item("hold", state="REVIEW_REQUIRED"),
            verified_item("blocked", decision="BLOCK_MATERIAL_FACTS"),
        ],
    }


def main() -> None:
    bridge = load_bridge()
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    source = source_payload()
    original = copy.deepcopy(source)
    reference = bridge.parse_iso(source["asOf"]) + timedelta(hours=1)

    projected = bridge.build_projection(source, "abc123", contract, reference)
    assert source == original, "source object mutated"
    assert projected["bridge_state"] == "READY"
    assert [row["id"] for row in projected["opportunities"]] == ["good"]
    row = projected["opportunities"][0]
    assert row["actionable"] is True
    assert row["commercial_state"] == "VERIFIED_AVAILABLE"
    assert set(row["material_facts"]) == {"status", "deadline"}
    assert "budget" not in row["material_facts"], "unverified budget leaked"
    assert "unverified_internal_note" not in row["material_facts"]

    stale = bridge.build_projection(
        source, "abc123", contract,
        bridge.parse_iso(source["asOf"]) + timedelta(hours=int(contract["freshness"]["max_age_hours"]) + 1),
    )
    assert stale["bridge_state"] == "STALE_SOURCE_HOLD"
    assert stale["opportunities"][0]["commercial_state"] == "HOLD_STALE_SOURCE"
    assert stale["opportunities"][0]["actionable"] is False

    wrong_policy = source_payload()
    wrong_policy["policy"]["unverifiedMaterialFactsVisible"] = True
    rejected = bridge.build_projection(wrong_policy, "badpolicy", contract, reference)
    assert rejected["bridge_state"] == "SOURCE_POLICY_REJECTED"
    assert rejected["opportunities"] == []
    assert rejected["summary"]["actionable_open_count"] == 0

    no_evidence = source_payload()
    no_evidence["opportunities"] = [verified_item("no-evidence")]
    no_evidence["opportunities"][0]["verificationEvidence"] = []
    no_evidence_projection = bridge.build_projection(no_evidence, "noev", contract, reference)
    assert no_evidence_projection["opportunities"] == []

    invalid_time = source_payload()
    invalid_time["asOf"] = "not-a-time"
    invalid = bridge.build_projection(invalid_time, "badtime", contract, reference)
    assert invalid["bridge_state"] == "STALE_SOURCE_HOLD"
    assert invalid["summary"]["actionable_open_count"] == 0
    assert all(row["commercial_state"] == "HOLD_STALE_SOURCE" for row in invalid["opportunities"])

    print("PASS: E09 opportunity bridge fail-closed regressions")


if __name__ == "__main__":
    main()
