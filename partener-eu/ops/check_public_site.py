#!/usr/bin/env python3
import datetime as dt, hashlib, json, pathlib, urllib.request, os, tempfile, re
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
obs={'url':URL,'observed_at':dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z'),'status':'PENDING','http_status':None,'marker_ok':False,'markers':{'PARTENER.EU':False,'Funding Intelligence':False},'final_url':None,'content_type':None,'bytes':0,'body_sha256':None,'title':None,'error':None}
try:
    req=urllib.request.Request(URL,headers={'User-Agent':'PARTENER.EU-CIVORA-P10/1.1','Cache-Control':'no-cache'})
    with urllib.request.urlopen(req,timeout=30) as r:
        body=r.read(1_000_000); obs['http_status']=getattr(r,'status',200); obs['final_url']=r.geturl(); obs['content_type']=r.headers.get('Content-Type'); text=body.decode('utf-8','ignore')
    obs['bytes']=len(body); obs['body_sha256']=hashlib.sha256(body).hexdigest()
    m=re.search(r'(?is)<title[^>]*>(.*?)</title>',text)
    if m: obs['title']=re.sub(r'\s+',' ',m.group(1)).strip()[:300]
    obs['markers']['PARTENER.EU']='PARTENER.EU' in text
    obs['markers']['Funding Intelligence']='Funding Intelligence' in text
    obs['marker_ok']=all(obs['markers'].values())
    obs['status']='PASS' if 200 <= obs['http_status'] < 400 and obs['marker_ok'] else 'DEGRADED'
except Exception as e:
    obs['error']=f'{type(e).__name__}: {e}'
atomic(OUT,obs)
print(json.dumps(obs,ensure_ascii=False,indent=2))
