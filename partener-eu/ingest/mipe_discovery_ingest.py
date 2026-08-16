#!/usr/bin/env python3
import datetime as dt
import hashlib
import html as html_lib
import json
import re
import ssl
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SOURCES=ROOT/'partener-eu/ingest/state/mipe_discovery_sources.json'
SEEDS=ROOT/'partener-eu/ingest/state/mipe_known_canonical_seeds.json'
STATE=ROOT/'partener-eu/ingest/state/mipe_state.json'
MYSMIS='https://reporting.mysmis2021.gov.ro/ords/repo_bo/r/mysmis-2021/finantari-programe-2021-2027'
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36'
MONTHS=['ian','feb','mar','apr','mai','iun','iul','aug','sept','oct','nov','dec']

# One-time migration baseline: direct canonical MySMIS observations recorded
# by PARTENER.EU on 2026-08-12. After the first successful run the current
# canonical snapshot is stored in the feed item and becomes the baseline.
BASELINE={
'6d68ba2cacb203e077d5':{'programme':'Program Incluziune și Demnitate Socială','call':'Servicii de îngrijire la domiciliu pentru persoanele vârstnice - Regiuni mai putin dezvoltate','status':'FINALIZAT','contracts':'147','callBudgetRon':'486.535.603','totalProjectBudgetRon':'82.965.454.363','submittedGrantBudgetRon':'1.726.250.853'},
'd51e289bfad269b11210':{'programme':'Program Dezvoltare Durabilă și Tranziție Justă (fost PTJ)','call':'DJ-Sprijin pentru dezvoltarea microîntreprinderilor','status':'FINALIZAT','contracts':'54','callBudgetRon':'181.407.092','totalProjectBudgetRon':'12.841.264.383','submittedGrantBudgetRon':'575.424.052'},
'd1dca0c5f73236b508b7':{'programme':'Program Regional Sud-Est','call':'Apel PRSE/1.6/A.2/1/2025_Operațiunea A.2 Creșterea competitivității IMM-urilor','status':'FINALIZAT','contracts':'2','callBudgetRon':'438.898.831','totalProjectBudgetRon':'196.698.061.081','submittedGrantBudgetRon':'2.160.447.247'},
'ba7f1d2c724617cd40c5':{'programme':'Program Educație și Ocupare','call':'“Ține pasul” - Regiuni mai putin dezvoltate','status':'FINALIZAT','contracts':'286','callBudgetRon':'499.299.881','totalProjectBudgetRon':'133.714.835.106','submittedGrantBudgetRon':'2.378.139.845'}
}


def clean(v): return re.sub(r'\s+',' ',html_lib.unescape(str(v or ''))).strip()
def now(): return dt.datetime.now(dt.timezone.utc)

def fetch(url,timeout=12,max_bytes=3_000_000):
    req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'text/html,application/xhtml+xml','Accept-Language':'ro,en;q=0.7'})
    with urllib.request.urlopen(req,timeout=timeout,context=ssl.create_default_context()) as r:
        return r.geturl(),r.read(max_bytes).decode('utf-8','ignore')

def canonical(u,base):
    u=urllib.parse.urljoin(base,u);p=urllib.parse.urlparse(u)
    if p.scheme not in ('http','https') or (p.hostname or '').lower() not in ('mfe.gov.ro','www.mfe.gov.ro'): return None
    path=re.sub(r'/{2,}','/',p.path or '/')
    if not (path.startswith('/ghiduri_peos/') or path.startswith('/ghiduri_pids/') or path.startswith('/pdds/') or path.startswith('/wp-content/uploads/')): return None
    return urllib.parse.urlunparse(('https','mfe.gov.ro',path,'','',''))

def infer(u):
    if '/ghiduri_peos/' in u:return 'PEO'
    if '/ghiduri_pids/' in u:return 'PoIDS'
    if '/pdds/' in u:return 'PDDS'
    return 'MIPE'

class T(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.rows=[];self.row=None;self.cell=None;self.buf=[]
    def handle_starttag(self,t,a):
        if t=='tr': self.row=[]
        elif t in ('td','th') and self.row is not None:self.cell=t;self.buf=[]
    def handle_data(self,d):
        if self.cell is not None:self.buf.append(d)
    def handle_endtag(self,t):
        if t in ('td','th') and self.cell==t and self.row is not None:
            self.row.append(clean(' '.join(self.buf)));self.cell=None;self.buf=[]
        elif t=='tr' and self.row is not None:
            if self.row:self.rows.append(self.row)
            self.row=None;self.cell=None;self.buf=[]

def parse_mysmis(raw):
    if 'Apeluri validate 2021-2027' not in raw: raise RuntimeError('expected registry marker missing')
    total=None;m=re.search(r'1\s*-\s*50\s*of\s*([0-9][0-9.,]*)',clean(raw),re.I)
    if m: total=int(re.sub(r'\D','',m.group(1)))
    p=T();p.feed(raw);rows={};statuses=set()
    for c in p.rows:
        if len(c)<12:continue
        programme,call_type,call,status=c[:4]
        if not programme or not call or programme.lower().startswith('program opera'):continue
        if not any(k in programme.lower() for k in ('program','fondul')):continue
        key=hashlib.sha256((programme+'\n'+call).encode()).hexdigest()[:20]
        rows[key]={'programme':programme,'type':call_type,'call':call,'status':status,'entities':c[4],'drafts':c[5],'submitted':c[6],'contracts':c[7],'withdrawn':c[8],'callBudgetRon':c[9],'totalProjectBudgetRon':c[10],'submittedGrantBudgetRon':c[11]}
        if status:statuses.add(status)
    if not rows:raise RuntimeError('registry table parsed with zero rows')
    return total,rows,sorted(statuses)

def changes(old,new):
    fields=[('status','status'),('contracts','contracts'),('callBudgetRon','call budget'),('totalProjectBudgetRon','total project budget'),('submittedGrantBudgetRon','submitted grant budget')]
    out=[]
    for k,b in old.items():
        c=new.get(k)
        if not c:continue
        d=[f"{label}: {b.get(field,'—')} → {c.get(field,'—')}" for field,label in fields if str(b.get(field,''))!=str(c.get(field,''))]
        if d:out.append({'call':c['call'],'change':'; '.join(d)})
    return out

def snapshot_signature(total,rows):
    payload={'validatedCallCount':total,'rows':rows}
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def persist_state(state):
    STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def ingest_mysmis():
    state=json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {'status':'SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED','items':[],'runs':[]}
    byurl={x.get('url'):x for x in state.get('items',[]) if isinstance(x,dict) and x.get('url')}
    prior=byurl.get(MYSMIS,{})
    baseline=prior.get('registrySnapshot') or BASELINE
    try:
        final,raw=fetch(MYSMIS,20,4_000_000)
        if not final.startswith('https://reporting.mysmis2021.gov.ro/'):raise RuntimeError(f'redirected outside official MySMIS host: {final}')
        total,rows,statuses=parse_mysmis(raw)
    except Exception as e:
        return {'ok':False,'preserved':True,'error':f'{type(e).__name__}: {e}'}
    diff=changes(baseline,rows)
    old_count=prior.get('validatedCallCount')
    count_changed=old_count is not None and old_count!=total
    semantic_candidate=not prior or bool(diff) or count_changed
    observed=now()

    # Fail closed on transient/oscillating official values. A semantic change
    # must be observed identically in two consecutive canonical runs before it
    # can replace the last-known-good feed item. This prevents load-balanced or
    # mid-refresh MySMIS responses from making News bounce between snapshots.
    if prior and semantic_candidate:
        sig=snapshot_signature(total,rows)
        pending=state.get('mysmisPendingChange') if isinstance(state.get('mysmisPendingChange'),dict) else None
        if pending and pending.get('signature')==sig:
            confirmations=int(pending.get('confirmations',1))+1
            first_observed=pending.get('firstObservedAt') or observed.isoformat()
        else:
            confirmations=1
            first_observed=observed.isoformat()
        state['mysmisPendingChange']={
            'signature':sig,
            'firstObservedAt':first_observed,
            'lastObservedAt':observed.isoformat(),
            'confirmations':confirmations,
            'validatedCallCount':total,
            'changes':diff[:5],
            'publicationPolicy':'publish only after two consecutive identical direct canonical observations'
        }
        if confirmations<2:
            persist_state(state)
            return {'ok':True,'url':MYSMIS,'validatedCallCount':total,'visibleRowCount':len(rows),'explicitStatuses':statuses,'semanticChange':False,'pendingSemanticChange':True,'pendingConfirmations':confirmations,'preserved':True,'changes':diff[:5]}
    elif not semantic_candidate and state.pop('mysmisPendingChange',None) is not None:
        persist_state(state)

    semantic=semantic_candidate
    if semantic:
        parts=[]
        if count_changed:parts.append(f'validated-call count: {old_count} → {total}')
        parts += [f"{x['call']}: {x['change']}" for x in diff[:5]]
        if parts: summary='Official MySMIS reporting changed since the last direct canonical snapshot. '+' | '.join(parts)+'. '
        else: summary=f'Official MySMIS reporting was verified directly and currently lists {total if total is not None else "the current set of"} validated calls for 2021–2027. '
        summary+='No OPEN state is inferred; the source status is preserved exactly as published.'
        day=observed.date()
        byurl[MYSMIS]={'id':hashlib.sha256(MYSMIS.encode()).hexdigest()[:20],'title':'MySMIS official funding registry changed' if parts else f'MySMIS official funding registry verified: {total} validated calls','url':MYSMIS,'date':day.isoformat(),'dateLabel':f'{day.day} {MONTHS[day.month-1]} {day.year}','summary':summary[:1400],'tag':'MySMIS','kind':'OFFICIAL_UPDATE','tier':'T1','source':'MIPE / MySMIS','observedAt':observed.isoformat(),'discovery':'canonical-official-fetch','verification':'CANONICAL_OFFICIAL_FETCH','explicitStatuses':statuses,'validatedCallCount':total,'registrySnapshot':rows}
        state['items']=sorted(byurl.values(),key=lambda x:(x.get('date',''),x.get('observedAt','')),reverse=True)[:80]
        state.pop('mysmisPendingChange',None)
        persist_state(state)
    return {'ok':True,'url':MYSMIS,'validatedCallCount':total,'visibleRowCount':len(rows),'explicitStatuses':statuses,'semanticChange':semantic,'changes':diff[:5]}

def main():
    src=json.loads(SOURCES.read_text(encoding='utf-8')).get('sources',[])
    obj=json.loads(SEEDS.read_text(encoding='utf-8'))
    items=obj.get('items',[]);known={x['url'] for x in items};added=[];failures=[]
    for s in src:
        if s.get('role')!='T2_OFFICIAL_DISCOVERY_ONLY':continue
        url=s['url']
        try:
            _,raw=fetch(url)
            hrefs=re.findall(r'href\s*=\s*["\']([^"\']+)["\']',raw,re.I)
            hrefs+=re.findall(r'https?://(?:www\.)?mfe\.gov\.ro/[^\s<"\']+',raw,re.I)
            for h in hrefs:
                u=canonical(h,url)
                if not u or u in known:continue
                known.add(u);item={'url':u,'programme':infer(u),'titleHint':'','discoveredVia':url};items.append(item);added.append(item)
        except Exception as e:failures.append({'source':url,'error':f'{type(e).__name__}: {e}'})
    if added:
        obj['version']=int(obj.get('version',1))+1;obj['items']=items;SEEDS.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    mysmis=ingest_mysmis()
    print(json.dumps({'discoverySourceCount':sum(1 for s in src if s.get('role')=='T2_OFFICIAL_DISCOVERY_ONLY'),'newCanonicalSeeds':len(added),'added':added,'failures':failures,'mysmis':mysmis},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
