#!/usr/bin/env python3
from __future__ import annotations
import copy, pathlib, sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/"ingest"))
from eu_direct_smp_ft_exact import sha256_json, programme_fit_evidence
from eu_direct_smp_ft_reconcile import reconcile, validate_receipt
REF="SMP-FOOD-2026-FW-STAKEHOLDERS-PJ"
def evidence(ts="2026-09-01T22:10:00+00:00",state="OPEN_CALL",status="Open",deadline="2026-12-31T17:00:00Z"):
    u="https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/"+REF
    sem={"identifier":REF,"call_identifier":REF,"title":"Synthetic SMP topic","programme_reference":"43252476","programme_label":"Single Market Programme (SMP)","status_label":status,"observation_state":state,"authority_url":u,"deadline_candidate":deadline,"budget_candidate":None}; fit=programme_fit_evidence(observed_at=ts)
    d={"schema":"PARTENER_EU_SMP_FT_EXACT_EVIDENCE_V1","parser_version":"EU_DIRECT_SMP_FT_EXACT_V1","source_family":"EU_DIRECT","programme_family":"SINGLE_MARKET_PROGRAMME","authority_class":"EU_COMMISSION_FUNDING_TENDERS","observation_state":"EXACT_CURRENT_TOPIC_NON_AUTHORIZING","reference":REF,"fetched_at":ts,"run_id":"synthetic","search_receipt":{"sha256":"a"*64},"facet_receipt":{"sha256":"b"*64},"search_raw_sha256":"c"*64,"facet_raw_sha256":"d"*64,"authority_url":u,"authority_readback":{"url":u,"verified":True},"authority_url_verified":True,"candidate_state":state,"status_label":status,"call_identifier":REF,"title":"Synthetic SMP topic","programme_reference":"43252476","programme_label_official":"Single Market Programme (SMP)","deadline_candidate":deadline,"budget_candidate":None,"exact_semantics":sem,"exact_semantic_fingerprint":sha256_json(sem),"primary_exact_record_count":1,"linked_type8_record_count":0,"linked_type8_record_hashes":[],"source_candidate":{},"source_candidate_fingerprint":None,"programme_fit_evidence":fit,"programme_fit_semantic_fingerprint":sha256_json(fit),"semantic_reconciliation_required":True,"field_scoped_material_admission_required":True,"publication_effect":"NONE","canonical_corpus_mutation":False}
    for k in ("material_fact_use","open_call_authorized","deadline_authorized","budget_authorized","eligibility_authorized","publish_authorized","distribution_authorized","call_alert_authorized"): d[k]=False
    return d
def main():
    current=evidence(); baseline=reconcile(current); validate_receipt(baseline,current=current); assert baseline["reconciliation_state"]=="BASELINE_CAPTURED_NON_AUTHORIZING"; assert baseline["open_call_authorized"] is False
    same=evidence("2026-09-01T22:20:00+00:00"); no_change=reconcile(same,current); assert no_change["reconciliation_state"]=="NO_CHANGE"
    closed=evidence("2026-09-01T22:30:00+00:00",state="CLOSED_CALL",status="Closed"); changed=reconcile(closed,same); assert changed["reconciliation_state"]=="SMP_EXACT_TOPIC_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"; assert changed["call_alert_authorized"] is False
    tampered=copy.deepcopy(baseline); tampered["deadline_authorized"]=True
    try: validate_receipt(tampered,current=current); raise AssertionError("scope broadened")
    except ValueError: pass
    print("eu_direct_smp_ft_reconcile regression: PASS")
if __name__=="__main__": main()
