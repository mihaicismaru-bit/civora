#!/usr/bin/env python3
"""Secondary 20-Nov PEO ReSTART report is never official OPEN_CALL evidence."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
SOURCE_ID = "SRC-RO-PEO-RESTART-20261120-SECONDARY-LAUNCH-WATCH"
SECONDARY = "https://www.fonduri-structurale.ro/stiri/41838/peo-s-a-lansat-apelul-re-start-femei-pe-piata-muncii"
OFFICIAL_UNVERIFIED = "https://mfe.gov.ro/?p=113289"

EXPECTED = {
    "tier": "T3",
    "url": SECONDARY,
    "official_primary_gateway_unverified": OFFICIAL_UNVERIFIED,
    "authority_class": "T3_SECONDARY_NON_AUTHORITY_DISCOVERY",
    "authority_scope": "SECONDARY_LAUNCH_AND_FUTURE_INTAKE_REPORT_NOT_CURRENT_MYSMIS_ACCEPTANCE",
    "observation_state": "SECONDARY_LAUNCH_CLAIM_T1_RAW_PENDING_NO_OPEN_CALL",
    "report_publication_date_discovery": "2026-11-20",
    "readback_date_discovery": "2026-11-21",
    "reported_future_submission_window_unverified": (
        "26 November 2026 16:00–29 January 2027 16:00 "
        "(secondary only; not active on 21 November)"
    ),
    "official_origin_readback_result": "MIPE_ORIGINAL_NOT_ACCESSIBLE_20261121",
    "adapter_required": "PEO_RESTART_2026_SURFACEMC_T1_GUIDE_QA_AND_EXACT_MYSMIS_RECONCILE_V1",
}
NO_MATERIAL_FIELDS = {
    "status", "current_status", "call_status", "deadline", "submission_deadline",
    "application_deadline", "start_at", "end_at", "opening_date",
    "budget", "budget_eur", "eligibility", "eligible_applicants",
    "call_identifier", "exact_call_identifier", "exact_topic_identifier",
    "submission_endpoint", "exact_submission_endpoint",
    "final_url", "fetched_at", "raw_sha256", "semantic_sha256",
    "parser_version", "run_id", "handoff_sha256", "published_at",
}
REQUIRED_FAMILIES = {
    "ROMANIA", "MIPE", "PEO", "CALL_DISCOVERY", "MARKET_INTELLIGENCE", "DISCOVERY"
}
REQUIRED_MARKERS = {
    "secondary_20_nov_2026_launch_announcement_discovery_only",
    "guide_and_QA_reported_updated_but_original_NOT_CAPTURED",
    "future_26_nov_2026_application_start_UNVERIFIED",
    "exact_call_topic_identifier_and_accepting_MySMIS_endpoint_UNVERIFIED",
    "no_submitted_live_call_evidence_NO_OPEN_CALL",
    "T1_MIPE_original_and_immutable_SURFACEMC_handoff_required",
    "NO_MATERIAL_PUBLICATION_NO_DISTRIBUTION_NO_ALERT",
}


def validate(rows):
    assert len({row["id"] for row in rows}) == len(rows), "duplicate source ID"
    matching = [row for row in rows if row.get("id") == SOURCE_ID]
    assert len(matching) == 1, "discovery identity absent or duplicated"
    row = matching[0]
    for key, expected in EXPECTED.items():
        assert row.get(key) == expected, ("source identity / quarantine drift", key)
    assert row.get("programmes") == ["Programul Educație și Ocupare 2021-2027"]
    assert row.get("programme_family") == "PEO 2021-2027"
    assert REQUIRED_FAMILIES <= set(row.get("source_families") or [])
    assert not ({"OPEN_CALL", "CURRENT_OPEN", "T1", "T1B", "CALL_REGISTRY"}
                & set(row["source_families"]))
    assert row.get("freshness_hours") == 24
    for key in ("material_fact_use", "open_call_authorized",
                "material_fact_publication_authorized", "credentials_required"):
        assert row.get(key) is False, ("secondary report promoted", key)
    assert not (NO_MATERIAL_FIELDS & row.keys()), "fabricated immutable receipt / call facts"
    assert REQUIRED_MARKERS <= set(row.get("extract") or [])
    for key, host in (("url", "www.fonduri-structurale.ro"),
                      ("official_primary_gateway_unverified", "mfe.gov.ro")):
        parsed = urlsplit(row[key])
        assert parsed.scheme == "https" and parsed.hostname == host
        assert parsed.username is None and parsed.password is None and parsed.port is None
        assert not parsed.fragment
        if key == "url":
            assert not parsed.query
        else:
            assert parsed.path == "/" and parsed.query == "p=113289"
    note = row.get("note") or ""
    for token in ("20 November 2026", "T3", "MIPE", "MySMIS",
                  "UNVERIFIED", "NOT_ACCESSIBLE", "SURFACEMC",
                  "fetched_at UTC", "raw_sha256", "semantic_sha256",
                  "parser_version", "run_id", "handoff_sha256",
                  "LKG", "REVIEW", "OPEN_CALL", "NO DISTRIBUTION", "NO ALERT"):
        assert token in note, ("missing provenance warning", token)


def main():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    validate(rows)
    candidate = next(row for row in rows if row["id"] == SOURCE_ID)
    mutations = [
        ("tier", "T1"),
        ("tier", "T1B"),
        ("url", "https://example.invalid/call"),
        ("official_primary_gateway_unverified", "https://example.invalid/?p=113289"),
        ("authority_class", "T1_MIPE"),
        ("authority_scope", "OFFICIAL_ACCEPTING_SUBMISSION"),
        ("observation_state", "OPEN_CALL"),
        ("report_publication_date_discovery", "2026-11-19"),
        ("readback_date_discovery", "2026-11-20"),
        ("reported_future_submission_window_unverified", "OPEN now"),
        ("official_origin_readback_result", "T1_VERIFIED"),
        ("adapter_required", "NO_ADAPTER"),
        ("programme_family", "Horizon Europe"),
        ("source_families", ["ROMANIA", "PEO", "OPEN_CALL"]),
        ("material_fact_use", True),
        ("open_call_authorized", True),
        ("material_fact_publication_authorized", True),
        ("credentials_required", True),
        ("status", "OPEN"),
        ("deadline", "2027-01-29"),
        ("budget_eur", 4198231),
        ("eligibility", ["all applicants"]),
        ("exact_call_identifier", "INVENTED-PEO-CODE"),
        ("submission_endpoint", "https://mysmis2021.gov.ro/fictional-accepting-call"),
        ("fetched_at", "2026-11-21T11:25:00Z"),
        ("raw_sha256", "0" * 64),
        ("semantic_sha256", "0" * 64),
        ("parser_version", "unverified"),
        ("run_id", "invented"),
        ("handoff_sha256", "0" * 64),
        ("extract", ["NO_OPEN_CALL"]),
        ("note", "Verified OPEN"),
    ]
    for field, value in mutations:
        unsafe_rows = copy.deepcopy(rows)
        next(row for row in unsafe_rows if row["id"] == SOURCE_ID)[field] = value
        try:
            validate(unsafe_rows)
        except AssertionError:
            continue
        raise AssertionError("unsafe secondary promotion accepted: " + field)
    with_duplicate = copy.deepcopy(rows)
    with_duplicate.append(copy.deepcopy(candidate))
    try:
        validate(with_duplicate)
    except AssertionError:
        pass
    else:
        raise AssertionError("duplicate source accepted")
    print(json.dumps({
        "result": "PASS",
        "source": SOURCE_ID,
        "negative_mutations_rejected": len(mutations) + 1,
        "open_call_authorized": False,
        "material_publication": "NONE",
        "distribution": "NONE"
    }))


if __name__ == "__main__":
    main()
