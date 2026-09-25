#!/usr/bin/env python3
"""S6 governance audit for VÂLCEA CLAR.

The audit is repository-local and deterministic. It consolidates existing
quality/recovery/hold/delivery state without taking publication authority.
Persistent governance state and the audit log change only when the material
state fingerprint changes, preventing hourly log spam.
"""
from __future__ import annotations
import argparse, hashlib, json, os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
GOV=ROOT/"governance"
OPS=ROOT/"ops"
POLICY=GOV/"s6_governance_policy.json"
INCIDENTS=OPS/"incidents.json"
BASELINES=OPS/"rollback_baselines.json"
STATE=OPS/"governance_state.json"
AUDIT_LOG=OPS/"audit_log.jsonl"

PATHS={
 "automation_registry":ROOT/"engine/automation_registry.json",
 "publication_holds":ROOT/"editorial/publication_holds.json",
 "corrections":ROOT/"editorial/corrections.json",
 "delivery_report":ROOT/"delivery/report.json",
 "s3_visual_manifest":ROOT/"visuals/s3_visual_manifest.json",
 "public_ux_state":ROOT/"site/public_ux_state.json",
 "current_edition":ROOT/"site/current_edition.json",
 "story_manifest":ROOT/"site/runtime/stiri/manifest.json",
}

REQUIRED_JOBS={
 "quality_gate","ownership_guard","public_http_health","edition_recovery_operator",
 "edition_delivery_ledger","s2_research_writing_acceptance","s3_visuals_channels",
 "s4_publication_experience","s5_distinctive_products"
}

def now()->str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def load(path:Path,default=None):
    if not path.is_file(): return default
    return json.loads(path.read_text(encoding="utf-8"))

def stable_hash(value:Any)->str:
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def problem(code:str,summary:str,evidence:Any=None)->dict[str,Any]:
    row={"code":code,"summary":summary}
    if evidence is not None: row["evidence"]=evidence
    return row

def audit()->dict[str,Any]:
    blockers=[]; warnings=[]; checks={}

    policy=load(POLICY,{}) or {}
    incidents=load(INCIDENTS,{"incidents":[]}) or {"incidents":[]}
    baselines=load(BASELINES,{}) or {}
    registry=load(PATHS["automation_registry"],{}) or {}
    holds=load(PATHS["publication_holds"],{"holds":[]}) or {"holds":[]}
    corrections=load(PATHS["corrections"],{}) or {}
    delivery=load(PATHS["delivery_report"],{}) or {}
    s3=load(PATHS["s3_visual_manifest"],{}) or {}
    ux=load(PATHS["public_ux_state"],{}) or {}
    edition=load(PATHS["current_edition"],{}) or {}
    stories=load(PATHS["story_manifest"],{"stories":[]}) or {"stories":[]}

    # Governance authority contract.
    principles=policy.get("principles") or {}
    checks["governance_policy"]={
      "automatic_rollback_forbidden":principles.get("automatic_rollback_forbidden") is True,
      "holds_fail_closed":principles.get("publication_holds_fail_closed") is True,
      "material_corrections_visible":principles.get("material_corrections_are_visible") is True
    }
    if not all(checks["governance_policy"].values()):
        blockers.append(problem("GOVERNANCE_INVARIANT_BROKEN","S6 governance policy is incomplete or permissive",checks["governance_policy"]))

    # Registered canonical jobs and ChatGPT boundary.
    jobs={str(x.get("id")):x for x in registry.get("jobs") or [] if isinstance(x,dict) and x.get("id")}
    missing=sorted(REQUIRED_JOBS-set(jobs))
    checks["automation_registry"]={"required_jobs":len(REQUIRED_JOBS),"missing":missing}
    if missing:
        blockers.append(problem("CANONICAL_STAGE_REGRESSION","Required registered jobs are missing",missing))
    chatgpt=registry.get("chatgpt") or {}
    boundary_ok=(
      chatgpt.get("direct_social_publication_allowed") is False
      and chatgpt.get("social_credential_access_allowed") is False
      and chatgpt.get("conversation_runtime_allowed") is False
      and chatgpt.get("state_ownership_allowed") is False
      and chatgpt.get("production_scheduler_allowed") is False
      and chatgpt.get("scheduled_tasks_allowed") is True
      and chatgpt.get("scheduled_task_scope") == "external_control_plane_only"
      and chatgpt.get("external_control_plane_worker_allowed") is True
    )
    checks["chatgpt_boundary"]={"ok":boundary_ok}
    if not boundary_ok:
        blockers.append(problem("GOVERNANCE_INVARIANT_BROKEN","ChatGPT runtime boundary no longer matches governance policy",chatgpt))

    # Publication holds must remain fail-closed.
    unsafe_holds=[]
    for row in holds.get("holds") or []:
        if not isinstance(row,dict): continue
        if row.get("public_projection") is not False or row.get("social_distribution_allowed") is not False:
            unsafe_holds.append(str(row.get("story_id")))
    checks["publication_holds"]={"count":len(holds.get("holds") or []),"unsafe":unsafe_holds}
    if unsafe_holds:
        blockers.append(problem("GOVERNANCE_INVARIANT_BROKEN","One or more publication holds are not fail-closed",unsafe_holds))

    # Stage contracts already established by S1-S5.
    checks["s1_delivery"]={
      "edition_id":delivery.get("edition_id"),
      "complete":delivery.get("complete"),
      "fully_delivered":delivery.get("fully_delivered"),
      "counts":delivery.get("counts")
    }
    if delivery.get("complete") is not True:
        blockers.append(problem("CANONICAL_STAGE_REGRESSION","S1 delivery ledger is no longer reconciled",delivery.get("counts")))
    elif delivery.get("fully_delivered") is not True:
        warnings.append(problem("KNOWN_CHANNEL_MEDIA_BACKLOG","S1 has explicit blocked channel deliveries",delivery.get("counts")))

    s3summary=s3.get("summary") or {}
    checks["s3_visuals"]={"stories_ready":s3summary.get("stories_ready"),"assets":s3summary.get("assets")}
    if int(s3summary.get("stories_ready") or 0)<8 or int(s3summary.get("assets") or 0)<16:
        blockers.append(problem("CANONICAL_STAGE_REGRESSION","S3 visual baseline dropped below accepted pilot",checks["s3_visuals"]))

    s4=ux.get("s4_publication_experience") or {}
    s5=ux.get("s5_distinctive_products") or {}
    checks["s4_publication_experience"]={"status":s4.get("status"),"rss":s4.get("rss"),"correction_register":s4.get("correction_register")}
    checks["s5_distinctive_products"]={"status":s5.get("status"),"clarification_products":s5.get("clarification_products"),"verified_venue_cards":s5.get("verified_venue_cards"),"dossiers":s5.get("dossiers")}
    if s4.get("status")!="OPERATIONAL":
        blockers.append(problem("CANONICAL_STAGE_REGRESSION","S4 publication experience is not operational",s4))
    if s5.get("status")!="OPERATIONAL":
        blockers.append(problem("CANONICAL_STAGE_REGRESSION","S5 distinctive products are not operational",s5))

    correction_policy=corrections.get("policy") or {}
    checks["corrections"]={
      "material_public":correction_policy.get("material_corrections_are_public"),
      "silent_rewrite_forbidden":correction_policy.get("silent_material_rewrite_forbidden"),
      "historical_migration_complete":correction_policy.get("historical_migration_complete")
    }
    if correction_policy.get("material_corrections_are_public") is not True or correction_policy.get("silent_material_rewrite_forbidden") is not True:
        blockers.append(problem("GOVERNANCE_INVARIANT_BROKEN","Correction policy no longer guarantees visible material corrections"))
    if correction_policy.get("historical_migration_complete") is False:
        warnings.append(problem("INCOMPLETE_HISTORICAL_CORRECTION_MIGRATION","Historical correction migration is intentionally not claimed complete"))

    # Incident ledger.
    open_incidents=[]
    for row in incidents.get("incidents") or []:
        if not isinstance(row,dict) or str(row.get("status") or "").upper()=="CLOSED": continue
        open_incidents.append(row)
        sev=str(row.get("severity") or "").upper()
        if sev in {"P0","P1"}:
            blockers.append(problem(f"OPEN_{sev}_INCIDENT",str(row.get("summary") or row.get("id")),row.get("evidence")))
        elif sev=="P2":
            warnings.append(problem("OPEN_P2_INCIDENT",str(row.get("summary") or row.get("id")),row.get("evidence")))
    checks["incidents"]={"open":len(open_incidents),"ids":[str(x.get("id")) for x in open_incidents]}

    # Rollback baseline.
    current_lkg=str(baselines.get("current_lkg") or "")
    baseline=next((x for x in baselines.get("baselines") or [] if str(x.get("id"))==current_lkg),None)
    baseline_ok=bool(
      isinstance(baseline,dict)
      and baseline.get("rollback_eligible") is True
      and baseline.get("scope")=="runtime_only"
      and len(str(baseline.get("commit") or ""))==40
    )
    checks["rollback_baseline"]={"id":current_lkg,"commit":baseline.get("commit") if baseline else None,"valid":baseline_ok}
    if not baseline_ok:
        blockers.append(problem("NO_VALID_ROLLBACK_BASELINE","No executable runtime LKG baseline is registered"))

    # Public state sanity without treating backlog as incident.
    checks["public_runtime"]={
      "edition_id":edition.get("edition_id"),
      "story_routes":len(stories.get("stories") or []),
      "ux_routes":len(ux.get("routes") or []),
      "safe_story_count":ux.get("safe_story_count")
    }
    if not edition.get("edition_id") or len(stories.get("stories") or [])<1:
        blockers.append(problem("CANONICAL_STAGE_REGRESSION","Canonical public runtime is empty or has no current edition",checks["public_runtime"]))

    material={
      "policy_version":policy.get("schema_version"),
      "status":"BLOCKED" if blockers else ("READY_WITH_KNOWN_LIMITATIONS" if warnings else "READY"),
      "blockers":blockers,
      "warnings":warnings,
      "checks":checks,
      "lkg":checks["rollback_baseline"],
    }
    fingerprint=stable_hash(material)
    return {
      "schema_version":"1.0",
      "product":"VÂLCEA CLAR",
      "stage":"S6_OPERATIONS_GOVERNANCE",
      "observed_at":now(),
      "material_fingerprint_sha256":fingerprint,
      **material
    }

def persist(doc:dict[str,Any])->bool:
    old=load(STATE,{}) or {}
    changed=old.get("material_fingerprint_sha256")!=doc.get("material_fingerprint_sha256")
    log_missing_or_empty=not AUDIT_LOG.is_file() or not AUDIT_LOG.read_text(encoding="utf-8").strip()
    if not changed and not log_missing_or_empty:
        return False
    OPS.mkdir(parents=True,exist_ok=True)
    if changed:
        STATE.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    event={
      "at":doc["observed_at"],
      "event":"material_governance_state_change" if changed else "material_governance_state_bootstrap",
      "status":doc["status"],
      "fingerprint":doc["material_fingerprint_sha256"],
      "blocker_codes":[x["code"] for x in doc.get("blockers") or []],
      "warning_codes":[x["code"] for x in doc.get("warnings") or []],
      "head_sha":os.environ.get("GITHUB_SHA")
    }
    with AUDIT_LOG.open("a",encoding="utf-8") as fh:
        fh.write(json.dumps(event,ensure_ascii=False,separators=(",",":"))+"\n")
    return True

def check(doc:dict[str,Any]|None=None)->None:
    doc=doc or load(STATE,{}) or {}
    if doc.get("status")=="BLOCKED":
        codes=[x.get("code") for x in doc.get("blockers") or []]
        raise SystemExit("S6 material governance blockers: "+", ".join(str(x) for x in codes))
    required={"governance_policy","automation_registry","chatgpt_boundary","publication_holds","s1_delivery","s3_visuals","s4_publication_experience","s5_distinctive_products","corrections","incidents","rollback_baseline","public_runtime"}
    missing=required-set((doc.get("checks") or {}).keys())
    if missing: raise SystemExit("S6 check coverage missing: "+", ".join(sorted(missing)))

def self_test()->None:
    assert stable_hash({"b":2,"a":1})==stable_hash({"a":1,"b":2})
    assert problem("X","Y")["code"]=="X"
    print("VÂLCEA CLAR S6 governance self-test: PASS")

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--audit",action="store_true")
    p.add_argument("--persist",action="store_true")
    p.add_argument("--check",action="store_true")
    p.add_argument("--output")
    args=p.parse_args()
    if args.self_test:
        self_test(); return 0
    doc=audit() if args.audit or args.persist else load(STATE,{}) or {}
    if args.output:
        Path(args.output).write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    changed=False
    if args.persist:
        changed=persist(doc)
    if args.check:
        check(doc)
    print(json.dumps({
      "status":doc.get("status"),"changed":changed,
      "blockers":len(doc.get("blockers") or []),"warnings":len(doc.get("warnings") or []),
      "fingerprint":doc.get("material_fingerprint_sha256")
    },ensure_ascii=False))
    return 0

if __name__=="__main__": raise SystemExit(main())
