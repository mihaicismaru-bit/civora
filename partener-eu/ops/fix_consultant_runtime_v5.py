#!/usr/bin/env python3
"""Repair Consultant Workspace v3 activation and simplify public-facing UX.

The legacy app owns the top-level mode button. When consultant mode is entered,
the button label becomes Romanian `Site public`. Older v3 code waited for the
stale English label `Public site`, so the production v3 workspace never took
over and users were left inside the legacy read-only demo. This fixer makes the
handoff explicit and also removes remaining English/internal UX labels.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "partener-eu" / "web" / "consultant-workspace-v3.js"
CSS = ROOT / "partener-eu" / "web" / "consultant-workspace-v3.css"
INDEX = ROOT / "partener-eu" / "web" / "index.html"
text = JS.read_text(encoding="utf-8")
css = CSS.read_text(encoding="utf-8")
index = INDEX.read_text(encoding="utf-8")
changed = False

# Critical production handoff: app.js renders the legacy shell first and changes
# the mode button from `Spațiu consultant` to `Site public`. v3 must activate
# after that exact state transition.
old_activation = "mode.textContent.trim()==='Public site'"
new_activation = "['Site public','Public site'].includes(mode.textContent.trim())"
if old_activation in text:
    text = text.replace(old_activation, new_activation)
    changed = True
if new_activation not in text:
    raise SystemExit("Consultant v3 mode handoff contract missing")

# Make the main workflow readable to a Romanian consultant, while preserving
# internal status keys used by matching logic.
replacements = {
    "<small>Consultant Workspace v3</small>": "<small>Spațiu de lucru consultant</small>",
    "<h2>Opportunity Radar</h2>": "<h2>Radar de oportunități</h2>",
    "<h3>Deadline-uri apropiate</h3>": "<h3>Termene apropiate</h3>",
    "<h2>Hard gates automate</h2>": "<h2>Condiții eliminatorii automate</h2>",
    "<small>Deadline</small>": "<small>Termen</small>",
    "<h3>Deadline</h3>": "<h3>Termen</h3>",
    "let label='VERIFY'": "let label='VERIFICĂ'",
    "label='VERIFY ELIGIBILITY'": "label='VERIFICĂ ELIGIBILITATEA'",
    "return {label:'REVIEW',tone:'warn'": "return {label:'DE VERIFICAT',tone:'warn'",
    "<span>candidați OPEN ≥60</span>": "<span>apeluri deschise cu potrivire bună</span>",
    "Ranking explicabil, nu probabilitate de aprobare.": "Potrivire explicabilă cu profilul clientului; nu reprezintă probabilitate de aprobare.",
    "Taskuri manuale și checklisturi generate din dosarele apelurilor.": "Sarcini manuale și liste de verificare generate din dosarele apelurilor.",
    "Task nou": "Sarcină nouă",
    "Task general": "Sarcină generală",
    "Nu există taskuri.": "Nu există sarcini.",
}
for old, new in replacements.items():
    if old in text:
        text = text.replace(old, new)
        changed = True

# Humanize status badges without changing canonical status values.
old_status_badge = "function statusBadge(s){return `<span class=\"cw3Status ${esc(s||'UNKNOWN')}\">${esc(String(s||'UNKNOWN').replaceAll('_',' '))}</span>`}"
new_status_badge = "function statusBadge(s){const labels={OPEN:'DESCHIS',EXPECTED:'ÎN PREGĂTIRE',PUBLIC_CONSULTATION:'ÎN CONSULTARE',ANNOUNCED:'ANUNȚAT',CLOSED:'ÎNCHIS',CANCELLED:'ANULAT',SUSPENDED:'SUSPENDAT',NEWS:'INFORMARE'};return `<span class=\"cw3Status ${esc(s||'UNKNOWN')}\">${esc(labels[String(s||'').toUpperCase()]||'DE VERIFICAT')}</span>`}"
if old_status_badge in text:
    text = text.replace(old_status_badge, new_status_badge, 1)
    changed = True
if "const labels={OPEN:'DESCHIS'" not in text:
    raise SystemExit("Consultant status localization contract missing")

# Use Romanian labels for task priorities at render time only. Stored values
# remain stable for sorting and backward compatibility.
if "function priorityLabel(" not in text:
    anchor = "function statusBadge(s){"
    pos = text.find(anchor)
    if pos < 0:
        raise SystemExit("statusBadge anchor missing")
    text = text[:pos] + "function priorityLabel(v){return {CRITICAL:'CRITICĂ',HIGH:'RIDICATĂ',MEDIUM:'MEDIE',LOW:'SCĂZUTĂ'}[String(v||'').toUpperCase()]||String(v||'')}\n" + text[pos:]
    changed = True
text = re.sub(r">\$\{esc\(t\.priority\)\}<", ">${esc(priorityLabel(t.priority))}<", text)

# More obvious portfolio controls on small screens.
css_add = "\n.cw3ClientManageHint{font-size:10px;color:#9fb2a8;margin:2px 6px 0}.cw3DeleteText{min-height:38px;padding:8px 10px;border-radius:9px}.cw3AddClient{min-height:42px}\n@media(max-width:760px){.cw3AddClient{position:sticky;top:0;z-index:2}.cw3DeleteText{width:100%;text-align:center;background:#fff0f0;border:1px solid #f1cece}}\n"
if ".cw3ClientManageHint{" not in css:
    css += css_add
    changed = True

# Explain where deletion lives so it is discoverable rather than hidden.
sidebar_marker = "<button class=\"cw3AddClient\" data-cw3-new-client>＋ Adaugă firmă / organizație</button><div class=\"cw3ClientList\">"
sidebar_new = "<button class=\"cw3AddClient\" data-cw3-new-client>＋ Adaugă firmă / organizație</button><div class=\"cw3ClientManageHint\">Selectează o firmă și intră în Profil pentru editare sau ștergere.</div><div class=\"cw3ClientList\">"
if sidebar_marker in text:
    text = text.replace(sidebar_marker, sidebar_new, 1)
    changed = True
if "Selectează o firmă și intră în Profil" not in text:
    raise SystemExit("Consultant portfolio management hint missing")

if changed:
    JS.write_text(text, encoding="utf-8")
    CSS.write_text(css, encoding="utf-8")

# Force fresh mobile assets after the runtime handoff repair.
index2 = re.sub(r"consultant-workspace-v3\.js\?v=[^\"']+", "consultant-workspace-v3.js?v=20260815-2145", index)
index2 = re.sub(r"consultant-workspace-v3\.css\?v=[^\"']+", "consultant-workspace-v3.css?v=20260815-2145", index2)
index2 = re.sub(r"consultant-onboarding-v3\.js\?v=[^\"']+", "consultant-onboarding-v3.js?v=20260815-2145", index2)
index2 = re.sub(r"consultant-mysmis-v1\.js\?v=[^\"']+", "consultant-mysmis-v1.js?v=20260815-2145", index2)
if index2 != index:
    INDEX.write_text(index2, encoding="utf-8")

print("Consultant Workspace v5 runtime handoff and UX: PASS")
