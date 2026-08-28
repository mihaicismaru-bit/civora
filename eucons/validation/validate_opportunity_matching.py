#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def synthetic_official_registry(matcher, bridge: dict, matching_contract: dict) -> dict:
    allowed = set(matching_contract["official_source_guards"]["material_fact_classes_requiring_official_binding"])
    receipts = []
    for record in bridge.get("opportunities") or []:
        material = record.get("material_facts") or {}
        hashes = {key: matcher.canonical_hash(material[key]) for key in sorted(set(material) & allowed)}
        if not {"status", "deadline"}.issubset(hashes):
            continue
        opportunity_id = str(record.get("id") or "")
        receipt_id = hashlib.sha256(("synthetic-official:" + opportunity_id).encode("utf-8")).hexdigest()
        receipts.append({
            "receipt_id": receipt_id,
            "opportunity_id": opportunity_id,
            "verification_state": "VERIFIED_OFFICIAL_SOURCE",
            "verification_method": "OFFICIAL_SOURCE_READBACK",
            "source_product": "SYNTHETIC_OFFICIAL_VALIDATION_FIXTURE",
            "source_authority": "Synthetic official-source validator fixture",
            "source_url": "https://official.example.test/" + opportunity_id,
            "source_document_sha256": hashlib.sha256(("document:" + opportunity_id).encode("utf-8")).hexdigest(),
            "verified_at": "2026-08-28T20:00:00Z",
            "verified_fact_hashes": hashes,
        })
    return {
        "schema_version": matching_contract["official_source_guards"]["registry_schema_version"],
        "state": matching_contract["official_source_guards"]["registry_state"],
        "receipts": receipts,
    }


def main() -> None:
    bridge_mod = load_module("e10_bridge", EUCONS / "opportunities" / "build_projection.py")
    matcher = load_module("e10_matcher", EUCONS / "opportunities" / "match_opportunities.py")
    bridge_contract = json.loads((EUCONS / "opportunities" / "bridge_contract.json").read_text(encoding="utf-8"))
    matching_contract = json.loads((EUCONS / "opportunities" / "matching_contract.json").read_text(encoding="utf-8"))

    assert matching_contract["score_semantics"] == "RELEVANCE_NOT_APPROVAL_PROBABILITY"
    assert matching_contract["rules"]["never_claim_eligibility_or_award_probability"] is True
    assert matching_contract["rules"]["source_provenance_must_be_retained"] is True
    assert matching_contract["official_source_guards"]["partener_role"] == "DISCOVERY_ONLY"
    assert matching_contract["rules"]["partener_material_facts_never_authoritative_without_official_binding"] is True

    source_path = ROOT / bridge_contract["source"]["path"]
    source, source_hash = bridge_mod.load_partener_payload(source_path, bridge_contract["source"]["expected_prefix"])
    source_as_of = bridge_mod.parse_iso(source["asOf"])
    fresh_bridge = bridge_mod.build_projection(source, source_hash, bridge_contract, source_as_of + timedelta(hours=1))

    profile = {
        "profile_id": "SYNTHETIC-E10-AFIR",
        "audience_id": "companies_entrepreneurs",
        "organization_labels": ["intreprindere", "agricol"],
        "activity_codes": ["CAEN 10"],
        "region_terms": ["romania"],
        "investment_terms": ["energie", "solar"],
        "requested_grant_eur": 500000,
    }

    no_official = matcher.match(profile, fresh_bridge, matching_contract)
    assert no_official["summary"]["candidates"] == 0
    assert no_official["summary"]["held_source_state"] == no_official["summary"]["evaluated"]
    assert no_official["summary"]["waiting_source"] == no_official["summary"]["evaluated"]
    assert all(row["authority_state"] == "WAITING_SOURCE" and row["score"] == 0 for row in no_official["results"])

    official_registry = synthetic_official_registry(matcher, fresh_bridge, matching_contract)
    result = matcher.match(profile, fresh_bridge, matching_contract, official_registry)
    assert result["score_semantics"] == "RELEVANCE_NOT_APPROVAL_PROBABILITY"
    assert result["partener_role"] == "DISCOVERY_ONLY"
    assert result["summary"]["evaluated"] == fresh_bridge["summary"]["admitted_verified_count"]
    assert result["summary"]["candidates"] >= 1
    candidates = [row for row in result["results"] if row["state"] == "MATCH_CANDIDATE"]
    assert candidates
    assert all(row["source_provenance"] for row in result["results"])
    assert all(row["score_semantics"] == "RELEVANCE_NOT_APPROVAL_PROBABILITY" for row in result["results"])
    assert all(row["explanations"] for row in result["results"])
    assert any(row["opportunity_id"] == "afir-energy-2026" for row in candidates), "AFIR energy opportunity should match only after synthetic official-source binding"

    stale_bridge = bridge_mod.build_projection(
        source,
        source_hash,
        bridge_contract,
        source_as_of + timedelta(hours=int(bridge_contract["freshness"]["max_age_hours"]) + 1),
    )
    stale_result = matcher.match(profile, stale_bridge, matching_contract, official_registry)
    assert stale_result["summary"]["candidates"] == 0
    assert stale_result["summary"]["held_source_state"] == stale_result["summary"]["evaluated"]
    assert all(row["score"] == 0 and row["state"] == "HOLD_SOURCE_STATE" for row in stale_result["results"])

    scores = [row["score"] for row in result["results"]]
    assert scores == sorted(scores, reverse=True), "matching results must be deterministically score-sorted"

    print(json.dumps({
        "status": "PASS",
        "phase": "E10",
        "evaluated": result["summary"]["evaluated"],
        "candidates": result["summary"]["candidates"],
        "waiting_without_official": no_official["summary"]["waiting_source"],
        "stale_held": stale_result["summary"]["held_source_state"],
        "score_semantics": result["score_semantics"],
        "partener_role": result["partener_role"],
        "official_authority": "PASS",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
