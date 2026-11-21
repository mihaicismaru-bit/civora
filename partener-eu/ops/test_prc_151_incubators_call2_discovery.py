#!/usr/bin/env python3
"""ADR Centru action 1.5.1 call 2: exact-ID discovery, never OPEN authority."""
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
ID = "SRC-RO-PRC-151-INCUBATORS-CALL2-20261121"
CONSULT = "SRC-PRC-151-INCUBATORS-RESIDENTS-CONSULT-20261113"
URL = "https://www.regiocentru.ro/actiuni/1-5-1-incubatoare-si-acceleratoare-de-afaceri-apel-2/"
PROGRAM = "Programul Regiunea Centru 2021-2027"
FORBIDDEN = {
    "status", "current_status", "call_status", "deadline",
    "submission_deadline", "budget", "budget_eur", "eligibility",
    "submission_endpoint", "exact_submission_endpoint", "last_verified_open",
    "fetched_at", "final_url", "raw_sha256", "semantic_sha256",
    "parser_version", "run_id", "handoff_sha256",
}

def validate(rows, domains):
    found = [s for s in rows if s.get("id") == ID]
    assert len(found) == 1, "missing or duplicate action detail source"
    assert len([s for s in rows if s.get("id") == CONSULT]) == 1
    s = found[0]
    assert s["tier"] == "T1"
    assert s["class"] == "official_regional_managing_authority_call_action_detail_discovery"
    assert s["owner"].startswith("ADR Centru /")
    assert s["url"] == URL
    p = urlsplit(s["url"])
    assert p.scheme == "https" and p.hostname == "www.regiocentru.ro"
    assert not p.username and not p.password and not p.fragment
    assert s["programmes"] == [PROGRAM] and s["programme_family"] == PROGRAM
    assert domains[PROGRAM] == ["COHESION_CROSS_PROGRAMME"]
    assert set(s["source_families"]) == {"ROMANIA","ADR","REGIONAL_PROGRAMME","CALL_DETAIL","MARKET_INTELLIGENCE","DISCOVERY"}
    assert s["authority_class"] == "T1_OFFICIAL_REGIONAL_MANAGING_AUTHORITY_ACTION_DETAIL"
    assert s["authority_scope"] == "CALL_ACTION_DETAIL_DISCOVERY_ONLY_NOT_EXACT_MYSMIS_SUBMISSION"
    assert s["observation_state"] == "OFFICIAL_ACTION_PAGE_INDEX_DISCOVERED_RAW_PENDING"
    assert s["readback_date_discovery"] == "2026-11-21"
    assert s["official_page_call_code_hint_discovery"] == "RC/1218/PRC_P1/OP1"
    assert s["official_page_status_label_discovery"] == "Activ"
    assert s["official_page_submission_window_label_discovery"] == "21.10.2026 ora 12.00 - 21.12.2026 ora 12.00"
    assert s["origin_readback_result"] == "HTTP_403_NOT_CAPTURED"
    assert s["separate_from_consultation_id"] == CONSULT
    assert s["adapter_required"] == "PRC_151_CALL2_SURFACEMC_ACQUISITION_HANDOFF_AND_EXACT_MYSMIS_RECONCILE"
    assert s["freshness_hours"] == 24
    for field in ("material_fact_use", "open_call_authorized", "material_fact_publication_authorized", "credentials_required"):
        assert s[field] is False, field
    assert not (FORBIDDEN & s.keys()), "fabricated material fact or provenance"
    for token in ("SURFACEMC", "NOT_CAPTURED", "final_url", "fetched_at UTC", "raw_sha256", "parser_version", "run_id", "handoff_sha256", "MySMIS", "REVIEW", "LKG", "NO OPEN_CALL", "NO DISTRIBUTION", "NO ALERT"):
        assert token in s["note"], token
    return s

def main():
    rows = json.loads((ROOT/"ingest"/"source_registry.json").read_text(encoding="utf-8"))["sources"]
    domains = json.loads((ROOT/"ingest"/"data_plane_contract.json").read_text(encoding="utf-8"))["programmeDomains"]
    validate(rows, domains)
    unsafe = [
        ("tier","T2"), ("authority_scope","EXACT_CALL_OPEN"),
        ("observation_state","OPEN_CALL"), ("origin_readback_result","HTTP_200_IMMUTABLE_CAPTURE"),
        ("separate_from_consultation_id","a-different-programme"),
        ("open_call_authorized",True), ("material_fact_use",True),
        ("material_fact_publication_authorized",True),
        ("source_families",["ROMANIA","ADR","OPEN_CALL"]),
        ("url","https://not-an-authority.invalid/"),
        ("programmes",["Programul Regional Nord-Est 2021-2027"]),
        ("official_page_call_code_hint_discovery","PRC/1218/PRC_P1/OP1"),
        ("official_page_status_label_discovery","OPEN_CALL"),
        ("official_page_submission_window_label_discovery","until 2035"),
        ("readback_date_discovery","2026-11-22"),
        ("adapter_required","NONE"),
        ("deadline","2026-12-21T12:00:00+02:00"),
        ("budget_eur",9201232),
        ("eligibility",["any Romanian company"]),
        ("exact_submission_endpoint","https://mysmis2021.gov.ro"),
        ("fetched_at","2026-11-21T05:00:00Z"),
        ("raw_sha256","0"*64),
        ("parser_version","invented"),
        ("run_id","invented"),
        ("handoff_sha256","0"*64),
    ]
    rejected=0
    for field,value in unsafe:
        mutant=copy.deepcopy(rows)
        next(s for s in mutant if s.get("id")==ID)[field]=value
        try:
            validate(mutant,domains)
        except (AssertionError,KeyError):
            rejected+=1
        else:
            raise AssertionError("Unsafe source admission permitted: "+field)
    dup=copy.deepcopy(rows)
    dup.append(copy.deepcopy(next(s for s in rows if s.get("id")==ID)))
    try:
        validate(dup,domains)
    except AssertionError:
        rejected+=1
    else:
        raise AssertionError("Duplicate official source permitted")
    assert rejected==len(unsafe)+1
    print(json.dumps({"status":"PASS","source_id":ID,"unsafe_mutations_rejected":rejected,
        "open_call_authorized":False,"publication_effect":"NONE"}))

if __name__=="__main__":
    main()
