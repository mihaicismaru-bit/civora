#!/usr/bin/env python3
import hashlib,json,re,ssl,urllib.request
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
REG=ROOT/'partener-eu'/'ingest'/'mff_2028_source_registry.json'
STATE=ROOT/'partener-eu'/'ingest'/'state'/'mff_2028_health.json'
UA='Mozilla/5.0 CIVORA-PARTENER-EU/1.0 (+mff-2028-validation)'

def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sem(raw,ctype):
    if 'html' not in (ctype or '').lower(): return raw
    t=raw.decode('utf-8','ignore')
    t=re.sub(r'<script\b[^>]*>.*?</script>',' ',t,flags=re.I|re.S)
    t=re.sub(r'<style\b[^>]*>.*?</style>',' ',t,flags=re.I|re.S)
    t=re.sub(r'<[^>]+>',' ',t)
    t=re.sub(r'\s+',' ',t).strip()
    return t.encode()
def fetch(url):
    req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'text/html,application/xhtml+xml,*/*;q=0.8'})
    with urllib.request.urlopen(req,timeout=25,context=ssl.create_default_context()) as r:
        raw=r.read(3000000); ctype=r.headers.get('content-type') or ''; s=sem(raw,ctype)
        return {'ok':200<=r.status<400,'http_status':r.status,'final_url':r.geturl(),'bytes':len(raw),'semantic_sha256':hashlib.sha256(s).hexdigest()}
def main():
    reg=json.loads(REG.read_text(encoding='utf-8')); prev={}
    if STATE.exists():
        try: prev={x['id']:x for x in json.loads(STATE.read_text(encoding='utf-8')).get('sources',[])}
        except Exception: pass
    out={'schema_version':'1.0','observed_at':now(),'policy':'health-hash-stage-only-no-auto-adoption','sources':[]}
    for src in reg['sources']:
        row={'id':src['id'],'tier':src['tier'],'class':src['class'],'stage':src.get('stage'),'url':src['url']}
        try:
            row.update(fetch(src['url'])); old=prev.get(src['id'],{}).get('semantic_sha256')
            row['semantic_hash_changed']=bool(old and old!=row['semantic_sha256'])
            row['review_required']=row['semantic_hash_changed']
            row['auto_promote_legislative_stage']=False
            row['health']='PASS' if row['ok'] else 'FAIL'
        except Exception as e:
            row.update({'ok':False,'health':'FAIL','error':f'{type(e).__name__}: {e}','semantic_hash_changed':False,'review_required':False,'auto_promote_legislative_stage':False})
        out['sources'].append(row)
    out['summary']={'total':len(out['sources']),'pass':sum(x['health']=='PASS' for x in out['sources']),'fail':sum(x['health']=='FAIL' for x in out['sources']),'review_required':sum(bool(x.get('review_required')) for x in out['sources'])}
    STATE.parent.mkdir(parents=True,exist_ok=True); STATE.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(out['summary']))
if __name__=='__main__': main()
