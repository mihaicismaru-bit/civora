#!/usr/bin/env python3
"""ADR Vest's official Programul Sanatate OI guides index is discovery only.

An "active guides" heading is NOT evidence that a named MySMIS call still
accepts applications; MIPE AM and the exact MySMIS submission endpoint govern.
No SURFACEMC immutable original has been collected for this registry entry.
"""
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "ingest" / "source_registry.json"
PLANE = ROOT / "ingest" / "data_plane_contract.json"
ID = "SRC-RO-ADRVEST-OI-PS-GUIDE-INDEX"
URL = "https://adrvest.ro/programul-sanatate-ghiduri-active/"
PROGRAMME = "Programul Sanatate"
FORBIDDEN = {
    "status", "current_status", "call_status", "deadline", "submission_deadline",
    "budget", "budget_eur", "eligibility", "call_identifier",
    "exact_call_identifier", "submission_endpoint", "exact_submission_endpoint",
    "last_verified_open", "fetched_at", "final_url", "raw_sha256",
    "semantic_sha256", "parser_version", "run_id", "handoff_sha256",
}


def verify(sources, domains):
    found = [s for s in sources if s.get("id") == ID]
    assert len(found) == 1, "missing/duplicated OI health guide source"
    assert domains[PROGRAMME] == ["HEALTH"]
    source = found[0]
    url = urlsplit(source["url"])
    assert source["url"] == URL
    assert url.scheme == "https" and url.hostname == "adrvest.ro"
    assert not url.username and not url.password and not url.fragment
    assert source["tier"] == "T1B", "OI must not impersonate MIPE AM"
    assert source["owner"] == "ADR Vest / OI Programul Sanatate (MIPE is AM)"
    assert source["class"] == "official_intermediate_body_health_guide_index"
    assert source["authority_class"] == "T1B_OFFICIAL_INTERMEDIATE_BODY_INDEX"
    assert source["authority_scope"] == "GUIDE_INDEX_DISCOVERY_ONLY"
    assert source["observation_state"] == "OFFICIAL_OI_GUIDE_INDEX_DISCOVERED_RAW_PENDING"
    assert source["discovery_date"] == "2026-11-21"
    assert source["programmes"] == [PROGRAMME]
    assert source["programme_family"] == PROGRAMME
    assert set(source["source_families"]) == {"ROMANIA", "OI", "HEALTH", "DISCOVERY"}
    assert source["freshness_hours"] == 24
    assert source["adapter_required"] == "ADR_VEST_PS_OI_SURFACEMC_HANDOFF_AND_MIPE_MYSMIS_EXACT_RECONCILE"
    assert set(source["extract"]) == {
        "guide_link_discovery", "corrigendum_link_discovery",
        "apparent_active_label_conflict_discovery", "guide_revision_signal_discovery",
    }
    for flag in ("material_fact_use", "open_call_authorized",
                 "material_fact_publication_authorized", "credentials_required"):
        assert source[flag] is False, "unsafe promotion flag: " + flag
    assert not (FORBIDDEN & source.keys()), "fabricated call fact / raw provenance"
    note = source["note"]
    for token in ("SURFACEMC", "NOT_CAPTURED", "MIPE", "MySMIS", "2026-11-16",
                  "final_url", "fetched_at UTC", "raw_sha256", "parser_version",
                  "run_id", "LKG", "OPEN_CALL", "NO MATERIAL PUBLICATION",
                  "NO DISTRIBUTION", "NO ALERT"):
        assert token in note, "missing authority/provenance guard: " + token


def main():
    sources = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    domains = json.loads(PLANE.read_text(encoding="utf-8"))["programmeDomains"]
    verify(sources, domains)
    mutations = [
        ("tier", "T1"),
        ("owner", "MIPE / AM Programul Sanatate"),
        ("class", "official_managing_authority_exact_call"),
        ("authority_class", "T1_OFFICIAL_MANAGING_AUTHORITY"),
        ("authority_scope", "EXACT_CALL_OPEN"),
        ("observation_state", "OPEN_CALL"),
        ("open_call_authorized", True),
        ("material_fact_use", True),
        ("material_fact_publication_authorized", True),
        ("programmes", ["PTJ"]),
        ("programme_family", "PTJ"),
        ("source_families", ["ROMANIA", "OI", "OPEN_CALL"]),
        ("url", "https://example.invalid/something"),
        ("adapter_required", "NONE"),
        ("discovery_date", "2026-11-20"),
        ("status", "OPEN"),
        ("deadline", "2026-11-30T17:00:00+02:00"),
        ("budget_eur", 1000000),
        ("eligibility", ["all businesses"]),
        ("exact_call_identifier", "invented"),
        ("exact_submission_endpoint", "https://example.invalid/apply"),
        ("fetched_at", "2026-11-21T01:00:00Z"),
        ("raw_sha256", "0" * 64),
        ("parser_version", "fabricated"),
        ("run_id", "fabricated"),
        ("handoff_sha256", "0" * 64),
    ]
    rejected = 0
    for key, value in mutations:
        mutant = copy.deepcopy(sources)
        next(s for s in mutant if s["id"] == ID)[key] = value
        try:
            verify(mutant, domains)
        except (AssertionError, KeyError):
            rejected += 1
        else:
            raise AssertionError("Unsafe OI health guide mutation admitted: " + key)
    dup = copy.deepcopy(sources)
    dup.append(copy.deepcopy(next(s for s in sources if s["id"] == ID)))
    try:
        verify(dup, domains)
    except AssertionError:
        rejected += 1
    else:
        raise AssertionError("Duplicated OI health source admitted")
    assert rejected == len(mutations) + 1
    print(json.dumps({
        "result": "PASS", "source_id": ID, "unsafe_mutations_rejected": rejected,
        "open_call_authorized": False, "publication_effect": "NONE",
    }))


if __name__ == "__main__":
    main()
