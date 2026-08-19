#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
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
        "provenance": {"source_product": "PARTENER.EU", "source_opportunity_id": item_id, "verification_evidence": [{"id": "EV"}]},
    }


def bridge(*records, state="READY"):
    return {"bridge_state": state, "opportunities": list(records)}


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

    good = matcher.match(profile, bridge(record("good")), CONTRACT)
    row = good["results"][0]
    assert row["state"] == "MATCH_CANDIDATE"
    assert row["score"] >= CONTRACT["thresholds"]["match_candidate_min"]
    assert row["score_semantics"] == "RELEVANCE_NOT_APPROVAL_PROBABILITY"
    assert row["source_provenance"]["source_product"] == "PARTENER.EU"

    code_mismatch = matcher.match(profile, bridge(record("wrong-code", codes=["CAEN 62"])), CONTRACT)["results"][0]
    assert code_mismatch["state"] == "EXCLUDED_KNOWN_RULE"
    assert code_mismatch["score"] == 0
    assert code_mismatch["hard_exclusion_reasons"]

    too_large = dict(profile, requested_grant_eur=1500000)
    grant_mismatch = matcher.match(too_large, bridge(record("small-cap", cap=1000000)), CONTRACT)["results"][0]
    assert grant_mismatch["state"] == "EXCLUDED_KNOWN_RULE"
    assert "exceeds verified_cap_eur" in grant_mismatch["hard_exclusion_reasons"][0]

    held_bridge = matcher.match(profile, bridge(record("good"), state="STALE_SOURCE_HOLD"), CONTRACT)["results"][0]
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
    sparse = matcher.match(sparse_profile, bridge(record("needs-data")), CONTRACT)["results"][0]
    assert sparse["state"] == "REQUIRES_DATA"
    assert sparse["confidence"] == "LOW"
    assert sparse["score"] == 0

    try:
        matcher.match(dict(profile, email="person@example.com"), bridge(record("good")), CONTRACT)
        raise AssertionError("PII field must be rejected")
    except ValueError:
        pass

    first = record("b")
    second = record("a")
    ordered = matcher.match(profile, bridge(first, second), CONTRACT)["results"]
    assert [row["opportunity_id"] for row in ordered] == ["a", "b"], "score ties must sort by opportunity id"

    joined = json.dumps(good, ensure_ascii=False).lower()
    assert "probabilitate de aprobare" not in joined
    assert "eligibil" not in " ".join(row["explanations"]).lower(), "matcher must not claim eligibility"

    print("PASS: E10 opportunity matching fail-closed regressions")


if __name__ == "__main__":
    main()
