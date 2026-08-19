#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
CONTRACT_PATH = EUCONS / "opportunities" / "bridge_contract.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_bridge():
    path = EUCONS / "opportunities" / "build_projection.py"
    spec = importlib.util.spec_from_file_location("eucons_opportunity_bridge", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> None:
    bridge = load_bridge()
    contract = load_json(CONTRACT_PATH)

    assert contract["mode"] == "READ_ONLY"
    assert contract["source"]["path"] == "partener-eu/web/p11-public-data.js"
    assert contract["source"]["expected_prefix"] == "window.PARTENER_P11="
    assert contract["source"]["required_integrity_gate"] == "STRICT_FAIL_CLOSED"
    assert contract["source"]["required_policy"]["unverifiedMaterialFactsVisible"] is False
    assert contract["source"]["required_policy"]["verificationProvenanceVisible"] is True
    assert contract["output"]["source_mutation_allowed"] is False
    assert 1 <= int(contract["freshness"]["max_age_hours"]) <= 168

    source_path = ROOT / contract["source"]["path"]
    source, source_hash = bridge.load_partener_payload(source_path, contract["source"]["expected_prefix"])
    assert source.get("schemaVersion")
    assert source.get("opportunities"), "PARTENER P11 projection must expose opportunities"
    assert bridge.policy_is_acceptable(source, contract), "PARTENER public projection policy drifted"

    source_as_of = bridge.parse_iso(source["asOf"])
    fresh_reference = source_as_of + timedelta(hours=1)
    fresh_projection = bridge.build_projection(source, source_hash, contract, fresh_reference)

    assert fresh_projection["bridge_state"] == "READY"
    assert fresh_projection["read_only"] is True
    assert fresh_projection["source_mutation_allowed"] is False
    assert fresh_projection["source"]["sha256"] == source_hash
    assert fresh_projection["summary"]["admitted_verified_count"] > 0

    allowed = set(contract["admission"]["allowed_material_fact_classes"])
    for record in fresh_projection["opportunities"]:
        assert record["commercial_state"] == "VERIFIED_AVAILABLE"
        assert record["provenance"]["source_product"] == "PARTENER.EU"
        assert record["provenance"]["source_path"] == contract["source"]["path"]
        assert record["provenance"]["source_projection_sha256"] == source_hash
        assert record["provenance"]["verification_evidence"], f"missing evidence for {record['id']}"
        assert (record["provenance"]["publication_decision"] or {}).get("decision") == "ALLOW_VERIFIED_FACTS"
        fact_classes = set(record["verified_fact_classes"])
        assert fact_classes <= allowed
        assert set(record["material_facts"]) == fact_classes

    stale_reference = source_as_of + timedelta(hours=int(contract["freshness"]["max_age_hours"]) + 1)
    stale_projection = bridge.build_projection(source, source_hash, contract, stale_reference)
    assert stale_projection["bridge_state"] == "STALE_SOURCE_HOLD"
    assert stale_projection["summary"]["actionable_open_count"] == 0
    assert stale_projection["summary"]["held_stale_count"] == stale_projection["summary"]["admitted_verified_count"]
    assert all(row["commercial_state"] == "HOLD_STALE_SOURCE" for row in stale_projection["opportunities"])
    assert all(row["actionable"] is False for row in stale_projection["opportunities"])

    admitted_ids = {row["id"] for row in fresh_projection["opportunities"]}
    for item in source["opportunities"]:
        decision = (item.get("publicationDecision") or {}).get("decision")
        if item.get("publicationState") != "PUBLISHABLE" or decision != "ALLOW_VERIFIED_FACTS":
            assert item.get("id") not in admitted_ids, f"blocked PARTENER record leaked: {item.get('id')}"

    print(json.dumps({
        "status": "PASS",
        "phase": "E09",
        "source_opportunities": len(source["opportunities"]),
        "admitted_verified": fresh_projection["summary"]["admitted_verified_count"],
        "fresh_actionable_open": fresh_projection["summary"]["actionable_open_count"],
        "stale_actionable_open": stale_projection["summary"]["actionable_open_count"],
        "read_only": True,
        "provenance": "PASS",
        "stale_fail_closed": "PASS"
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
