#!/usr/bin/env python3
"""Make Consultant Workspace client CRUD atomic, mobile-safe and explicit."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "partener-eu" / "web" / "consultant-workspace-v3.js"
CSS = ROOT / "partener-eu" / "web" / "consultant-workspace-v3.css"
text = JS.read_text(encoding="utf-8")
css = CSS.read_text(encoding="utf-8")
changed = False

replacements = [
    (
        "const uid=p=>`${p}-${(crypto.randomUUID?crypto.randomUUID():Date.now().toString(36)+'-'+Math.random().toString(36).slice(2))}`;",
        "const uid=p=>`${p}-${(globalThis.crypto?.randomUUID?.()||Date.now().toString(36)+'-'+Math.random().toString(36).slice(2))}`;",
        "safe UUID fallback",
    ),
    (
        "function sidebar(client){return `<aside class=\"cw3Sidebar\"><div class=\"cw3SideHead\"><div><b>Portofoliu</b><span>${state.clients.length} clienți</span></div><button class=\"cw3Icon\" data-cw3-new-client title=\"Client nou\">＋</button></div><div class=\"cw3ClientList\">",
        "function sidebar(client){return `<aside class=\"cw3Sidebar\"><div class=\"cw3SideHead\"><div><b>Portofoliu</b><span>${state.clients.length} firme / organizații</span></div><button class=\"cw3Icon\" data-cw3-new-client title=\"Adaugă firmă sau organizație\">＋</button></div><button class=\"cw3AddClient\" data-cw3-new-client>＋ Adaugă firmă / organizație</button><div class=\"cw3ClientList\">",
        "explicit add button",
    ),
    (
        "function profileForm(client,isNew=false){const c=isNew?normaliseClient({}):client;return `<section><div class=\"cw3SectionHead\"><div><h2>${isNew?'Client nou':'Profil client'}</h2><p>Datele sunt folosite pentru screening explicabil și pentru dosarul de lucru.</p></div>${!isNew?'<button class=\"cw3DeleteText\" data-cw3-delete-client>Șterge clientul</button>':''}</div>",
        "function profileForm(client,isNew=false){const c=isNew?normaliseClient({}):client;return `<section><div class=\"cw3SectionHead\"><div><h2>${isNew?'Firmă / organizație nouă':'Profil firmă / organizație'}</h2><p>Datele sunt folosite pentru screening explicabil și pentru dosarul de lucru.</p></div>${!isNew?'<button class=\"cw3DeleteText\" data-cw3-delete-client>Șterge din portofoliu</button>':''}</div>",
        "clear profile labels",
    ),
    (
        " root.querySelectorAll('[data-cw3-new-client]').forEach(b=>b.onclick=()=>{state.editingClient='new';state.tab='profile';renderWorkspace()});",
        " root.querySelectorAll('[data-cw3-new-client]').forEach(b=>b.onclick=async()=>{state.editingClient='new';state.tab='profile';state.selectedCallId=null;await persistNow();renderWorkspace()});",
        "atomic new-client transition",
    ),
    (
        " const form=document.getElementById('cw3ClientForm');if(form)form.onsubmit=e=>{e.preventDefault();const isNew=form.dataset.new==='1';const base=isNew?{}:selectedClient();const client=readClientForm(base);if(isNew){state.clients.push(client);state.selectedClientId=client.id}else{const i=state.clients.findIndex(c=>c.id===client.id);state.clients[i]=client}state.editingClient=null;state.tab='dashboard';persist();renderWorkspace()};",
        " const form=document.getElementById('cw3ClientForm');if(form)form.onsubmit=async e=>{e.preventDefault();try{const isNew=form.dataset.new==='1';const base=isNew?{}:selectedClient();const client=readClientForm(base);if(!client.name.trim()){alert('Completează numele firmei sau organizației.');return}if(isNew){const duplicate=client.cui&&state.clients.find(c=>c.cui&&norm(c.cui)===norm(client.cui));if(duplicate&&!confirm(`Există deja ${duplicate.name} cu acest CUI. Adaugi totuși o înregistrare separată?`))return;state.clients.push(client);state.selectedClientId=client.id}else{const i=state.clients.findIndex(c=>c.id===client.id);if(i<0){alert('Profilul nu mai există în portofoliu. Reîncarcă pagina.');return}state.clients[i]=client;state.selectedClientId=client.id}state.editingClient=null;state.tab='dashboard';await persistNow();await renderWorkspace()}catch(err){console.error('Consultant client save failed',err);alert('Nu am putut salva profilul. Datele introduse rămân pe ecran; încearcă din nou.')}};",
        "atomic save handler",
    ),
    (
        " root.querySelectorAll('[data-cw3-delete-client]').forEach(b=>b.onclick=async()=>{const client=selectedClient();if(!client||!confirm(`Ștergi clientul ${client.name}?`))return;state.clients=state.clients.filter(c=>c.id!==client.id);delete state.tracked[client.id];delete state.compare[client.id];state.tasks=state.tasks.filter(t=>t.clientId!==client.id);for(const key of Object.keys(state.evaluations))if(key.startsWith(client.id+':'))delete state.evaluations[key];for(const doc of await idbListDocuments(client.id))await idbDeleteDocument(doc.id);state.selectedClientId=state.clients[0]?.id||null;state.tab='dashboard';persist();renderWorkspace()});",
        " root.querySelectorAll('[data-cw3-delete-client]').forEach(b=>b.onclick=async()=>{const client=selectedClient();if(!client||!confirm(`Ștergi din portofoliu ${client.name}? Profilul, taskurile și evaluările locale vor fi eliminate.`))return;try{const removedId=client.id;state.clients=state.clients.filter(c=>c.id!==removedId);delete state.tracked[removedId];delete state.compare[removedId];state.tasks=state.tasks.filter(t=>t.clientId!==removedId);for(const key of Object.keys(state.evaluations))if(key.startsWith(removedId+':'))delete state.evaluations[key];state.selectedClientId=state.clients[0]?.id||null;state.selectedCallId=null;state.editingClient=state.clients.length?null:'new';state.tab=state.clients.length?'dashboard':'profile';await persistNow();try{const docs=await idbListDocuments(removedId);for(const doc of docs)await idbDeleteDocument(doc.id)}catch(docErr){console.warn('Document cleanup skipped',docErr)}await renderWorkspace()}catch(err){console.error('Consultant client delete failed',err);alert('Ștergerea nu a putut fi finalizată. Reîncarcă pagina și încearcă din nou.')}});",
        "atomic delete handler",
    ),
    (
        " root.querySelectorAll('[data-cw3-remove-demo]').forEach(b=>b.onclick=()=>{if(!confirm('Elimini clienții exemplu?'))return;const ids=new Set(state.clients.filter(c=>c.seed).map(c=>c.id));state.clients=state.clients.filter(c=>!c.seed);for(const id of ids){delete state.tracked[id];delete state.compare[id]}state.tasks=state.tasks.filter(t=>!ids.has(t.clientId));state.demoClientsRemoved=true;state.selectedClientId=state.clients[0]?.id||null;state.editingClient=state.clients.length?null:'new';persist();renderWorkspace()});",
        " root.querySelectorAll('[data-cw3-remove-demo]').forEach(b=>b.onclick=async()=>{if(!confirm('Elimini firmele și organizațiile exemplu?'))return;const ids=new Set(state.clients.filter(c=>c.seed).map(c=>c.id));state.clients=state.clients.filter(c=>!c.seed);for(const id of ids){delete state.tracked[id];delete state.compare[id]}state.tasks=state.tasks.filter(t=>!ids.has(t.clientId));state.demoClientsRemoved=true;state.selectedClientId=state.clients[0]?.id||null;state.editingClient=state.clients.length?null:'new';state.tab=state.clients.length?'dashboard':'profile';await persistNow();renderWorkspace()});",
        "atomic demo removal",
    ),
]

for old, new, label in replacements:
    if new in text:
        print(f"Consultant CRUD {label}: already fixed")
    elif old in text:
        text = text.replace(old, new, 1)
        changed = True
        print(f"Consultant CRUD {label}: fixed")
    else:
        raise SystemExit(f"Expected Consultant CRUD pattern missing for {label}; refusing blind edit")

css_block = """
.cw3AddClient{width:100%;border:1px solid rgba(255,255,255,.22);background:rgba(255,255,255,.1);color:#fff;border-radius:11px;padding:10px 12px;text-align:left;font-weight:850;cursor:pointer}.cw3AddClient:hover{background:rgba(255,255,255,.16)}
""".strip()
if ".cw3AddClient{" not in css:
    css += "\n" + css_block + "\n"
    changed = True

if changed:
    JS.write_text(text, encoding="utf-8")
    CSS.write_text(css, encoding="utf-8")
