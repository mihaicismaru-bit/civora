#!/usr/bin/env python3
"""ADR Centru 2.2 Apel 2: 'Activ' in November is NOT a live December intake."""
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
ID = "SRC-PRC-22-DIGITAL-SMES-APEL2-FUTURE-INTAKE-20261119"
URL = "https://www.regiocentru.ro/actiuni/2-2-intreprinderi-digitale-pentru-o-economie-avansata-apel-2/"
EXPECTED = {
    "tier": "T1",
    "url": URL,
    "authority_class": "T1_OFFICIAL_REGIONAL_MANAGING_AUTHORITY",
    "authority_scope": "OFFICIAL_ACTIVE_BADGE_BUT_FUTURE_APPLICATION_START_NOT_LIVE_OPEN",
    "observation_state": "OFFICIAL_FUTURE_SUBMISSION_WINDOW_DISCOVERED_RAW_PENDING",
    "source_publication_date_discovery": "2026-10-30",
    "readback_date_discovery": "2026-11-19",
    "mysmis_identifier_discovery_hint": "PRC/1059/PRC_P2/OP1/RSO1.2/PRC_A32",
    "submission_window_label_discovery": (
        "2 December 2026 12:00–2 February 2027 12:00 "
        "(Europe/Bucharest, official future window ONLY)"
    ),
    "information_session_label_discovery": (
        "23 November 2026 12:00 (online information session, NOT an application endpoint)"
    ),
    "metadata_conflict_discovery": "OFFICIAL_ACTIVE_LABEL_PRECEDES_2026_12_02_SUBMISSION_OPENING",
}
FORBIDDEN = {
    "status", "current_status", "call_status", "deadline", "submission_deadline",
    "application_deadline", "budget", "budget_eur", "eligibility", "call_identifier",
    "mysmis_call_identifier", "submission_endpoint", "application_endpoint",
    "exact_submission_endpoint", "final_url", "fetched_at", "raw_sha256",
    "semantic_sha256", "parser_version", "run_id", "handoff_sha256", "published_at",
}

def validate(sources):
    ids = [s["id"] for s in sources]
    assert len(ids) == len(set(ids)), "Globally duplicated source ID"
    row = next(s for s in sources if s["id"] == ID)
    for field, value in EXPECTED.items():
        assert row.get(field) == value, ("Identity, stage or date drift", field)
    assert row.get("programme_family") == "Programul Regiunea Centru 2021-2027"
    assert row.get("programmes") == ["Programul Regiunea Centru 2021-2027"]
    for key in ("url", "official_announcement_witness_url", "official_info_session_witness_url"):
        p = urlsplit(row[key])
        assert (p.scheme, p.hostname, p.username, p.password, p.port) == (
            "https", "www.regiocentru.ro", None, None, None
        ), ("Non-official witness", key)
        assert not (p.query or p.fragment)
    assert {"ROMANIA", "ADR", "PLANNED", "CALL_REGISTRY", "MARKET_INTELLIGENCE",
            "DISCOVERY"} <= set(row["source_families"])
    assert not {"OPEN_CALL", "CURRENT_OPEN", "CONSULTATION", "CLOSED_CALL"} & set(row["source_families"])
    for field in ("material_fact_use", "credentials_required", "open_call_authorized",
                  "material_fact_publication_authorized"):
        assert row.get(field) is False, ("Unsafe authorization", field)
    assert not FORBIDDEN.intersection(row), "Synthetic receipt or material fact"
    assert row["adapter_required"] == "PR_CENTRU_22_APEL2_GUIDE_MYSMIS_SURFACEMC_RECONCILE_V1"
    assert {"exact_action_mysmis_identifier_discovery_not_live_submission_receipt",
            "approved_guide_and_annexes_discovery_no_bytes_yet",
            "official_Activ_label_vs_future_2026_12_02_submission_window",
            "2026_11_23_information_session_is_not_submission",
            "exact_MySMIS_application_route_and_live_status_not_reconciled"
            } <= set(row["extract"])
    for marker in (
        "19 November 2026", "30 October 2026", "Activ", "2 December 2026",
        "2 February 2027", "23 November 2026", "MySMIS", "SURFACEMC",
        "NOT_CAPTURED", "fetched_at UTC", "raw_sha256", "parser_version",
        "run_id", "handoff_sha256", "LKG", "HTTP 403", "OPEN_CALL",
        "NO DISTRIBUTION", "NO ALERT"
    ):
        assert marker in row["note"], ("Lost fail-closed evidence gate", marker)
    return row

def main():
    sources = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    validate(sources)
    unsafe = [
        ("observation_state", "OPEN_CALL"),
        ("authority_scope", "CURRENT_OPEN_CALL"),
        ("open_call_authorized", True),
        ("material_fact_use", True),
        ("material_fact_publication_authorized", True),
        ("metadata_conflict_discovery", "NO_CONFLICT"),
        ("mysmis_identifier_discovery_hint", "PRC/FAKE"),
        ("submission_window_label_discovery", "19 November 2026 OPEN NOW"),
        ("information_session_label_discovery", "Application endpoint on 23 November"),
        ("readback_date_discovery", "2026-11-20"),
        ("source_publication_date_discovery", "2027-10-30"),
        ("tier", "T3"),
        ("url", "https://example.invalid/"),
        ("official_announcement_witness_url", "http://example.invalid/"),
        ("official_info_session_witness_url", "https://example.invalid/"),
        ("deadline", "2027-02-02"),
        ("application_deadline", "2027-02-02"),
        ("budget_eur", 14113032),
        ("eligibility", "all Romanian companies"),
        ("submission_endpoint", "https://example.invalid/apply"),
        ("status", "OPEN_CALL"),
        ("fetched_at", "2026-11-19T16:00:00Z"),
        ("raw_sha256", "0" * 64),
        ("parser_version", "invented"),
        ("run_id", "invented"),
        ("handoff_sha256", "0" * 64),
    ]
    rejected = 0
    for key, value in unsafe:
        changed = copy.deepcopy(sources)
        next(s for s in changed if s["id"] == ID)[key] = value
        try:
            validate(changed)
        except AssertionError:
            rejected += 1
        else:
            raise AssertionError("Unsafe future intake promotion accepted: " + key)
    duplicated = copy.deepcopy(sources)
    duplicated.append(copy.deepcopy(next(s for s in sources if s["id"] == ID)))
    try:
        validate(duplicated)
    except AssertionError:
        rejected += 1
    else:
        raise AssertionError("Duplicate source ID accepted")
    assert rejected == len(unsafe) + 1, rejected
    print(json.dumps({
        "result": "PASS", "source_id": ID,
        "negative_mutations_rejected": rejected,
        "open_call_authorized": False, "publication_effect": "NONE"
    }))

if __name__ == "__main__":
    main()
