#!/usr/bin/env python3
"""PR SV Oltenia AM indexes are discovery-only, not exact OPEN_CALL authority."""
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "ingest" / "source_registry.json"
PLANE = ROOT / "ingest" / "data_plane_contract.json"
PROGRAMME = "Programul Regional Sud-Vest Oltenia 2021-2027"
CASES = {
    "SRC-RO-PRSV-OLTENIA-AM-CALL-INDEX": {
        "url": "https://pr2021-2027.adroltenia.ro/page.php?id=32",
        "class": "official_regional_managing_authority_call_index",
        "scope": "CALL_INDEX_DISCOVERY_ONLY",
        "state": "OFFICIAL_CALL_INDEX_SEARCH_DISCOVERY_RAW_PENDING",
        "families": {"ROMANIA", "ADR", "CALL_REGISTRY", "DISCOVERY"},
        "adapter": "PRSV_AM_INDEX_SURFACEMC_HANDOFF_AND_EXACT_MYSMIS_RECONCILE",
    },
    "SRC-RO-PRSV-OLTENIA-AM-CALENDAR-2026": {
        "url": "https://pr2021-2027.adroltenia.ro/page.php?id=13",
        "class": "official_regional_managing_authority_programming_calendar_index",
        "scope": "CALENDAR_DISCOVERY_ONLY",
        "state": "PROGRAMMING_PIPELINE",
        "families": {"ROMANIA", "ADR", "CALENDARS", "PROGRAMMING_PIPELINE", "DISCOVERY"},
        "adapter": "PRSV_AM_CALENDAR_SURFACEMC_HANDOFF_AND_MYSMIS_RECONCILE",
    },
}
FORBIDDEN = {
    "status", "current_status", "call_status", "deadline", "submission_deadline",
    "budget", "budget_eur", "eligibility", "submission_endpoint",
    "exact_submission_endpoint", "last_verified_open", "fetched_at", "final_url",
    "raw_sha256", "semantic_sha256", "parser_version", "run_id", "handoff_sha256",
    "call_identifier", "exact_call_identifier",
}

def verify(rows, domains):
    assert domains.get(PROGRAMME) == ["COHESION_CROSS_PROGRAMME"]
    all_ids = [str(s.get("id")) for s in rows]
    assert len(all_ids) == len(set(all_ids)), "duplicate source registry ID"
    for source_id, expected in CASES.items():
        matches = [s for s in rows if s.get("id") == source_id]
        assert len(matches) == 1, "missing/duplicate official index: " + source_id
        s = matches[0]
        u = urlsplit(s["url"])
        assert s["url"] == expected["url"]
        assert u.scheme == "https" and u.hostname == "pr2021-2027.adroltenia.ro"
        assert not u.username and not u.password and not u.fragment
        assert s["tier"] == "T1"
        assert s["class"] == expected["class"]
        assert s["programmes"] == [PROGRAMME] and s["programme_family"] == PROGRAMME
        assert set(s["source_families"]) == expected["families"]
        assert s["authority_class"] == "T1_OFFICIAL_REGIONAL_MANAGING_AUTHORITY_INDEX"
        assert s["authority_scope"] == expected["scope"]
        assert s["observation_state"] == expected["state"]
        assert s["discovery_date"] == "2026-11-21"
        assert s["adapter_required"] == expected["adapter"]
        assert s["freshness_hours"] == 24
        for flag in ("material_fact_use", "open_call_authorized",
                     "material_fact_publication_authorized", "credentials_required"):
            assert s[flag] is False, source_id + " unsafe " + flag
        assert not (FORBIDDEN & s.keys()), source_id + " invented material or raw provenance"
        note = s["note"]
        for token in ("HTTP 502", "NOT_CAPTURED", "SURFACEMC", "final_url", "fetched_at UTC",
                      "raw_sha256", "parser_version", "run_id", "MySMIS", "LKG",
                      "OPEN_CALL", "NO MATERIAL PUBLICATION", "NO DISTRIBUTION", "NO ALERT"):
            assert token in note, source_id + " missing limitation " + token

def main():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    domains = json.loads(PLANE.read_text(encoding="utf-8"))["programmeDomains"]
    verify(rows, domains)
    rejected = 0
    for source_id in CASES:
        for key, value in [
            ("tier", "T2"), ("authority_scope", "EXACT_CALL_OPEN"),
            ("observation_state", "OPEN_CALL"), ("open_call_authorized", True),
            ("material_fact_use", True), ("material_fact_publication_authorized", True),
            ("programme_family", "another programme"), ("programmes", ["another"]),
            ("source_families", ["OPEN_CALL"]), ("url", "https://example.invalid"),
            ("adapter_required", "NONE"), ("deadline", "2026-11-27"),
            ("budget_eur", 1), ("eligibility", ["all businesses"]),
            ("exact_submission_endpoint", "https://example.invalid/apply"),
            ("fetched_at", "2026-11-21T00:00:00Z"),
            ("raw_sha256", "0" * 64), ("parser_version", "fake"),
            ("run_id", "fake"), ("handoff_sha256", "0" * 64),
        ]:
            mutant = copy.deepcopy(rows)
            next(s for s in mutant if s["id"] == source_id)[key] = value
            try:
                verify(mutant, domains)
            except (AssertionError, KeyError):
                rejected += 1
            else:
                raise AssertionError("unsafe indexed discovery mutation admitted: " + source_id + ":" + key)
    assert rejected == 40
    print(json.dumps({"result": "PASS", "source_ids": list(CASES),
                      "unsafe_mutations_rejected": rejected,
                      "open_call_authorized": False, "publication_effect": "NONE"}))

if __name__ == "__main__":
    main()
