#!/usr/bin/env python3
"""Secondary PEO deadline-extension claim is discovery, never T1 or OPEN evidence."""
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

SOURCE_ID = "SRC-PEO-SCOLI-VIITOR-SECONDARY-EXTENSION-WATCH-20261119"
REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
REPORT = "https://www.fonduri-structurale.ro/stiri/41823/peo-s-a-prelungit-apelul-scoli-pentru-viitor"
OFFICIAL = "https://mfe.gov.ro/peo-apelurile-competitive-scoli-pentru-viitor/"
SECONDARY_TIME_WITNESS = "https://www.edupedu.ro/apelul-scoli-pentru-viitor-perioada-de-depunere-a-proiectelor-se-prelungeste-cu-doua-luni-pana-la-27-ianuarie-2027/"
TIME_CONFLICT = ("19 Nov 2026: Fonduri Structurale reports 27 Jan 2027 16:00; Edupedu quotes purported amended section 4.3.2 as 27 Jan 2027 16:10. Neither source is a verified MIPE original; exact end time UNRESOLVED.")
EXPECTED = {
    "tier": "T3",
    "url": REPORT,
    "official_primary_gateway_unverified": OFFICIAL,
    "authority_class": "T3_SECONDARY_NON_AUTHORITY_DISCOVERY",
    "authority_scope": "UNVERIFIED_SECONDARY_CORRIGENDUM_CLAIM_NOT_CANONICAL",
    "observation_state": "SECONDARY_EXTENSION_CLAIM_RAW_PENDING_PRIMARY_UNAVAILABLE",
    "report_publication_date_discovery": "2026-11-19",
    "readback_date_discovery": "2026-11-19",
    "reported_order_number_unverified": "1874/19.11.2026",
    "reported_new_deadline_unverified": "27 January 2027 16:00 (secondary report only)",
    "secondary_time_conflict_witness_url": SECONDARY_TIME_WITNESS,
    "secondary_time_conflict_discovery": TIME_CONFLICT,
}
FORBIDDEN = {
    "status", "current_status", "call_status", "deadline", "submission_deadline",
    "application_deadline", "call_identifier", "exact_submission_endpoint",
    "application_endpoint", "submission_endpoint", "eligibility", "budget",
    "budget_eur", "final_url", "fetched_at", "raw_sha256", "semantic_sha256",
    "parser_version", "run_id", "handoff_sha256", "published_at",
}

def validate(sources):
    assert len({s["id"] for s in sources}) == len(sources), "Duplicate source ID"
    source = next(s for s in sources if s["id"] == SOURCE_ID)
    for key, value in EXPECTED.items():
        assert source.get(key) == value, ("Unverified report identity changed", key)
    assert source["programme_family"] == "PEO 2021-2027"
    assert source["programmes"] == ["Programul Educație și Ocupare 2021-2027"]
    assert {"ROMANIA", "PEO", "MIPE", "DISCOVERY", "SOURCE_CONFLICT"} <= set(source["source_families"])
    assert not ({"OPEN_CALL", "CURRENT_OPEN", "T1", "T1B", "CLOSED_CALL"} & set(source["source_families"]))
    for key, host in (("url", "www.fonduri-structurale.ro"), ("official_primary_gateway_unverified", "mfe.gov.ro"), ("secondary_time_conflict_witness_url", "www.edupedu.ro")):
        p = urlsplit(source[key])
        assert p.scheme == "https" and p.hostname == host
        assert p.username is None and p.password is None and p.port is None and not p.query and not p.fragment
    for key in ("open_call_authorized", "material_fact_publication_authorized", "material_fact_use", "credentials_required"):
        assert source.get(key) is False, ("Unverified report improperly authorized", key)
    assert not FORBIDDEN.intersection(source), "Synthetic material fact or immutable provenance"
    assert source.get("adapter_required") == "PEO_SCHOOLS_2026_MIPE_ORDER_MYSMIS_PRIMARY_RAW_RECONCILE_V1"
    for value in ("secondary_report_only", "reported_order_1874_not_acquired",
                  "new_2027_01_27_deadline_UNVERIFIED",
                  "secondary_reports_16_00_vs_16_10_DEADLINE_TIME_CONFLICT",
                  "original_MIPE_timeout", "NO_OPEN_CALL", "NO_DISTRIBUTION"):
        assert value in source["extract"], ("Lost quarantine gate", value)
    for value in ("19 November 2026", "27 January 2027", "27 November 2026",
                  "1874", "T3", "mfe.gov.ro", "SURFACEMC", "NOT_CAPTURED",
                  "raw_sha256", "fetched_at UTC", "parser_version", "run_id",
                  "16:00", "16:10", "SOURCE_CONFLICT", "4.3.2",
                  "handoff_sha256", "LKG", "OPEN_CALL", "NO DISTRIBUTION", "NO ALERT"):
        assert value in source["note"], ("Safety explanation lost", value)

def main():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    validate(rows)
    unsafe = [
        ("tier", "T1"), ("tier", "T1B"), ("authority_class", "T1_MIPE"),
        ("authority_scope", "CANONICAL_EXTENDED_DEADLINE"),
        ("observation_state", "OPEN_CALL"),
        ("open_call_authorized", True), ("material_fact_use", True),
        ("material_fact_publication_authorized", True),
        ("reported_new_deadline_unverified", "27 January 2027 CONFIRMED"),
        ("secondary_time_conflict_discovery", "Time confirmed 16:00"),
        ("secondary_time_conflict_witness_url", "https://example.invalid"),
        ("reported_order_number_unverified", "1874/2027"),
        ("report_publication_date_discovery", "2026-11-20"),
        ("url", "https://example.invalid"),
        ("official_primary_gateway_unverified", "https://example.invalid"),
        ("submission_deadline", "2027-01-27"),
        ("status", "OPEN_CALL"),
        ("submission_endpoint", "https://mfe.gov.ro/fake/submit"),
        ("eligibility", "all schools"), ("budget_eur", 52853355),
        ("fetched_at", "2026-11-19T17:28:00Z"),
        ("raw_sha256", "0" * 64), ("parser_version", "invented"),
        ("run_id", "invented"), ("handoff_sha256", "0" * 64),
    ]
    rejected = 0
    for field, value in unsafe:
        candidate = copy.deepcopy(rows)
        next(s for s in candidate if s["id"] == SOURCE_ID)[field] = value
        try:
            validate(candidate)
        except AssertionError:
            rejected += 1
        else:
            raise AssertionError("Unsafe promotion accepted: " + field)
    duplicate = copy.deepcopy(rows)
    duplicate.append(copy.deepcopy(next(s for s in rows if s["id"] == SOURCE_ID)))
    try:
        validate(duplicate)
    except AssertionError:
        rejected += 1
    else:
        raise AssertionError("Duplicate accepted")
    assert rejected == len(unsafe) + 1
    print(json.dumps({
        "result": "PASS", "source": SOURCE_ID,
        "negative_mutations_rejected": rejected,
        "authorized_current_deadline": False, "open_call_authorized": False,
        "publication_effect": "NONE"
    }))

if __name__ == "__main__":
    main()
