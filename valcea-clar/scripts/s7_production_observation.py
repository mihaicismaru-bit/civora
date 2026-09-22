#!/usr/bin/env python3
"""VÂLCEA CLAR S7 production-cycle observation ledger.

S7 is an operational extension after the formal S0-S6 implementation roadmap.
It does not publish, schedule or mutate editorial facts. It records material
production-cycle outcomes from the canonical S1-S6 state so repeated real
operation can be evaluated over time.

A record is material when:
- the newsroom published/updated canonical story state (changed=true), or
- the operator explicitly records a requested production cycle with
  --record-no-publication, allowing a deliberate no-publication decision to be
  part of the observation sample.

Routine five-minute polling runs are therefore not journalled automatically.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
OPS=ROOT/"ops"
LEDGER=OPS/"production_cycles.json"
TRIGGER=OPS/"live-newsroom-trigger.json"

PATHS={
    "decision":ROOT/"site/newsroom_decision.json",
    "discovery":ROOT/"editorial/news_discovery_state.json",
    "story_event":ROOT/"site/story_publication_event.json",
    "delivery":ROOT/"delivery/report.json",
    "governance":ROOT/"ops/governance_state.json",
    "ux":ROOT/"site/public_ux_state.json",
    "s3":ROOT/"visuals/s3_visual_manifest.json",
    "corrections":ROOT/"editorial/corrections.json",
}

def load(path:Path, default=None):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))

def write_json(path:Path,value:Any):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def stable_hash(value:Any)->str:
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")).hexdigest()

def snapshot()->dict[str,Any]:
    decision=load(PATHS["decision"],{}) or {}
    discovery=load(PATHS["discovery"],{}) or {}
    event=load(PATHS["story_event"],{}) or {}
    delivery=load(PATHS["delivery"],{}) or {}
    governance=load(PATHS["governance"],{}) or {}
    ux=load(PATHS["ux"],{}) or {}
    s3=load(PATHS["s3"],{}) or {}
    corrections=load(PATHS["corrections"],{"entries":[]}) or {"entries":[]}
    trigger=load(TRIGGER,{}) or {}

    changed=decision.get("changed") is True
    event_matches=bool(
        changed
        and str(event.get("fingerprint") or "")
        and str(event.get("fingerprint"))==str(decision.get("fingerprint"))
    )
    outcome="PUBLISHED_OR_UPDATED" if changed else "NO_NEW_PUBLISHABLE_STORY"
    new_ids=[str(x) for x in decision.get("new_story_ids") or []]

    material={
        "evaluated_local":decision.get("evaluated_local"),
        "newsroom_fingerprint":decision.get("fingerprint"),
        "outcome":outcome,
        "new_story_ids":new_ids,
        "publishable_story_count":decision.get("publishable_story_count"),
        "publication_event_matches":event_matches,
        "publication_event_at":event.get("published_at") if event_matches else None,
        "discovery":{
            "observed_at":discovery.get("observed_at"),
            "sources_total":discovery.get("sources_total"),
            "sources_ok":discovery.get("sources_ok"),
            "facts_admitted":discovery.get("facts_admitted"),
            "source_notice_briefs":discovery.get("source_notice_briefs"),
            "host_incident_count":discovery.get("host_incident_count"),
        },
        "editorial":{
            "writer":decision.get("editorial_writer"),
            "integrity":decision.get("editorial_integrity"),
            "active_publication_holds":decision.get("active_publication_holds") or [],
        },
        "delivery":{
            "edition_id":delivery.get("edition_id"),
            "counts":delivery.get("counts"),
            "complete":delivery.get("complete"),
            "fully_delivered":delivery.get("fully_delivered"),
        },
        "visuals":{
            "stories_ready":(s3.get("summary") or {}).get("stories_ready"),
            "assets":(s3.get("summary") or {}).get("assets"),
        },
        "experience":{
            "s4_status":(ux.get("s4_publication_experience") or {}).get("status"),
            "s5_status":(ux.get("s5_distinctive_products") or {}).get("status"),
            "safe_story_count":ux.get("safe_story_count"),
            "route_count":len(ux.get("routes") or []),
        },
        "corrections":{
            "entries":len(corrections.get("entries") or []),
            "historical_migration_complete":(corrections.get("policy") or {}).get("historical_migration_complete"),
        },
        "governance":{
            "status":governance.get("status"),
            "blocker_codes":[str(x.get("code")) for x in governance.get("blockers") or [] if isinstance(x,dict)],
            "warning_codes":[str(x.get("code")) for x in governance.get("warnings") or [] if isinstance(x,dict)],
        },
        "operator_trigger":{
            "requested_at":trigger.get("requested_at"),
            "requested_by":trigger.get("requested_by"),
        },
    }
    cycle_id=stable_hash({
        "evaluated_local":material["evaluated_local"],
        "newsroom_fingerprint":material["newsroom_fingerprint"],
        "operator_trigger":material["operator_trigger"],
    })[:20]
    return {"cycle_id":cycle_id,**material}

def default_ledger()->dict[str,Any]:
    return {
      "schema_version":"1.0",
      "product":"VÂLCEA CLAR",
      "stage":"S7_PRODUCTION_LOOP_OBSERVATION",
      "formal_roadmap_note":"S7 is an operational extension; the source development plan formally ends with exploitation validation after three complete editions and seven days.",
      "acceptance_target":{
        "complete_editions_required":3,
        "observation_days_required":7,
        "no_lost_delivery":True,
        "no_accidental_duplicate":True,
        "no_unproven_success":True,
      },
      "cycles":[],
      "observation":{
        "started":False,
        "first_cycle_at":None,
        "material_cycles":0,
        "publication_cycles":0,
        "no_publication_cycles":0,
        "distinct_local_dates":[],
        "formal_validation_complete":False,
      }
    }

def recompute(doc:dict[str,Any])->None:
    cycles=doc.get("cycles") or []
    dates=sorted({str(x.get("evaluated_local") or "")[:10] for x in cycles if x.get("evaluated_local")})
    doc["observation"]={
        "started":bool(cycles),
        "first_cycle_at":cycles[0].get("evaluated_local") if cycles else None,
        "material_cycles":len(cycles),
        "publication_cycles":sum(1 for x in cycles if x.get("outcome")=="PUBLISHED_OR_UPDATED"),
        "no_publication_cycles":sum(1 for x in cycles if x.get("outcome")=="NO_NEW_PUBLISHABLE_STORY"),
        "distinct_local_dates":dates,
        "formal_validation_complete":False,
    }

def record(*,allow_no_publication:bool)->dict[str,Any]:
    row=snapshot()
    if row["outcome"]=="NO_NEW_PUBLISHABLE_STORY" and not allow_no_publication:
        return {"status":"SKIPPED_NON_MATERIAL_POLL","cycle":row}
    doc=load(LEDGER,None) or default_ledger()
    ids={str(x.get("cycle_id")) for x in doc.get("cycles") or [] if isinstance(x,dict)}
    if row["cycle_id"] in ids:
        return {"status":"ALREADY_RECORDED","cycle":row}
    doc.setdefault("cycles",[]).append(row)
    recompute(doc)
    write_json(LEDGER,doc)
    return {"status":"RECORDED","cycle":row,"observation":doc["observation"]}

def validate()->dict[str,Any]:
    doc=load(LEDGER,None) or default_ledger()
    for row in doc.get("cycles") or []:
        if row.get("outcome")=="PUBLISHED_OR_UPDATED" and row.get("publication_event_matches") is not True:
            raise SystemExit(f"S7 publication cycle lacks matching durable story event: {row.get('cycle_id')}")
        gov=row.get("governance") or {}
        if gov.get("blocker_codes"):
            raise SystemExit(f"S7 recorded cycle has material governance blockers: {row.get('cycle_id')}")
        delivery=row.get("delivery") or {}
        if delivery.get("complete") is not True:
            raise SystemExit(f"S7 recorded cycle has unreconciled delivery state: {row.get('cycle_id')}")
    obs=doc.get("observation") or {}
    if obs.get("formal_validation_complete") is True:
        if len(obs.get("distinct_local_dates") or [])<7:
            raise SystemExit("S7 cannot claim seven-day validation with fewer than seven local dates")
        if int(obs.get("publication_cycles") or 0)<3:
            raise SystemExit("S7 cannot claim validation with fewer than three publication cycles")
    result={
      "status":"PASS",
      "cycles":len(doc.get("cycles") or []),
      "publication_cycles":obs.get("publication_cycles",0),
      "no_publication_cycles":obs.get("no_publication_cycles",0),
      "distinct_local_dates":len(obs.get("distinct_local_dates") or []),
      "formal_validation_complete":obs.get("formal_validation_complete",False),
    }
    print(json.dumps(result,ensure_ascii=False))
    return result

def self_test():
    a={"x":1,"y":2}; b={"y":2,"x":1}
    assert stable_hash(a)==stable_hash(b)
    doc=default_ledger(); recompute(doc)
    assert doc["observation"]["formal_validation_complete"] is False
    print("VÂLCEA CLAR S7 production observation self-test: PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--record",action="store_true")
    p.add_argument("--record-no-publication",action="store_true")
    p.add_argument("--check",action="store_true")
    p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if args.self_test:
        self_test(); return 0
    if args.record or args.record_no_publication:
        result=record(allow_no_publication=args.record_no_publication)
        print(json.dumps(result,ensure_ascii=False))
    if args.check:
        validate()
    if not any((args.record,args.record_no_publication,args.check,args.self_test)):
        p.error("choose --record, --record-no-publication, --check or --self-test")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
