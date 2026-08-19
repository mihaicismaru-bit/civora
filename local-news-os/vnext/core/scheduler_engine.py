#!/usr/bin/env python3
"""Site-owned retry/self-heal scheduler for LOCAL NEWS OS vNext P15."""
from __future__ import annotations
import argparse, hashlib, json, sqlite3, tempfile, uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from distribution_engine import ensure_distribution_schema, materialize_story_distribution
from editorial_qa import evaluate_story_draft, get_latest_qa_decision
from fact_kernel_engine import materialize_fact_kernel
from instance_model import build_release_manifest, load_instance, validate_pack_bindings
from media_intelligence import ensure_media_schema, get_story_media_selection, resolve_story_media
from newsworthiness_engine import get_latest_newsworthiness, score_fact_kernel
from primary_resolver import resolve_signal
from runtime_store import connect, initialize, register_instance, utc_now
from site_publication import ensure_publication_schema, publish_story
from source_adapters import validate_source_pack
from story_engine import get_story_draft_by_kernel, materialize_story_draft

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "local-news-os" / "vnext" / "runtime" / "scheduler_schema.sql"
STAGES=("VERIFY_SIGNAL","BUILD_KERNEL","SCORE_KERNEL","BUILD_STORY","QA_STORY","PUBLISH_STORY","SELECT_MEDIA","DISTRIBUTE_STORY")
ACTIVE=("PENDING","RETRY")

class SchedulerError(RuntimeError): pass
class LeaseBusy(SchedulerError): pass
class RetryableStageError(SchedulerError): pass

@dataclass(frozen=True)
class SchedulerPolicy:
    batch_size:int=20; lease_seconds:int=120; base_backoff_seconds:int=30; max_backoff_seconds:int=3600; max_attempts:int=5
    def validate(self):
        if not 1<=self.batch_size<=200: raise SchedulerError("batch_size out of range")
        if not 10<=self.lease_seconds<=3600: raise SchedulerError("lease_seconds out of range")
        if not 1<=self.base_backoff_seconds<=self.max_backoff_seconds<=86400: raise SchedulerError("invalid backoff")
        if not 1<=self.max_attempts<=20: raise SchedulerError("max_attempts out of range")
        return self

def _now()->datetime: return datetime.now(timezone.utc)
def _iso(dt:datetime)->str: return dt.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
def _hash(*parts:str,n:int=24)->str: return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:n]
def _json(v:Any)->str: return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def _decode(row:sqlite3.Row|None)->dict[str,Any]|None:
    if row is None:return None
    d=dict(row)
    for k in ("payload_json","summary_json","detail_json","result_json"):
        if k in d:d[k[:-5]]=json.loads(d.pop(k) or "{}")
    return d

def ensure_scheduler_schema(conn): conn.executescript(SCHEMA.read_text(encoding="utf-8")); conn.commit()
def _event(conn,instance_id,aggregate_type,aggregate_id,event_type,engine_version,reason,payload=None):
    conn.execute("INSERT INTO runtime_events(instance_id,aggregate_type,aggregate_id,event_type,reason,payload_json,engine_version,created_at) VALUES(?,?,?,?,?,?,?,?)",
                 (instance_id,aggregate_type,aggregate_id,event_type,reason,_json(payload or {}),engine_version,utc_now()))

def enqueue_job(conn,*,instance_id,stage,aggregate_type,aggregate_id,desired_fingerprint="",payload=None,priority=50,policy=SchedulerPolicy()):
    policy.validate()
    if stage not in STAGES: raise SchedulerError("unknown scheduler stage")
    dedupe=_hash(instance_id,stage,aggregate_type,aggregate_id,desired_fingerprint,n=40); job_id="job_"+dedupe[:24]; now=utc_now()
    conn.execute("""INSERT INTO scheduler_jobs(instance_id,job_id,dedupe_key,stage,aggregate_type,aggregate_id,desired_fingerprint,status,priority,attempts,max_attempts,next_attempt_at,payload_json,created_at,updated_at)
                  VALUES(?,?,?,?,?,?,?,'PENDING',?,0,?,?,?,?,?) ON CONFLICT(instance_id,dedupe_key) DO NOTHING""",
                 (instance_id,job_id,dedupe,stage,aggregate_type,aggregate_id,desired_fingerprint,priority,policy.max_attempts,now,_json(payload or {}),now,now)); conn.commit()
    return _decode(conn.execute("SELECT * FROM scheduler_jobs WHERE instance_id=? AND dedupe_key=?",(instance_id,dedupe)).fetchone())

def _supports_ready(conn,instance_id,signal_id):
    tasks=conn.execute("SELECT task_id,state FROM verification_tasks WHERE instance_id=? AND signal_id=?",(instance_id,signal_id)).fetchall()
    if not tasks or any(r["state"]!="TARGETS_READY" for r in tasks):return False
    for task in tasks:
        verdicts={r["verdict"] for r in conn.execute("SELECT verdict FROM verification_results WHERE instance_id=? AND task_id=?",(instance_id,task["task_id"])).fetchall()}
        if "CONTRADICTS" in verdicts or "SUPPORTS" not in verdicts:return False
    return True

def _current_product_missing(conn,instance_id,story_id,channels_pack):
    ensure_publication_schema(conn); ensure_distribution_schema(conn)
    pub=conn.execute("SELECT current_revision FROM story_publications WHERE instance_id=? AND story_id=?",(instance_id,story_id)).fetchone()
    if pub is None:return False
    rev=int(pub["current_revision"]); enabled=[c for c in channels_pack.get("channels",[]) if c.get("enabled",True) and c.get("mode","disabled")!="disabled"]
    for c in enabled:
        if conn.execute("SELECT 1 FROM channel_products WHERE instance_id=? AND story_id=? AND channel_id=? AND desired_revision=?",(instance_id,story_id,c.get("id"),rev)).fetchone() is None:return True
    return False

def discover_missing_work(conn,*,instance_id,packs,engine_version,policy=SchedulerPolicy()):
    ensure_scheduler_schema(conn); before=conn.total_changes
    for s in conn.execute("SELECT signal_id,fingerprint FROM signals WHERE instance_id=?",(instance_id,)).fetchall():
        sid=s["signal_id"]
        if conn.execute("SELECT 1 FROM verification_tasks WHERE instance_id=? AND signal_id=? LIMIT 1",(instance_id,sid)).fetchone() is None:
            enqueue_job(conn,instance_id=instance_id,stage="VERIFY_SIGNAL",aggregate_type="signal",aggregate_id=sid,desired_fingerprint=s["fingerprint"],priority=90,policy=policy)
        elif conn.execute("SELECT 1 FROM fact_kernels WHERE instance_id=? AND signal_id=?",(instance_id,sid)).fetchone() is None and _supports_ready(conn,instance_id,sid):
            enqueue_job(conn,instance_id=instance_id,stage="BUILD_KERNEL",aggregate_type="signal",aggregate_id=sid,desired_fingerprint=s["fingerprint"],priority=85,policy=policy)
    kernels=conn.execute("SELECT kernel_id,fingerprint FROM fact_kernels WHERE instance_id=?",(instance_id,)).fetchall()
    for k in kernels:
        ev=get_latest_newsworthiness(conn,instance_id=instance_id,kernel_id=k["kernel_id"])
        if ev is None or (ev.get("payload") or {}).get("kernel_fingerprint")!=k["fingerprint"]:
            enqueue_job(conn,instance_id=instance_id,stage="SCORE_KERNEL",aggregate_type="fact_kernel",aggregate_id=k["kernel_id"],desired_fingerprint=k["fingerprint"],priority=75,policy=policy); continue
        if (ev.get("payload") or {}).get("route") in {"BUILD","BUILD_PRIORITY"} and get_story_draft_by_kernel(conn,instance_id=instance_id,kernel_id=k["kernel_id"]) is None:
            enqueue_job(conn,instance_id=instance_id,stage="BUILD_STORY",aggregate_type="fact_kernel",aggregate_id=k["kernel_id"],desired_fingerprint=(ev.get("payload") or {}).get("decision_fingerprint",k["fingerprint"]),priority=70,policy=policy)
    for st in conn.execute("SELECT story_id,state FROM stories WHERE instance_id=?",(instance_id,)).fetchall():
        sid,state=st["story_id"],st["state"]
        if state=="STORY_DRAFTED":
            try:draft=get_story_draft_by_story(conn,instance_id,sid)
            except Exception:draft=None
            qa=get_latest_qa_decision(conn,instance_id=instance_id,story_id=sid)
            if draft and (qa is None or qa.get("draft_fingerprint")!=draft.get("fingerprint")):
                enqueue_job(conn,instance_id=instance_id,stage="QA_STORY",aggregate_type="story",aggregate_id=sid,desired_fingerprint=draft["fingerprint"],priority=65,policy=policy)
        elif state=="QA_PASSED" and conn.execute("SELECT 1 FROM story_publications WHERE instance_id=? AND story_id=?",(instance_id,sid)).fetchone() is None:
            enqueue_job(conn,instance_id=instance_id,stage="PUBLISH_STORY",aggregate_type="story",aggregate_id=sid,priority=60,policy=policy)
        elif state=="PUBLISHED":
            ensure_media_schema(conn)
            if get_story_media_selection(conn,instance_id=instance_id,story_id=sid,usage_scope="SITE_HERO") is None:
                enqueue_job(conn,instance_id=instance_id,stage="SELECT_MEDIA",aggregate_type="story",aggregate_id=sid,priority=55,policy=policy)
            if _current_product_missing(conn,instance_id,sid,packs["channels"]):
                enqueue_job(conn,instance_id=instance_id,stage="DISTRIBUTE_STORY",aggregate_type="story",aggregate_id=sid,priority=50,policy=policy)
    return conn.total_changes-before

def get_story_draft_by_story(conn,instance_id,story_id):
    row=conn.execute("SELECT * FROM story_drafts WHERE instance_id=? AND story_id=?",(instance_id,story_id)).fetchone()
    if row is None:return None
    d=dict(row); d["fingerprint"]=row["fingerprint"]; return d

def acquire_lease(conn,*,instance_id,owner_id,policy=SchedulerPolicy()):
    ensure_scheduler_schema(conn); now=_now(); until=now+timedelta(seconds=policy.lease_seconds); token=uuid.uuid4().hex
    try:
        conn.execute("BEGIN IMMEDIATE"); row=conn.execute("SELECT * FROM scheduler_leases WHERE instance_id=?",(instance_id,)).fetchone()
        if row and str(row["lease_until"])>_iso(now): raise LeaseBusy("scheduler lease is active")
        generation=(int(row["generation"])+1) if row else 1
        conn.execute("""INSERT INTO scheduler_leases(instance_id,lease_token,owner_id,generation,acquired_at,heartbeat_at,lease_until) VALUES(?,?,?,?,?,?,?)
                      ON CONFLICT(instance_id) DO UPDATE SET lease_token=excluded.lease_token,owner_id=excluded.owner_id,generation=excluded.generation,acquired_at=excluded.acquired_at,heartbeat_at=excluded.heartbeat_at,lease_until=excluded.lease_until""",
                     (instance_id,token,owner_id,generation,_iso(now),_iso(now),_iso(until))); conn.commit(); return token
    except Exception: conn.rollback(); raise

def release_lease(conn,*,instance_id,lease_token):
    conn.execute("DELETE FROM scheduler_leases WHERE instance_id=? AND lease_token=?",(instance_id,lease_token)); conn.commit()

def _circuit_open(conn,instance_id,stage,now):
    row=conn.execute("SELECT cursor_value FROM scheduler_cursors WHERE instance_id=? AND stage=?",(instance_id,"circuit:"+stage)).fetchone()
    return bool(row and row["cursor_value"]>now)
def _open_circuit(conn,instance_id,stage,seconds):
    until=_iso(_now()+timedelta(seconds=seconds)); now=utc_now()
    conn.execute("INSERT INTO scheduler_cursors(instance_id,stage,cursor_value,updated_at) VALUES(?,?,?,?) ON CONFLICT(instance_id,stage) DO UPDATE SET cursor_value=excluded.cursor_value,updated_at=excluded.updated_at",(instance_id,"circuit:"+stage,until,now))

def claim_due_jobs(conn,*,instance_id,tick_id,lease_token,limit):
    now=utc_now(); rows=conn.execute("SELECT * FROM scheduler_jobs WHERE instance_id=? AND status IN ('PENDING','RETRY') AND next_attempt_at<=? ORDER BY priority DESC,created_at,job_id LIMIT ?",(instance_id,now,limit*3)).fetchall(); out=[]
    for row in rows:
        if len(out)>=limit:break
        if _circuit_open(conn,instance_id,row["stage"],now):continue
        cur=conn.execute("UPDATE scheduler_jobs SET status='RUNNING',lease_token=?,tick_id=?,started_at=COALESCE(started_at,?),updated_at=? WHERE instance_id=? AND job_id=? AND status IN ('PENDING','RETRY')",(lease_token,tick_id,now,now,instance_id,row["job_id"]))
        if cur.rowcount: out.append(_decode(conn.execute("SELECT * FROM scheduler_jobs WHERE instance_id=? AND job_id=?",(instance_id,row["job_id"])).fetchone()))
    conn.commit(); return out

def _finish(conn,*,job,tick_id,outcome,error,result,policy,engine_version):
    now=_now(); attempts=int(job["attempts"])+1; final=outcome
    if outcome=="RETRY" and attempts>=int(job["max_attempts"]): final="NEEDS_ATTENTION"
    delay=min(policy.max_backoff_seconds,policy.base_backoff_seconds*(2**max(0,attempts-1))); next_at=_iso(now+timedelta(seconds=delay))
    conn.execute("INSERT INTO scheduler_attempts(instance_id,job_id,attempt_number,tick_id,stage,outcome,error_text,result_json,started_at,finished_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                 (job["instance_id"],job["job_id"],attempts,tick_id,job["stage"],final,error,_json(result),job.get("started_at") or _iso(now),_iso(now)))
    conn.execute("UPDATE scheduler_jobs SET status=?,attempts=?,next_attempt_at=?,lease_token=NULL,tick_id=NULL,last_error=?,finished_at=CASE WHEN ? IN ('DONE','NEEDS_ATTENTION','CANCELLED') THEN ? ELSE NULL END,updated_at=? WHERE instance_id=? AND job_id=?",
                 (final,attempts,next_at,error,final,_iso(now),_iso(now),job["instance_id"],job["job_id"]))
    if final=="NEEDS_ATTENTION": _open_circuit(conn,job["instance_id"],job["stage"],policy.max_backoff_seconds)
    _event(conn,job["instance_id"],"scheduler_job",job["job_id"],"SCHEDULER_JOB_"+final,engine_version,error or "scheduler stage completed",{"stage":job["stage"],"aggregate_id":job["aggregate_id"],"attempt":attempts})
    conn.commit(); return final

def record_health(conn,*,instance_id,component,status,detail):
    if status not in {"OK","DEGRADED","BLOCKED"}:raise SchedulerError("invalid health status")
    conn.execute("INSERT INTO scheduler_health(instance_id,component,status,observed_at,detail_json) VALUES(?,?,?,?,?)",(instance_id,component,status,utc_now(),_json(detail))); conn.commit()

def scheduler_snapshot(conn,*,instance_id):
    ensure_scheduler_schema(conn)
    counts={r["status"]:r["n"] for r in conn.execute("SELECT status,COUNT(*) n FROM scheduler_jobs WHERE instance_id=? GROUP BY status",(instance_id,)).fetchall()}
    stages={r["stage"]:r["n"] for r in conn.execute("SELECT stage,COUNT(*) n FROM scheduler_jobs WHERE instance_id=? AND status IN ('PENDING','RETRY','RUNNING','NEEDS_ATTENTION') GROUP BY stage",(instance_id,)).fetchall()}
    health=[_decode(r) for r in conn.execute("SELECT * FROM scheduler_health WHERE instance_id=? ORDER BY health_id DESC LIMIT 20",(instance_id,)).fetchall()]
    jobs=[_decode(r) for r in conn.execute("SELECT * FROM scheduler_jobs WHERE instance_id=? ORDER BY updated_at DESC LIMIT 100",(instance_id,)).fetchall()]
    return {"instance_id":instance_id,"job_counts":counts,"active_by_stage":stages,"health":health,"jobs":jobs}

def load_runtime_packs(instance_id):
    cfg=load_instance(instance_id); return cfg,validate_pack_bindings(cfg)

def build_default_stage_handlers(*,packs,source_definitions,dimension_provider=None):
    def verify(conn,job,ctx): return {"tasks":len(resolve_signal(conn,instance_id=ctx["instance_id"],signal_id=job["aggregate_id"],source_definitions=source_definitions,engine_version=ctx["engine_version"]))}
    def kernel(conn,job,ctx): return {"kernel":materialize_fact_kernel(conn,instance_id=ctx["instance_id"],signal_id=job["aggregate_id"],engine_version=ctx["engine_version"])[0]["kernel_id"]}
    def score(conn,job,ctx):
        if dimension_provider is None: raise RetryableStageError("newsworthiness dimension provider is not configured in site runtime")
        signals=dimension_provider(conn,ctx["instance_id"],job["aggregate_id"])
        ev,_=score_fact_kernel(conn,instance_id=ctx["instance_id"],kernel_id=job["aggregate_id"],dimension_signals=signals,editorial_pack=packs["editorial"],engine_version=ctx["engine_version"]); return {"route":ev["payload"]["route"]}
    def story(conn,job,ctx): return {"story":materialize_story_draft(conn,instance_id=ctx["instance_id"],kernel_id=job["aggregate_id"],editorial_pack=packs["editorial"],engine_version=ctx["engine_version"])[0]["story_id"]}
    def qa(conn,job,ctx): return {"outcome":evaluate_story_draft(conn,instance_id=ctx["instance_id"],story_id=job["aggregate_id"],editorial_pack=packs["editorial"],engine_version=ctx["engine_version"])[0]["outcome"]}
    def publish(conn,job,ctx): return {"path":publish_story(conn,instance_id=ctx["instance_id"],story_id=job["aggregate_id"],publication_pack=packs["publication"],engine_version=ctx["engine_version"])[0]["canonical_path"]}
    def media(conn,job,ctx):
        result,_=resolve_story_media(conn,instance_id=ctx["instance_id"],story_id=job["aggregate_id"],usage_scope="SITE_HERO",media_policy=packs["photos"],engine_version=ctx["engine_version"]); return {"selection":result["selection_kind"]}
    def distribute(conn,job,ctx): return {"products":len(materialize_story_distribution(conn,instance_id=ctx["instance_id"],story_id=job["aggregate_id"],channels_pack=packs["channels"],engine_version=ctx["engine_version"]))}
    return dict(zip(STAGES,(verify,kernel,score,story,qa,publish,media,distribute)))

def run_tick(conn,*,instance_id,engine_version,packs,handlers,owner_id="site-runtime",policy=SchedulerPolicy()):
    policy.validate(); ensure_scheduler_schema(conn); tick_id="tick_"+uuid.uuid4().hex[:20]
    try: lease=acquire_lease(conn,instance_id=instance_id,owner_id=owner_id,policy=policy)
    except LeaseBusy:
        record_health(conn,instance_id=instance_id,component="scheduler",status="DEGRADED",detail={"reason":"lease_busy"}); return {"tick_id":tick_id,"status":"LEASE_BUSY"}
    started=utc_now(); conn.execute("INSERT INTO scheduler_ticks(instance_id,tick_id,owner_id,lease_token,status,started_at) VALUES(?,?,?,?, 'RUNNING',?)",(instance_id,tick_id,owner_id,lease,started)); conn.commit()
    stats={"discovered":0,"claimed":0,"done":0,"retry":0,"needs_attention":0}
    try:
        stats["discovered"]=discover_missing_work(conn,instance_id=instance_id,packs=packs,engine_version=engine_version,policy=policy)
        jobs=claim_due_jobs(conn,instance_id=instance_id,tick_id=tick_id,lease_token=lease,limit=policy.batch_size); stats["claimed"]=len(jobs)
        ctx={"instance_id":instance_id,"engine_version":engine_version,"tick_id":tick_id}
        for job in jobs:
            try:
                handler=handlers.get(job["stage"])
                if handler is None: raise RetryableStageError("stage handler is not configured")
                result=handler(conn,job,ctx) or {}; final=_finish(conn,job=job,tick_id=tick_id,outcome="DONE",error="",result=result,policy=policy,engine_version=engine_version)
            except Exception as exc:
                final=_finish(conn,job=job,tick_id=tick_id,outcome="RETRY",error=f"{type(exc).__name__}: {exc}"[:1000],result={},policy=policy,engine_version=engine_version)
            stats["done" if final=="DONE" else "needs_attention" if final=="NEEDS_ATTENTION" else "retry"]+=1
        status="PASS" if not stats["retry"] and not stats["needs_attention"] else "PARTIAL"
        record_health(conn,instance_id=instance_id,component="scheduler",status="OK" if status=="PASS" else "DEGRADED",detail=stats)
        conn.execute("UPDATE scheduler_ticks SET status=?,discovered_jobs=?,claimed_jobs=?,completed_jobs=?,retry_jobs=?,needs_attention_jobs=?,finished_at=?,summary_json=? WHERE instance_id=? AND tick_id=?",
                     (status,stats["discovered"],stats["claimed"],stats["done"],stats["retry"],stats["needs_attention"],utc_now(),_json(stats),instance_id,tick_id)); conn.commit(); return {"tick_id":tick_id,"status":status,**stats}
    finally: release_lease(conn,instance_id=instance_id,lease_token=lease)

def _manifest(instance_id,domain): return {"instance_id":instance_id,"publication":{"canonical_domain":domain},"config_sha256":hashlib.sha256(instance_id.encode()).hexdigest(),"runtime":{"owner":"site_application","repository_runtime_state_enabled":False}}
def self_test():
    with tempfile.TemporaryDirectory() as td:
        conn=connect(Path(td)/"s.db"); initialize(conn); ensure_scheduler_schema(conn)
        for iid,dom in (("alpha-local","alpha.invalid"),("beta-local","beta.invalid")):register_instance(conn,_manifest(iid,dom),engine_version="test")
        a=enqueue_job(conn,instance_id="alpha-local",stage="VERIFY_SIGNAL",aggregate_type="signal",aggregate_id="s1",desired_fingerprint="fp",policy=SchedulerPolicy(max_attempts=3))
        b=enqueue_job(conn,instance_id="alpha-local",stage="VERIFY_SIGNAL",aggregate_type="signal",aggregate_id="s1",desired_fingerprint="fp",policy=SchedulerPolicy(max_attempts=3)); assert a["job_id"]==b["job_id"]
        enqueue_job(conn,instance_id="beta-local",stage="VERIFY_SIGNAL",aggregate_type="signal",aggregate_id="s1",desired_fingerprint="fp")
        assert conn.execute("SELECT COUNT(*) n FROM scheduler_jobs WHERE instance_id='alpha-local'").fetchone()["n"]==1
        assert conn.execute("SELECT COUNT(*) n FROM scheduler_jobs WHERE instance_id='beta-local'").fetchone()["n"]==1
        token=acquire_lease(conn,instance_id="alpha-local",owner_id="one")
        try: acquire_lease(conn,instance_id="alpha-local",owner_id="two"); raise AssertionError("concurrent lease accepted")
        except LeaseBusy: pass
        release_lease(conn,instance_id="alpha-local",lease_token=token)
        handlers={"VERIFY_SIGNAL":lambda c,j,x:{"ok":True}}
        first=run_tick(conn,instance_id="alpha-local",engine_version="test",packs={"channels":{"channels":[]}},handlers=handlers,policy=SchedulerPolicy(max_attempts=3)); assert first["done"]==1
        second=run_tick(conn,instance_id="alpha-local",engine_version="test",packs={"channels":{"channels":[]}},handlers=handlers,policy=SchedulerPolicy(max_attempts=3)); assert second["claimed"]==0
        enqueue_job(conn,instance_id="alpha-local",stage="QA_STORY",aggregate_type="story",aggregate_id="bad",desired_fingerprint="x",policy=SchedulerPolicy(max_attempts=2,base_backoff_seconds=1,max_backoff_seconds=1))
        fail={"QA_STORY":lambda c,j,x:(_ for _ in ()).throw(RuntimeError("fixture"))}
        run_tick(conn,instance_id="alpha-local",engine_version="test",packs={"channels":{"channels":[]}},handlers=fail,policy=SchedulerPolicy(max_attempts=2,base_backoff_seconds=1,max_backoff_seconds=1))
        conn.execute("UPDATE scheduler_jobs SET next_attempt_at='2000-01-01T00:00:00Z' WHERE instance_id='alpha-local' AND aggregate_id='bad'"); conn.execute("DELETE FROM scheduler_cursors WHERE instance_id='alpha-local' AND stage='circuit:QA_STORY'"); conn.commit()
        run_tick(conn,instance_id="alpha-local",engine_version="test",packs={"channels":{"channels":[]}},handlers=fail,policy=SchedulerPolicy(max_attempts=2,base_backoff_seconds=1,max_backoff_seconds=1))
        assert conn.execute("SELECT status FROM scheduler_jobs WHERE instance_id='alpha-local' AND aggregate_id='bad'").fetchone()["status"]=="NEEDS_ATTENTION"
        assert scheduler_snapshot(conn,instance_id="beta-local")["job_counts"].get("PENDING")==1
        print("VNEXT_P15_SCHEDULER_SELF_TEST_PASS")
def main():
    p=argparse.ArgumentParser(); p.add_argument("--self-test",action="store_true"); p.add_argument("--db"); p.add_argument("--instance"); p.add_argument("--engine-version",default="vnext-dev"); args=p.parse_args()
    if args.self_test:self_test();return 0
    if not args.db or not args.instance:p.error("--db and --instance required")
    cfg,packs=load_runtime_packs(args.instance); conn=connect(args.db); initialize(conn); register_instance(conn,build_release_manifest(cfg),engine_version=args.engine_version); sources=validate_source_pack(packs["sources"],args.instance); handlers=build_default_stage_handlers(packs=packs,source_definitions=sources)
    print(json.dumps(run_tick(conn,instance_id=args.instance,engine_version=args.engine_version,packs=packs,handlers=handlers),ensure_ascii=False,indent=2)); return 0
if __name__=="__main__": raise SystemExit(main())
