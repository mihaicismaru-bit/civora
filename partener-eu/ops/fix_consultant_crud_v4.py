#!/usr/bin/env python3
"""Canonical Consultant Workspace client CRUD repair.

Creates one robust add/edit/delete path that is atomic, mobile-safe, resilient
when IndexedDB cleanup fails, and prevents deleted demo clients from returning.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "partener-eu" / "web" / "consultant-workspace-v3.js"
CSS = ROOT / "partener-eu" / "web" / "consultant-workspace-v3.css"
INDEX = ROOT / "partener-eu" / "web" / "index.html"
text = JS.read_text(encoding="utf-8")
css = CSS.read_text(encoding="utf-8")
changed = False

text2 = text.replace(
    "const uid=p=>`${p}-${(crypto.randomUUID?crypto.randomUUID():Date.now().toString(36)+'-'+Math.random().toString(36).slice(2))}`;",
    "const uid=p=>`${p}-${(globalThis.crypto?.randomUUID?.()||Date.now().toString(36)+'-'+Math.random().toString(36).slice(2))}`;",
)
if text2 != text: text, changed = text2, True

text2 = re.sub(
    r"editingClient:null,demoClientsRemoved:false,(?:deletedClientIds:\[\],)?updatedAt:",
    "editingClient:null,demoClientsRemoved:false,deletedClientIds:[],updatedAt:",
    text,
    count=1,
)
if text2 != text: text, changed = text2, True

merge_pattern = re.compile(r"function mergeSeeds\(s\)\{.*?s\.version=3;return s\}")
merge_replacement = "function mergeSeeds(s){s.clients=Array.isArray(s.clients)?s.clients.map(normaliseClient):[];s.deletedClientIds=Array.isArray(s.deletedClientIds)?s.deletedClientIds:[];const deleted=new Set(s.deletedClientIds);if(!s.demoClientsRemoved){for(const raw of (D.clients||[])){if(!deleted.has(raw.id)&&!s.clients.some(c=>c.id===raw.id))s.clients.push(normaliseClient({...raw,seed:true}))}}if(s.selectedClientId&&!s.clients.some(c=>c.id===s.selectedClientId))s.selectedClientId=null;if(!s.selectedClientId&&s.clients[0])s.selectedClientId=s.clients[0].id;s.tracked=s.tracked||{};s.compare=s.compare||{};s.tasks=Array.isArray(s.tasks)?s.tasks:[];s.evaluations=s.evaluations||{};s.filters={q:'',status:'ALL',minScore:0,onlyTracked:false,...(s.filters||{})};s.version=3;return s}"
text2, n = merge_pattern.subn(merge_replacement, text, count=1)
if n and text2 != text: text, changed = text2, True

if '＋ Adaugă firmă / organizație' not in text:
    text2 = text.replace(
        '<button class="cw3Icon" data-cw3-new-client title="Client nou">＋</button></div><div class="cw3ClientList">',
        '<button class="cw3Icon" data-cw3-new-client title="Adaugă firmă sau organizație">＋</button></div><button class="cw3AddClient" data-cw3-new-client>＋ Adaugă firmă / organizație</button><div class="cw3ClientList">',
        1,
    )
    if text2 != text: text, changed = text2, True
text = text.replace('${state.clients.length} clienți', '${state.clients.length} firme / organizații')
text = text.replace("${isNew?'Client nou':'Profil client'}", "${isNew?'Firmă / organizație nouă':'Profil firmă / organizație'}")
text = text.replace('>Șterge clientul<', '>Șterge din portofoliu<')

new_handler = "root.querySelectorAll('[data-cw3-new-client]').forEach(b=>b.onclick=async()=>{state.editingClient='new';state.tab='profile';state.selectedCallId=null;await persistNow();await renderWorkspace();setTimeout(()=>document.getElementById('cw3Name')?.focus(),0)});"
text2, n = re.subn(
    r"root\.querySelectorAll\('\[data-cw3-new-client\]'\)\.forEach\(b=>b\.onclick=.*?\);(?=\n root\.querySelectorAll\('\[data-cw3-edit-client\]'\))",
    new_handler,
    text,
    count=1,
    flags=re.S,
)
if n and text2 != text: text, changed = text2, True

save_handler = "const form=document.getElementById('cw3ClientForm');if(form)form.onsubmit=async e=>{e.preventDefault();try{const isNew=form.dataset.new==='1';const base=isNew?{}:selectedClient();const client=readClientForm(base);if(!client.name.trim()){alert('Completează numele firmei sau organizației.');return}if(isNew){const duplicate=client.cui&&state.clients.find(c=>c.cui&&norm(c.cui)===norm(client.cui));if(duplicate&&!confirm(`Există deja ${duplicate.name} cu acest CUI. Adaugi totuși o înregistrare separată?`))return;state.clients.push(client);state.selectedClientId=client.id}else{const i=state.clients.findIndex(c=>c.id===client.id);if(i<0){alert('Profilul nu mai există în portofoliu. Reîncarcă pagina.');return}state.clients[i]=client;state.selectedClientId=client.id}state.deletedClientIds=(state.deletedClientIds||[]).filter(id=>id!==client.id);state.editingClient=null;state.tab='dashboard';await persistNow();await renderWorkspace()}catch(err){console.error('Consultant client save failed',err);alert('Nu am putut salva profilul. Datele introduse rămân pe ecran; încearcă din nou.')}};"
text2, n = re.subn(
    r"const form=document\.getElementById\('cw3ClientForm'\);if\(form\)form\.onsubmit=.*?(?=\n root\.querySelectorAll\('\[data-cw3-cancel-new\]'\))",
    save_handler,
    text,
    count=1,
    flags=re.S,
)
if n and text2 != text: text, changed = text2, True

delete_handler = "root.querySelectorAll('[data-cw3-delete-client]').forEach(b=>b.onclick=async()=>{const client=selectedClient();if(!client||!confirm(`Ștergi din portofoliu ${client.name}? Profilul, sarcinile și evaluările locale vor fi eliminate.`))return;try{const removedId=client.id;state.clients=state.clients.filter(c=>c.id!==removedId);state.deletedClientIds=[...new Set([...(state.deletedClientIds||[]),removedId])];delete state.tracked[removedId];delete state.compare[removedId];state.tasks=state.tasks.filter(t=>t.clientId!==removedId);for(const key of Object.keys(state.evaluations))if(key.startsWith(removedId+':'))delete state.evaluations[key];state.selectedClientId=state.clients[0]?.id||null;state.selectedCallId=null;state.editingClient=state.clients.length?null:'new';state.tab=state.clients.length?'dashboard':'profile';await persistNow();try{const docs=await idbListDocuments(removedId);for(const doc of docs)await idbDeleteDocument(doc.id)}catch(docErr){console.warn('Document cleanup skipped during client deletion',docErr)}await renderWorkspace()}catch(err){console.error('Consultant client delete failed',err);alert('Ștergerea nu a putut fi finalizată. Reîncarcă pagina și încearcă din nou.')}});"
text2, n = re.subn(
    r"root\.querySelectorAll\('\[data-cw3-delete-client\]'\)\.forEach\(b=>b\.onclick=.*?(?=\n root\.querySelectorAll\('\[data-cw3-remove-demo\]'\))",
    delete_handler,
    text,
    count=1,
    flags=re.S,
)
if n and text2 != text: text, changed = text2, True

demo_handler = "root.querySelectorAll('[data-cw3-remove-demo]').forEach(b=>b.onclick=async()=>{if(!confirm('Elimini firmele și organizațiile exemplu?'))return;const ids=new Set(state.clients.filter(c=>c.seed).map(c=>c.id));state.clients=state.clients.filter(c=>!c.seed);for(const id of ids){delete state.tracked[id];delete state.compare[id]}state.tasks=state.tasks.filter(t=>!ids.has(t.clientId));state.demoClientsRemoved=true;state.deletedClientIds=[...new Set([...(state.deletedClientIds||[]),...ids])];state.selectedClientId=state.clients[0]?.id||null;state.editingClient=state.clients.length?null:'new';state.tab=state.clients.length?'dashboard':'profile';await persistNow();await renderWorkspace()});"
text2, n = re.subn(
    r"root\.querySelectorAll\('\[data-cw3-remove-demo\]'\)\.forEach\(b=>b\.onclick=.*?(?=\n const q=document\.getElementById\('cw3FilterQ'\))",
    demo_handler,
    text,
    count=1,
    flags=re.S,
)
if n and text2 != text: text, changed = text2, True

css_block = ".cw3AddClient{width:100%;border:1px solid rgba(255,255,255,.22);background:rgba(255,255,255,.1);color:#fff;border-radius:11px;padding:10px 12px;text-align:left;font-weight:850;cursor:pointer}.cw3AddClient:hover{background:rgba(255,255,255,.16)}"
if '.cw3AddClient{' not in css:
    css += '\n' + css_block + '\n'; changed = True

required = [
    '＋ Adaugă firmă / organizație', 'form.onsubmit=async', 'Consultant client save failed',
    'Consultant client delete failed', 'deletedClientIds', 'deleted.has(raw.id)',
    'Document cleanup skipped during client deletion', 'globalThis.crypto?.randomUUID?.()'
]
missing = [token for token in required if token not in text]
if missing:
    raise SystemExit('Consultant CRUD contract incomplete: ' + ', '.join(missing))

if changed:
    JS.write_text(text, encoding='utf-8')
    CSS.write_text(css, encoding='utf-8')
    if INDEX.exists():
        index = INDEX.read_text(encoding='utf-8')
        index = re.sub(r'consultant-workspace-v3\.js\?v=[^"\']+', 'consultant-workspace-v3.js?v=20260815-2032', index)
        index = re.sub(r'consultant-workspace-v3\.css\?v=[^"\']+', 'consultant-workspace-v3.css?v=20260815-2032', index)
        index = re.sub(r'consultant-onboarding-v3\.js\?v=[^"\']+', 'consultant-onboarding-v3.js?v=20260815-2032', index)
        INDEX.write_text(index, encoding='utf-8')
print('Consultant CRUD v4 canonical repair: PASS')
