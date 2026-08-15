#!/usr/bin/env python3
from __future__ import annotations
import ast, datetime as dt, json, re
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[2]
PRODUCTS=ROOT/'partener-eu'/'ingest'/'state'/'decision_products.json'
OUT_JS=ROOT/'partener-eu'/'web'/'decision-products.js'
MONTHS=['ianuarie','februarie','martie','aprilie','mai','iunie','iulie','august','septembrie','octombrie','noiembrie','decembrie']
ENGLISH={
 'Eligible applicant':'Solicitant eligibil','Eligible applicants':'Solicitanți eligibili',
 'Mandatory institutional partner':'Partener instituțional obligatoriu','Institutional partner':'Partener instituțional',
 'Individual applicant':'Solicitant individual','Partnership':'Parteneriat','Excluded':'Excluderi',
 'Competitive':'Competitiv','Maximum points':'Punctaj maxim','Minimum quality points':'Prag minim de calitate',
 'Minimum project points':'Prag minim al proiectului','Number of criteria':'Număr de criterii','Ranking':'Clasament',
 'Tie breaker':'Criteriu de departajare','UPDATE':'ACTUALIZARE','OPEN':'DESCHIS','PREPARE':'PREGĂTEȘTE',
 'VERIFY':'VERIFICĂ','REFERENCE':'REFERINȚĂ','ACT NOW':'ACȚIONEAZĂ ACUM'
}

def ro_date(s:str)->str:
    try:
        v=s.strip()
        if not re.match(r'^20\d\d-\d\d-\d\dT',v): return s
        x=dt.datetime.fromisoformat(v.replace('Z','+00:00'))
        out=f"{x.day} {MONTHS[x.month-1]} {x.year}"
        if x.hour or x.minute: out+=f", {x.hour:02d}:{x.minute:02d}"
        return out
    except Exception:return s

def clean_text(s:Any)->str:
    t=str(s or '').strip()
    t=ro_date(t)
    for a,b in ENGLISH.items():
        t=re.sub(rf'\b{re.escape(a)}\b',b,t,flags=re.I)
    return re.sub(r'\s+',' ',t).strip()

def raw_object(v:Any)->bool:
    return isinstance(v,(dict,list)) or (isinstance(v,str) and v.strip().startswith(('{','[')))

def compact_object(v:Any,label:str)->str:
    obj=v
    if isinstance(v,str):
        try: obj=ast.literal_eval(v)
        except Exception:
            try: obj=json.loads(v)
            except Exception:return 'Detalii disponibile în dosarul complet'
    if not isinstance(obj,dict):return 'Detalii disponibile în dosarul complet'
    if label in {'Grant','Finanțare / valoare proiect','Valoare proiect'}:
        maxv=obj.get('maximum_total_project_value_eur') or obj.get('maximum_eur')
        intensity=obj.get('eligible_cost_intensity_percent')
        form=obj.get('form')
        parts=[]
        if form: parts.append(clean_text(form))
        if maxv:
            try: parts.append(f"valoare maximă proiect: {float(maxv):,.0f} EUR".replace(',','.'))
            except Exception: pass
        if intensity is not None: parts.append(f"finanțare de până la {intensity}%")
        rule=obj.get('cofinancing_rule')
        if rule: parts.append(clean_text(rule))
        return ' · '.join(parts[:3]) or 'Detalii disponibile în dosarul complet'
    if label=='Buget':
        for k,curr in [('session_total_eur','EUR'),('total_eur','EUR'),('callBudgetRon','RON')]:
            if obj.get(k) is not None:
                try:return f"{float(obj[k]):,.0f} {curr}".replace(',','.')
                except Exception:return clean_text(obj[k])
    return 'Detalii disponibile în dosarul complet'

def main()->int:
    p=json.loads(PRODUCTS.read_text(encoding='utf-8'))
    for d in p.get('dossiers',[]):
        d['statusLabel']=clean_text(d.get('statusLabel') or d.get('status'))
        d['decisionLabel']=clean_text(d.get('decisionLabel') or d.get('decision'))
        d['audience']=[clean_text(x) for x in d.get('audience') or []]
        d['standfirst']=clean_text(d.get('standfirst'))
        d['decisionAction']=clean_text(d.get('decisionAction'))
        for f in d.get('quickFacts') or []:
            label=str(f.get('label') or '')
            value=f.get('value')
            if raw_object(value):
                f['value']=compact_object(value,label)
                if label=='Grant' and 'valoare maximă proiect' in f['value'].lower(): f['label']='Finanțare / valoare proiect'
            else:f['value']=clean_text(value)
        for sec in d.get('sections') or []:
            sec['items']=[clean_text(x) if not raw_object(x) else compact_object(x,sec.get('title','')) for x in sec.get('items') or []]
    kinds={'CALL_OPENED':'APEL DESCHIS','DEADLINE_EXTENDED':'TERMEN PRELUNGIT','GUIDE_PUBLISHED':'GHID PUBLICAT','GUIDE_MODIFIED':'GHID MODIFICAT','CONSULTATION_OPENED':'CONSULTARE PUBLICĂ','CALL_CLOSED':'APEL ÎNCHIS','RESULTS_PUBLISHED':'REZULTATE PUBLICATE','OFFICIAL_UPDATE':'ACTUALIZARE OFICIALĂ'}
    for n in p.get('news',[]):
        n['kindLabel']=kinds.get(n.get('kind'),clean_text(n.get('kind')))
        for k in ('headline','standfirst','meaning'): n[k]=clean_text(n.get(k))
        for k in ('confirmed','notConfirmed','actions','audience'): n[k]=[clean_text(x) for x in n.get(k) or []]
    p.setdefault('policy',{})['publicRomanianOnly']=True
    p['policy']['rawTechnicalObjectsVisible']=False
    PRODUCTS.write_text(json.dumps(p,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    OUT_JS.write_text('window.PARTENER_DECISION_PRODUCTS='+json.dumps(p,ensure_ascii=False,separators=(',',':'))+';\nwindow.PARTENER_DATA=window.PARTENER_DATA||{};\nwindow.PARTENER_DATA.decisionProducts=window.PARTENER_DECISION_PRODUCTS;\n',encoding='utf-8')
    print(json.dumps({'dossiers':len(p.get('dossiers',[])),'romanianOnly':True,'rawObjects':False},ensure_ascii=False))
    return 0
if __name__=='__main__':raise SystemExit(main())
