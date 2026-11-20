#!/usr/bin/env python3
"""AFM household battery intake is not AFIR public-sector Modernisation Fund."""
import copy
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "ingest" / "source_registry.json"
NOTICE_ID = "SRC-RO-MMAP-AFM-STORAGE-PROSUMERS-NOTICE-20261117"
SESSION_ID = "SRC-RO-AFM-STORAGE-PROSUMERS-SESSION-20261120"
NOTICE_URL = "https://mmediu.ro/comunicare/comunicate-de-presa/incepe-programul-pentru-baterii-pana-la-15-000-de-lei-pentru-sisteme-de-stocare-a-energiei-inscrierile-persoanelor-fizice-incep-pe-20-noiembrie/"
SESSION_URL = "https://inscrierionline.afm.ro/Sesiune/Lista"
PROGRAMME = "AFM / Fondul pentru Mediu — baterii prosumatori 2026"
FAMILY = "AFM_MMAP_2026/RESIDENTIAL_PROSUMER_BATTERIES"
FORBIDDEN = {
    "status", "current_status", "call_status", "open_at", "close_at",
    "deadline", "application_deadline", "budget", "budget_ron",
    "eligibility", "exact_call_identifier", "exact_submission_endpoint",
    "submission_endpoint", "last_verified_open", "publish_authorized",
    "fetched_at", "final_url", "raw_sha256", "semantic_sha256",
    "parser_version", "run_id", "handoff_sha256",
}

def validate(rows):
    by_id = {row.get("id"): row for row in rows}
    assert len(rows) == len(by_id), "Source IDs duplicated"
    assert NOTICE_ID in by_id and SESSION_ID in by_id, "AFM official pair absent"
    for source_id, url, authority, state, peer in (
        (NOTICE_ID, NOTICE_URL, "T1_OFFICIAL_ROMANIAN_ENVIRONMENT_MINISTRY_MMAP",
         "OFFICIAL_PROGRAMME_NOTICE_DISCOVERED_RAW_PENDING", SESSION_ID),
        (SESSION_ID, SESSION_URL, "T1_OFFICIAL_AFM_APPLICATION_SYSTEM_SESSION_INDEX",
         "OFFICIAL_INTAKE_SESSION_LIST_DISCOVERED_RAW_PENDING", NOTICE_ID),
    ):
        row = by_id[source_id]
        expected = {
            "url": url, "tier": "T1", "authority_class": authority,
            "observation_state": state, "programme_family": FAMILY,
            "programmes": [PROGRAMME], "paired_official_source_id": peer,
            "readback_date_discovery": "2026-11-20",
            "material_fact_use": False, "credentials_required": False,
            "open_call_authorized": False, "material_fact_publication_authorized": False,
            "call_identifiers_verified": False,
            "current_application_endpoints_verified": False,
        }
        for key, expected_value in expected.items():
            assert row.get(key) == expected_value, source_id + " drift: " + key
        parsed = urlparse(row["url"])
        assert parsed.scheme == "https" and parsed.hostname in {
            "mmediu.ro", "inscrierionline.afm.ro"}, "Not an official AFM/MMAP host"
        assert not FORBIDDEN.intersection(row), "Invented live evidence or call fact"
        assert {"ROMANIA", "AFM", "ENERGY_STORAGE", "DISCOVERY"} <= set(
            row.get("source_families") or []), "AFM taxonomy incomplete"
        assert "AFIR" not in row.get("source_families", []), "AFM confused with AFIR"
        assert "OPEN_CALL" not in row.get("source_families", []), "Unverified OPEN"
        assert "NOT_CAPTURED" in row.get("note", ""), "Missing acquisition disclaimer"
    notice = by_id[NOTICE_ID]
    session = by_id[SESSION_ID]
    assert notice["announcement_date_discovery"] == "2026-11-17"
    assert notice["announced_intake_start_discovery"] == "2026-11-20 10:00 Europe/Bucharest"
    assert notice["announced_intake_end_discovery"] == "2026-11-25 23:59 Europe/Bucharest"
    assert session["session_row_label_discovery"] == "Stocare baterii"
    assert session["source_snapshot_is_volatile"] is True
    assert session["available_funds_state_discovery"] == "NOT_REPORTED_DASH"
    assert "SOURCE_VOLATILE" in session["note"]
    for key in ("record_identity", "call_identity", "programme_identity"):
        assert notice.get(key) is None and session.get(key) is None
    for source_id in (NOTICE_ID, SESSION_ID):
        assert source_id != "SRC-RO-AFIR-ENERGY-PUBLIC-20260917"
        assert "AFIR" not in by_id[source_id]["programme_family"]
    afir = by_id.get("SRC-RO-AFIR-ENERGY-PUBLIC-20260917")
    assert afir and afir["programme_family"] == "FOND_MODERNIZARE_2026/PUBLIC_ENERGY"
    assert afir.get("application_gateway_discovery") == "https://depunerepspac.afir.ro/"
    assert afir.get("open_call_authorized") is False
    assert notice["programme_family"] != afir["programme_family"]
    assert session["url"] != afir["application_gateway_discovery"]

def main():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    validate(rows)
    rejected = 0
    for ident, key, value in [
        (NOTICE_ID, "programme_family", "FOND_MODERNIZARE_2026/PUBLIC_ENERGY"),
        (SESSION_ID, "programme_family", "FOND_MODERNIZARE_2026/PUBLIC_ENERGY"),
        (SESSION_ID, "url", "https://depunerepspac.afir.ro/"),
        (SESSION_ID, "authority_class", "T1_OFFICIAL_AFIR"),
        (NOTICE_ID, "observation_state", "OPEN_CALL"),
        (SESSION_ID, "observation_state", "OPEN_CALL"),
        (SESSION_ID, "available_funds_state_discovery", "FUNDS_EXHAUSTED"),
        (SESSION_ID, "source_snapshot_is_volatile", False),
        (NOTICE_ID, "open_call_authorized", True),
        (SESSION_ID, "open_call_authorized", True),
        (SESSION_ID, "current_application_endpoints_verified", True),
        (SESSION_ID, "raw_sha256", "0" * 64),
        (SESSION_ID, "fetched_at", "2026-11-20T13:27:00Z"),
        (SESSION_ID, "exact_submission_endpoint", "https://inscrierionline.afm.ro/"),
        (SESSION_ID, "budget_ron", 400000000),
        (NOTICE_ID, "eligibility", ["everyone"]),
    ]:
        altered = copy.deepcopy(rows)
        next(row for row in altered if row["id"] == ident)[key] = value
        try:
            validate(altered)
        except AssertionError:
            rejected += 1
        else:
            raise AssertionError("Unsafe AFM source mutation admitted: " + key)
    duplicate = copy.deepcopy(rows)
    duplicate.append(copy.deepcopy(next(row for row in rows if row["id"] == SESSION_ID)))
    try:
        validate(duplicate)
    except AssertionError:
        rejected += 1
    else:
        raise AssertionError("Duplicate AFM source accepted")
    print(json.dumps({"status": "PASS", "sources": [NOTICE_ID, SESSION_ID],
                      "negative_mutations_rejected": rejected,
                      "open_call_authorized": False, "publication_effect": "NONE"}))

if __name__ == "__main__":
    main()
