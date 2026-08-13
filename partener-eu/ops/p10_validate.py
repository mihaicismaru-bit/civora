#!/usr/bin/env python3
import argparse, datetime as dt, hashlib, html, json, os, pathlib, re, subprocess, sys, tempfile, time, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OPS = ROOT / "ops"
VALIDATION = ROOT / "validation"
STATE = VALIDATION / "source_state.json"
LATEST = VALIDATION / "latest.json"
HISTORY = VALIDATION / "history"
CHECKPOINT = VALIDATION / "source_state.checkpoint.json"
MIN_SEMANTIC_CHARS = 256
MIN_HTML_BYTES_FOR_LOW_INFO = 4096


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
    return {'schema_version':3,'sources':{},'last_run':None}, False

def static_frontend_checks():
    files = {p.name:p for p in (ROOT/'web').glob('*') if p.is_file()}
    required = ['index.html','app.js','data.js','styles.css']
    checks=[]
    for name in required: checks.append({'name':f'file:{name}','pass':name in files and files[name].stat().st_size>100})
    text = ''.join(p.read_text(encoding='utf-8', errors='ignore') for p in files.values())
    for marker in ['Explorer finanțări','Modificări','Întreabă PARTENER.EU','Spațiu consultant','Pot aplica?','Sursa oficială']:
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

def make_observation(src, body, code, final, response_headers, method, attempts):
    txt=body.decode('utf-8','ignore').lower()
    markers=[m for m in src.get('markers_any',[]) if m.lower() in txt]
    sem=semantic_text(body).encode('utf-8')
    return {'ok':200<=code<400,'http_status':code,'final_url':final,'bytes':len(body),'raw_sha256':sha(body),'semantic_sha256':sha(sem),'semantic_chars':len(sem),'markers_found':markers,'etag':response_headers.get('ETag'),'last_modified':response_headers.get('Last-Modified'),'fetch_method':method,'attempts':attempts,'error':None}

def observation_content_quality(obs):
    """Reject successful HTTP responses that are clearly low-information HTML shells.

    Several official sites occasionally return a normal-sized HTML framework with
    only a few dozen visible characters. Treating that shell as authoritative
    content creates identical semantic hashes across unrelated sources and can
    manufacture false change candidates. Such responses remain observable but
    may not advance the semantic-change confirmation counter.
    """
    if not obs.get('ok'):
        return False, None
    semantic_chars=int(obs.get('semantic_chars') or 0)
    body_bytes=int(obs.get('bytes') or 0)
    if body_bytes >= MIN_HTML_BYTES_FOR_LOW_INFO and semantic_chars < MIN_SEMANTIC_CHARS:
        return False, 'LOW_INFORMATION_HTML_SHELL'
    return True, None

def fetch_source(src, timeout=35, attempts=3):
    headers={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36 PARTENER.EU-CIVORA-P10/1.2','Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8','Accept-Language':'ro-RO,ro;q=0.9,en;q=0.7','Cache-Control':'no-cache','Connection':'close'}
    last=None
    for attempt in range(1,attempts+1):
        req=urllib.request.Request(src['url'], headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body=r.read(4_000_000); code=getattr(r,'status',200); final=r.geturl(); response_headers=dict(r.headers.items())
            return make_observation(src,body,code,final,response_headers,'urllib',attempt)
        except Exception as e:
            last=f'{type(e).__name__}: {e}'
            if attempt<attempts: time.sleep(attempt)
    try:
        cp=subprocess.run(['curl','-4','--http1.1','-L','--fail','--silent','--show-error','--max-time',str(timeout),'--retry','2','--retry-delay','1','-A',headers['User-Agent'],'-H','Accept-Language: ro-RO,ro;q=0.9,en;q=0.7',src['url']],capture_output=True,timeout=timeout*3+10)
        if cp.returncode==0 and cp.stdout:
            return make_observation(src,cp.stdout,200,src['url'],{},'curl-fallback',attempts+1)
        last=f'curl exit {cp.returncode}: {cp.stderr.decode("utf-8","ignore")[:500]}'
    except Exception as e:
        last=f'curl fallback {type(e).__name__}: {e}'
    return {'ok':False,'http_status':None,'final_url':None,'bytes':0,'raw_sha256':None,'semantic_sha256':None,'semantic_chars':0,'markers_found':[],'etag':None,'last_modified':None,'fetch_method':'urllib+curl','attempts':attempts+1,'error':last}

def evaluate_change(prev, observed_semantic):
    baseline=prev.get('semantic_sha256')
    if not observed_semantic: return False, False, prev.get('pending_semantic_sha256'), int(prev.get('pending_count',0))
    if not baseline: return False, False, None, 0
    if observed_semantic==baseline: return False, False, None, 0
    pending=prev.get('pending_semantic_sha256'); count=int(prev.get('pending_count',0))
    if pending==observed_semantic: count+=1
    else: pending=observed_semantic; count=1
    return True, count>=2, pending, count

def run(live=True):
    started=nowz(); state,recovered=recover_state(); registry=load_json(OPS/'sources.json', {'sources':[]})
    frontend=static_frontend_checks(); results=[]; critical_fail=False
    for src in registry['sources']:
        prev=state['sources'].get(src['id'],{})
        if live: obs=fetch_source(src)
        else: obs={'ok':True,'http_status':0,'final_url':src['url'],'bytes':0,'raw_sha256':'OFFLINE','semantic_sha256':prev.get('semantic_sha256') or 'OFFLINE_SMOKE','semantic_chars':0,'markers_found':['OFFLINE_SMOKE'],'etag':None,'last_modified':None,'fetch_method':'offline-smoke','attempts':0,'error':None}
        failures=0 if obs['ok'] else int(prev.get('consecutive_failures',0))+1
        content_quality_ok,quality_issue=observation_content_quality(obs)
        observed_semantic=obs.get('semantic_sha256') if content_quality_ok else None
        candidate,change,pending,pending_count=evaluate_change(prev,observed_semantic)
        markers_ok=bool(obs.get('markers_found')) if src.get('markers_any') else True
        if obs['ok'] and content_quality_ok and markers_ok: health='PASS'
        elif obs['ok']: health='DEGRADED'
        elif failures<3: health='DEGRADED'
        else: health='FAIL'
        quarantined=health=='FAIL'
        if quarantined and src.get('criticality')=='CRITICAL': critical_fail=True
        result={**src,'observed_at':started,**obs,'markers_ok':markers_ok,'content_quality_ok':content_quality_ok,'quality_issue':quality_issue,'change_candidate':candidate,'change_detected':change,'resolution_task_required':change,'confirmation_observations':pending_count,'consecutive_failures':failures,'health':health,'quarantined':quarantined,'dependent_material_facts_publishable':(not quarantined and content_quality_ok)}
        results.append(result)
        current_sem=prev.get('semantic_sha256')
        if observed_semantic and not current_sem: current_sem=observed_semantic
        elif change: current_sem=observed_semantic; pending=None; pending_count=0
        state['sources'][src['id']]={'raw_sha256':obs.get('raw_sha256') if content_quality_ok else prev.get('raw_sha256'),'semantic_sha256':current_sem,'pending_semantic_sha256':pending,'pending_count':pending_count,'last_success':started if (obs['ok'] and content_quality_ok) else prev.get('last_success'),'last_observed':started,'consecutive_failures':failures,'health':health,'quarantined':quarantined,'final_url':obs.get('final_url') or prev.get('final_url')}
    state['last_run']=started; state['schema_version']=3
    report={'checkpoint':'PARTENER-EU-CIVORA-P10-0020','run_started':started,'live':live,'state_recovered_from_checkpoint':recovered,'frontend_checks':frontend,'sources':results,'summary':{'frontend_pass':sum(x['pass'] for x in frontend),'frontend_total':len(frontend),'source_pass':sum(x['health']=='PASS' for x in results),'source_degraded':sum(x['health']=='DEGRADED' for x in results),'source_fail':sum(x['health']=='FAIL' for x in results),'source_quarantined':sum(x['quarantined'] for x in results),'change_candidates':sum(x['change_candidate'] for x in results),'change_detected':sum(x['change_detected'] for x in results),'low_information_sources':sum(not x.get('content_quality_ok',True) and x.get('quality_issue')=='LOW_INFORMATION_HTML_SHELL' for x in results),'critical_fail':critical_fail},'change_policy':'semantic fingerprint + two consecutive identical high-information observations before resolution task; low-information HTML shells are suppressed fail-closed','source_failure_policy':'failed non-CRITICAL source is quarantined and blocks dependent material facts; low-information shells also block dependent material facts until a high-information observation returns; CRITICAL source failure stops global qualifying run','civora_v1':'NOT_CLOSED','production_day_count_rule':'>=30 distinct UTC dates with qualifying runs before closure'}
    atomic_json(CHECKPOINT,state); atomic_json(STATE,state); atomic_json(LATEST,report)
    HISTORY.mkdir(parents=True,exist_ok=True); stamp=started.replace(':','').replace('-',''); atomic_json(HISTORY/(stamp+'.json'),report)
    frontend_fail=not all(x['pass'] for x in frontend)
    return report, 2 if (critical_fail or frontend_fail) else 0

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--offline-smoke',action='store_true'); args=ap.parse_args()
    report,code=run(live=not args.offline_smoke); print(json.dumps(report['summary'],ensure_ascii=False,indent=2)); sys.exit(code)
