#!/usr/bin/env python3
from __future__ import annotations
import copy, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ingest"))
import funding_tenders_fetch as ft
from eu_direct_smp_ft_exact import ExactSMPConflict, collect_exact, select_smp_candidate, validate_evidence
REF="SMP-FOOD-2026-FW-STAKEHOLDERS-PJ"; PROGRAMME_CODE="43252476"; STATUS_CODE="31094502"; PROGRAMME_LABEL="Single Market Programme (SMP)"
def facet_payload(): return {"facets":[{"name":"frameworkProgramme","values":[{"rawValue":PROGRAMME_CODE,"value":PROGRAMME_LABEL}]},{"name":"status","values":[{"rawValue":STATUS_CODE,"value":"Open"}]}]}
def search_payload(deadline="2026-12-31T17:00:00Z"): return [{"identifier":REF,"topicAbbreviation":REF,"callIdentifier":REF,"type":"1","frameworkProgramme":PROGRAMME_CODE,"programmePeriod":"2021 - 2027","status":STATUS_CODE,"title":"Synthetic SMP topic","deadlineDate":deadline}]
def receipt(url): return {"url":url,"final_url":url,"http_status":200,"content_type":"application/json","bytes":2,"sha256":"a"*64}
def make_post(search=None,facet=None):
    search=search if search is not None else search_payload(); facet=facet if facet is not None else facet_payload()
    def post(endpoint,**kwargs):
        if endpoint==ft.SEARCH_ENDPOINT: return copy.deepcopy(search),b"{}",receipt(endpoint)
        if endpoint==ft.FACET_ENDPOINT: return copy.deepcopy(facet),b"{}",receipt(endpoint)
        raise AssertionError(endpoint)
    return post
def topic(url): return {"url":url,"final_url":url,"http_status":200,"content_type":"text/html","bytes":10,"body_sha256":"b"*64,"verified":True}
def main():
    taxonomy={"schema":"PARTENER_EU_FT_PROGRAMME_TAXONOMY_V1","market_intelligence_only":True,"material_fact_use":False,"records":[{"identifier":REF,"programme_family_normalized":"SINGLE_MARKET_PROGRAMME","status_label_candidate":"Open","taxonomy_fingerprint":"3"*64,"source_semantic_fingerprint":"4"*64,"authority_url_candidate":ft.topic_url(REF)}]}
    selected=select_smp_candidate(taxonomy); assert selected["identifier"]==REF
    evidence=collect_exact(REF,run_id="synthetic",fetched_at="2026-09-01T22:10:00+00:00",source_candidate=selected,post_func=make_post(),topic_func=topic)
    validate_evidence(evidence); assert evidence["candidate_state"]=="OPEN_CALL"; assert evidence["programme_family"]=="SINGLE_MARKET_PROGRAMME"; assert evidence["open_call_authorized"] is False; assert evidence["eligibility_authorized"] is False
    assert evidence["programme_fit_evidence"]["facts"]["fit_state"]=="ROMANIA_PROGRAMME_LEVEL_FIT_DEMONSTRATED_NON_AUTHORIZING"
    bad=facet_payload(); bad["facets"][0]["values"][0]["value"]="Digital Europe Programme (DIGITAL)"
    try: collect_exact(REF,run_id="bad",fetched_at="2026-09-01T22:10:00+00:00",post_func=make_post(facet=bad),topic_func=topic); raise AssertionError("wrong programme accepted")
    except ValueError as exc: assert "not proven to belong to Single Market Programme" in str(exc)
    conflict=search_payload("2026-12-31T17:00:00Z")+search_payload("2027-01-31T17:00:00Z")
    try: collect_exact(REF,run_id="conflict",fetched_at="2026-09-01T22:10:00+00:00",post_func=make_post(search=conflict),topic_func=topic); raise AssertionError("conflict accepted")
    except ExactSMPConflict: pass
    tampered=copy.deepcopy(evidence); tampered["programme_fit_evidence"]["eligibility_fact_authorized"]=True
    try: validate_evidence(tampered); raise AssertionError("fit self-authorization accepted")
    except ValueError: pass
    print("eu_direct_smp_ft_exact regression: PASS")
if __name__=="__main__": main()
