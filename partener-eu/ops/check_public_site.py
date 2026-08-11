#!/usr/bin/env python3
import datetime as dt, json, pathlib, urllib.request, os, tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'validation'/'deployment.json'
URL='https://mihaicismaru-bit.github.io/civora/'
def atomic(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f: json.dump(obj,f,ensure_ascii=False,indent=2); f.write('\n')
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
obs={'url':URL,'observed_at':dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z'),'status':'PENDING','http_status':None,'marker_ok':False,'error':None}
try:
    req=urllib.request.Request(URL,headers={'User-Agent':'PARTENER.EU-CIVORA-P10/1.0'})
    with urllib.request.urlopen(req,timeout=30) as r:
        body=r.read(1_000_000); obs['http_status']=getattr(r,'status',200); text=body.decode('utf-8','ignore')
    obs['marker_ok']='PARTENER.EU' in text and 'Funding Intelligence' in text
    obs['status']='PASS' if 200 <= obs['http_status'] < 400 and obs['marker_ok'] else 'DEGRADED'
except Exception as e:
    obs['error']=f'{type(e).__name__}: {e}'
atomic(OUT,obs)
print(json.dumps(obs,ensure_ascii=False,indent=2))
