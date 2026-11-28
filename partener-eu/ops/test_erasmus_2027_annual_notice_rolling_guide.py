#!/usr/bin/env python3
"""Erasmus+ 2027 official programme launch and OJ notice cannot authorize exact OPEN."""
import copy
import json
from pathlib import Path
from urllib.parse import urlparse

REGISTRY=Path(__file__).resolve().parents[1]/"ingest"/"source_registry.json"
OJ="SRC-EU-ERASMUS-2027-OJ-ANNUAL-CALL-EACA11-2026"
NEWS="SRC-EU-ERASMUS-2027-EC-LAUNCH-20261118"
OLD="SRC-EU-ERASMUS-GUIDE-2026"
FORBIDDEN={"fetched_at","final_url","raw_sha256","semantic_sha256","parser_version",
           "run_id","handoff_sha256","status","current_status","call_status",
           "deadline","application_deadline","submission_deadline","budget","budget_eur",
           "eligibility","exact_submission_endpoint","submission_endpoint",
           "application_endpoint","topic_identifier"}

def validate(sources):
    ids=[s["id"] for s in sources]
    assert len(ids)==len(set(ids)),"duplicate source IDs"
    rows={s["id"]:s for s in sources}
    assert OJ in rows and NEWS in rows and OLD in rows
    oj,news,old=rows[OJ],rows[NEWS],rows[OLD]
    assert oj["url"]=="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=OJ:C_202606148"
    assert news["url"]=="https://erasmus-plus.ec.europa.eu/whats-new/news/over-eur53-billion-for-wider-opportunities-under-erasmus-2027-call"
    for src,host in ((oj,"eur-lex.europa.eu"),(news,"erasmus-plus.ec.europa.eu")):
        u=urlparse(src["url"])
        assert u.scheme=="https" and u.hostname==host and not (u.username or u.password or u.port)
        assert src["tier"]=="T1"
        assert {"EU_DIRECT","BRUSSELS","ERASMUS_PLUS","DISCOVERY"}<=set(src["source_families"])
        assert "OPEN_CALL" not in src["source_families"]
        assert not FORBIDDEN.intersection(src),"Synthetic provenance or material fact"
        for key in ("material_fact_use","credentials_required","open_call_authorized","material_fact_publication_authorized"):
            assert src.get(key) is False,(src["id"],key)
        for marker in ("SURFACEMC","NOT_CAPTURED","fetched_at UTC","raw_sha256",
                       "semantic_sha256","parser_version","run_id","handoff_sha256",
                       "LKG","OPEN_CALL","NO DISTRIBUTION","NO ALERT"):
            assert marker in src["note"],(src["id"],marker)
    assert oj["notice_reference_discovery"]=="C/2026/6148"
    assert oj["annual_call_identifier_discovery"]=="EAC/A11/2026"
    assert oj["notice_publication_date_discovery"]=="2026-11-18"
    assert oj["readback_date_discovery"]=="2026-11-19"
    assert oj["linked_2027_launch_source_id"]==NEWS
    assert oj["observation_state"]=="2027_ANNUAL_OJ_NOTICE_LINKED_BOT_BLOCKED_RAW_PENDING"
    assert oj["authority_scope"]=="ANNUAL_2027_CALL_NOTICE_NOT_AN_EXACT_ACTION_SUBMISSION_RECEIPT"
    assert news["source_publication_date_discovery"]=="2026-11-18"
    assert news["readback_date_discovery"]=="2026-11-19"
    assert news["linked_official_journal_source_id"]==OJ
    assert news["observation_state"]=="2027_PROGRAMME_LAUNCH_OFFICIAL_LABEL_RAW_PENDING"
    assert news["authority_scope"]=="PROGRAMME_LEVEL_2027_ANNUAL_OPEN_ANNOUNCEMENT_NOT_PER_ACTION_OPEN"
    assert news["annual_programme_call_label_discovery"]=="2027 call now open (programme-wide official wording only)"
    assert "NOT per-action" in news["annual_programme_budget_label_discovery"]
    assert old["url"]==news["official_2027_guide_url"]
    assert old["linked_2027_annual_call_source_id"]==OJ
    assert old["linked_2027_launch_source_id"]==NEWS
    assert old["current_gateway_rollover_observed_date_discovery"]=="2026-11-19"
    assert old["historical_2026_version_available_at_current_url"] is False
    assert "2027" in old["current_gateway_version_discovery"]
    assert old["material_fact_use"] is False
    assert "ROLLING" in old["note"] and "DO NOT extract 2026" in old["note"]

def main():
    sources=json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    validate(sources)
    mutations=[
        (NEWS,"observation_state","OPEN_CALL"),(NEWS,"authority_scope","EXACT_ACTION_OPEN"),
        (NEWS,"open_call_authorized",True),(NEWS,"material_fact_use",True),
        (NEWS,"material_fact_publication_authorized",True),
        (NEWS,"budget_eur",5300000000),(NEWS,"deadline","2027-03-01"),
        (NEWS,"application_endpoint","https://example.invalid/apply"),
        (NEWS,"url","https://example.invalid"),
        (NEWS,"source_publication_date_discovery","2026-11-19"),
        (NEWS,"annual_programme_call_label_discovery","all topics open"),
        (NEWS,"annual_programme_budget_label_discovery","5.3 billion per topic"),
        (NEWS,"raw_sha256","0"*64),(NEWS,"fetched_at","2026-11-19T12:00:00Z"),
        (OJ,"observation_state","OPEN_CALL"),(OJ,"open_call_authorized",True),
        (OJ,"annual_call_identifier_discovery","ERASMUS-EDU-2027-EUR-UNIV"),
        (OJ,"notice_reference_discovery","C/2025/6080"),
        (OJ,"url","https://example.invalid"),
        (OJ,"submission_endpoint","https://example.invalid"),
        (OJ,"parser_version","invented"),
        (OLD,"historical_2026_version_available_at_current_url",True),
        (OLD,"current_gateway_rollover_observed_date_discovery","2026-11-18"),
        (OLD,"linked_2027_annual_call_source_id","SRC-FAKE"),
    ]
    rejected=0
    for ident,key,value in mutations:
        m=copy.deepcopy(sources)
        next(s for s in m if s["id"]==ident)[key]=value
        try:validate(m)
        except AssertionError:rejected+=1
        else:raise AssertionError("unsafe Erasmus 2027 mutation accepted "+ident+"/"+key)
    m=copy.deepcopy(sources)
    m.append(copy.deepcopy(next(s for s in sources if s["id"]==OJ)))
    try:validate(m)
    except AssertionError:rejected+=1
    else:raise AssertionError("duplicate annual OJ source accepted")
    assert rejected==25,rejected
    print(json.dumps({"result":"PASS","pair":[OJ,NEWS],
                      "negative_mutations_rejected":rejected,
                      "rolling_2026_gateway_historical_use_authorized":False,
                      "open_call_authorized":False,"publication_effect":"NONE"}))
if __name__=="__main__":main()
