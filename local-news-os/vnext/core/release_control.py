#!/usr/bin/env python3
"""Versioned development/production release separation for LOCAL NEWS OS vNext P16."""
from __future__ import annotations
import argparse, hashlib, json, re, sqlite3, tempfile
from pathlib import Path
from typing import Any
from runtime_store import connect, initialize, register_instance, utc_now

ROOT=Path(__file__).resolve().parents[3]
SCHEMA=ROOT/'local-news-os'/'vnext'/'runtime'/'release_schema.sql'
REQUIRED_GATES=('vnext_validation','scheduler_validation','instance_pack_compatibility','db_migration_compatibility')
VERSION_RE=re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+-]{0,79}$')
SHA_RE=re.compile(r'^[0-9a-f]{40,64}$')
HEX_RE=re.compile(r'^[0-9a-f]{32,128}$')

class ReleaseControlError(RuntimeError):pass

def _clean(v):return ' '.join(str(v or '').split())
def _stable(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def _id(*p):return 'rel_'+hashlib.sha256('\n'.join(p).encode()).hexdigest()[:24]
def ensure_release_schema(conn):conn.executescript(SCHEMA.read_text(encoding='utf-8'));conn.commit()
def _decode(row):
    if row is None:return None
    d=dict(row)
    if 'evidence_json' in d:d['evidence']=json.loads(d.pop('evidence_json') or '{}')
    return d

def validate_release_manifest(manifest:dict[str,Any])->dict[str,Any]:
    if not isinstance(manifest,dict):raise ReleaseControlError('release manifest must be an object')
    version=_clean(manifest.get('engine_version')); code=_clean(manifest.get('code_sha')).lower(); schema=_clean(manifest.get('schema_fingerprint')).lower(); migration=_clean(manifest.get('migration_fingerprint')).lower()
    if not VERSION_RE.fullmatch(version):raise ReleaseControlError('invalid engine_version')
    if not SHA_RE.fullmatch(code):raise ReleaseControlError('code_sha must be a git hash')
    if not HEX_RE.fullmatch(schema) or not HEX_RE.fullmatch(migration):raise ReleaseControlError('schema and migration fingerprints must be hex')
    artifact=_clean(manifest.get('artifact_fingerprint')).lower()
    canonical={'engine_version':version,'code_sha':code,'schema_fingerprint':schema,'migration_fingerprint':migration}
    expected=_stable(canonical)
    if artifact and artifact!=expected:raise ReleaseControlError('artifact_fingerprint does not match immutable release identity')
    canonical['artifact_fingerprint']=expected
    return canonical

def validate_compatibility_evidence(evidence:dict[str,Any])->dict[str,Any]:
    if not isinstance(evidence,dict):raise ReleaseControlError('compatibility evidence must be an object')
    if set(evidence)!=set(REQUIRED_GATES):raise ReleaseControlError('compatibility evidence must define exactly required gates')
    out={}
    for gate in REQUIRED_GATES:
        item=evidence[gate]
        if not isinstance(item,dict) or item.get('pass') is not True:raise ReleaseControlError(f'candidate gate not PASS: {gate}')
        ref=_clean(item.get('evidence_ref'))
        if not ref or any(x in ref.lower() for x in ('token=','password=','secret=')):raise ReleaseControlError(f'invalid evidence_ref: {gate}')
        out[gate]={'pass':True,'evidence_ref':ref}
    return out

def _history(conn,instance_id,action,candidate_id,from_version,to_version,artifact,evidence,reason):
    conn.execute('INSERT INTO release_history(instance_id,action,candidate_id,from_engine_version,to_engine_version,artifact_fingerprint,evidence_json,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                 (instance_id,action,candidate_id,from_version,to_version,artifact,json.dumps(evidence,ensure_ascii=False,sort_keys=True),reason,utc_now()))

def initialize_release_state(conn,*,instance_id,current_engine_version):
    ensure_release_schema(conn); now=utc_now()
    conn.execute("INSERT INTO release_state(instance_id,current_engine_version,updated_at) VALUES(?,?,?) ON CONFLICT(instance_id) DO NOTHING",(instance_id,current_engine_version,now));conn.commit()
    return get_release_state(conn,instance_id=instance_id)

def register_candidate(conn,*,instance_id,manifest,engine_version):
    ensure_release_schema(conn); m=validate_release_manifest(manifest); cid=_id(instance_id,m['engine_version'],m['artifact_fingerprint']); now=utc_now()
    existing=conn.execute('SELECT * FROM release_candidates WHERE instance_id=? AND candidate_id=?',(instance_id,cid)).fetchone()
    if existing:return _decode(existing),False
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("INSERT INTO release_candidates(instance_id,candidate_id,engine_version,code_sha,artifact_fingerprint,schema_fingerprint,migration_fingerprint,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'CANDIDATE',?,?)",
                     (instance_id,cid,m['engine_version'],m['code_sha'],m['artifact_fingerprint'],m['schema_fingerprint'],m['migration_fingerprint'],now,now))
        _history(conn,instance_id,'REGISTER',cid,None,m['engine_version'],m['artifact_fingerprint'],{},'candidate registered without affecting validated runtime')
        conn.commit()
    except Exception:conn.rollback();raise
    return get_candidate(conn,instance_id=instance_id,candidate_id=cid),True

def get_candidate(conn,*,instance_id,candidate_id):
    row=conn.execute('SELECT * FROM release_candidates WHERE instance_id=? AND candidate_id=?',(instance_id,candidate_id)).fetchone()
    if row is None:raise ReleaseControlError('release candidate not found')
    return _decode(row)
def get_release_state(conn,*,instance_id):
    row=conn.execute('SELECT * FROM release_state WHERE instance_id=?',(instance_id,)).fetchone()
    if row is None:raise ReleaseControlError('release state not initialized')
    return dict(row)

def validate_candidate(conn,*,instance_id,candidate_id,evidence,engine_version):
    gate=validate_compatibility_evidence(evidence); c=get_candidate(conn,instance_id=instance_id,candidate_id=candidate_id)
    if c['status']=='REJECTED':raise ReleaseControlError('rejected candidate cannot be validated')
    if c['status'] in {'VALIDATED','PROMOTED'}:
        if c['evidence']==gate:return c,False
        raise ReleaseControlError('candidate already validated with different evidence')
    now=utc_now()
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("UPDATE release_candidates SET status='VALIDATED',evidence_json=?,updated_at=? WHERE instance_id=? AND candidate_id=? AND status='CANDIDATE'",(json.dumps(gate,sort_keys=True),now,instance_id,candidate_id))
        _history(conn,instance_id,'VALIDATE',candidate_id,None,c['engine_version'],c['artifact_fingerprint'],gate,'all candidate compatibility gates passed')
        conn.commit()
    except Exception:conn.rollback();raise
    return get_candidate(conn,instance_id=instance_id,candidate_id=candidate_id),True

def reject_candidate(conn,*,instance_id,candidate_id,reason):
    c=get_candidate(conn,instance_id=instance_id,candidate_id=candidate_id); reason=_clean(reason)
    if not reason:raise ReleaseControlError('rejection reason required')
    if c['status']=='PROMOTED':raise ReleaseControlError('promoted runtime cannot be rejected; use rollback')
    state=get_release_state(conn,instance_id=instance_id); before=state['current_engine_version']; now=utc_now()
    conn.execute("UPDATE release_candidates SET status='REJECTED',rejection_reason=?,updated_at=? WHERE instance_id=? AND candidate_id=?",(reason,now,instance_id,candidate_id));_history(conn,instance_id,'REJECT',candidate_id,before,before,c['artifact_fingerprint'],{},reason);conn.commit()
    assert get_release_state(conn,instance_id=instance_id)['current_engine_version']==before
    return get_candidate(conn,instance_id=instance_id,candidate_id=candidate_id)

def promote_candidate(conn,*,instance_id,candidate_id,engine_version):
    c=get_candidate(conn,instance_id=instance_id,candidate_id=candidate_id)
    if c['status']!='VALIDATED':raise ReleaseControlError('only a VALIDATED candidate may be promoted')
    validate_compatibility_evidence(c['evidence']); state=get_release_state(conn,instance_id=instance_id); now=utc_now()
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("UPDATE release_state SET previous_candidate_id=current_candidate_id,previous_engine_version=current_engine_version,previous_artifact_fingerprint=current_artifact_fingerprint,current_candidate_id=?,current_engine_version=?,current_artifact_fingerprint=?,generation=generation+1,updated_at=? WHERE instance_id=?",
                     (candidate_id,c['engine_version'],c['artifact_fingerprint'],now,instance_id))
        conn.execute("UPDATE publication_instances SET engine_version=?,updated_at=? WHERE instance_id=?",(c['engine_version'],now,instance_id))
        conn.execute("UPDATE release_candidates SET status='PROMOTED',updated_at=? WHERE instance_id=? AND candidate_id=?",(now,instance_id,candidate_id))
        _history(conn,instance_id,'PROMOTE',candidate_id,state['current_engine_version'],c['engine_version'],c['artifact_fingerprint'],c['evidence'],'atomic site-runtime version promotion')
        conn.commit()
    except Exception:conn.rollback();raise
    return get_release_state(conn,instance_id=instance_id)

def rollback(conn,*,instance_id,reason,engine_version):
    state=get_release_state(conn,instance_id=instance_id); reason=_clean(reason)
    if not reason:raise ReleaseControlError('rollback reason required')
    if not state['previous_engine_version']:raise ReleaseControlError('no rollback version available')
    now=utc_now(); old_current=state['current_engine_version']; old_current_id=state['current_candidate_id']; old_current_fp=state['current_artifact_fingerprint']
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("UPDATE release_state SET current_candidate_id=previous_candidate_id,current_engine_version=previous_engine_version,current_artifact_fingerprint=previous_artifact_fingerprint,previous_candidate_id=?,previous_engine_version=?,previous_artifact_fingerprint=?,generation=generation+1,updated_at=? WHERE instance_id=?",
                     (old_current_id,old_current,old_current_fp,now,instance_id))
        current=conn.execute('SELECT current_engine_version,current_artifact_fingerprint,current_candidate_id FROM release_state WHERE instance_id=?',(instance_id,)).fetchone()
        conn.execute("UPDATE publication_instances SET engine_version=?,updated_at=? WHERE instance_id=?",(current['current_engine_version'],now,instance_id))
        _history(conn,instance_id,'ROLLBACK',current['current_candidate_id'],old_current,current['current_engine_version'],current['current_artifact_fingerprint'],{},reason)
        conn.commit()
    except Exception:conn.rollback();raise
    return get_release_state(conn,instance_id=instance_id)

def release_snapshot(conn,*,instance_id):
    ensure_release_schema(conn); state=get_release_state(conn,instance_id=instance_id)
    candidates=[_decode(r) for r in conn.execute('SELECT * FROM release_candidates WHERE instance_id=? ORDER BY updated_at DESC LIMIT 50',(instance_id,)).fetchall()]
    history=[_decode(r) for r in conn.execute('SELECT * FROM release_history WHERE instance_id=? ORDER BY history_id DESC LIMIT 50',(instance_id,)).fetchall()]
    return {'instance_id':instance_id,'state':state,'candidates':candidates,'history':history}

def _manifest(instance_id,domain,version):return {'instance_id':instance_id,'publication':{'canonical_domain':domain},'config_sha256':hashlib.sha256(instance_id.encode()).hexdigest(),'runtime':{'owner':'site_application','repository_runtime_state_enabled':False}}
def _candidate(version,seed):
    base={'engine_version':version,'code_sha':hashlib.sha1(seed.encode()).hexdigest(),'schema_fingerprint':hashlib.sha256(('schema'+seed).encode()).hexdigest(),'migration_fingerprint':hashlib.sha256(('migration'+seed).encode()).hexdigest()};base['artifact_fingerprint']=_stable(base);return base
def _evidence(prefix):return {k:{'pass':True,'evidence_ref':f'{prefix}:{k}:PASS'} for k in REQUIRED_GATES}
def self_test():
    with tempfile.TemporaryDirectory() as td:
        conn=connect(Path(td)/'r.db');initialize(conn);ensure_release_schema(conn)
        for iid,dom in (('alpha-local','alpha.invalid'),('beta-local','beta.invalid')):
            register_instance(conn,_manifest(iid,dom,'1.0.0'),engine_version='1.0.0');initialize_release_state(conn,instance_id=iid,current_engine_version='1.0.0')
        manifest=_candidate('1.1.0','same-artifact')
        a,_=register_candidate(conn,instance_id='alpha-local',manifest=manifest,engine_version='test');b,_=register_candidate(conn,instance_id='beta-local',manifest=manifest,engine_version='test');assert a['artifact_fingerprint']==b['artifact_fingerprint']
        validate_candidate(conn,instance_id='alpha-local',candidate_id=a['candidate_id'],evidence=_evidence('ci'),engine_version='test')
        before=get_release_state(conn,instance_id='beta-local')['current_engine_version'];reject_candidate(conn,instance_id='beta-local',candidate_id=b['candidate_id'],reason='fixture rejection');assert get_release_state(conn,instance_id='beta-local')['current_engine_version']==before
        promoted=promote_candidate(conn,instance_id='alpha-local',candidate_id=a['candidate_id'],engine_version='test');assert promoted['current_engine_version']=='1.1.0' and promoted['previous_engine_version']=='1.0.0'
        assert conn.execute("SELECT engine_version FROM publication_instances WHERE instance_id='alpha-local'").fetchone()['engine_version']=='1.1.0'
        rolled=rollback(conn,instance_id='alpha-local',reason='fixture rollback',engine_version='test');assert rolled['current_engine_version']=='1.0.0' and rolled['previous_engine_version']=='1.1.0'
        assert get_release_state(conn,instance_id='beta-local')['current_engine_version']=='1.0.0'
        try:validate_compatibility_evidence({});raise AssertionError('missing gates accepted')
        except ReleaseControlError:pass
        print('VNEXT_P16_RELEASE_CONTROL_SELF_TEST_PASS')
def main():
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');args=p.parse_args()
    if args.self_test:self_test();return 0
    p.error('release_control is a site-runtime library; use --self-test for validation')
if __name__=='__main__':raise SystemExit(main())
