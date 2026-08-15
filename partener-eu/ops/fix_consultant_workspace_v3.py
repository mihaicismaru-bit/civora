#!/usr/bin/env python3
"""Apply baseline, idempotent corrections to Consultant Workspace v3.

Client CRUD is owned by fix_consultant_crud_v4.py. This fixer deliberately
avoids competing handlers and only repairs shared screening/state primitives.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "partener-eu" / "web" / "consultant-workspace-v3.js"
text = PATH.read_text(encoding="utf-8")
changed = False

legacy = "if(!dataGate(call.cofinancing).state==='PASS')unknowns.push('Cofinanțare neextrasă');"
fixed = "if(dataGate(call.cofinancing).state!=='PASS')unknowns.push('Cofinanțare neextrasă');"
if legacy in text:
    text = text.replace(legacy, fixed, 1); changed = True
if fixed not in text:
    raise SystemExit('Consultant cofinancing gate contract missing')

old_status = "function statusGate(call){if(call.status==='CLOSED'||call.status==='CANCELLED')return {state:'FAIL',label:'Apel inactiv',detail:call.status};if(call.status==='OPEN')return {state:'PASS',label:'Apel deschis',detail:call.close||'Termen neextras'};if(['EXPECTED','PUBLIC_CONSULTATION','ANNOUNCED'].includes(call.status))return {state:'UNKNOWN',label:'Pregătire / monitorizare',detail:call.status};return {state:'UNKNOWN',label:'Status de verificat',detail:call.status||'Necunoscut'}}"
new_status = "function statusGate(call){if(call.status==='CLOSED'||call.status==='CANCELLED')return {state:'FAIL',label:'Apel inactiv',detail:call.status};if(call.status==='OPEN'){const deadline=parseDeadline(call.close);if(deadline&&deadline<Date.now())return {state:'FAIL',label:'Termen expirat / status de reconciliat',detail:`Termen în corpus: ${call.close}. Verifică o eventuală prelungire înainte de acțiune.`};return {state:'PASS',label:'Apel deschis',detail:call.close||'Termen neextras'}}if(['EXPECTED','PUBLIC_CONSULTATION','ANNOUNCED'].includes(call.status))return {state:'UNKNOWN',label:'Pregătire / monitorizare',detail:call.status};return {state:'UNKNOWN',label:'Status de verificat',detail:call.status||'Necunoscut'}}"
if old_status in text:
    text = text.replace(old_status, new_status, 1); changed = True
if 'Termen expirat / status de reconciliat' not in text:
    raise SystemExit('Consultant expired-deadline hard gate missing')

if 'demoClientsRemoved:false' not in text:
    raise SystemExit('Consultant persistent demo-client preference missing')

if changed:
    PATH.write_text(text, encoding='utf-8')
print('Consultant baseline v3: PASS')
