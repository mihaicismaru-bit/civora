#!/usr/bin/env python3
"""T2 Romanian EEN cross-programme digest is not exact Funding & Tenders OPEN authority.

ADR Centru 20-Nov-2026 summarises six grouped EU opportunities, including
ECCC expressions of interest that must not be merged with corresponding
joint-procurement grant proposal topics.
"""
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
PLANE = Path(__file__).resolve().parents[1] / "ingest" / "data_plane_contract.json"
ID = "SRC-ADR-CENTRU-EEN-EU-SIX-OPPORTUNITIES-20261120"
URL = ("https://www.adrcentru.ro/proiecte-regionale/"
       "oportunitati-de-finantare-europeana-pentru-agentiile-de-dezvoltare-regionala-"
       "si-actorii-ecosistemelor-regionale-de-inovare/")
EXACT_TOPICS = {"HORIZON-EIE-2027-02-CONNECT-01",
                "HORIZON-HLTH-2027-02-IND-02-two-stage"}
GROUPED_CALLS = {"HORIZON-NATURE-2027-01", "HORIZON-NATURE-2027-02"}
EOIS = {"EOI-ECCC-2027-DIGITAL-DEPLOY-CYBER-12-CEI-NATCH",
        "EOI-ECCC-2027-DIGITAL-DEPLOY-CYBER-12-CEI-CBCH"}
FORBIDDEN = {
    "status", "current_status", "call_status", "deadline",
    "submission_deadline", "budget", "budget_eur", "eligibility",
    "submission_endpoint", "application_endpoint", "exact_submission_endpoint",
    "last_verified_open", "fetched_at", "final_url", "raw_sha256",
    "semantic_sha256", "parser_version", "run_id", "handoff_sha256",
}


def validate(rows, domains):
    found = [s for s in rows if s.get("id") == ID]
    assert len(found) == 1, "EEN digest missing or duplicated"
    s = found[0]
    assert s["tier"] == "T2"
    assert s["url"] == URL
    assert s["authority_class"] == "T2_OFFICIAL_ROMANIAN_EEN_REGIONAL_SECONDARY_CURATION"
    assert s["authority_scope"] == (
        "REGIONAL_EEN_DIGEST_DISCOVERY_ONLY_NOT_COMMISSION_FUNDING_TENDERS_CALL_AUTHORITY"
    )
    assert s["observation_state"] == "SIX_GROUPED_EU_OPPORTUNITIES_DISCOVERED_RAW_PENDING"
    assert s["source_publication_date_discovery"] == "2026-11-20"
    assert s["readback_date_discovery"] == "2026-11-20"
    assert s["programme_family"] == "Horizon Europe + Digital Europe / EEN EU opportunity digest"
    assert s["programmes"] == ["EU direct programmes"]
    assert set(domains["EU direct programmes"]) == {"EU_DIRECT_FUNDING"}
    assert {"ROMANIA", "EU_DIRECT", "EEN", "MARKET_INTELLIGENCE", "DISCOVERY"} <= (
        set(s.get("source_families") or [])
    )
    assert not ({"OPEN_CALL", "EXACT_CALL_OPEN"} & set(s["source_families"]))
    assert set(s["exact_topic_identifiers_discovery"]) == EXACT_TOPICS
    assert set(s["grouped_call_identifiers_discovery"]) == GROUPED_CALLS
    assert set(s["eoi_identifiers_discovery"]) == EOIS
    assert s["generic_unresolved_health_families_discovery"] == ["HORIZON-HLTH-2027"]
    assert not (EOIS & EXACT_TOPICS)
    assert not (GROUPED_CALLS & EXACT_TOPICS)
    assert s["cross_programme_identity_guard"] == (
        "ECCC_EOI_REQUIRES_SEPARATE_JOINT_PROCUREMENT_PROPOSAL; "
        "HORIZON_HLTH_FAMILY_IS_NOT_EXACT_TOPIC"
    )
    assert s["primary_funding_tenders_exact_endpoint_reconciled"] is False
    assert not (FORBIDDEN & s.keys()), "Invented material fact or raw acquisition receipt"
    for key in ("material_fact_use", "credentials_required",
                "open_call_authorized", "material_fact_publication_authorized"):
        assert s.get(key) is False, key + " must be fail-closed"
    parsed = urlsplit(s["url"])
    assert parsed.scheme == "https" and parsed.hostname == "www.adrcentru.ro"
    hosts = set()
    for url in s["linked_official_eu_witness_urls_discovery"]:
        p = urlsplit(url)
        assert p.scheme == "https" and not p.username and not p.password
        hosts.add(p.hostname)
    assert hosts == {
        "eismea.ec.europa.eu", "rea.ec.europa.eu",
        "cybersecurity-centre.europa.eu", "hadea.ec.europa.eu"
    }
    assert "eccc_eoi_natch_and_cbch_are_not_grant_proposal_topic_identifiers" in s["extract"]
    assert "horizon_hlth_family_is_not_exact_topic" in s["cross_programme_identity_guard"].lower()
    note = s["note"]
    for token in ("20 November 2026", "T2", "Funding & Tenders", "ECCC",
                  "HORIZON-HLTH-2027", "NOT_CAPTURED", "SURFACEMC",
                  "final_url", "fetched_at UTC", "raw_sha256",
                  "parser_version", "run_id", "LKG",
                  "OPEN_CALL", "NO MATERIAL PUBLICATION", "NO DISTRIBUTION", "NO ALERT"):
        assert token in note, "Missing provenance/hold notice: " + token
    return s


def main():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    domains = json.loads(PLANE.read_text(encoding="utf-8"))["programmeDomains"]
    validate(rows, domains)
    cases = [
        ("tier", "T1"), ("authority_scope", "EXACT_CURRENT_CALL_AUTHORITY"),
        ("observation_state", "OPEN_CALL"),
        ("source_publication_date_discovery", "2026-11-19"),
        ("open_call_authorized", True), ("material_fact_use", True),
        ("material_fact_publication_authorized", True),
        ("primary_funding_tenders_exact_endpoint_reconciled", True),
        ("exact_topic_identifiers_discovery", sorted(EXACT_TOPICS | EOIS)),
        ("grouped_call_identifiers_discovery", ["HORIZON-NATURE-2027-01-01"]),
        ("eoi_identifiers_discovery", ["DIGITAL-ECCC-2027-DEPLOY-CYBER-12-NATCH"]),
        ("generic_unresolved_health_families_discovery", []),
        ("cross_programme_identity_guard", "ALL_APPLICANT_CALLS_OPEN"),
        ("url", "https://example.invalid/fake"),
        ("deadline", "2027-02-17"), ("budget_eur", 40000000),
        ("eligibility", ["all Romanian entities"]),
        ("exact_submission_endpoint", "https://example.invalid/submit"),
        ("fetched_at", "2026-11-20T16:00:00Z"),
        ("raw_sha256", "0" * 64), ("parser_version", "fictional"),
        ("run_id", "fictional"), ("handoff_sha256", "0" * 64),
    ]
    rejected = 0
    for key, value in cases:
        mutant = copy.deepcopy(rows)
        next(s for s in mutant if s["id"] == ID)[key] = value
        try:
            validate(mutant, domains)
        except (AssertionError, KeyError):
            rejected += 1
        else:
            raise AssertionError("Unsafe EEN mutation admitted: " + key)
    duplicate = copy.deepcopy(rows)
    duplicate.append(copy.deepcopy(next(s for s in rows if s["id"] == ID)))
    try:
        validate(duplicate, domains)
    except AssertionError:
        rejected += 1
    else:
        raise AssertionError("Duplicate regional EEN source admitted")
    assert rejected == len(cases) + 1
    print(json.dumps({
        "result": "PASS", "source_id": ID,
        "negative_mutations_rejected": rejected,
        "open_call_authorized": False, "publication_effect": "NONE",
    }))


if __name__ == "__main__":
    main()
