#!/usr/bin/env python3
"""Norway Grants Romania Green Business Innovation: programme launch != OPEN call."""
import copy
import json
from pathlib import Path
from urllib.parse import urlparse

SOURCE_ID = "SRC-EEA-NORWAY-RO-GREEN-BUSINESS-INNOVATION-LAUNCH-20261118"
URL = "https://www.innovasjonnorge.no/en/arrangement/lansering-av-green-business-innovation-programme-i-romania"
REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
FORBIDDEN_CALL_OR_RECEIPT = {
    "status", "current_status", "call_status", "submission_status",
    "call_identifier", "exact_call_identifier", "topic_identifier",
    "deadline", "submission_deadline", "application_deadline",
    "budget", "budget_eur", "call_budget_eur", "grant_max_eur",
    "eligibility", "applicant_eligibility", "application_endpoint",
    "exact_submission_endpoint", "last_verified_open", "publish_authorized",
    "final_url", "fetched_at", "raw_sha256", "semantic_sha256",
    "parser_version", "run_id", "handoff_sha256",
}
EXPECTED = {
    "id": SOURCE_ID,
    "url": URL,
    "tier": "T1",
    "class": "official_norway_grants_programme_launch_event_discovery",
    "authority_class": "T1_OFFICIAL_NORWEGIAN_PROGRAMME_OPERATOR_INNOVATION_NORWAY",
    "authority_scope": "PROGRAMMING_FRAMEWORK",
    "programme_family": "EEA_NORWAY_2021_2028/ROMANIA_GREEN_BUSINESS_INNOVATION",
    "observation_state": "PROGRAMMING_PIPELINE",
    "event_observation_state": "PROGRAMME_LAUNCH_EVENT_LISTED_CALLS_FUTURE_RAW_PENDING",
    "programmes": ["Norway Grants 2021-2028"],
    "programme_name_discovery": "Green Business Innovation Programme in Romania / Norway Grants 2021–2028",
    "launch_event_date_discovery": "2026-11-18",
    "launch_event_local_time_discovery": "09:30–16:00 Europe/Bucharest",
    "programme_envelope_eur_discovery": 50000000,
    "programme_envelope_scope": "PROGRAMME_TOTAL_NOT_CALL_OR_APPLICANT_GRANT",
    "official_organiser_event_listing_readback_date_discovery": "2026-11-18",
    "adapter_required": "INNOVATION_NORWAY_RO_GBI_PROGRAMME_LAUNCH_SURFACEMC_RAW_AND_EXACT_CALL_RECONCILE_V1",
}

def validate(rows):
    matches = [r for r in rows if r.get("id") == SOURCE_ID]
    assert len(matches) == 1, "Norway Grants programme discovery must be unique"
    row = matches[0]
    for key, value in EXPECTED.items():
        assert row.get(key) == value, "Programme launch evidence drift: " + key
    parsed = urlparse(row["url"])
    assert parsed.scheme == "https" and parsed.hostname == "www.innovasjonnorge.no"
    assert parsed.username is None and parsed.password is None and parsed.port is None
    families = set(row.get("source_families") or [])
    assert {"EEA_NORWAY", "ROMANIA", "PROGRAMMING_PIPELINE", "PROGRAMME_LAUNCH", "DISCOVERY"} <= families
    assert not {"OPEN_CALL", "CALL_REGISTRY", "CALL_EXACT_OPEN"} & families
    for key in ("material_fact_use", "credentials_required",
                "open_call_authorized", "material_fact_publication_authorized"):
        assert row.get(key) is False, "Premature programme-to-call promotion: " + key
    assert not FORBIDDEN_CALL_OR_RECEIPT & row.keys(), "Invented current call fact or acquisition receipt"
    required = {
        "norway_grants_2021_2028_programme_total_50_million_eur_not_call_allocation",
        "event_listing_describes_upcoming_calls_for_proposals_not_current_application_acceptance",
        "exact_future_call_identifiers_and_live_application_endpoints_not_yet_reconciled",
    }
    assert required <= set(row.get("extract") or [])
    note = row.get("note") or ""
    for token in ("18 November 2026", "50 million EUR", "UPCOMING",
                  "NOT_CAPTURED", "final_url", "fetched_at UTC", "raw_sha256",
                  "parser_version", "run_id", "SURFACEMC", "LKG",
                  "OPEN_CALL", "NO MATERIAL PUBLICATION", "NO DISTRIBUTION", "NO ALERT"):
        assert token in note, "Programme stage/provenance restriction lost: " + token

def main():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    validate(rows)
    changes = [
        ("observation_state", "OPEN_CALL"),
        ("observation_state", "OPEN"),
        ("authority_scope", "EXACT_OPEN_CALL"),
        ("event_observation_state", "CALL_OPEN"),
        ("tier", "T2"),
        ("authority_class", "T3_MEDIA"),
        ("url", "https://example.invalid/notice"),
        ("programme_envelope_eur_discovery", 5000000),
        ("programme_envelope_scope", "CALL_BUDGET"),
        ("launch_event_date_discovery", "2026-11-17"),
        ("material_fact_use", True),
        ("open_call_authorized", True),
        ("material_fact_publication_authorized", True),
        ("credentials_required", True),
        ("status", "OPEN"),
        ("call_identifier", "GBI-2026-CALL-1"),
        ("application_endpoint", "https://example.invalid/submit"),
        ("deadline", "2027-03-01"),
        ("budget_eur", 50000000),
        ("grant_max_eur", 5000000),
        ("eligibility", ["all firms"]),
        ("raw_sha256", "0"*64),
        ("semantic_sha256", "0"*64),
        ("fetched_at", "2026-11-18T16:00:00Z"),
        ("parser_version", "fictional"),
        ("run_id", "fictional"),
        ("handoff_sha256", "0"*64),
    ]
    rejected = 0
    for key, value in changes:
        trial = copy.deepcopy(rows)
        next(r for r in trial if r.get("id") == SOURCE_ID)[key] = value
        try:
            validate(trial)
        except AssertionError:
            rejected += 1
        else:
            raise AssertionError("Unsafe programme-to-call mutation admitted: " + key)
    duplicate = copy.deepcopy(rows)
    duplicate.append(copy.deepcopy(next(r for r in rows if r.get("id") == SOURCE_ID)))
    try:
        validate(duplicate)
    except AssertionError:
        rejected += 1
    else:
        raise AssertionError("Duplicate official source accepted")
    print(json.dumps({
        "result": "PASS", "source_id": SOURCE_ID,
        "negative_mutations_rejected": rejected,
        "observation_state": EXPECTED["observation_state"],
        "open_call_authorized": False, "publication_effect": "NONE",
    }))

if __name__ == "__main__":
    main()
