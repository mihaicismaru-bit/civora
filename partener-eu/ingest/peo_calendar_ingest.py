#!/usr/bin/env python3
import datetime as dt
import hashlib
import json
import re
import urllib.request
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / 'partener-eu/ingest/state/peo_calendar_state.json'
OUT = ROOT / 'partener-eu/web/peo-calendar.js'

MIPE_CONTAINER = 'https://mfe.gov.ro/peos/calendar-lansari-apeluri/'
OIR_PROGRAM_PAGE = 'https://oirvest.ro/program-peo-programul-educatie-si-ocupare/'
OIR_XLSX = 'https://oirvest.ro/wp-content/uploads/Calendarul-estimativ-consolidat-al-lansarilor-de-apeluri-de-proiecte.xlsx'
MIPE_CM_2026 = 'https://mfe.gov.ro/wp-content/uploads/2026/05/ce7339fe643b3ee00e250662c1aa10b3-2.pdf'

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36'


def now():
    return dt.datetime.now(dt.timezone.utc)


def clean(v):
    if v is None:
        return ''
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return re.sub(r'\s+', ' ', str(v)).strip()


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
    with urllib.request.urlopen(req, timeout=25) as r:
        data = r.read()
        return data, getattr(r, 'status', 200), r.headers.get('Content-Type', '')


def norm_header(s):
    s = clean(s).lower()
    table = str.maketrans('ăâîșşțţ', 'aaisstt')
    s = s.translate(table)
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def header_score(row):
    text = ' | '.join(norm_header(x) for x in row)
    keys = ['apel', 'prioritate', 'actiune', 'alocare', 'buget', 'lansare', 'data', 'perioada', 'solicitant']
    return sum(1 for k in keys if k in text)


def find_header(rows):
    best = (0, 0)
    for i, row in enumerate(rows[:40]):
        s = header_score(row)
        if s > best[1]:
            best = (i, s)
    return best[0] if best[1] >= 2 else 0


def classify_columns(headers):
    out = {}
    for i, h in enumerate(headers):
        n = norm_header(h)
        if not n:
            continue
        if 'prioritat' in n and 'prioritate' not in out: out['priority'] = i
        elif ('denumire' in n and 'apel' in n) or n == 'apel' or 'titlu apel' in n: out['title'] = i
        elif 'actiune' in n and 'action' not in out: out['action'] = i
        elif ('alocare' in n or 'buget' in n) and 'budget' not in out: out['budget'] = i
        elif ('data' in n and 'lans' in n) or ('lansare' in n and 'launch' not in out): out['launch'] = i
        elif ('tip' in n and 'apel' in n) and 'callType' not in out: out['callType'] = i
        elif ('solicitant' in n or 'beneficiar' in n) and 'applicants' not in out: out['applicants'] = i
        elif ('observ' in n or 'mentiuni' in n) and 'notes' not in out: out['notes'] = i
    return out


def cell(row, idx):
    if idx is None or idx >= len(row): return ''
    return clean(row[idx])


def parse_workbook(blob):
    wb = load_workbook(BytesIO(blob), data_only=True, read_only=True)
    diagnostics = []
    items = []
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        if not rows: continue
        hi = find_header(rows)
        headers = [clean(x) for x in rows[hi]]
        cols = classify_columns(headers)
        diagnostics.append({'sheet': ws.title, 'rows': len(rows), 'cols': len(headers), 'headerRow': hi + 1, 'headers': headers[:30], 'mapped': cols})
        if 'title' not in cols:
            continue
        for rn, row in enumerate(rows[hi+1:], start=hi+2):
            title = cell(row, cols.get('title'))
            if len(title) < 5:
                continue
            text = ' '.join(clean(x) for x in row)
            if not re.search(r'[A-Za-zĂÂÎȘȚăâîșț]', title):
                continue
            raw_launch = cell(row, cols.get('launch'))
            status = 'PLANNED'
            if any(x in text.lower() for x in ['lansat', 'lansată', 'lansata']): status = 'MATERIALIZED_HINT'
            key = hashlib.sha256((ws.title+'|'+title+'|'+cell(row, cols.get('priority'))).encode('utf-8')).hexdigest()[:18]
            items.append({
                'id': key,
                'programme': 'PEO',
                'priority': cell(row, cols.get('priority')),
                'action': cell(row, cols.get('action')),
                'title': title,
                'budget': cell(row, cols.get('budget')),
                'plannedLaunch': raw_launch,
                'callType': cell(row, cols.get('callType')),
                'applicants': cell(row, cols.get('applicants')),
                'notes': cell(row, cols.get('notes')),
                'calendarStatus': status,
                'materialization': 'NOT_YET_VERIFIED',
                'sourceSheet': ws.title,
                'sourceRow': rn,
            })
    return items, diagnostics


def load_state():
    try: return json.loads(STATE.read_text(encoding='utf-8'))
    except: return {'versions': [], 'items': []}


def main():
    observed = now().isoformat()
    prev = load_state()
    try:
        blob, code, ctype = fetch(OIR_XLSX)
        if len(blob) < 1000: raise RuntimeError('downloaded workbook too small')
        sha = hashlib.sha256(blob).hexdigest()
        items, diag = parse_workbook(blob)
        if not items: raise RuntimeError('workbook parsed but no calendar items found')
        old_by_id = {x.get('id'):x for x in prev.get('items', [])}
        changes=[]
        for x in items:
            old=old_by_id.get(x['id'])
            if not old:
                changes.append({'kind':'CALENDAR_ITEM_ADDED','id':x['id'],'title':x['title']})
                continue
            for f in ['plannedLaunch','budget','priority','callType','notes']:
                if clean(old.get(f)) != clean(x.get(f)):
                    changes.append({'kind':'CALENDAR_ITEM_CHANGED','id':x['id'],'title':x['title'],'field':f,'before':old.get(f,''),'after':x.get(f,'')})
        version={'observedAt':observed,'sha256':sha,'bytes':len(blob),'itemCount':len(items),'changes':len(changes),'source':OIR_XLSX}
        versions=(prev.get('versions') or [])
        if not versions or versions[-1].get('sha256') != sha:
            versions=(versions+[version])[-30:]
        state={
            'status':'OK_OFFICIAL_OIR_COPY',
            'lastRun':version,
            'canonicalContainer':MIPE_CONTAINER,
            'supportingOfficialReference':MIPE_CM_2026,
            'retrievalSource':OIR_XLSX,
            'retrievalSourceClass':'OFFICIAL_INSTITUTIONAL_COPY_OIR_PECU_VEST',
            'directMipeVerified':False,
            'items':items,
            'changes':changes[:200],
            'diagnostics':diag,
            'versions':versions,
        }
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        payload={
            'status':state['status'],'asOf':observed,'programme':'PEO','title':'Calendar estimativ consolidat al lansărilor de apeluri de proiecte',
            'canonicalContainer':MIPE_CONTAINER,'retrievalSource':OIR_XLSX,'retrievalSourceClass':state['retrievalSourceClass'],
            'directMipeVerified':False,'versionSha256':sha,'itemCount':len(items),'changeCount':len(changes),
            'items':items,'changes':changes[:100]
        }
        OUT.write_text('window.PARTENER_DATA=window.PARTENER_DATA||{};\nwindow.PARTENER_DATA.peoCalendar='+json.dumps(payload,ensure_ascii=False,separators=(',',':'))+';\n',encoding='utf-8')
        print(json.dumps({'status':state['status'],'sha256':sha,'itemCount':len(items),'changeCount':len(changes),'diagnostics':diag},ensure_ascii=False,indent=2))
    except Exception as e:
        # fail closed: preserve last known good calendar and record failure separately
        fail={'observedAt':observed,'error':f'{type(e).__name__}: {e}','source':OIR_XLSX}
        prev['lastFailure']=fail
        prev['status']='SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED'
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(prev,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'status':prev['status'],'failure':fail},ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
