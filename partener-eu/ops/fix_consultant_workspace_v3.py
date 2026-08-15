#!/usr/bin/env python3
"""Apply small, idempotent source corrections to Consultant Workspace v3."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "partener-eu" / "web" / "consultant-workspace-v3.js"
text = PATH.read_text(encoding="utf-8")
changed = False

replacements = [
    (
        "if(!dataGate(call.cofinancing).state==='PASS')unknowns.push('Cofinanțare neextrasă');",
        "if(dataGate(call.cofinancing).state!=='PASS')unknowns.push('Cofinanțare neextrasă');",
        "cofinancing unknown-state comparison",
    ),
    (
        "state.selectedClientId=state.clients[0]?.id||null;state.tab='dashboard';persist();renderWorkspace()};\n root.querySelectorAll('[data-cw3-remove-demo]')",
        "state.selectedClientId=state.clients[0]?.id||null;state.tab='dashboard';persist();renderWorkspace()});\n root.querySelectorAll('[data-cw3-remove-demo]')",
        "delete-client forEach closure",
    ),
    (
        "function baseState(){return {version:3,clients:[],selectedClientId:null,tab:'dashboard',selectedCallId:null,tracked:{},compare:{},tasks:[],evaluations:{},filters:{q:'',status:'ALL',minScore:0,onlyTracked:false},editingClient:null,updatedAt:new Date().toISOString()}}",
        "function baseState(){return {version:3,clients:[],selectedClientId:null,tab:'dashboard',selectedCallId:null,tracked:{},compare:{},tasks:[],evaluations:{},filters:{q:'',status:'ALL',minScore:0,onlyTracked:false},editingClient:null,demoClientsRemoved:false,updatedAt:new Date().toISOString()}}",
        "persistent demo-client preference",
    ),
    (
        "function mergeSeeds(s){for(const raw of (D.clients||[])){if(!s.clients.some(c=>c.id===raw.id))s.clients.push(normaliseClient({...raw,seed:true}))}if(!s.selectedClientId&&s.clients[0])s.selectedClientId=s.clients[0].id;s.tracked=s.tracked||{};s.compare=s.compare||{};s.tasks=Array.isArray(s.tasks)?s.tasks:[];s.evaluations=s.evaluations||{};s.filters={q:'',status:'ALL',minScore:0,onlyTracked:false,...(s.filters||{})};s.version=3;return s}",
        "function mergeSeeds(s){if(!s.demoClientsRemoved){for(const raw of (D.clients||[])){if(!s.clients.some(c=>c.id===raw.id))s.clients.push(normaliseClient({...raw,seed:true}))}}if(!s.selectedClientId&&s.clients[0])s.selectedClientId=s.clients[0].id;s.tracked=s.tracked||{};s.compare=s.compare||{};s.tasks=Array.isArray(s.tasks)?s.tasks:[];s.evaluations=s.evaluations||{};s.filters={q:'',status:'ALL',minScore:0,onlyTracked:false,...(s.filters||{})};s.version=3;return s}",
        "demo-client seed guard",
    ),
    (
        "state.tasks=state.tasks.filter(t=>!ids.has(t.clientId));state.selectedClientId=state.clients[0]?.id||null;state.editingClient=state.clients.length?null:'new';persist();renderWorkspace()});",
        "state.tasks=state.tasks.filter(t=>!ids.has(t.clientId));state.demoClientsRemoved=true;state.selectedClientId=state.clients[0]?.id||null;state.editingClient=state.clients.length?null:'new';persist();renderWorkspace()});",
        "demo-client removal persistence",
    ),
    (
        "function statusGate(call){if(call.status==='CLOSED'||call.status==='CANCELLED')return {state:'FAIL',label:'Apel inactiv',detail:call.status};if(call.status==='OPEN')return {state:'PASS',label:'Apel deschis',detail:call.close||'Termen neextras'};if(['EXPECTED','PUBLIC_CONSULTATION','ANNOUNCED'].includes(call.status))return {state:'UNKNOWN',label:'Pregătire / monitorizare',detail:call.status};return {state:'UNKNOWN',label:'Status de verificat',detail:call.status||'Necunoscut'}}",
        "function statusGate(call){if(call.status==='CLOSED'||call.status==='CANCELLED')return {state:'FAIL',label:'Apel inactiv',detail:call.status};if(call.status==='OPEN'){const deadline=parseDeadline(call.close);if(deadline&&deadline<Date.now())return {state:'FAIL',label:'Termen expirat / status de reconciliat',detail:`Termen în corpus: ${call.close}. Verifică o eventuală prelungire înainte de acțiune.`};return {state:'PASS',label:'Apel deschis',detail:call.close||'Termen neextras'}}if(['EXPECTED','PUBLIC_CONSULTATION','ANNOUNCED'].includes(call.status))return {state:'UNKNOWN',label:'Pregătire / monitorizare',detail:call.status};return {state:'UNKNOWN',label:'Status de verificat',detail:call.status||'Necunoscut'}}",
        "expired-deadline hard gate",
    ),
]

for old, new, label in replacements:
    if new in text:
        print(f"Consultant v3 {label}: already fixed")
    elif old in text:
        text = text.replace(old, new, 1)
        changed = True
        print(f"Consultant v3 {label}: fixed")
    else:
        raise SystemExit(f"Expected Consultant v3 source pattern not found for {label}; refusing blind edit")

if changed:
    PATH.write_text(text, encoding="utf-8")
