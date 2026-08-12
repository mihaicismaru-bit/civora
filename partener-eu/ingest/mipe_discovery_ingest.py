#!/usr/bin/env python3
import json, re, ssl, urllib.request, urllib.parse
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SOURCES=ROOT/'partener-eu/ingest/state/mipe_discovery_sources.json'
SEEDS=ROOT/'partener-eu/ingest/state/mipe_known_canonical_seeds.json'
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36'

def fetch(url):
    req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'text/html,application/xhtml+xml'})
    with urllib.request.urlopen(req,timeout=12,context=ssl.create_default_context()) as r:
        return r.read(3_000_000).decode('utf-8','ignore')

def canonical(u,base):
    u=urllib.parse.urljoin(base,u)
    p=urllib.parse.urlparse(u)
    if p.scheme not in ('http','https') or (p.hostname or '').lower() not in ('mfe.gov.ro','www.mfe.gov.ro'):
        return None
    path=re.sub(r'/{2,}','/',p.path or '/')
    # Funding intelligence focuses on programme pages and official uploaded documents.
    if not (path.startswith('/ghiduri_peos/') or path.startswith('/ghiduri_pids/') or path.startswith('/pdds/') or path.startswith('/wp-content/uploads/')):
        return None
    return urllib.parse.urlunparse(('https','mfe.gov.ro',path,'','',''))

def infer(u):
    if '/ghiduri_peos/' in u:return 'PEO'
    if '/ghiduri_pids/' in u:return 'PoIDS'
    if '/pdds/' in u:return 'PDDS'
    return 'MIPE'

def main():
    src=json.loads(SOURCES.read_text(encoding='utf-8')).get('sources',[])
    obj=json.loads(SEEDS.read_text(encoding='utf-8'))
    items=obj.get('items',[]); known={x['url'] for x in items}; added=[]; failures=[]
    for s in src:
        if s.get('role')!='T2_OFFICIAL_DISCOVERY_ONLY': continue
        url=s['url']
        try:
            html=fetch(url)
            hrefs=re.findall(r'''href\s*=\s*["']([^"']+)["']''',html,re.I)
            # Also catch canonical URLs printed as plain text in institutional notices.
            hrefs += re.findall(r'https?://(?:www\.)?mfe\.gov\.ro/[^\s<"\']+',html,re.I)
            for h in hrefs:
                u=canonical(h,url)
                if not u or u in known: continue
                known.add(u)
                item={'url':u,'programme':infer(u),'titleHint':'','discoveredVia':url}
                items.append(item);added.append(item)
        except Exception as e:
            failures.append({'source':url,'error':f'{type(e).__name__}: {e}'})
    if added:
        obj['version']=int(obj.get('version',1))+1
        obj['items']=items
        SEEDS.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'discoverySourceCount':sum(1 for s in src if s.get('role')=='T2_OFFICIAL_DISCOVERY_ONLY'),'newCanonicalSeeds':len(added),'added':added,'failures':failures},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
