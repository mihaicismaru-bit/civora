#!/usr/bin/env python3
"""Apply idempotent production corrections to Consultant Workspace v3."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "partener-eu" / "web" / "consultant-workspace-v3.js"
INDEX = ROOT / "partener-eu" / "web" / "index.html"
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
        "function baseState(){return {version:3,clients:[],selectedClientId:null,tab:'dashboard',selectedCallId:null,tracked:{},compare:{},tasks:[],evaluations:{},filters:{q:'',status:'ALL',minScore:0,onlyTracked:false},editingClient:null,demoClientsRemoved:false,deletedClientIds:[],updatedAt:new Date().toISOString()}}",
        "persistent client tombstones",
    ),
    (
        "function baseState(){return {version:3,clients:[],selectedClientId:null,tab:'dashboard',selectedCallId:null,tracked:{},compare:{},tasks:[],evaluations:{},filters:{q:'',status:'ALL',minScore:0,onlyTracked:false},editingClient:null,demoClientsRemoved:false,updatedAt:new Date().toISOString()}}",
        "function baseState(){return {version:3,clients:[],selectedClientId:null,tab:'dashboard',selectedCallId:null,tracked:{},compare:{},tasks:[],evaluations:{},filters:{q:'',status:'ALL',minScore:0,onlyTracked:false},editingClient:null,demoClientsRemoved:false,deletedClientIds:[],updatedAt:new Date().toISOString()}}",
        "upgrade existing base state with tombstones",
    ),
    (
        "function mergeSeeds(s){if(!s.demoClientsRemoved){for(const raw of (D.clients||[])){if(!s.clients.some(c=>c.id===raw.id))s.clients.push(normaliseClient({...raw,seed:true}))}}if(!s.selectedClientId&&s.clients[0])s.selectedClientId=s.clients[0].id;s.tracked=s.tracked||{};s.compare=s.compare||{};s.tasks=Array.isArray(s.tasks)?s.tasks:[];s.evaluations=s.evaluations||{};s.filters={q:'',status:'ALL',minScore:0,onlyTracked:false,...(s.filters||{})};s.version=3;return s}",
        "function mergeSeeds(s){s.clients=Array.isArray(s.clients)?s.clients.map(normaliseClient):[];s.deletedClientIds=Array.isArray(s.deletedClientIds)?s.deletedClientIds:[];const deleted=new Set(s.deletedClientIds);if(!s.demoClientsRemoved){for(const raw of (D.clients||[])){if(!deleted.has(raw.id)&&!s.clients.some(c=>c.id===raw.id))s.clients.push(normaliseClient({...raw,seed:true}))}}if(s.selectedClientId&&!s.clients.some(c=>c.id===s.selectedClientId))s.selectedClientId=null;if(!s.selectedClientId&&s.clients[0])s.selectedClientId=s.clients[0].id;s.tracked=s.tracked||{};s.compare=s.compare||{};s.tasks=Array.isArray(s.tasks)?s.tasks:[];s.evaluations=s.evaluations||{};s.filters={q:'',status:'ALL',minScore:0,onlyTracked:false,...(s.filters||{})};s.version=3;return s}",
        "seed resurrection guard",
    ),
    (
        "state.tasks=state.tasks.filter(t=>!ids.has(t.clientId));state.demoClientsRemoved=true;state.selectedClientId=state.clients[0]?.id||null;state.editingClient=state.clients.length?null:'new';persist();renderWorkspace()});",
        "state.tasks=state.tasks.filter(t=>!ids.has(t.clientId));state.demoClientsRemoved=true;state.deletedClientIds=[...new Set([...(state.deletedClientIds||[]),...ids])];state.selectedClientId=state.clients[0]?.id||null;state.editingClient=state.clients.length?null:'new';persistNow().finally(()=>renderWorkspace())});",
        "demo-client removal persistence",
    ),
    (
        "const form=document.getElementById('cw3ClientForm');if(form)form.onsubmit=e=>{e.preventDefault();const isNew=form.dataset.new==='1';const base=isNew?{}:selectedClient();const client=readClientForm(base);if(isNew){state.clients.push(client);state.selectedClientId=client.id}else{const i=state.clients.findIndex(c=>c.id===client.id);state.clients[i]=client}state.editingClient=null;state.tab='dashboard';persist();renderWorkspace()};",
        "const form=document.getElementById('cw3ClientForm');if(form)form.onsubmit=async e=>{e.preventDefault();const isNew=form.dataset.new==='1';const base=isNew?{}:selectedClient();const client=readClientForm(base);if(!client.name.trim()){alert('Introdu numele organizației.');return}if(isNew){state.clients.push(client);state.selectedClientId=client.id}else{const i=state.clients.findIndex(c=>c.id===client.id);if(i<0){alert('Clientul nu mai există în portofoliu. Reîncarcă pagina.');return}state.clients[i]=client}state.deletedClientIds=(state.deletedClientIds||[]).filter(id=>id!==client.id);state.editingClient=null;state.tab='dashboard';await persistNow();await renderWorkspace()};",
        "atomic add/edit client persistence",
    ),
    (
        "root.querySelectorAll('[data-cw3-delete-client]').forEach(b=>b.onclick=async()=>{const client=selectedClient();if(!client||!confirm(`Ștergi clientul ${client.name}?`))return;state.clients=state.clients.filter(c=>c.id!==client.id);delete state.tracked[client.id];delete state.compare[client.id];state.tasks=state.tasks.filter(t=>t.clientId!==client.id);for(const key of Object.keys(state.evaluations))if(key.startsWith(client.id+':'))delete state.evaluations[key];for(const doc of await idbListDocuments(client.id))await idbDeleteDocument(doc.id);state.selectedClientId=state.clients[0]?.id||null;state.tab='dashboard';persist();renderWorkspace()});",
        "root.querySelectorAll('[data-cw3-delete-client]').forEach(b=>b.onclick=async()=>{const client=selectedClient();if(!client||!confirm(`Ștergi definitiv clientul ${client.name}?`))return;state.clients=state.clients.filter(c=>c.id!==client.id);state.deletedClientIds=[...new Set([...(state.deletedClientIds||[]),client.id])];delete state.tracked[client.id];delete state.compare[client.id];state.tasks=state.tasks.filter(t=>t.clientId!==client.id);for(const key of Object.keys(state.evaluations))if(key.startsWith(client.id+':'))delete state.evaluations[key];try{for(const doc of await idbListDocuments(client.id))await idbDeleteDocument(doc.id)}catch(err){console.warn('Document cleanup skipped during client deletion',err)}state.selectedClientId=state.clients[0]?.id||null;state.editingClient=state.clients.length?null:'new';state.tab=state.clients.length?'dashboard':'profile';await persistNow();await renderWorkspace()});",
        "resilient client deletion",
    ),
    (
        "root.querySelectorAll('[data-cw3-new-client]').forEach(b=>b.onclick=()=>{state.editingClient='new';state.tab='profile';renderWorkspace()});",
        "root.querySelectorAll('[data-cw3-new-client]').forEach(b=>b.onclick=async()=>{state.editingClient='new';state.tab='profile';await renderWorkspace();setTimeout(()=>document.getElementById('cw3Name')?.focus(),0)});",
        "new client interaction",
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
        # Two base-state variants are alternatives across revisions.
        if label in {"persistent client tombstones", "upgrade existing base state with tombstones"} and "deletedClientIds:[]" in text:
            print(f"Consultant v3 {label}: already fixed")
            continue
        raise SystemExit(f"Expected Consultant v3 source pattern not found for {label}; refusing blind edit")

if changed:
    PATH.write_text(text, encoding="utf-8")
    if INDEX.exists():
        index = INDEX.read_text(encoding="utf-8")
        index = index.replace('consultant-workspace-v3.js?v=20260815-1006', 'consultant-workspace-v3.js?v=20260815-2025')
        index = index.replace('consultant-workspace-v3.js?v=20260815-2020', 'consultant-workspace-v3.js?v=20260815-2025')
        index = index.replace('consultant-workspace-v3.css?v=20260815-1006', 'consultant-workspace-v3.css?v=20260815-2025')
        index = index.replace('consultant-workspace-v3.css?v=20260815-2020', 'consultant-workspace-v3.css?v=20260815-2025')
        INDEX.write_text(index, encoding="utf-8")
