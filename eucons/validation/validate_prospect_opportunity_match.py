#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
FIXTURE_PATH = EUCONS / "prospects" / "fixtures" / "client_finder_queue_non_evidence.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_state(engine, payload):
    state = engine.empty_state(payload["reference_time"])
    observations = deepcopy(payload["observations"])
    for observation in observations:
        record = observation["record"]
        if record["prospect_id"] == "PROS-SYNTH-B":
            record["organization"]["public_activity_codes"] = ["CAEN 10"]
            for assertion in record["assertions"]:
                if assertion["assertion_id"] == "AST-B-FACT":
                    assertion["statement"] = "Synthetic company announced an investment in solar energy for CAEN 10 food production."
        state = engine.ingest(state, observation["request_id"], record, payload["reference_time"])
    return state


def synthetic_fresh_projection(reference_time: str) -> dict:
    return {
        "schema_version": 1,
        "product": "EUCONS_COMMERCIAL_OS",
        "bridge_id": "PARTENER_P11_TO_EUCONS_E09",
        "generated_at": reference_time,
        "bridge_state": "READY",
        "read_only": True,
        "source_mutation_allowed": False,
        "evidence_label": "NON_EVIDENCE",
        "source": {"product": "PARTENER.EU", "as_of": reference_time, "policy_accepted": True},
        "freshness": {"state": "FRESH", "age_seconds": 0, "max_age_seconds": 259200},
        "summary": {"source_opportunity_count": 1, "admitted_verified_count": 1, "actionable_open_count": 1, "held_stale_count": 0},
        "opportunities": [{
            "id": "SYNTH-OPP-SOLAR-CAEN10",
            "title": "Synthetic solar-energy investment opportunity",
            "programme": "Synthetic verified projection",
            "code": "SYNTH",
            "status": "OPEN",
            "commercial_state": "VERIFIED_AVAILABLE",
            "actionable": True,
            "verified_fact_classes": ["status", "deadline", "grant", "beneficiaries", "eligibility"],
            "material_facts": {
                "status": "OPEN",
                "deadline": {"closes_at": "2026-09-30T12:00:00+03:00"},
                "grant": {"maximum_eur": 1000000},
                "beneficiaries": ["Synthetic agricultural enterprise"],
                "eligibility": {"activity_codes_at_application": ["CAEN 10"], "eligible_classes": ["intreprindere"]},
                "scope": "solar energy investment for food production"
            },
            "provenance": {
                "source_product": "PARTENER.EU",
                "source_path": "NON_EVIDENCE_SYNTHETIC_FIXTURE",
                "source_opportunity_id": "SYNTH-OPP-SOLAR-CAEN10",
                "source_as_of": reference_time,
                "source_projection_sha256": "d" * 64,
                "publication_decision": {"decision": "ALLOW_VERIFIED_FACTS"},
                "verification_evidence": [{"id": "SYNTHETIC-NON-EVIDENCE"}]
            }
        }]
    }


def synthetic_official_registry(r07_matcher, projection: dict, fact_classes=None, *, conflict: bool = False) -> dict:
    opportunity = projection["opportunities"][0]
    e10 = r07_matcher.OPPORTUNITY_MATCHER
    contract = json.loads((EUCONS / "opportunities" / "matching_contract.json").read_text(encoding="utf-8"))
    guards = contract["official_source_guards"]
    classes = fact_classes or ["status", "deadline", "grant", "beneficiaries", "eligibility"]
    hashes = {
        key: e10.canonical_hash(opportunity["material_facts"][key])
        for key in classes
        if key in opportunity["material_facts"]
    }
    return {
        "schema_version": guards["registry_schema_version"],
        "state": guards["registry_state"],
        "receipts": [{
            "receipt_id": hashlib.sha256(("r07-official:" + opportunity["id"] + (":conflict" if conflict else "")).encode("utf-8")).hexdigest(),
            "opportunity_id": opportunity["id"],
            "verification_state": guards["conflict_state"] if conflict else guards["verified_state"],
            "verification_method": guards["verification_method"],
            "source_product": "SYNTHETIC_OFFICIAL_R07_FIXTURE",
            "source_authority": "Synthetic R07 official-source fixture",
            "source_url": "https://official.example.test/r07/" + opportunity["id"],
            "source_document_sha256": hashlib.sha256(("r07-document:" + opportunity["id"]).encode("utf-8")).hexdigest(),
            "verified_at": "2026-08-28T20:00:00Z",
            "verified_fact_hashes": {} if conflict else hashes,
        }],
    }


def by_prospect(result: dict) -> dict:
    return {row["prospect_id"]: row for row in result["results"]}


def main() -> None:
    matcher = load_module("r07_match_validator", EUCONS / "prospects" / "prospect_opportunity_match.py")
    engine = load_module("r07_client_engine_validator", EUCONS / "prospects" / "client_finder_engine.py")
    bridge = load_module("r07_bridge_validator", EUCONS / "opportunities" / "build_projection.py")
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    state = build_state(engine, payload)
    fresh_projection = synthetic_fresh_projection(payload["reference_time"])
    projection_before = engine.canonical_hash(fresh_projection)

    without_official = matcher.match_state(state, fresh_projection, payload["reference_time"])
    if without_official["summary"]["matched"] != 0:
        raise SystemExit("PARTENER-only projection produced a research candidate")
    if without_official["summary"]["held_source"] < 1 or without_official["summary"]["waiting_source_rows"] < 1:
        raise SystemExit("missing official source did not fail closed to WAITING_SOURCE")

    official_registry = synthetic_official_registry(matcher, fresh_projection)
    registry_before = engine.canonical_hash(official_registry)
    result = matcher.match_state(state, fresh_projection, payload["reference_time"], official_registry=official_registry)
    rows = by_prospect(result)
    beta = rows["PROS-SYNTH-B"]
    if beta["state"] != "MATCHED_RESEARCH_CANDIDATE":
        raise SystemExit("synthetic company did not produce an aligned research candidate after official binding")
    if beta["selected_opportunity_id"] != "SYNTH-OPP-SOLAR-CAEN10":
        raise SystemExit("deterministic opportunity selection drift")
    if beta["recommended_service_id"] != "funding_strategy_and_eligibility":
        raise SystemExit("prospect service recommendation drift")
    selected = beta["opportunity_matches"][0]
    if selected["aligned_service_ids"] != ["funding_strategy_and_eligibility"]:
        raise SystemExit("opportunity-to-service overlap drift")
    if selected["selected_service_id"] != "funding_strategy_and_eligibility":
        raise SystemExit("opportunity-to-service selection drift")
    if beta["selected_service_id"] != "funding_strategy_and_eligibility":
        raise SystemExit("prospect-opportunity-service selection drift")
    if beta["eligibility_state"] != "NOT_ASSESSED" or beta["maximum_next_state"] != "RESEARCH_READY":
        raise SystemExit("match crossed eligibility or research boundary")
    if selected["authority_state"] != "OFFICIAL_SOURCE_VERIFIED":
        raise SystemExit("R07 selected opportunity without official authority")
    if not {"status", "deadline"}.issubset(set(selected["official_fact_classes"])):
        raise SystemExit("R07 selected opportunity without official status/deadline bindings")
    if not selected["source_provenance"] or not selected["source_supported_deadline"]:
        raise SystemExit("officially bound opportunity provenance/deadline was not retained")
    if set(selected["verified_fact_classes"]) != set(selected["official_fact_classes"]):
        raise SystemExit("R07 compatibility fact classes diverged from official authority classes")
    if engine.canonical_hash(fresh_projection) != projection_before:
        raise SystemExit("read-only opportunity projection was mutated")
    if engine.canonical_hash(official_registry) != registry_before:
        raise SystemExit("read-only official registry was mutated")

    conflict_registry = synthetic_official_registry(matcher, fresh_projection, conflict=True)
    conflict = matcher.match_state(state, fresh_projection, payload["reference_time"], official_registry=conflict_registry)
    if conflict["summary"]["matched"] != 0 or conflict["summary"]["blocked_source_conflict_rows"] < 1:
        raise SystemExit("official-source conflict did not block R07 matching")

    source_contract = json.loads((EUCONS / "opportunities" / "bridge_contract.json").read_text(encoding="utf-8"))
    source_path = ROOT / source_contract["source"]["path"]
    source, source_hash = bridge.load_partener_payload(source_path, source_contract["source"]["expected_prefix"])
    current_projection = bridge.build_projection(
        source,
        source_hash,
        source_contract,
        bridge.parse_iso(payload["reference_time"]),
    )
    if current_projection["bridge_state"] != "STALE_SOURCE_HOLD":
        raise SystemExit("expected stale canonical PARTENER projection at fixture reference time")
    held = matcher.match_state(state, current_projection, payload["reference_time"])
    if held["summary"]["held_source"] != held["summary"]["evaluated_prospects"]:
        raise SystemExit("stale canonical projection did not hold every prospect")
    if any(row["selected_opportunity_id"] is not None or row["selected_service_id"] is not None for row in held["results"]):
        raise SystemExit("stale projection selected an opportunity or service")

    repeated = matcher.match_state(state, fresh_projection, payload["reference_time"], official_registry=official_registry)
    if engine.canonical_hash(result) != engine.canonical_hash(repeated):
        raise SystemExit("R07 match is not deterministic")
    serialized = json.dumps(result, ensure_ascii=False).casefold()
    for forbidden in ("instituție sintetică alfa", "companie sintetică beta", "alfa.synthetic.invalid", "beta.synthetic.invalid"):
        if forbidden in serialized:
            raise SystemExit("organization identity leaked into R07 output")
    for forbidden_claim in ("este eligibil", "probabilitate de aprobare", "intenție de cumpărare"):
        if forbidden_claim in serialized:
            raise SystemExit("R07 output made a forbidden conclusion")

    with tempfile.TemporaryDirectory() as td:
        output = Path(td) / "matches.json"
        engine.write_atomic(output, result)
        readback = json.loads(output.read_text(encoding="utf-8"))
        if engine.canonical_hash(readback) != engine.canonical_hash(result):
            raise SystemExit("R07 atomic readback drift")

    print(json.dumps({
        "status": "PASS",
        "unit": "R07-PROSPECT-MATCH-001",
        "evaluated_prospects": result["summary"]["evaluated_prospects"],
        "matched": result["summary"]["matched"],
        "selected_opportunity": beta["selected_opportunity_id"],
        "recommended_service": beta["recommended_service_id"],
        "selected_service": beta["selected_service_id"],
        "waiting_without_official": without_official["summary"]["waiting_source_rows"],
        "blocked_official_conflict": conflict["summary"]["blocked_source_conflict_rows"],
        "stale_projection_held": held["summary"]["held_source"],
        "eligibility_state": result["eligibility_state"],
        "maximum_next_state": result["maximum_next_state"],
        "partener_role": result["partener_role"],
        "production_records": 0,
        "external_contact": False
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
