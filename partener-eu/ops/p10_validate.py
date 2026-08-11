#!/usr/bin/env python3
import argparse, datetime as dt, hashlib, json, os, pathlib, sys, tempfile, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OPS = ROOT / "ops"
VALIDATION = ROOT / "validation"
STATE = VALIDATION / "source_state.json"
LATEST = VALIDATION / "latest.json"
HISTORY = VALIDATION / "history"
CHECKPOINT = VALIDATION / "source_state.checkpoint.json"


def nowz(): return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')
def sha(b): return hashlib.sha256(b).hexdigest()
def load_json(p, default=None):
    try: return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
    except Exception: return default

def atomic_json(path, obj):
    path = pathlib.Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name+'.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def recover_state():
    current = load_json(STATE)
    if isinstance(current, dict) and current.get('sources') is not None: return current, False
    cp = load_json(CHECKPOINT)
    if isinstance(cp, dict) and cp.get('sources') is not None:
        atomic_json(STATE, cp); return cp, True
    return {'schema_version':1,'sources':{},'last_run':None}, False

def static_frontend_checks():
    files = {p.name:p for p in (ROOT/'web').glob('*') if p.is_file()}
    required = ['index.html','app.js','data.js','styles.css']
    checks=[]
    for name in required: checks.append({'name':f'file:{name}','pass':name in files and files[name].stat().st_size>100})
    text = ''.join(p.read_text(encoding='utf-8', errors='ignore') for p in files.values())
    for marker in ['Funding Explorer','What Changed','Ask PARTENER.EU','Consultant mode','Pot aplica?','provenien']:
        checks.append({'name':f'ui:{marker}','pass':marker.lower() in text.lower()})
    return checks

def fetch_source(src, timeout=30):
    req=urllib.request.Request(src['url'], headers={'User-Agent':'PARTENER.EU-CIVORA-P10/1.0 (+production-validation)'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body=r.read(4_000_000); code=getattr(r,'status',200); final=r.geturl(); headers=dict(r.headers.items())
        txt=body.decode('utf-8','ignore').lower()
        markers=[m for m in src.get('markers_any',[]) if m.lower() in txt]
        return {'ok':200<=code<400,'http_status':code,'final_url':final,'bytes':len(body),'sha256':sha(body),'markers_found':markers,'etag':headers.get('ETag'),'last_modified':headers.get('Last-Modified'),'error':None}
    except Exception as e:
        return {'ok':False,'http_status':None,'final_url':None,'bytes':0,'sha256':None,'markers_found':[],'etag':None,'last_modified':None,'error':f'{type(e).__name__}: {e}'}

def run(live=True):
    started=nowz(); state,recovered=recover_state(); registry=load_json(OPS/'sources.json', {'sources':[]})
    frontend=static_frontend_checks(); results=[]; critical_fail=False
    for src in registry['sources']:
        prev=state['sources'].get(src['id'],{})
        if live: obs=fetch_source(src)
        else: obs={'ok':True,'http_status':0,'final_url':src['url'],'bytes':0,'sha256':prev.get('sha256') or 'OFFLINE_SMOKE','markers_found':['OFFLINE_SMOKE'],'etag':None,'last_modified':None,'error':None}
        failures=0 if obs['ok'] else int(prev.get('consecutive_failures',0))+1
        change=bool(obs.get('sha256') and prev.get('sha256') and obs['sha256']!=prev['sha256'])
        markers_ok=bool(obs.get('markers_found')) if src.get('markers_any') else True
        if obs['ok'] and markers_ok: health='PASS'
        elif obs['ok']: health='DEGRADED'
        elif failures<3: health='DEGRADED'
        else: health='FAIL'
        if health=='FAIL' and src.get('criticality') in ('CRITICAL','HIGH'): critical_fail=True
        result={**src,'observed_at':started,**obs,'markers_ok':markers_ok,'change_detected':change,'resolution_task_required':change,'consecutive_failures':failures,'health':health}
        results.append(result)
        state['sources'][src['id']]={'sha256':obs.get('sha256') or prev.get('sha256'),'last_success':started if obs['ok'] else prev.get('last_success'),'last_observed':started,'consecutive_failures':failures,'health':health,'final_url':obs.get('final_url') or prev.get('final_url')}
    state['last_run']=started; state['schema_version']=1
    report={'checkpoint':'PARTENER-EU-CIVORA-P10-0017','run_started':started,'live':live,'state_recovered_from_checkpoint':recovered,'frontend_checks':frontend,'sources':results,'summary':{'frontend_pass':sum(x['pass'] for x in frontend),'frontend_total':len(frontend),'source_pass':sum(x['health']=='PASS' for x in results),'source_degraded':sum(x['health']=='DEGRADED' for x in results),'source_fail':sum(x['health']=='FAIL' for x in results),'change_detected':sum(x['change_detected'] for x in results),'critical_fail':critical_fail},'civora_v1':'NOT_CLOSED','production_day_count_rule':'>=30 distinct UTC dates with qualifying runs before closure'}
    atomic_json(CHECKPOINT, state); atomic_json(STATE, state); atomic_json(LATEST, report)
    HISTORY.mkdir(parents=True,exist_ok=True); stamp=started.replace(':','').replace('-',''); atomic_json(HISTORY/(stamp+'.json'), report)
    frontend_fail=not all(x['pass'] for x in frontend)
    return report, 2 if (critical_fail or frontend_fail) else 0

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--offline-smoke',action='store_true'); args=ap.parse_args()
    report,code=run(live=not args.offline_smoke); print(json.dumps(report['summary'],ensure_ascii=False,indent=2)); sys.exit(code)
