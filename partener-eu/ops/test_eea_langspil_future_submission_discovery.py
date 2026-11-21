#!/usr/bin/env python3
"""NCN LANGSPIL 2026 announcement is not an accepting current OPEN_CALL.

The Polish programme operator and EEA official portal differ in their meaning
of "Open" before the announced 16 December 2026 OSF application start.
No exact accepting OSF route or immutable original has been acquired.
"""
import copy
import json
from pathlib import Path
from urllib.parse import urlparse

REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
PLANE = Path(__file__).resolve().parents[1] / "ingest" / "data_plane_contract.json"
SOURCE_ID = "SRC-EEA-PL-NCN-LANGSPIL-20261117"
NCN_URL = "https://www.ncn.gov.pl/ogloszenia/konkursy/langspil"
EEA_URL = "https://eeagrants.org/en/poland/programmes/basic-research/calls/langspil"
OSF_GATEWAY = "https://osf.opi.org.pl"
FAMILY = "EEA and Norway Grants Poland / Basic Research / LANGSPIL 2026-2027"

FORBIDDEN_ADMITTED = {
    "status", "call_status", "current_status", "open_at", "close_at",
    "application_deadline", "deadline", "budget", "budget_eur", "eligibility",
    "exact_topic_identifier", "exact_submission_endpoint",
    "submission_endpoint", "final_url", "fetched_at", "raw_sha256",
    "semantic_sha256", "parser_version", "run_id", "handoff_sha256",
    "publish_authorized", "last_verified_open",
}


def validate(rows, domains):
    matches = [s for s in rows if s.get("id") == SOURCE_ID]
    assert len(matches) == 1, "LANGSPIL exact official source missing or duplicated"
    s = matches[0]
    expected = {
        "id": SOURCE_ID,
        "tier": "T1",
        "class": "official_eea_poland_basic_research_langspil_future_submission_announcement",
        "url": NCN_URL,
        "linked_official_eea_call_url_discovery": EEA_URL,
        "linked_osf_generic_gateway_url_discovery": OSF_GATEWAY,
        "programmes": [FAMILY],
        "programme_family": FAMILY,
        "authority_class": "T1_OFFICIAL_POLAND_NCN_BASIC_RESEARCH_PROGRAMME_OPERATOR",
        "authority_scope": "POLISH_LED_RESEARCH_CALL_ANNOUNCEMENT_FUTURE_SUBMISSION_WINDOW_NOT_ROMANIA",
        "observation_state": "OFFICIAL_CALL_ANNOUNCEMENT_FUTURE_SUBMISSION_RAW_PENDING",
        "event_date_discovery": "2026-11-17",
        "eea_call_number_discovery": "1.3",
        "announced_submission_start_discovery": "2026-12-16",
        "announced_submission_close_discovery": "2027-03-16 14:00 CET",
        "eea_portal_status_label_discovery": "Open",
        "osf_submission_status_reconciled": False,
        "adapter_required": "EEA_POLAND_LANGSPIL_NCN_EEA_PORTAL_OSF_EXACT_RAW_RECONCILE_V1",
    }
    for key, value in expected.items():
        assert s.get(key) == value, f"LANGSPIL identity/window/provenance drift: {key}"
    assert urlparse(s["url"]).hostname == "www.ncn.gov.pl"
    assert urlparse(s["linked_official_eea_call_url_discovery"]).hostname == "eeagrants.org"
    assert urlparse(s["linked_osf_generic_gateway_url_discovery"]).hostname == "osf.opi.org.pl"
    assert {"EEA_NORWAY", "POLAND", "PLANNED", "DISCOVERY", "BASIC_RESEARCH"}.issubset(
        set(s.get("source_families") or [])
    ), "Wrong country/future funding taxonomy"
    assert set(domains.get(FAMILY, [])) == {"EEA_NORWAY_GRANTS", "PROGRAMMING_FUTURE"}, (
        "Future Polish programme must not enter current Romanian calls plane"
    )
    assert {"material_fact_use", "credentials_required", "open_call_authorized",
            "material_fact_publication_authorized"}.issubset(s)
    for key in ("material_fact_use", "credentials_required",
                "open_call_authorized", "material_fact_publication_authorized"):
        assert s[key] is False, "Unverified LANGSPIL announcement promoted: " + key
    assert not (FORBIDDEN_ADMITTED & s.keys()), (
        "Unacquired official originals cannot provide current admissible call facts"
    )
    extracts = set(s.get("extract") or [])
    assert {
        "eea_portal_open_label_vs_future_application_window_requires_current_osf_reconcile",
        "polish_research_organisation_project_promoter_and_donor_state_partners_not_romania_general_eligibility",
        "eea_call_number_1_3_not_exact_live_osf_application_identifier",
        "official_originals_and_live_exact_osf_submit_route_not_yet_acquired",
    }.issubset(extracts), "EEA portal label/Polish-only scope/source distinction lost"
    note = s.get("note", "")
    for token in ("17 November 2026", "16 December 2026", "16 March 2027",
                  "Open", "Polish", "Romanian", "NOT_CAPTURED", "SURFACEMC",
                  "OPEN_CALL", "LKG"):
        assert token in note, "LANGSPIL source boundary lost: " + token


def main():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    domains = json.loads(PLANE.read_text(encoding="utf-8"))["programmeDomains"]
    validate(rows, domains)
    rejected = 0
    cases = [
        ("observation_state", "OPEN_CALL"),
        ("open_call_authorized", True),
        ("material_fact_use", True),
        ("material_fact_publication_authorized", True),
        ("osf_submission_status_reconciled", True),
        ("announced_submission_start_discovery", "2026-11-17"),
        ("announced_submission_close_discovery", "2027-03-17 14:00 CET"),
        ("eea_portal_status_label_discovery", "Confirmed currently accepting"),
        ("url", "https://example.com/unofficial-langspil"),
        ("linked_official_eea_call_url_discovery", "https://example.com/eea"),
        ("exact_submission_endpoint", "https://osf.opi.org.pl/fake-submit"),
        ("deadline", "2027-03-16"),
        ("budget_eur", 12_000_000),
        ("eligibility", ["all Romanian SMEs"]),
        ("raw_sha256", "0" * 64),
        ("fetched_at", "2026-11-18T05:00:00Z"),
        ("run_id", "fabricated-run"),
        ("authority_class", "T1_EEA_ROMANIA_OPERATOR"),
        ("programme_family", "EEA Civil Society Fund Romania 2021-2028"),
    ]
    for key, value in cases:
        altered = copy.deepcopy(rows)
        next(s for s in altered if s["id"] == SOURCE_ID)[key] = value
        try:
            validate(altered, domains)
        except AssertionError:
            rejected += 1
        else:
            raise AssertionError("Unsafe LANGSPIL mutation admitted: " + key)
    changed_domains = copy.deepcopy(domains)
    changed_domains[FAMILY] = ["EEA_NORWAY_GRANTS"]
    try:
        validate(rows, changed_domains)
    except AssertionError:
        rejected += 1
    else:
        raise AssertionError("Future-window domain promotion admitted")
    print(json.dumps({
        "result": "PASS",
        "source_id": SOURCE_ID,
        "negative_mutations_rejected": rejected,
        "authority": "NCN_POLAND_T1",
        "observation": "ANNOUNCED_FUTURE_SUBMISSION_RAW_PENDING",
        "open_call_authorized": False,
        "publication_effect": "NONE",
    }))


if __name__ == "__main__":
    main()
