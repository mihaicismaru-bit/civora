#!/usr/bin/env python3
"""AM11H official stale Active and currency conflict must not authorize OPEN_CALL."""
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

ID = "SRC-MAI-FAMI-AM11H-STALE-STATUS-CURRENCY-CONFLICT-20261119"
FILE = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
EXPECTED = {
    "tier": "T1",
    "url": "https://fed.mai.gov.ro/11311/lansare-apel-am11h-asistenta-sociala-materiala-pentru-solicitantii-de-azil/",
    "call_identifier_discovery": "AM11H",
    "authority_class": "T1_MANAGING_AUTHORITY_AFACERI_INTERNE",
    "authority_scope": "EXACT_CALL_DETAIL_DISCOVERY_CONFLICT_NOT_CURRENT_APPLICATION_RECEIPT",
    "observation_state": "EXACT_CALL_STALE_ACTIVE_CURRENCY_CONFLICT_RAW_PENDING",
    "currency_conflict_discovery": "BODY_5250000_RON_VS_SUMMARY_5250000_EUR",
    "source_publication_date_discovery": "2026-09-16",
    "source_last_edited_date_discovery": "2026-09-29",
    "readback_date_discovery": "2026-11-19",
    "historical_deadline_label_discovery": "16 October 2026 16:00 (historical deadline label only)",
    "conflicting_status_label_discovery": "Status Apel: Activ after historical October 16 cutoff; OPEN unverified",
    "generic_rofed_url_discovery": "https://rofed.mai.gov.ro/",
}
FORBIDDEN = {"status","current_status","call_status","deadline","submission_deadline",
             "budget","budget_ron","budget_eur","eligibility","submission_endpoint",
             "application_endpoint","final_url","fetched_at","raw_sha256",
             "semantic_sha256","parser_version","run_id","handoff_sha256"}

def validate(rows):
    assert len(rows) == len({s["id"] for s in rows}), "duplicate source"
    source = next(s for s in rows if s["id"] == ID)
    for key, value in EXPECTED.items():
        assert source.get(key) == value, ("incorrect identity/stage", key)
    assert source["programme_family"] == "FAMI 2021-2027"
    assert {"ROMANIA","MAI","FAMI","CALL_REGISTRY","SOURCE_CONFLICT","DISCOVERY"} <= set(source["source_families"])
    assert not {"OPEN_CALL","CLOSED_CALL"} & set(source["source_families"])
    for key, host in (("url","fed.mai.gov.ro"),("generic_rofed_url_discovery","rofed.mai.gov.ro")):
        p = urlsplit(source[key])
        assert p.scheme == "https" and p.hostname == host and not (p.username or p.password or p.port or p.query or p.fragment)
    for key in ("material_fact_use","open_call_authorized","material_fact_publication_authorized","credentials_required"):
        assert source.get(key) is False, ("unsupported authorization", key)
    assert not FORBIDDEN.intersection(source), "invented material or provenance"
    for key in ("official_body_FEN_5250000_RON_conflicts_summary_FEN_5250000_EUR",
                "historical_deadline_2026_10_16_vs_Activ_label",
                "exact_AM11H_identity_not_current_OPEN","generic_ROFED_gateway_not_exact_call_endpoint"):
        assert key in source["extract"], ("lost conflict", key)
    for marker in ("5,250,000 lei","5,250,000 EUR","16 October 2026",
                   "Status Apel: Activ","SURFACEMC","NOT_CAPTURED","raw_sha256",
                   "fetched_at UTC","parser_version","run_id","handoff_sha256",
                   "LKG","OPEN_CALL","NO DISTRIBUTION","NO ALERT"):
        assert marker in source["note"], ("lost safety marker", marker)

def main():
    rows = json.loads(FILE.read_text(encoding="utf-8"))["sources"]
    validate(rows)
    mutations = [
        ("observation_state","OPEN_CALL"),("authority_scope","EXACT_OPEN"),
        ("open_call_authorized",True),("material_fact_use",True),
        ("material_fact_publication_authorized",True),("call_identifier_discovery","AM11G"),
        ("currency_conflict_discovery","NO_CONFLICT"),
        ("conflicting_status_label_discovery","OPEN_CONFIRMED"),
        ("source_publication_date_discovery","2026-11-19"),
        ("historical_deadline_label_discovery","2026-11-19"),
        ("url","https://example.invalid"),("budget_eur",5250000),
        ("budget_ron",5250000),("deadline","2026-12-16"),
        ("submission_endpoint","https://rofed.mai.gov.ro/fake"),
        ("raw_sha256","0"*64),("fetched_at","2026-11-19T12:00:00Z"),
        ("run_id","invented"),("parser_version","invented"),
        ("generic_rofed_url_discovery","https://example.invalid"),
    ]
    rejected = 0
    for field, value in mutations:
        candidate = copy.deepcopy(rows)
        next(s for s in candidate if s["id"] == ID)[field] = value
        try: validate(candidate)
        except AssertionError: rejected += 1
        else: raise AssertionError("Unsafe AM11H mutation accepted: " + field)
    duplicate = copy.deepcopy(rows)
    duplicate.append(copy.deepcopy(next(s for s in rows if s["id"] == ID)))
    try: validate(duplicate)
    except AssertionError: rejected += 1
    else: raise AssertionError("Duplicate AM11H source accepted")
    assert rejected == 21, rejected
    print(json.dumps({"result":"PASS","source":ID,"negative_mutations_rejected":rejected,
                      "open_call_authorized":False,"publication_effect":"NONE"}))
if __name__ == "__main__":
    main()
