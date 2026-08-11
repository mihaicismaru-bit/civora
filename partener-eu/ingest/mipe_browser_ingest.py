#!/usr/bin/env python3
import datetime as dt
import hashlib
import json
import re
import urllib.parse
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / 'partener-eu/ingest/state/mipe_state.json'
OUT = ROOT / 'partener-eu/web/mipe-news.js'
SEED = 'https://mfe.gov.ro/pdds/despre-program-programare/'
ROOT_URL = 'https://mfe.gov.ro/'
HOSTS = {'mfe.gov.ro','www.mfe.gov.ro'}
KW = ['fonduri','finanț','finant','apel','ghid','program','proiect','investi','beneficiar','grant','alocare','buget','pdds','dezvoltare durabil','prioritate','consultare','corrigendum','termen','eligibil','mysmis','fse','feder','tranziție justă','tranzitie justa']
EX = ['post vacant','concurs recrutare','declarație de avere','declaratie de avere','achiziție publică','achizitie publica','anunț de angajare','anunt de angajare']
MON=['ian','feb','mar','apr','mai','iun','iul','aug','sept','oct','nov','dec']
MAX_PAGES=55

def now(): return dt.datetime.now(dt.timezone.utc)
def clean(s): return re.sub(r'\s+',' ',str(s or '')).strip()
def norm(u, base=None):
    if base: u=urllib.parse.urljoin(base,u)
    p=urllib.parse.urlparse(u)
    if p.scheme not in ('http','https') or p.hostname not in HOSTS: return None
    path=re.sub(r'/{2,}','/',p.path or '/')
    return urllib.parse.urlunparse(('https',p.netloc.lower(),path,'',p.query,''))
def score(title, body, url):
    h=(title+' '+body[:3000]+' '+url).lower(); s=sum(2 if k in title.lower() else 1 for k in KW if k in h)
    if any(x in title.lower() for x in EX): s-=8
    return s
def kind(t):
    x=t.lower()
    if 'prelung' in x and 'termen' in x:return 'DEADLINE_EXTENDED'
    if 'corrigendum' in x or 'corrigend' in x:return 'GUIDE_MODIFIED'
    if 'consultare' in x and ('ghid' in x or 'apel' in x):return 'CONSULTATION_OPENED'
    if 'ghid' in x and ('publicat' in x or 'aprobat' in x or 'final' in x):return 'GUIDE_PUBLISHED'
    if ('lans' in x and 'apel' in x) or 'apel de proiecte' in x or 'apelul este deschis' in x:return 'CALL_OPENED'
    return 'OFFICIAL_UPDATE'
def tag(t):
    x=t.lower()
    if '/pdds/' in x or 'pdds' in x or 'dezvoltare durabil' in x:return 'PDDS'
    if 'poids' in x or 'pids' in x:return 'PoIDS'
    if re.search(r'\bpeo\b',x):return 'PEO'
    if 'pnrr' in x:return 'PNRR'
    if 'tranziție justă' in x or 'tranzitie justa' in x:return 'PTJ'
    return 'MIPE'
def pdate(text):
    text=text or ''
    pats=[r'\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b',r'\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b']
    for i,p in enumerate(pats):
        m=re.search(p,text[:7000])
        if not m: continue
        try:
            if i==0:y,mo,d=map(int,m.groups())
            else:d,mo,y=map(int,m.groups())
            return dt.date(y,mo,d)
        except: pass
    return None
def label(d): return f'{d.day} {MON[d.month-1]} {d.year}'
def load_state():
    try:return json.loads(STATE.read_text(encoding='utf-8'))
    except:return {'items':[],'runs':[]}
def persist(st, fresh, run):
    prev={x.get('url'):x for x in st.get('items',[]) if x.get('url')}
    for x in fresh: prev[x['url']]=x
    items=sorted(prev.values(),key=lambda x:(x.get('date',''),x.get('observedAt','')),reverse=True)[:40]
    status='OK' if fresh else ('OK_NO_NEW_RELEVANT_ITEMS' if run.get('sourceAvailable') else 'SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED')
    run['status']=status; run['publishedItemCount']=len(items)
    runs=(st.get('runs') or [])[-29:]+[run]
    obj={'status':status,'lastRun':run,'items':items,'runs':runs}
    STATE.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    meta={'status':status,'asOf':run['observedAt'],'source':'MIPE official web properties','roots':run.get('roots',[]),'itemCount':len(items),'transport':'playwright-chromium'}
    OUT.write_text('window.PARTENER_DATA=window.PARTENER_DATA||{};\nwindow.PARTENER_DATA.mipeIngestion='+json.dumps(meta,ensure_ascii=False,separators=(',',':'))+';\nwindow.PARTENER_DATA.mipeNews='+json.dumps(items,ensure_ascii=False,separators=(',',':'))+';\n',encoding='utf-8')
    print(json.dumps(run,ensure_ascii=False,indent=2))

def main():
    st=load_state(); fresh=[]; seen=set(); queue=[(SEED,0),(ROOT_URL,0)]; roots=[]; source_available=False; failures=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=['--disable-dev-shm-usage','--no-sandbox'])
        context=browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36',locale='ro-RO',ignore_https_errors=False)
        while queue and len(seen)<MAX_PAGES:
            url,depth=queue.pop(0); url=norm(url)
            if not url or url in seen: continue
            # PDDS discovery is strictly scoped below the explicit seed; homepage is only for broader MIPE discovery.
            if depth>0 and '/pdds/' not in url and url!=ROOT_URL: continue
            seen.add(url); page=context.new_page()
            try:
                resp=page.goto(url,wait_until='domcontentloaded',timeout=30000)
                page.wait_for_timeout(1200)
                status=resp.status if resp else 0
                if status and status>=400: raise RuntimeError(f'HTTP {status}')
                final=norm(page.url)
                if not final: raise RuntimeError('redirected outside official MIPE host')
                source_available=True
                title=clean(page.locator('h1').first.text_content(timeout=1500) if page.locator('h1').count() else page.title())
                body=clean(page.locator('body').inner_text(timeout=5000))
                desc=''
                try: desc=clean(page.locator('meta[name="description"]').get_attribute('content'))
                except: pass
                if score(title,body,final)>=2 and final!=ROOT_URL:
                    d=pdate(body) or now().date(); summary=clean(desc or body[:900])[:900]
                    fp=hashlib.sha256((final+'\n'+title).encode()).hexdigest()[:20]
                    fresh.append({'id':fp,'title':title[:360],'url':final,'date':d.isoformat(),'dateLabel':label(d),'summary':summary,'tag':tag(final+' '+title+' '+summary),'kind':kind(title),'tier':'T1','source':'MIPE','observedAt':now().isoformat(),'discovery':'playwright-browser'})
                if depth<2:
                    links=page.locator('a[href]').evaluate_all("els => els.map(a => ({href:a.href,text:(a.innerText||'').trim()}))")
                    for z in links:
                        u=norm(z.get('href'),final)
                        if not u or u in seen: continue
                        up=urllib.parse.urlparse(u)
                        if '/pdds/' in final:
                            if up.path.startswith('/pdds/') and not re.search(r'\.(pdf|docx?|xlsx?|zip|jpg|jpeg|png|gif|svg)(\?|$)',u,re.I): queue.append((u,depth+1))
                        elif final==ROOT_URL and score(clean(z.get('text')),'',u)>0 and not re.search(r'\.(pdf|docx?|xlsx?|zip|jpg|jpeg|png|gif|svg)(\?|$)',u,re.I): queue.append((u,1))
                if url in (SEED,ROOT_URL): roots.append({'root':url,'ok':True,'transport':'playwright-chromium','status':status})
            except Exception as e:
                failures.append({'url':url,'error':f'{type(e).__name__}: {e}'})
                if url in (SEED,ROOT_URL): roots.append({'root':url,'ok':False,'transport':'playwright-chromium','error':f'{type(e).__name__}: {e}'})
            finally: page.close()
        browser.close()
    # De-duplicate by canonical official URL; browser output itself is the provenance, never a mirror.
    uniq={}
    for x in fresh: uniq[x['url']]=x
    run={'observedAt':now().isoformat(),'roots':roots,'sourceAvailable':source_available,'candidateCount':len(seen),'parsedRelevantCount':len(uniq),'browserFailures':failures[:12]}
    persist(st,list(uniq.values()),run)
if __name__=='__main__': main()
