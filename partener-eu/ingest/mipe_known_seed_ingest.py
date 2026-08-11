#!/usr/bin/env python3
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SEEDS = ROOT / 'partener-eu/ingest/state/mipe_known_canonical_seeds.json'
STATE = ROOT / 'partener-eu/ingest/state/mipe_state.json'
OUT = ROOT / 'partener-eu/web/mipe-news.js'
MON=['ian','feb','mar','apr','mai','iun','iul','aug','sept','oct','nov','dec']
KW=['fonduri','finanț','finant','apel','ghid','program','proiect','beneficiar','grant','alocare','buget','consultare','corrigendum','termen','eligibil','mysmis','step','educație','educatie','ocupare','incluziune','demnitate']

def now(): return dt.datetime.now(dt.timezone.utc)
def clean(s): return re.sub(r'\s+',' ',str(s or '')).strip()
def label(d): return f'{d.day} {MON[d.month-1]} {d.year}'
def pdate(text):
    text=text or ''
    for i,p in enumerate([r'\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b',r'\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b']):
        m=re.search(p,text[:10000])
        if m:
            try:
                if i==0:y,mo,d=map(int,m.groups())
                else:d,mo,y=map(int,m.groups())
                return dt.date(y,mo,d)
            except: pass
    return None
def kind(t):
    x=t.lower()
    if 'prelung' in x and 'termen' in x:return 'DEADLINE_EXTENDED'
    if 'corrigendum' in x or 'corrigend' in x:return 'GUIDE_MODIFIED'
    if 'consultare' in x and ('ghid' in x or 'apel' in x):return 'CONSULTATION_OPENED'
    if 'ghid' in x and ('publicat' in x or 'aprobat' in x or 'final' in x):return 'GUIDE_PUBLISHED'
    if ('lans' in x and 'apel' in x) or 'apel de proiecte' in x:return 'CALL_OPENED'
    return 'OFFICIAL_UPDATE'
def load_state():
    try:return json.loads(STATE.read_text(encoding='utf-8'))
    except:return {'items':[],'runs':[]}
def persist(st,fresh,run):
    prev={x.get('url'):x for x in st.get('items',[]) if x.get('url')}
    for x in fresh:prev[x['url']]=x
    items=sorted(prev.values(),key=lambda x:(x.get('date',''),x.get('observedAt','')),reverse=True)[:60]
    status='OK' if fresh else ('OK_NO_NEW_RELEVANT_ITEMS' if run.get('verifiedFetches',0)>0 else 'SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED')
    run['status']=status;run['publishedItemCount']=len(items)
    runs=(st.get('runs') or [])[-39:]+[run]
    STATE.write_text(json.dumps({'status':status,'lastRun':run,'items':items,'runs':runs},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    meta={'status':status,'asOf':run['observedAt'],'source':'MIPE canonical mapped seeds','itemCount':len(items),'transport':'playwright-known-canonical-seeds'}
    OUT.write_text('window.PARTENER_DATA=window.PARTENER_DATA||{};\nwindow.PARTENER_DATA.mipeIngestion='+json.dumps(meta,ensure_ascii=False,separators=(',',':'))+';\nwindow.PARTENER_DATA.mipeNews='+json.dumps(items,ensure_ascii=False,separators=(',',':'))+';\n',encoding='utf-8')

def main():
    seeds=json.loads(SEEDS.read_text(encoding='utf-8')).get('items',[])
    st=load_state();fresh=[];fail=[];verified=0;host_timeouts=0;probed=0
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=['--disable-dev-shm-usage','--no-sandbox'])
        ctx=browser.new_context(locale='ro-RO',user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36')
        for seed in seeds:
            if host_timeouts >= 2:
                break
            url=seed['url']; page=ctx.new_page();probed+=1
            try:
                resp=page.goto(url,wait_until='domcontentloaded',timeout=7000)
                status=resp.status if resp else 0
                if status and status>=400: raise RuntimeError(f'HTTP {status}')
                if not page.url.startswith('https://mfe.gov.ro/'): raise RuntimeError('redirected outside canonical MIPE host')
                title=clean(page.locator('h1').first.text_content(timeout=1200) if page.locator('h1').count() else page.title()) or seed.get('titleHint','')
                body=clean(page.locator('body').inner_text(timeout=3500))
                if len(body)<80: raise RuntimeError('insufficient official page content')
                verified+=1;host_timeouts=0
                hay=(title+' '+body[:4000]).lower()
                if sum(1 for k in KW if k in hay)<2: continue
                d=pdate(body) or now().date(); summary=body[:900]
                fp=hashlib.sha256((url+'\n'+title).encode()).hexdigest()[:20]
                fresh.append({'id':fp,'title':title[:360],'url':url,'date':d.isoformat(),'dateLabel':label(d),'summary':summary,'tag':seed.get('programme','MIPE'),'kind':kind(title+' '+body[:1200]),'tier':'T1','source':'MIPE','observedAt':now().isoformat(),'discovery':'mapped-canonical-seed+verified-fetch'})
            except Exception as e:
                msg=f'{type(e).__name__}: {e}'
                if 'Timeout' in msg or 'ERR_CONNECTION' in msg or 'net::' in msg:
                    host_timeouts+=1
                fail.append({'url':url,'error':msg})
            finally: page.close()
        browser.close()
    uniq={x['url']:x for x in fresh}
    run={'observedAt':now().isoformat(),'mappedSeedCount':len(seeds),'probedSeedCount':probed,'verifiedFetches':verified,'parsedRelevantCount':len(uniq),'hostFastFail':host_timeouts>=2,'seedFailures':fail[:20]}
    persist(st,list(uniq.values()),run)
    print(json.dumps(run,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
