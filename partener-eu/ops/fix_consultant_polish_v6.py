#!/usr/bin/env python3
"""Polish Consultant Workspace v3/v5 for a Romanian production UX."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / 'partener-eu/web/consultant-workspace-v3.js'
INDEX = ROOT / 'partener-eu/web/index.html'
text = JS.read_text(encoding='utf-8')
changed = False

replacements = [
    ("<small>Consultant Workspace v3</small>", "<small>Spațiu de lucru consultant</small>"),
    ("<h2>Opportunity Radar</h2>", "<h2>Radar de oportunități</h2>"),
    ("<h2>Hard gates automate</h2>", "<h2>Condiții eliminatorii verificate automat</h2>"),
    ("<h2>Condiții eliminatorii automate</h2>", "<h2>Condiții eliminatorii verificate automat</h2>"),
    ("<span>candidați OPEN ≥60</span>", "<span>apeluri deschise potrivite</span>"),
    ("<span>apeluri deschise cu potrivire bună</span>", "<span>apeluri deschise potrivite</span>"),
    ("<h3>Deadline-uri apropiate</h3>", "<h3>Termene apropiate</h3>"),
    ("<span>taskuri deschise</span>", "<span>sarcini deschise</span>"),
    ("<h3>Următoarele taskuri</h3>", "<h3>Următoarele sarcini</h3>"),
    ("Nu există taskuri deschise.", "Nu există sarcini deschise."),
    ("Task nou", "Sarcină nouă"),
    ("Task general", "Sarcină generală"),
    ("Nu există taskuri. Generează planul de lucru dintr-un dosar de apel.", "Nu există sarcini. Generează planul de lucru dintr-un dosar de apel."),
    ("Scorul explică relevanța operațională.", "Scorul arată cât de bine se potrivește oportunitatea profilului clientului."),
    ("GO PENTRU PREGĂTIRE", "PREGĂTIRE RECOMANDATĂ"),
    ("NO-GO / BLOCAT", "NU CONTINUA / BLOCAT"),
    ("hard-gate negativ", "condiție eliminatorie negativă"),
    ("hard-gates explicabile", "condiții eliminatorii explicabile"),
    ("compareRow('Fit'", "compareRow('Potrivire'"),
    ("compareRow('Deadline'", "compareRow('Termen'"),
    ("['dashboard','Panou'],['profile','Profil'],['opportunities','Oportunități'],['dossier','Dosar apel'],['compare','Compară'],['documents','Documente'],['tasks','Taskuri'],['backup','Backup']", "['dashboard','Panou'],['profile','Profil'],['opportunities','Oportunități'],['dossier','Dosar apel'],['compare','Compară'],['documents','Documente'],['tasks','Sarcini'],['backup','Backup']"),
]
for old,new in replacements:
    if old in text:
        text=text.replace(old,new)
        changed=True

# Translate select display text while retaining canonical machine values.
old_status_select="${['ALL','OPEN','PUBLIC_CONSULTATION','EXPECTED','CLOSED'].map(s=>`<option ${filters.status===s?'selected':''}>${s}</option>`).join('')}"
new_status_select="${['ALL','OPEN','PUBLIC_CONSULTATION','EXPECTED','CLOSED'].map(s=>`<option value=\"${s}\" ${filters.status===s?'selected':''}>${({ALL:'Toate',OPEN:'Deschis',PUBLIC_CONSULTATION:'În consultare',EXPECTED:'În pregătire',CLOSED:'Închis'})[s]||s}</option>`).join('')}"
if old_status_select in text:
    text=text.replace(old_status_select,new_status_select,1);changed=True

old_priority="<select class=\"cw3Select\" id=\"cw3TaskPriority\"><option>MEDIUM</option><option>HIGH</option><option>CRITICAL</option><option>LOW</option></select>"
new_priority="<select class=\"cw3Select\" id=\"cw3TaskPriority\"><option value=\"MEDIUM\">Medie</option><option value=\"HIGH\">Ridicată</option><option value=\"CRITICAL\">Critică</option><option value=\"LOW\">Scăzută</option></select>"
if old_priority in text:
    text=text.replace(old_priority,new_priority,1);changed=True

# Existing v5 status/priority helpers are valid; only create them for older runtimes.
legacy_status = "function statusBadge(s){return `<span class=\"cw3Status ${esc(s||'UNKNOWN')}\">${esc(String(s||'UNKNOWN').replaceAll('_',' '))}</span>`}"
if legacy_status in text:
    helper = "const CW3_STATUS_LABELS={OPEN:'DESCHIS',EXPECTED:'ÎN PREGĂTIRE',PUBLIC_CONSULTATION:'ÎN CONSULTARE',ANNOUNCED:'ANUNȚAT',CLOSED:'ÎNCHIS',CANCELLED:'ANULAT',SUSPENDED:'SUSPENDAT',NEWS:'INFORMARE'};\nfunction statusBadge(s){return `<span class=\"cw3Status ${esc(s||'UNKNOWN')}\">${esc(CW3_STATUS_LABELS[String(s||'').toUpperCase()]||'DE VERIFICAT')}</span>`}"
    text=text.replace(legacy_status,helper,1); changed=True
if not ('function statusBadge(s){const labels=' in text or 'CW3_STATUS_LABELS' in text):
    raise SystemExit('Consultant status badge contract not found')
if 'function priorityLabel(v)' not in text and 'CW3_PRIORITY_LABELS' not in text:
    marker='function statusBadge(s)'
    text=text.replace(marker,"const CW3_PRIORITY_LABELS={CRITICAL:'CRITICĂ',HIGH:'RIDICATĂ',MEDIUM:'MEDIE',LOW:'SCĂZUTĂ'};\n"+marker,1); changed=True
    text=re.sub(r">\$\{esc\(t\.priority\)\}</span>", ">${esc(CW3_PRIORITY_LABELS[t.priority]||t.priority)}</span>", text)

# Surface edit/delete from the dashboard, reusing profile deletion logic.
needle = '<button class="cw3Btn" data-cw3-edit-client>Completează profilul</button>'
replacement = '<div class="cw3HeroActions"><button class="cw3Btn" data-cw3-edit-client>Completează profilul</button><button class="cw3Btn ghost" data-cw3-tabgo="profile">Editează / șterge organizația</button></div>'
if needle in text:
    text=text.replace(needle,replacement,1); changed=True

if changed:
    JS.write_text(text,encoding='utf-8')
    index=INDEX.read_text(encoding='utf-8')
    index=re.sub(r'consultant-workspace-v3\.js\?v=[^"\']+', 'consultant-workspace-v3.js?v=20260816-0931', index)
    index=re.sub(r'consultant-workspace-v3\.css\?v=[^"\']+', 'consultant-workspace-v3.css?v=20260816-0931', index)
    INDEX.write_text(index,encoding='utf-8')

required=['Radar de oportunități','Condiții eliminatorii verificate automat','Editează / șterge organizația','sarcini deschise','Potrivire','Termen']
missing=[x for x in required if x not in text]
if missing: raise SystemExit('Consultant polish incomplete: '+', '.join(missing))
if not ('function priorityLabel(v)' in text or 'CW3_PRIORITY_LABELS' in text): raise SystemExit('Consultant priority localization missing')
print('Consultant Workspace Romanian UX v6: PASS')
