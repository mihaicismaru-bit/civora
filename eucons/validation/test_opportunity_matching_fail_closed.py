#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
CONTRACT = json.loads((EUCONS / "opportunities" / "matching_contract.json").read_text(encoding="utf-8"))


def load_matcher():
    path = EUCONS / "opportunities" / "match_opportunities.py"
    spec = importlib.util.spec_from_file_location("e10_match_tests", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def record(item_id: str, *, codes=None, cap=1000000, actionable=True, state="VERIFIED_AVAILABLE"):
    codes = codes or ["CAEN 10"]
    return {
        "id": item_id,
        "title": "Investiții în energie solară pentru întreprinderi",
        "programme": "Program test",
        "code": "TEST",
        "status": "OPEN",
        "commercial_state": state,
        "actionable": actionable,
        "verified_fact_classes": ["status", "deadline", "eligibility", "grant"],
        "material_facts": {
            "status": "OPEN",
            "deadline": {"closes_at": "2026-10-01T12:00:00+03:00"},
            "eligibility": {"activity_codes_at_application": codes, "eligible_classes": ["întreprindere agricolă"]},
            "grant": {"maximum_eur": cap},
        },
        "provenance": {
            "source_product": "PARTENER.EU",
            "source_opportunity_id": item_id,
            "verification_evidence": [{"id": "DISCOVERY-EV"}],
        },
    }


def bridge(*records, state="READY"):
    return {"bridge_state": state, "opportunities": list(records)}


def registry(matcher, item, classes, *, state="VERIFIED_OFFICIAL_SOURCE", receipt_char="a", source_product="MIPE_TEST_FIXTURE", source_url="https://official.example.test/source", override_hashes=None):
    material = item["material_facts"]
    hashes = {name: matcher.canonical_hash(material[name]) for name in classes}
    if override_hashes:
        hashes.update(override_hashes)
    return {
        "schema_version": 1,
        "state": "READ_ONLY_OFFICIAL_SOURCE_RECEIPTS",
        "receipts": [{
            "receipt_id": receipt_char * 64,
            "opportunity_id": item["id"],
            "verification_state": state,
            "verification_method": "OFFICIAL_SOURCE_READBACK",
            "source_product": source_product,
            "source_authority": "Official test authority",
            "source_url": source_url,
            "source_document_sha256": "d" * 64,
            "verified_at": "2026-08-28T20:00:00Z",
            "verified_fact_hashes": hashes if state == "VERIFIED_OFFICIAL_SOURCE" else {},
        }],
    }


def main() -> None:
    matcher = load_matcher()
    profile = {
        "profile_id": "fixture-company",
        "audience_id": "companies_entrepreneurs",
        "organization_labels": ["intreprindere", "agricola"],
        "activity_codes": ["CAEN 10"],
        "region_terms": [],
        "investment_terms": ["energie", "solara"],
        "requested_grant_eur": 500000,
    }

    discovery = record("discovery-only")
    discovery_only = matcher.match(profile, bridge(discovery), CONTRACT)
    row = discovery_only["results"][0]
    assert row["state"] == "HOLD_SOURCE_STATE"
    assert row["authority_state"] == "WAITING_SOURCE"
    assert row["score"] == 0
    assert discovery_only["partener_role"] == "DISCOVERY_ONLY"
    assert discovery_only["summary"]["waiting_source"] == 1
    assert "discovery/intelligence only" in " ".join(row["explanations"])

    status_deadline = matcher.match(
        profile,
        bridge(discovery),
        CONTRACT,
        registry(matcher, discovery, ["status", "deadline"]),
    )["results"][0]
    assert status_deadline["authority_state"] == "OFFICIAL_SOURCE_VERIFIED"
    assert set(status_deadline["official_fact_classes"]) == {"status", "deadline"}
    assert status_deadline["state"] == "REQUIRES_DATA", "unbound eligibility/grant facts must not silently qualify the match"
    assert status_deadline["score"] < CONTRACT["thresholds"]["match_candidate_min"]

    full_registry = registry(matcher, discovery, ["status", "deadline", "eligibility", "grant"])
    good = matcher.match(profile, bridge(discovery), CONTRACT, full_registry)
    row = good["results"][0]
    assert row["state"] == "MATCH_CANDIDATE"
    assert row["score"] >= CONTRACT["thresholds"]["match_candidate_min"]
    assert row["score_semantics"] == "RELEVANCE_NOT_APPROVAL_PROBABILITY"
    assert row["source_provenance"]["source_product"] == "PARTENER.EU"
    assert row["authority_state"] == "OFFICIAL_SOURCE_VERIFIED"
    assert set(row["official_fact_classes"]) == {"status", "deadline", "eligibility", "grant"}

    wrong_code = record("wrong-code", codes=["CAEN 62"])
    no_official_code_exclusion = matcher.match(profile, bridge(wrong_code), CONTRACT)["results"][0]
    assert no_official_code_exclusion["state"] == "HOLD_SOURCE_STATE"
    assert not no_official_code_exclusion["hard_exclusion_reasons"]
    code_registry = registry(matcher, wrong_code, ["status", "deadline", "eligibility"], receipt_char="b")
    code_mismatch = matcher.match(profile, bridge(wrong_code), CONTRACT, code_registry)["results"][0]
    assert code_mismatch["state"] == "EXCLUDED_KNOWN_RULE"
    assert code_mismatch["score"] == 0
    assert code_mismatch["hard_exclusion_reasons"]

    small_cap = record("small-cap", cap=1000000)
    too_large = dict(profile, requested_grant_eur=1500000)
    no_official_grant_exclusion = matcher.match(too_large, bridge(small_cap), CONTRACT)["results"][0]
    assert no_official_grant_exclusion["state"] == "HOLD_SOURCE_STATE"
    grant_registry = registry(matcher, small_cap, ["status", "deadline", "grant"], receipt_char="c")
    grant_mismatch = matcher.match(too_large, bridge(small_cap), CONTRACT, grant_registry)["results"][0]
    assert grant_mismatch["state"] == "EXCLUDED_KNOWN_RULE"
    assert "officially_bound_cap_eur" in grant_mismatch["hard_exclusion_reasons"][0]

    conflict = registry(matcher, discovery, [], state="BLOCKED_SOURCE_CONFLICT", receipt_char="e")
    conflict_row = matcher.match(profile, bridge(discovery), CONTRACT, conflict)["results"][0]
    assert conflict_row["state"] == "HOLD_SOURCE_STATE"
    assert conflict_row["authority_state"] == "BLOCKED_SOURCE_CONFLICT"
    assert conflict_row["score"] == 0

    mismatched = registry(
        matcher,
        discovery,
        ["status", "deadline"],
        receipt_char="f",
        override_hashes={"deadline": "0" * 64},
    )
    mismatch_row = matcher.match(profile, bridge(discovery), CONTRACT, mismatched)["results"][0]
    assert mismatch_row["authority_state"] == "BLOCKED_SOURCE_CONFLICT"
    assert mismatch_row["state"] == "HOLD_SOURCE_STATE"

    bad_product = registry(matcher, discovery, ["status", "deadline"], receipt_char="1", source_product="PARTENER.EU")
    try:
        matcher.match(profile, bridge(discovery), CONTRACT, bad_product)
        raise AssertionError("PARTENER.EU must never satisfy official authority")
    except ValueError:
        pass

    bad_url = registry(matcher, discovery, ["status", "deadline"], receipt_char="2", source_url="http://official.example.test/source")
    try:
        matcher.match(profile, bridge(discovery), CONTRACT, bad_url)
        raise AssertionError("non-HTTPS official source must fail closed")
    except ValueError:
        pass

    held_bridge = matcher.match(profile, bridge(discovery, state="STALE_SOURCE_HOLD"), CONTRACT, full_registry)["results"][0]
    assert held_bridge["state"] == "HOLD_SOURCE_STATE" and held_bridge["score"] == 0

    held_record = matcher.match(profile, bridge(record("held", actionable=False)), CONTRACT)["results"][0]
    assert held_record["state"] == "HOLD_SOURCE_STATE" and held_record["score"] == 0

    sparse_profile = {
        "profile_id": "sparse",
        "audience_id": "companies_entrepreneurs",
        "organization_labels": [],
        "activity_codes": [],
        "region_terms": [],
        "investment_terms": [],
    }
    sparse_item = record("needs-data")
    sparse = matcher.match(
        sparse_profile,
        bridge(sparse_item),
        CONTRACT,
        registry(matcher, sparse_item, ["status", "deadline"], receipt_char="3"),
    )["results"][0]
    assert sparse["state"] == "REQUIRES_DATA"
    assert sparse["confidence"] == "LOW"
    assert sparse["score"] == 0

    try:
        matcher.match(dict(profile, email="person@example.com"), bridge(discovery), CONTRACT, full_registry)
        raise AssertionError("PII field must be rejected")
    except ValueError:
        pass

    first = record("b")
    second = record("a")
    combined_registry = {
        "schema_version": 1,
        "state": "READ_ONLY_OFFICIAL_SOURCE_RECEIPTS",
        "receipts": registry(matcher, first, ["status", "deadline", "eligibility", "grant"], receipt_char="4")["receipts"]
        + registry(matcher, second, ["status", "deadline", "eligibility", "grant"], receipt_char="5")["receipts"],
    }
    ordered = matcher.match(profile, bridge(first, second), CONTRACT, combined_registry)["results"]
    assert [item["opportunity_id"] for item in ordered] == ["a", "b"], "score ties must sort by opportunity id"

    joined = json.dumps(good, ensure_ascii=False).lower()
    assert "probabilitate de aprobare" not in joined
    assert "eligibil" not in " ".join(row["explanations"]).lower(), "matcher must not claim eligibility"

    mutated = deepcopy(full_registry)
    mutated["receipts"][0]["verified_fact_hashes"]["eligibility"] = "9" * 64
    blocked = matcher.match(profile, bridge(discovery), CONTRACT, mutated)["results"][0]
    assert blocked["authority_state"] == "BLOCKED_SOURCE_CONFLICT"

    print("PASS: E10 opportunity matching official-source fail-closed regressions")


if __name__ == "__main__":
    main()
