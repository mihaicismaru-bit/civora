#!/usr/bin/env python3
"""Commission multi-programme digital funding index: discovery, not OPEN authority."""
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
SOURCE_ID = "SRC-EU-INTEROPERABLE-DIGITAL-FUNDING-INDEX-20261121"
SOURCE_URL = "https://interoperable-europe.ec.europa.eu/eu-digital-funding-opportunities"
FORBIDDEN = {
    "status", "call_status", "current_status", "deadline", "submission_deadline",
    "budget", "budget_eur", "eligibility", "topic_identifier", "submission_endpoint",
    "application_endpoint", "open_at", "closes_at", "fetched_at", "final_url",
    "raw_sha256", "semantic_sha256", "parser_version", "run_id", "handoff_sha256",
    "confirmed_current_open", "source_fingerprint_matches_corpus"
}

def validate(rows):
    found = [s for s in rows if s.get("id") == SOURCE_ID]
    assert len(found) == 1, "Official EC index absent or duplicate"
    s = found[0]
    uri = urlsplit(s["url"])
    assert s["url"] == SOURCE_URL
    assert uri.scheme == "https" and uri.hostname == "interoperable-europe.ec.europa.eu"
    assert not (uri.username or uri.password or uri.port or uri.query or uri.fragment)
    assert s["tier"] == "T1B"
    assert s["authority_class"] == "T1B_OFFICIAL_EC_MULTI_PROGRAMME_AGGREGATOR"
    assert s["authority_scope"] == "DIGITAL_FUNDING_AGGREGATOR_DISCOVERY_ONLY_NOT_EXACT_TOPIC_OPERATOR"
    assert s["observation_state"] == "OFFICIAL_AGGREGATOR_INDEX_DISCOVERED_RAW_PENDING"
    assert s["origin_readback_result"] == "OFFICIAL_PORTAL_TEXT_READBACK_NOT_SURFACEMC_RAW_CAPTURE"
    assert s["readback_date_discovery"] == "2026-11-21"
    assert s["adapter_required"] == "EU_DIGITAL_INDEX_SURFACEMC_IMMUTABLE_RAW_AND_FT_EXACT_TOPIC_SEMANTIC_RECONCILE"
    assert s["freshness_hours"] == 24
    assert set(s["source_families"]) == {
        "EU_DIRECT", "BRUSSELS", "DIGITAL_FUNDING", "MARKET_INTELLIGENCE", "DISCOVERY"
    }
    assert {"Digital Europe Programme", "Horizon Europe", "Interreg"} <= set(s["programmes"])
    assert {"reconcile_exact_topic_identifier_and_operator_endpoint",
            "detect_aggregator_vs_funding_tenders_lifecycle_conflicts"} <= set(s["extract"])
    for field in ("material_fact_use", "open_call_authorized",
                  "material_fact_publication_authorized", "credentials_required"):
        assert s[field] is False, ("Unsafe publication authorization", field)
    assert not FORBIDDEN.intersection(s), "Material fact or invented raw evidence"
    for marker in ("SURFACEMC", "NOT_CAPTURED", "fetched_at UTC",
                   "raw_sha256", "semantic_sha256", "parser_version",
                   "run_id", "handoff_sha256", "Funding & Tenders",
                   "LKG", "NO OPEN_CALL", "NO MATERIAL PUBLICATION",
                   "NO DISTRIBUTION", "NO ALERT"):
        assert marker in s["note"], ("Missing evidence boundary", marker)
    return s

def main():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    validate(rows)
    unsafe = [
        ("tier", "T2"),
        ("url", "https://example.invalid/fake"),
        ("authority_class", "T1_DIRECT_TOPIC_OPERATOR"),
        ("authority_scope", "CURRENT_OPEN_CALL"),
        ("observation_state", "OPEN_CALL"),
        ("origin_readback_result", "SURFACEMC_CAPTURED"),
        ("readback_date_discovery", "2026-11-22"),
        ("adapter_required", "NONE"),
        ("open_call_authorized", True),
        ("material_fact_use", True),
        ("material_fact_publication_authorized", True),
        ("source_families", ["EU_DIRECT", "OPEN_CALL"]),
        ("deadline", "2027-03-18"),
        ("budget_eur", 999999999),
        ("eligibility", "All EU applicants"),
        ("topic_identifier", "FAKE-TOPIC"),
        ("submission_endpoint", "https://example.invalid/submit"),
        ("confirmed_current_open", True),
        ("fetched_at", "2026-11-21T10:00:00Z"),
        ("final_url", SOURCE_URL),
        ("raw_sha256", "0"*64),
        ("semantic_sha256", "0"*64),
        ("parser_version", "fake"),
        ("run_id", "fake"),
        ("handoff_sha256", "0"*64),
    ]
    rejected=0
    for key,value in unsafe:
        mutated=copy.deepcopy(rows)
        next(s for s in mutated if s["id"] == SOURCE_ID)[key]=value
        try:
            validate(mutated)
        except (AssertionError, KeyError):
            rejected+=1
        else:
            raise AssertionError("Unsafe index mutation admitted: "+key)
    duplicate=copy.deepcopy(rows)
    duplicate.append(copy.deepcopy(next(s for s in rows if s["id"] == SOURCE_ID)))
    try:
        validate(duplicate)
    except AssertionError:
        rejected+=1
    else:
        raise AssertionError("Duplicate source admitted")
    assert rejected == len(unsafe)+1
    print(json.dumps({"result":"PASS","source_id":SOURCE_ID,
          "negative_mutations_rejected":rejected,
          "open_call_authorized":False,"publication_effect":"NONE"}))

if __name__ == "__main__":
    main()
