#!/usr/bin/env python3
from __future__ import annotations
import copy, pathlib, sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/"ingest"))
from eu_direct_smp_ft_exact import sha256_json, programme_fit_evidence
from eu_direct_smp_ft_reconcile import DEGRADED_STATE, reconcile, validate_receipt
REF="SMP-FOOD-2026-FW-STAKEHOLDERS-PJ"
def evidence(ts="2026-09-01T22:10:00+00:00",state="OPEN_CALL",status="Open",deadline="2026-12-31T17:00:00Z"):
    u="https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/"+REF
    sem={"identifier":REF,"call_identifier":REF,"title":"Synthetic SMP topic","programme_reference":"43252476","programme_label":"Single Market Programme (SMP)","status_label":status,"observation_state":state,"authority_url":u,"deadline_candidate":deadline,"budget_candidate":None}; fit=programme_fit_evidence(observed_at=ts)
    d={"schema":"PARTENER_EU_SMP_FT_EXACT_EVIDENCE_V1","parser_version":"EU_DIRECT_SMP_FT_EXACT_V1_1","source_family":"EU_DIRECT","programme_family":"SINGLE_MARKET_PROGRAMME","authority_class":"EU_COMMISSION_FUNDING_TENDERS","observation_state":"EXACT_CURRENT_TOPIC_NON_AUTHORIZING","reference":REF,"fetched_at":ts,"run_id":"synthetic","search_receipt":{"sha256":"a"*64},"facet_receipt":{"sha256":"b"*64},"search_raw_sha256":"c"*64,"facet_raw_sha256":"d"*64,"authority_url":u,"authority_readback":{"url":u,"verified":True},"authority_url_verified":True,"source_health_state":"HEALTHY","lkg_required":False,"evidence_usable_for_reconciliation":True,"degradation_reason":None,"candidate_state":state,"status_label":status,"call_identifier":REF,"title":"Synthetic SMP topic","programme_reference":"43252476","programme_label_official":"Single Market Programme (SMP)","deadline_candidate":deadline,"budget_candidate":None,"structured_candidate_snapshot":{"identifier":REF,"record_type":"1","programme_reference":"43252476","programme_label":"Single Market Programme (SMP)","call_identifier":REF,"status_code":"31094502","status_label":status,"title":"Synthetic SMP topic","deadline_candidate":deadline,"budget_candidate":None},"exact_semantics":sem,"exact_semantic_fingerprint":sha256_json(sem),"primary_exact_record_count":1,"linked_type8_record_count":0,"linked_type8_record_hashes":[],"source_candidate":{},"source_candidate_fingerprint":None,"programme_fit_evidence":fit,"programme_fit_semantic_fingerprint":sha256_json(fit),"semantic_reconciliation_required":True,"field_scoped_material_admission_required":True,"publication_effect":"NONE","canonical_corpus_mutation":False}
    for k in ("material_fact_use","open_call_authorized","deadline_authorized","budget_authorized","eligibility_authorized","publish_authorized","distribution_authorized","call_alert_authorized"): d[k]=False
    return d
def degraded(ts="2026-09-01T22:40:00+00:00"):
    d=evidence(ts)
    d["authority_readback"]={"url":d["authority_url"],"verified":False,"error":"HTTPError: HTTP Error 404: Not Found"}
    d["authority_url_verified"]=False; d["source_health_state"]="DEGRADED_AUTHORITY_READBACK"; d["lkg_required"]=True; d["evidence_usable_for_reconciliation"]=False; d["degradation_reason"]="HTTPError: HTTP Error 404: Not Found"
    d["candidate_state"]="UNKNOWN"; d["status_label"]=None; d["deadline_candidate"]=None; d["budget_candidate"]=None
    d["exact_semantics"]={"identifier":REF,"call_identifier_candidate":REF,"title_candidate":"Synthetic SMP topic","programme_reference":"43252476","programme_label":"Single Market Programme (SMP)","status_label_candidate":"Open","authority_url":d["authority_url"],"authority_endpoint_verified":False,"deadline_candidate_structured_only":"2026-12-31T17:00:00Z","budget_candidate_structured_only":None}
    d["exact_semantic_fingerprint"]=sha256_json(d["exact_semantics"])
    return d
def main():
    current=evidence(); baseline=reconcile(current); validate_receipt(baseline,current=current); assert baseline["reconciliation_state"]=="BASELINE_CAPTURED_NON_AUTHORIZING"; assert baseline["open_call_authorized"] is False
    same=evidence("2026-09-01T22:20:00+00:00"); no_change=reconcile(same,current); assert no_change["reconciliation_state"]=="NO_CHANGE"
    closed=evidence("2026-09-01T22:30:00+00:00",state="CLOSED_CALL",status="Closed"); changed=reconcile(closed,same); assert changed["reconciliation_state"]=="SMP_EXACT_TOPIC_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"; assert changed["call_alert_authorized"] is False
    down=degraded(); degraded_rec=reconcile(down,same); validate_receipt(degraded_rec,current=down,previous=same); assert degraded_rec["reconciliation_state"]==DEGRADED_STATE; assert degraded_rec["semantic_reconciliation_passed"] is False; assert degraded_rec["semantic_change_count"]==0; assert degraded_rec["lkg_reference_required"] is True; assert degraded_rec["lkg_reference_available"] is True; assert degraded_rec["lkg_reference_is_current_truth"] is False; assert degraded_rec["material_admission_ready_for_downstream_review"] is False
    tampered=copy.deepcopy(degraded_rec); tampered["material_admission_ready_for_downstream_review"]=True
    try: validate_receipt(tampered,current=down,previous=same); raise AssertionError("degraded current became review ready")
    except ValueError: pass
    tampered=copy.deepcopy(baseline); tampered["deadline_authorized"]=True
    try: validate_receipt(tampered,current=current); raise AssertionError("scope broadened")
    except ValueError: pass
    print("eu_direct_smp_ft_reconcile regression: PASS")
if __name__=="__main__": main()
