#!/usr/bin/env python3
"""Hold ADR Centru Action 6.5 19-Nov-2026 consultation and mixed legacy metadata out of OPEN."""
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
ID = "SRC-PRC-65-INTEGRATED-VOCATIONAL-CAMPUSES-CONSULT-20261119"
URL = "https://www.regiocentru.ro/actiuni/6-5-dezvoltarea-de-campusuri-profesionale-integrate/"
FORBIDDEN = {
    "status", "current_status", "call_status", "deadline", "application_deadline",
    "submission_deadline", "budget", "budget_eur", "eligibility", "call_identifier",
    "mysmis_call_identifier", "application_endpoint", "submission_endpoint",
    "exact_submission_endpoint", "final_url", "fetched_at", "raw_sha256",
    "semantic_sha256", "parser_version", "run_id", "handoff_sha256",
    "publish_authorized", "submission_open",
}
EXPECTED = {
    "tier": "T1",
    "url": URL,
    "authority_class": "T1_OFFICIAL_REGIONAL_MANAGING_AUTHORITY",
    "authority_scope": "DRAFT_GUIDE_CONSULTATION_DISCOVERY_NOT_EXACT_APPLICATION_CALL",
    "observation_state": "PUBLIC_CONSULTATION_INDEXED_METADATA_CONFLICT_RAW_PENDING",
    "source_publication_date_discovery": "2026-11-19",
    "readback_date_discovery": "2026-11-19",
    "action_identifier_discovery": "6.5 / Dezvoltarea de campusuri profesionale integrate",
    "consultation_feedback_window_discovery": "19.11.2026–14.12.2026 (public comments only, NOT a funding submission deadline)",
    "metadata_conflict_discovery": "EXACT_PAGE_SHOWS_NEW_CONSULTATION_BUT_OLD_SUBMISSION_AND_CONSULTATION_PERIODS",
    "adapter_required": "PR_CENTRU_65_DRAFT_GUIDE_ANNEXES_TO_FINAL_MYSMIS_RAW_RECONCILE_V1",
    "official_index_witness_url": "https://www.regiocentru.ro/apeluri-in-consultare/",
}

def validate(rows):
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "Registry source IDs must be globally unique"
    s = next(r for r in rows if r["id"] == ID)
    for key, val in EXPECTED.items():
        assert s.get(key) == val, ("Action 6.5 identity/stage drift", key)
    for raw_url in (s["url"], s["official_index_witness_url"]):
        p = urlsplit(raw_url)
        assert p.scheme == "https" and p.hostname == "www.regiocentru.ro"
        assert p.username is None and p.password is None and p.port is None
    assert s.get("programme_family") == "Programul Regiunea Centru 2021-2027"
    assert s.get("programmes") == ["Programul Regiunea Centru 2021-2027"]
    assert {"ROMANIA", "ADR", "CONSULTATION", "MARKET_INTELLIGENCE", "DISCOVERY"} <= set(s.get("source_families", []))
    assert not {"OPEN_CALL", "EXACT_CALL_OPEN", "PROGRAMMING_PIPELINE"} & set(s.get("source_families", []))
    for field in ("material_fact_use", "credentials_required", "open_call_authorized", "material_fact_publication_authorized"):
        assert s.get(field) is False, ("Never authorize consultation as live funding", field)
    assert not FORBIDDEN.intersection(s), "Synthetic receipt or current material fact present"
    assert {"draft_guide_consultation_discovery", "public_feedback_window_not_funding_deadline",
            "same_page_old_2026_07_to_10_submission_and_2026_04_to_05_consultation_metadata_conflict",
            "exact_mysmis_identifier_and_final_call_not_acquired"} <= set(s.get("extract", []))
    for token in ("19 November 2026", "14 December 2026", "30 July", "30 October",
                  "28 April", "20 May", "MySMIS", "HTTP 403", "SURFACEMC", "NOT_CAPTURED",
                  "fetched_at UTC", "raw_sha256", "parser_version", "run_id",
                  "LKG", "OPEN_CALL", "NO DISTRIBUTION", "NO ALERT"):
        assert token in s.get("note", ""), ("Missing fail-closed conflict/provenance", token)
    return True

def main():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    validate(rows)
    invalid = [
        ("observation_state", "OPEN_CALL"), ("authority_scope", "LIVE_OPEN_CALL"),
        ("material_fact_use", True), ("open_call_authorized", True),
        ("material_fact_publication_authorized", True),
        ("consultation_feedback_window_discovery", "APPLICATION DEADLINE 2026-12-14"),
        ("metadata_conflict_discovery", "NO_CONFLICT"),
        ("source_publication_date_discovery", "2026-10-30"),
        ("action_identifier_discovery", "6.4"),
        ("tier", "T3"), ("url", "http://example.invalid"),
        ("official_index_witness_url", "https://example.invalid"),
        ("deadline", "2026-12-14"), ("submission_deadline", "2026-12-14"),
        ("budget_eur", 20305883), ("eligibility", ["all schools"]),
        ("call_identifier", "PRC/FAKE"), ("submission_endpoint", "https://example.invalid/apply"),
        ("raw_sha256", "0" * 64), ("fetched_at", "2026-11-19T12:00:00Z"),
        ("run_id", "fabricated"), ("parser_version", "fabricated"),
        ("final_url", "https://www.regiocentru.ro/"), ("handoff_sha256", "0" * 64),
    ]
    rejected = 0
    for key, value in invalid:
        changed = copy.deepcopy(rows)
        next(r for r in changed if r["id"] == ID)[key] = value
        try:
            validate(changed)
        except AssertionError:
            rejected += 1
        else:
            raise AssertionError("Unsafe consultation promotion accepted: " + key)
    duplicate = copy.deepcopy(rows)
    duplicate.append(copy.deepcopy(next(r for r in rows if r["id"] == ID)))
    try:
        validate(duplicate)
    except AssertionError:
        rejected += 1
    else:
        raise AssertionError("Duplicate source accepted")
    assert rejected == 25, rejected
    print(json.dumps({"result": "PASS", "source_id": ID,
                      "negative_mutations_rejected": rejected,
                      "open_call_authorized": False, "publication_effect": "NONE"}))

if __name__ == "__main__":
    main()
