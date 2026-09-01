#!/usr/bin/env python3
from __future__ import annotations
import pathlib, sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/"ingest"))
from eu_direct_smp_ft_handoff import resolve, validate
REF="SMP-FOOD-2026-FW-STAKEHOLDERS-PJ"
def main():
    tax={"schema":"PARTENER_EU_FT_PROGRAMME_TAXONOMY_V1","market_intelligence_only":True,"material_fact_use":False,"records":[{"identifier":REF,"programme_family_normalized":"SINGLE_MARKET_PROGRAMME","status_label_candidate":"Open","taxonomy_fingerprint":"1"*64,"source_semantic_fingerprint":"2"*64,"authority_url_candidate":"https://example.invalid"}]}
    state=resolve(tax,run_id="synthetic"); validate(state); assert state["exact_recheck_required"] is True; assert state["target_reference"]==REF; assert state["open_call_authorized"] is False
    empty={**tax,"records":[]}; omitted=resolve(empty,run_id="synthetic"); validate(omitted); assert omitted["exact_recheck_required"] is False; assert omitted["closure_inference_authorized"] is False
    print("eu_direct_smp_ft_handoff regression: PASS")
if __name__=="__main__": main()
