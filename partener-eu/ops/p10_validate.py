#!/usr/bin/env python3
import argparse, datetime as dt, hashlib, html, json, os, pathlib, re, sys, tempfile, time, urllib.request

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
    return {'schema_version':2,'sources':{},'last_run':None}, False

def static_frontend_checks():
    files = {p.name:p for p in (ROOT/'web').glob('*') if p.is_file()}
    required = ['index.html','app.js','data.js','styles.css']
    checks=[]
    for name in required: checks.append({'name':f'file:{name}','pass':name in files and files[name].stat().st_size>100})
    text = ''.join(p.read_text(encoding='utf-8', errors='ignore') for p in files.values())
    for marker in ['Funding Explorer','What Changed','Ask PARTENER.EU','Consultant mode','Pot aplica?','provenien']:
        checks.append({'name':f'ui:{marker}','pass':marker.lower() in text.lower()})
    return checks

def semantic_text(body):
    text=body.decode('utf-8','ignore')
    text=re.sub(r'(?is)<!--.*?-->',' ',text)
    text=re.sub(r'(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>',' ',text)
    text=re.sub(r'(?is)<[^>]+>',' ',text)
    text=html.unescape(text)
    text=re.sub(r'\b[0-9a-f]{24,}\b',' ',text,flags=re.I)
    text=re.sub(r'\s+',' ',text).strip().lower()
    return text

def fetch_source(src, timeout=35, attempts=3):
    headers={
        'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36 PARTENER.EU-CIVORA-P10/1.1',
        'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language':'ro-RO,ro;q=0.9,en;q=0.7',
        'Cache-Control':'no-cache',
        'Connection':'close'
    }
    last=None
    for attempt in range(1,attempts+1):
        req=urllib.request.Request(src['url'], headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body=r.read(4_000_000); code=getattr(r,'status',200); final=r.geturl(); response_headers=dict(r.headers.items())
            txt=body.decode('utf-8','ignore').lower()
            markers=[m for m in src.get('markers_any',[]) if m.lower() in txt]
            sem=semantic_text(body).encode('utf-8')
            return {'ok':200<=code<400,'http_status':code,'final_url':final,'bytes':len(body),'raw_sha256':sha(body),'semantic_sha256':sha(sem),'semantic_chars':len(sem),'markers_found':markers,'etag':response_headers.get('ETag'),'last_modified':response_headers.get('Last-Modified'),'attempts':attempt,'error':None}
        except Exception as e:
            last=f'{type(e).__name__}: {e}'
            if attempt<attempts: time.sleep(attempt)
    return {'ok':False,'http_status':None,'final_url':None,'bytes':0,'raw_sha256':None,'semantic_sha256':None,'semantic_chars':0,'markers_found':[],'etag':None,'last_modified':None,'attempts':attempts,'error':last}

def evaluate_change(prev, observed_semantic):
    baseline=prev.get('semantic_sha256')
    if not observed_semantic:
        return False, False, prev.get('pending_semantic_sha256'), int(prev.get('pending_count',0))
    if not baseline:
        return False, False, None, 0
    if observed_semantic==baseline:
        return False, False, None, 0
    pending=prev.get('pending_semantic_sha256')
    count=int(prev.get('pending_count',0))
    if pending==observed_semantic:
        count+=1
    else:
        pending=observed_semantic; count=1
    confirmed=count>=2
    return True, confirmed, pending, count

def run(live=True):
    started=nowz(); state,recovered=recover_state(); registry=load_json(OPS/'sources.json', {'sources':[]})
    frontend=static_frontend_checks(); results=[]; critical_fail=False
    for src in registry['sources']:
        prev=state['sources'].get(src['id'],{})
        if live: obs=fetch_source(src)
        else: obs={'ok':True,'http_status':0,'final_url':src['url'],'bytes':0,'raw_sha256':'OFFLINE','semantic_sha256':prev.get('semantic_sha256') or 'OFFLINE_SMOKE','semantic_chars':0,'markers_found':['OFFLINE_SMOKE'],'etag':None,'last_modified':None,'attempts':0,'error':None}
        failures=0 if obs['ok'] else int(prev.get('consecutive_failures',0))+1
        candidate,change,pending,pending_count=evaluate_change(prev,obs.get('semantic_sha256'))
        markers_ok=bool(obs.get('markers_found')) if src.get('markers_any') else True
        if obs['ok'] and markers_ok: health='PASS'
        elif obs['ok']: health='DEGRADED'
        elif failures<3: health='DEGRADED'
        else: health='FAIL'
        if health=='FAIL' and src.get('criticality') in ('CRITICAL','HIGH'): critical_fail=True
        result={**src,'observed_at':started,**obs,'markers_ok':markers_ok,'change_candidate':candidate,'change_detected':change,'resolution_task_required':change,'confirmation_observations':pending_count,'consecutive_failures':failures,'health':health}
        results.append(result)
        current_sem=prev.get('semantic_sha256')
        if obs.get('semantic_sha256') and not current_sem:
            current_sem=obs['semantic_sha256']
        elif change:
            current_sem=obs['semantic_sha256']; pending=None; pending_count=0
        state['sources'][src['id']]={'raw_sha256':obs.get('raw_sha256') or prev.get('raw_sha256'),'semantic_sha256':current_sem,'pending_semantic_sha256':pending,'pending_count':pending_count,'last_success':started if obs['ok'] else prev.get('last_success'),'last_observed':started,'consecutive_failures':failures,'health':health,'final_url':obs.get('final_url') or prev.get('final_url')}
    state['last_run']=started; state['schema_version']=2
    report={'checkpoint':'PARTENER-EU-CIVORA-P10-0019','run_started':started,'live':live,'state_recovered_from_checkpoint':recovered,'frontend_checks':frontend,'sources':results,'summary':{'frontend_pass':sum(x['pass'] for x in frontend),'frontend_total':len(frontend),'source_pass':sum(x['health']=='PASS' for x in results),'source_degraded':sum(x['health']=='DEGRADED' for x in results),'source_fail':sum(x['health']=='FAIL' for x in results),'change_candidates':sum(x['change_candidate'] for x in results),'change_detected':sum(x['change_detected'] for x in results),'critical_fail':critical_fail},'change_policy':'semantic fingerprint + two consecutive identical observations before resolution task','civora_v1':'NOT_CLOSED','production_day_count_rule':'>=30 distinct UTC dates with qualifying runs before closure'}
    atomic_json(CHECKPOINT, state); atomic_json(STATE, state); atomic_json(LATEST, report)
    HISTORY.mkdir(parents=True,exist_ok=True); stamp=started.replace(':','').replace('-',''); atomic_json(HISTORY/(stamp+'.json'), report)
    frontend_fail=not all(x['pass'] for x in frontend)
    return report, 2 if (critical_fail or frontend_fail) else 0

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--offline-smoke',action='store_true'); args=ap.parse_args()
    report,code=run(live=not args.offline_smoke); print(json.dumps(report['summary'],ensure_ascii=False,indent=2)); sys.exit(code)
