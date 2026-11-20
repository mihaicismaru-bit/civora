#!/usr/bin/env python3
"""Official PR Sud-Muntenia AM call index: discovery only, never exact OPEN authority.

Tests only source-registry admission boundaries; actual SURFACEMC raw and exact
MySMIS call reconciliation remain separate required evidence.
"""
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "ingest" / "source_registry.json"
PLANE = ROOT / "ingest" / "data_plane_contract.json"
ID = "SRC-RO-PRSM-AM-OFFICIAL-CALL-INDEX"
URL = "https://2021-2027.adrmuntenia.ro/apeluri-de-proiecte"
PROGRAMME = "Programul Regional Sud-Muntenia 2021-2027"
HINTS = {
    "PRSM/638/PRSM_P2/OP2",
    "PRSM/908/PRSM_P4/OP3/RSO3.2/PRSM_A29",
}
FORBIDDEN = {
    "status", "current_status", "call_status", "deadline", "submission_deadline",
    "budget", "budget_eur", "eligibility", "submission_endpoint",
    "exact_submission_endpoint", "last_verified_open", "fetched_at",
    "final_url", "raw_sha256", "semantic_sha256", "parser_version",
    "run_id", "handoff_sha256",
}


def validate(rows, domains):
    found = [x for x in rows if x.get("id") == ID]
    assert len(found) == 1, "PRSM authority index missing or duplicated"
    s = found[0]
    assert s["tier"] == "T1"
    assert s["class"] == "official_regional_managing_authority_call_index"
    assert s["url"] == URL
    p = urlsplit(s["url"])
    assert p.scheme == "https" and p.hostname == "2021-2027.adrmuntenia.ro"
    assert not p.username and not p.password and not p.fragment
    assert s["programmes"] == [PROGRAMME]
    assert s["programme_family"] == PROGRAMME
    assert domains.get(PROGRAMME) == ["COHESION_CROSS_PROGRAMME"]
    assert set(s["source_families"]) == {"ROMANIA", "ADR", "CALL_REGISTRY", "DISCOVERY"}
    assert s["authority_class"] == "T1_OFFICIAL_REGIONAL_MANAGING_AUTHORITY_INDEX"
    assert s["authority_scope"] == "CALL_INDEX_DISCOVERY_ONLY"
    assert s["observation_state"] == "OFFICIAL_CALL_INDEX_DISCOVERED_RAW_PENDING"
    assert s["readback_date_discovery"] == "2026-11-20"
    assert set(s["sample_exact_call_ids_discovery"]) == HINTS
    assert "exact_prsm_call_identifiers_discovery" in s["extract"]
    assert "material_conflict_signals" in s["extract"]
    assert s["adapter_required"] == "PRSM_AM_CALL_INDEX_SURFACEMC_HANDOFF_AND_EXACT_MYSMIS_RECONCILE"
    assert s["freshness_hours"] == 24
    for flag in ("material_fact_use", "open_call_authorized",
                 "material_fact_publication_authorized", "credentials_required"):
        assert s[flag] is False, flag + " must be fail-closed"
    assert not (FORBIDDEN & s.keys()), "Invented material fact or raw-receipt provenance"
    note = s["note"]
    for token in ("SURFACEMC", "NOT_CAPTURED", "final_url", "fetched_at UTC",
                  "raw_sha256", "parser_version", "run_id", "MySMIS",
                  "OPEN_CALL", "LKG", "NO MATERIAL PUBLICATION",
                  "NO DISTRIBUTION", "NO ALERT"):
        assert token in note, "missing authority/provenance boundary: " + token
    return s


def main():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    domains = json.loads(PLANE.read_text(encoding="utf-8"))["programmeDomains"]
    validate(rows, domains)
    cases = [
        ("tier", "T2"), ("authority_scope", "EXACT_CALL_OPEN"),
        ("observation_state", "OPEN_CALL"), ("open_call_authorized", True),
        ("material_fact_use", True), ("material_fact_publication_authorized", True),
        ("programmes", ["Programul Regiunea Centru 2021-2027"]),
        ("source_families", ["ROMANIA", "ADR", "CALL_REGISTRY", "OPEN_CALL"]),
        ("url", "https://example.invalid/anything"),
        ("sample_exact_call_ids_discovery", ["PRSM/908/ANOTHER_PROGRAMME"]),
        ("readback_date_discovery", "2026-11-21"),
        ("adapter_required", "NO_ADAPTER_REQUIRED"),
        ("deadline", "2026-12-02T14:00:00+02:00"),
        ("budget_eur", 2470588.24),
        ("eligibility", ["all Romanian firms"]),
        ("exact_submission_endpoint", "https://example.invalid/apply"),
        ("fetched_at", "2026-11-20T20:00:00Z"),
        ("raw_sha256", "0" * 64),
        ("parser_version", "fictional"),
        ("run_id", "fictional"),
        ("handoff_sha256", "0" * 64),
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
            raise AssertionError("Unsafe PRSM discovery mutation passed: " + key)
    duplicated = copy.deepcopy(rows)
    duplicated.append(copy.deepcopy(next(s for s in rows if s["id"] == ID)))
    try:
        validate(duplicated, domains)
    except AssertionError:
        rejected += 1
    else:
        raise AssertionError("Duplicate PRSM discovery source passed")
    assert rejected == len(cases) + 1
    print(json.dumps({
        "result": "PASS", "source_id": ID,
        "unsafe_mutations_rejected": rejected,
        "open_call_authorized": False, "publication_effect": "NONE",
    }))


if __name__ == "__main__":
    main()
