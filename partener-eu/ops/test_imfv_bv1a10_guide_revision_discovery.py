#!/usr/bin/env python3
"""Keep official MAI BV1A10 16-Nov guide v2 revision separate from BV1B6 and OPEN."""
import copy
import json
from pathlib import Path
from urllib.parse import urlparse

REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
ID = "SRC-MAI-IMFV-BV1A10-GUIDE-V2-20261116"
BV1B6 = "SRC-MAI-IMFV-BV1B6-LAUNCH-20261116"
URL = "https://fed.mai.gov.ro/11155/lansare-apel-bv1a10-dotarea-politiei-de-frontiera-romane-pentru-cresterea-capacitatii-operationale-a-frontex-ii/"
FORBIDDEN_ADMITTED = {
    "status", "call_status", "current_status", "deadline", "application_deadline",
    "budget", "budget_ron", "eligibility", "exact_submission_endpoint",
    "application_endpoint", "verified_guide_sha256", "final_url", "fetched_at",
    "raw_sha256", "semantic_sha256", "parser_version", "run_id", "handoff_sha256",
    "publish_authorized", "last_verified_open",
}

def validate(rows):
    a = [s for s in rows if s.get("id") == ID]
    b = [s for s in rows if s.get("id") == BV1B6]
    assert len(a) == 1 and len(b) == 1, "Missing or duplicated exact identity"
    s, other = a[0], b[0]
    expected = {
        "tier": "T1",
        "url": URL,
        "programmes": ["IMFV"],
        "authority_class": "T1_MANAGING_AUTHORITY_AFACERI_INTERNE",
        "authority_scope": "EXACT_BV1A10_GUIDE_REVISION_DISCOVERY_ONLY",
        "observation_state": "GUIDE_REVISION_V2_DISCOVERED_RAW_PENDING",
        "original_launch_date_discovery": "2026-07-31",
        "revision_announcement_date_discovery": "2026-11-16",
        "call_identifier_discovery": "BV1A10",
        "guide_version_discovery": "2.0",
        "linked_rofed_generic_gateway_url_discovery": "https://rofed.mai.gov.ro/",
        "distinct_from_call_identifier_discovery": "BV1B6",
        "adapter_required": "MAI_IMFV_BV1A10_ROFED_GUIDE_V2_RAW_IDENTITY_RECONCILE_V1",
    }
    for key, val in expected.items():
        assert s.get(key) == val, f"BV1A10 official discovery drift: {key}"
    assert urlparse(s["url"]).hostname == "fed.mai.gov.ro"
    assert urlparse(s["linked_rofed_generic_gateway_url_discovery"]).hostname == "rofed.mai.gov.ro"
    assert other.get("call_identifier_discovery") == "BV1B6"
    assert s.get("url") != other.get("url"), "Frontex title must not merge exact call identities"
    assert {"ROMANIA", "MAI", "IMFV", "GUIDE_AMENDMENT", "DISCOVERY"}.issubset(
        set(s.get("source_families", [])))
    for k in ("material_fact_use", "credentials_required", "open_call_authorized",
              "material_fact_publication_authorized"):
        assert s.get(k) is False, "Unverified guide-as-OPEN or publication: " + k
    assert not (FORBIDDEN_ADMITTED & s.keys()), "No raw guide, live route or admissible material facts"
    assert {
        "legacy_31_july_2026_launch_not_a_new_16_november_call",
        "bv1a10_distinct_from_bv1b6_similar_frontex_title",
        "summary_budget_typography_conflicts_with_narrative_requires_guide_review",
        "rofed_generic_gateway_not_verified_exact_current_application_endpoint",
    }.issubset(set(s.get("extract", [])))
    note = s.get("note", "")
    for token in ("31 July 2026", "16 November 2026", "BV1A10", "BV1B6",
                  "2.0", "NOT_CAPTURED", "SURFACEMC", "LKG", "NO OPEN_CALL"):
        assert token in note, "Guide revision safety detail lost: " + token

def main():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    validate(rows)
    mutations = [
        ("observation_state", "OPEN_CALL"),
        ("open_call_authorized", True),
        ("material_fact_use", True),
        ("material_fact_publication_authorized", True),
        ("call_identifier_discovery", "BV1B6"),
        ("distinct_from_call_identifier_discovery", "BV1A10"),
        ("url", "https://example.com/notice"),
        ("authority_class", "T1_UNKNOWN"),
        ("original_launch_date_discovery", "2026-11-16"),
        ("revision_announcement_date_discovery", "2026-11-17"),
        ("guide_version_discovery", "3.0"),
        ("exact_submission_endpoint", "https://rofed.mai.gov.ro/fake"),
        ("status", "OPEN"),
        ("deadline", "2027-07-31"),
        ("budget_ron", 283500000),
        ("eligibility", ["all Romanian NGOs"]),
        ("raw_sha256", "0"*64),
        ("run_id", "fabricated"),
        ("fetched_at", "2026-11-18T06:00:00Z"),
        ("verified_guide_sha256", "0"*64),
        ("linked_rofed_generic_gateway_url_discovery", "https://example.com"),
    ]
    rejected = 0
    for key, val in mutations:
        trial = copy.deepcopy(rows)
        next(x for x in trial if x["id"] == ID)[key] = val
        try:
            validate(trial)
        except AssertionError:
            rejected += 1
        else:
            raise AssertionError("Unsafe mutation admitted: " + key)
    trial = copy.deepcopy(rows)
    trial.append(copy.deepcopy(next(x for x in rows if x["id"] == ID)))
    try:
        validate(trial)
    except AssertionError:
        rejected += 1
    else:
        raise AssertionError("Duplicate source identifier admitted")
    print(json.dumps({"result":"PASS", "source_id":ID,
          "negative_mutations_rejected":rejected, "publication_effect":"NONE",
          "state":"GUIDE_V2_DISCOVERED_RAW_PENDING", "open_call_authorized":False}))

if __name__ == "__main__":
    main()
