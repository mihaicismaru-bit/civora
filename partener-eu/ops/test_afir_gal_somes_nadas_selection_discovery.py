#!/usr/bin/env python3
"""Official AFIR GAL local selection is not a nationwide DR36 OPEN_CALL."""
import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
ID = "SRC-RO-AFIR-GAL-SOMES-NADAS-STARTUP-SESSION3-20261120"
SELECTION = "a6a5ab7b-ddb6-4301-8ec7-ad0d24aad865"
GAL = "ca7caab8-f697-427f-a13d-8b0527254c79"
FORBIDDEN = {
    "status", "call_status", "current_status", "submission_status", "deadline",
    "submission_deadline", "budget", "budget_eur", "eligibility",
    "submission_endpoint", "application_endpoint", "exact_submission_endpoint",
    "fetched_at", "final_url", "raw_sha256", "semantic_sha256",
    "parser_version", "run_id", "handoff_sha256", "last_verified_open",
}

def check(rows):
    matches = [r for r in rows if r.get("id") == ID]
    assert len(matches) == 1, "Selection source duplicated or missing"
    s = matches[0]
    assert s["tier"] == "T1"
    assert s["class"] == "official_afir_gal_exact_selection_page_discovery"
    assert s["authority_class"] == "T1_OFFICIAL_AFIR_GAL_PUBLIC_SELECTION_SYSTEM"
    assert s["authority_scope"] == "GAL_107_CLUJ_PUBLIC_SELECTION_DETAIL_NOT_VERIFIED_SUBMISSION_ENDPOINT"
    assert s["observation_state"] == "OFFICIAL_GAL_SELECTION_PAGE_DISCOVERED_RAW_PENDING_EXACT_ENDPOINT_REVIEW"
    assert s["readback_date_discovery"] == "2026-11-20"
    assert s["programme_family"] == "PS_PAC_2023_2027/DR36_LEADER/GAL_LOCAL_SELECTION"
    assert s["programmes"] == ["Planul Strategic PAC 2023–2027 — DR36 LEADER, intervenție locală Start-up neagricol"]
    assert {"ROMANIA", "AFIR", "DR36_LEADER", "GAL_LOCAL_SELECTION", "CALL_REGISTRY",
            "MARKET_INTELLIGENCE", "DISCOVERY"} <= set(s["source_families"])
    assert "OPEN_CALL" not in s["source_families"]
    assert (s["gal_name_discovery"], s["gal_code_discovery"], s["gal_county_code_discovery"]) == (
        "ASOCIATIA GAL SOMES-NADAS", "107", "CJ")
    assert s["selection_page_identifier_discovery"] == SELECTION
    assert s["gal_selector_discovery"] == GAL
    for key, value in {
        "call_title_discovery": "Apel de selecție - 3. Start-up neagricol sesiunea 3",
        "official_page_start_label_discovery": "20.11.2026 09:00",
        "official_page_deadline_label_discovery": "19.12.2026 23:59",
        "official_page_current_status_label_discovery": "Apel de selecție în derulare: DA",
        "official_page_allocated_amount_label_discovery": "60.000,00 EUR",
        "official_page_max_grant_label_discovery": "30.000,00 EUR",
        "adapter_required": "AFIR_GAL_107_SELECTION_DETAIL_SURFACEMC_IMMUTABLE_ORIGINAL_AND_EXACT_INTAKE_RECONCILE_V1",
    }.items():
        assert s.get(key) == value, "Official selection observation drift: " + key
    for url, param, selector in [
        (s["url"], "idApelSelectie", SELECTION),
        (s["parent_gal_registry_url_discovery"], "g", GAL)
    ]:
        parsed = urlsplit(url)
        assert parsed.scheme == "https" and parsed.hostname == "gal.afir.ro"
        assert parsed.username is None and parsed.password is None and parsed.port is None
        assert parse_qs(parsed.query).get(param) == [selector]
    for key in ("exact_application_endpoint_reconciled",
                "exact_call_identity_semantically_reconciled",
                "territorial_eligibility_verified", "material_fact_use",
                "credentials_required", "open_call_authorized",
                "material_fact_publication_authorized"):
        assert s.get(key) is False, "Unreviewed GAL source authorized fact: " + key
    assert not (FORBIDDEN & set(s)), "Fabricated canonical fact or SURFACEMC receipt"
    assert "no_cross_gal_or_dr36_national_identity_budget_deadline_eligibility_alias" in s["extract"]
    assert "published_gal_status_label_is_not_authenticated_current_accepting_application_endpoint" in s["extract"]
    note = s["note"]
    for token in ("20 November 2026", "GAL 107", "county CJ", "19.12.2026",
                  "SOURCE-LABEL DISCOVERY", "NOT_CAPTURED", "SURFACEMC",
                  "final_url", "fetched_at UTC", "raw_sha256", "semantic_sha256",
                  "parser_version", "run_id", "handoff_sha256", "LKG",
                  "OPEN_CALL", "NO MATERIAL PUBLICATION",
                  "NO DISTRIBUTION", "NO ALERT"):
        assert token in note, "Provenance or hold lost: " + token
    return s

def main():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    check(rows)
    cases = [
        ("tier", "T2"), ("authority_scope", "NATIONAL_DR36_OPEN"),
        ("observation_state", "OPEN_CALL"), ("gal_code_discovery", "108"),
        ("gal_county_code_discovery", "VL"),
        ("gal_selector_discovery", "other"), ("selection_page_identifier_discovery", "other"),
        ("official_page_deadline_label_discovery", "02.12.2026 16:00"),
        ("official_page_current_status_label_discovery", "OPEN"),
        ("official_page_allocated_amount_label_discovery", "500000 EUR"),
        ("url", "https://example.invalid/selection"),
        ("parent_gal_registry_url_discovery", "https://example.invalid/gal"),
        ("exact_application_endpoint_reconciled", True),
        ("exact_call_identity_semantically_reconciled", True),
        ("territorial_eligibility_verified", True), ("material_fact_use", True),
        ("open_call_authorized", True), ("material_fact_publication_authorized", True),
        ("status", "OPEN"), ("deadline", "2026-12-19T23:59:00+02:00"),
        ("budget_eur", 60000), ("eligibility", ["all Romanian entities"]),
        ("submission_endpoint", "https://gal.afir.ro/not-verified/submit"),
        ("fetched_at", "2026-11-20T20:30:00Z"), ("raw_sha256", "0" * 64),
        ("parser_version", "fabricated"), ("run_id", "fabricated"),
        ("handoff_sha256", "0" * 64),
    ]
    rejected = 0
    for key, value in cases:
        mutant = copy.deepcopy(rows)
        next(s for s in mutant if s["id"] == ID)[key] = value
        try:
            check(mutant)
        except (AssertionError, KeyError):
            rejected += 1
        else:
            raise AssertionError("Unsafe GAL mutation admitted: " + key)
    duplicate = copy.deepcopy(rows)
    duplicate.append(copy.deepcopy(next(s for s in rows if s["id"] == ID)))
    try:
        check(duplicate)
    except AssertionError:
        rejected += 1
    else:
        raise AssertionError("Duplicate selection admitted")
    assert rejected == len(cases) + 1
    print(json.dumps({"result": "PASS", "source_id": ID,
                      "negative_mutations_rejected": rejected,
                      "open_call_authorized": False, "publication_effect": "NONE"}))

if __name__ == "__main__":
    main()
