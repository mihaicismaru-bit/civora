#!/usr/bin/env python3
import datetime as dt
import hashlib
import html
import json
import re
import subprocess
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
STATE=ROOT/'partener-eu/ingest/state/mipe_state.json'
OUT=ROOT/'partener-eu/web/mipe-news.js'
ROOTS=['https://mfe.gov.ro/','https://www.fonduri-ue.gov.ro/']
HOSTS={'mfe.gov.ro','www.mfe.gov.ro','fonduri-ue.gov.ro','www.fonduri-ue.gov.ro'}
UA='PARTENER.EU-CIVORA-MIPE-Ingest/1.1 (+https://partener.eu)'
KW=['fonduri','finanț','finant','apel','ghid','program','proiect','investi','beneficiar','grant','alocare','buget','poids','pids','peo','pnrr','coeziune','consultare','corrigendum','termen','eligibil','mysmis','fse','feder','tranziție justă','tranzitie justa']
EX=['post vacant','concurs recrutare','declarație de avere','declaratie de avere','achiziție publică','achizitie publica','anunț de angajare','anunt de angajare']
MON=['ian','feb','mar','apr','mai','iun','iul','aug','sept','oct','nov','dec']

def now(): return dt.datetime.now(dt.timezone.utc)
def clean(s): return re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',html.unescape(str(s or '')))).strip()
def norm(u,base=None):
    if base:u=urllib.parse.urljoin(base,u)
    p=urllib.parse.urlparse(u)
    if p.scheme not in ('http','https') or p.hostname not in HOSTS:return None
    return urllib.parse.urlunparse(('https',p.netloc.lower(),re.sub(r'/{2,}','/',p.path or '/'),' ',p.query,'')).replace('https:// ','https://').replace('/ /','/')

def curl(url,timeout=22):
    fmt='\n__PARTENER_META__%{http_code}\t%{url_effective}\t%{content_type}'
    cmd=['curl','-4','-L','--fail','--silent','--show-error','--compressed','--connect-timeout','8','--max-time',str(timeout),'-A',UA,'-H','Accept: text/html,application/json,application/xml;q=0.9,*/*;q=0.8','-w',fmt,url]
    p=subprocess.run(cmd,capture_output=True)
    if p.returncode!=0:return {'ok':False,'error':p.stderr.decode('utf-8','replace').strip() or f'curl rc={p.returncode}','url':url}
    b=p.stdout; mark=b.rfind(b'\n__PARTENER_META__')
    if mark<0:return {'ok':False,'error':'missing curl metadata','url':url}
    data=b[:mark]; meta=b[mark+len(b'\n__PARTENER_META__'):].decode('utf-8','replace').split('\t')
    code=int(meta[0] or 0); final=meta[1] if len(meta)>1 else url; ctype=meta[2] if len(meta)>2 else ''
    return {'ok':200<=code<400,'status':code,'url':final,'ctype':ctype,'data':data,'error':None if 200<=code<400 else f'HTTP {code}'}

class P(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.title=[];self.h1=[];self.ps=[];self.links=[];self.meta={};self.stack=[];self.ah=None;self.at=[];self.times=[]
    def handle_starttag(self,t,a):
        d=dict(a);self.stack.append(t)
        if t=='a':self.ah=d.get('href');self.at=[]
        elif t=='meta':
            k=(d.get('property') or d.get('name') or '').lower();v=d.get('content')
            if k and v:self.meta[k]=v
        elif t=='time' and d.get('datetime'):self.times.append(d['datetime'])
    def handle_endtag(self,t):
        if t=='a' and self.ah:self.links.append((self.ah,clean(' '.join(self.at))));self.ah=None;self.at=[]
        if self.stack:
            for i in range(len(self.stack)-1,-1,-1):
                if self.stack[i]==t:self.stack=self.stack[:i];break
    def handle_data(self,d):
        if not d.strip():return
        cur=self.stack[-1] if self.stack else ''
        if cur=='title':self.title.append(d)
        if cur=='h1':self.h1.append(d)
        if cur=='p':self.ps.append(d)
        if self.ah is not None:self.at.append(d)

def page(data):
    s=data.decode('utf-8','replace');p=P();p.feed(s)
    title=clean(p.meta.get('og:title') or p.meta.get('twitter:title') or ' '.join(p.h1) or ' '.join(p.title))
    desc=clean(p.meta.get('description') or p.meta.get('og:description') or p.meta.get('twitter:description'))
    body=clean(' '.join(p.ps));return p,title,desc,body

def score(title,desc,body,url):
    h=' '.join([title,desc,body[:2500],url]).lower();s=sum(2 if k in title.lower() else 1 for k in KW if k in h)
    if any(x in title.lower() for x in EX):s-=8
    return s

def pdate(v,body=''):
    vals=[v] if v else []
    vals+=re.findall(r'\b20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}\b',body[:5000]);vals+=re.findall(r'\b\d{1,2}[./-]\d{1,2}[./-]20\d{2}\b',body[:5000])
    for x in vals:
        if not x:continue
        z=str(x).strip().replace('Z','+00:00')
        try:return dt.datetime.fromisoformat(z).date()
        except:pass
        for f in ('%Y-%m-%d','%Y/%m/%d','%d.%m.%Y','%d/%m/%Y','%d-%m-%Y'):
            try:return dt.datetime.strptime(z[:10],f).date()
            except:pass
    return None

def label(d):return f'{d.day} {MON[d.month-1]} {d.year}'
def tag(t):
    x=t.lower()
    if 'poids' in x or 'pids' in x:return 'PoIDS'
    if re.search(r'\bpeo\b',x):return 'PEO'
    if 'pnrr' in x:return 'PNRR'
    if 'tranziție justă' in x or 'tranzitie justa' in x or re.search(r'\bptj\b',x):return 'PTJ'
    if 'program regional' in x:return 'REGIONAL'
    return 'MIPE'
def kind(t):
    x=t.lower()
    if 'prelung' in x and 'termen' in x:return 'DEADLINE_EXTENDED'
    if 'corrigendum' in x:return 'GUIDE_MODIFIED'
    if 'consultare' in x and ('ghid' in x or 'apel' in x):return 'CONSULTATION_OPENED'
    if 'ghid' in x and ('publicat' in x or 'aprobat' in x or 'final' in x):return 'GUIDE_PUBLISHED'
    if ('lans' in x and 'apel' in x) or 'apel de proiecte' in x:return 'CALL_OPENED'
    return 'OFFICIAL_UPDATE'

def state():
    try:return json.loads(STATE.read_text(encoding='utf-8'))
    except:return {'items':[],'runs':[]}

def discover(root):
    out=[]; health={'root':root,'ok':False,'error':None,'transport':'curl-ipv4-tls-verified'}
    r=curl(root,25)
    if not r['ok']:health['error']=r['error'];return out,health
    health['ok']=True
    try:
        p,t,d,b=page(r['data'])
        for href,a in p.links:
            u=norm(href,r['url'])
            if u and not re.search(r'\.(pdf|docx?|xlsx?|zip|jpg|png)(\?|$)',u,re.I) and score(a,'','',u)>0:out.append({'url':u,'title':a,'via':'home'})
    except Exception as e:health['error']=f'home parse: {e}'
    wp=urllib.parse.urljoin(root,'/wp-json/wp/v2/posts?per_page=50&_fields=link,date,title,excerpt')
    w=curl(wp,18)
    if w['ok']:
        try:
            rows=json.loads(w['data'].decode('utf-8','replace'))
            if isinstance(rows,list):
                for z in rows:
                    u=norm(z.get('link',''))
                    if u:out.append({'url':u,'title':clean((z.get('title') or {}).get('rendered')),'excerpt':clean((z.get('excerpt') or {}).get('rendered')),'date':z.get('date'),'via':'wp-json'})
        except:pass
    return out,health

def make(c):
    r=curl(c['url'],20)
    if not r['ok']:return None
    try:p,t,d,b=page(r['data'])
    except:return None
    t=clean(t or c.get('title'));d=clean(d or c.get('excerpt'))
    if len(t)<8 or score(t,d,b,c['url'])<2:return None
    pd=None
    for k in ('article:published_time','date','datepublished','dc.date'):
        if p.meta.get(k):pd=pdate(p.meta[k],b)
        if pd:break
    if not pd and p.times:pd=pdate(p.times[0],b)
    if not pd:pd=pdate(c.get('date'),b) or pdate(None,b) or now().date()
    sm=clean(d if len(d)>=40 else b[:900])[:900]
    u=norm(r['url']) or c['url'];fp=hashlib.sha256((u+'\n'+t).encode()).hexdigest()[:20]
    return {'id':fp,'title':t[:360],'url':u,'date':pd.isoformat(),'dateLabel':label(pd),'summary':sm,'tag':tag(t+' '+sm),'kind':kind(t),'tier':'T1','source':'MIPE','observedAt':now().isoformat(),'discovery':c.get('via','crawl')}

def main():
    st=state();prev={x.get('url'):x for x in st.get('items',[]) if x.get('url')};cand=[];health=[]
    for root in ROOTS:
        a,h=discover(root);cand+=a;health.append(h)
    uniq={}
    for c in cand:
        if c.get('url') and (c.get('url') not in uniq or len(c.get('title',''))>len(uniq[c['url']].get('title',''))):uniq[c['url']]=c
    q=sorted(uniq.values(),key=lambda c:(0 if c.get('via')=='wp-json' else 1,-score(c.get('title',''),c.get('excerpt',''),' ',c.get('url',''))))[:45]
    fresh=[]
    for c in q:
        x=make(c)
        if x:fresh.append(x)
    merged=dict(prev)
    for x in fresh:merged[x['url']]=x
    items=sorted(merged.values(),key=lambda x:(x.get('date',''),x.get('observedAt','')),reverse=True)[:40]
    up=sum(1 for h in health if h['ok'])
    status='OK' if fresh else ('OK_NO_NEW_RELEVANT_ITEMS' if up else 'SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED')
    run={'observedAt':now().isoformat(),'status':status,'roots':health,'candidateCount':len(uniq),'parsedRelevantCount':len(fresh),'publishedItemCount':len(items)}
    runs=(st.get('runs') or [])[-29:]+[run];obj={'status':status,'lastRun':run,'items':items,'runs':runs};STATE.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    meta={'status':status,'asOf':run['observedAt'],'source':'MIPE official web properties','roots':health,'itemCount':len(items)}
    OUT.write_text('window.PARTENER_DATA=window.PARTENER_DATA||{};\nwindow.PARTENER_DATA.mipeIngestion='+json.dumps(meta,ensure_ascii=False,separators=(',',':'))+';\nwindow.PARTENER_DATA.mipeNews='+json.dumps(items,ensure_ascii=False,separators=(',',':'))+';\n',encoding='utf-8')
    print(json.dumps(run,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
