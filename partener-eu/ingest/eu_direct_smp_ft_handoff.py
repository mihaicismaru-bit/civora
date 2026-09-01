#!/usr/bin/env python3
"""Fail-closed bounded handoff state for Single Market Programme discovery."""
from __future__ import annotations
import argparse, json, pathlib
from typing import Any, Mapping
from eu_direct_smp_ft_exact import select_smp_candidate
SCHEMA="PARTENER_EU_SMP_FT_HANDOFF_V1"

def resolve(taxonomy: Mapping[str,Any], *, run_id: str) -> dict[str,Any]:
    try:
        selected=select_smp_candidate(taxonomy)
        state="CURRENT_BOUNDED_SAMPLE_CANDIDATE_EXACT_RECHECK"; target=selected["identifier"]; required=True
    except ValueError as exc:
        if "contains no Single Market Programme candidate" not in str(exc): raise
        selected=None; state="BOUNDED_SAMPLE_FAMILY_OMITTED_NO_SAFE_IDENTITY_NON_AUTHORIZING"; target=None; required=False
    receipt={"schema":SCHEMA,"run_id":run_id,"source_family":"EU_DIRECT","programme_family":"SINGLE_MARKET_PROGRAMME","observation_state":state,"target_reference":target,"exact_recheck_required":required,"source_candidate":selected,"closure_inference_authorized":False,"material_fact_use":False,"open_call_authorized":False,"deadline_authorized":False,"budget_authorized":False,"eligibility_authorized":False,"publish_authorized":False,"distribution_authorized":False,"call_alert_authorized":False}
    validate(receipt); return receipt

def validate(receipt: Mapping[str,Any])->None:
    if receipt.get("schema")!=SCHEMA or receipt.get("programme_family")!="SINGLE_MARKET_PROGRAMME": raise ValueError("Single Market Programme handoff schema/family drift")
    if receipt.get("observation_state") not in {"CURRENT_BOUNDED_SAMPLE_CANDIDATE_EXACT_RECHECK","BOUNDED_SAMPLE_FAMILY_OMITTED_NO_SAFE_IDENTITY_NON_AUTHORIZING"}: raise ValueError("Single Market Programme handoff state unsupported")
    if receipt.get("exact_recheck_required") is True and not receipt.get("target_reference"): raise ValueError("Single Market Programme exact recheck lacks target")
    if receipt.get("exact_recheck_required") is False and receipt.get("target_reference") is not None: raise ValueError("Single Market Programme omitted-family skip leaked target")
    for key in ("closure_inference_authorized","material_fact_use","open_call_authorized","deadline_authorized","budget_authorized","eligibility_authorized","publish_authorized","distribution_authorized","call_alert_authorized"):
        if receipt.get(key) is not False: raise ValueError(f"Single Market Programme handoff attempted authorization: {key}")
def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--taxonomy",required=True,type=pathlib.Path); p.add_argument("--output",required=True,type=pathlib.Path); p.add_argument("--run-id",default="smp-ft-handoff-live"); a=p.parse_args()
    receipt=resolve(json.loads(a.taxonomy.read_text()),run_id=a.run_id); a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(receipt,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
    print(json.dumps({"observation_state":receipt["observation_state"],"target_reference":receipt["target_reference"],"exact_recheck_required":receipt["exact_recheck_required"]},sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
