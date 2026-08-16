#!/usr/bin/env python3
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
js = (ROOT / 'partener-eu/web/consultant-workspace-v3.js').read_text(encoding='utf-8')
css = (ROOT / 'partener-eu/web/consultant-workspace-v3.css').read_text(encoding='utf-8')
index = (ROOT / 'partener-eu/web/index.html').read_text(encoding='utf-8')
app = (ROOT / 'partener-eu/web/app.js').read_text(encoding='utf-8')

assert "${S.consultant?'Site public':'Spațiu consultant'}" in app, 'top-level app mode label changed unexpectedly'
assert "['Site public','Public site'].includes(mode.textContent.trim())" in js, 'v3 does not activate from actual Romanian consultant state'
assert "mode.textContent.trim()==='Public site'" not in js, 'stale English-only activation remains'
assert '＋ Adaugă firmă / organizație' in js
assert 'Șterge din portofoliu' in js
assert 'Editează / șterge organizația' in js
assert "form.onsubmit=async" in js
assert "state.clients.push(client)" in js
assert "state.clients=state.clients.filter(c=>c.id!==removedId)" in js
assert "await persistNow()" in js
assert "deletedClientIds" in js
assert "Radar de oportunități" in js
assert "Condiții eliminatorii verificate automat" in js
assert "VERIFICĂ ELIGIBILITATEA" in js
assert "DE VERIFICAT" in js
assert "const labels={OPEN:'DESCHIS'" in js or 'CW3_STATUS_LABELS' in js
assert "priorityLabel" in js or 'CW3_PRIORITY_LABELS' in js
assert 'Selectează o firmă și intră în Profil' in js
assert '.cw3ClientManageHint{' in css
assert 'sarcini deschise' in js
assert 'PREGĂTIRE RECOMANDATĂ' in js
assert 'NU CONTINUA / BLOCAT' in js
assert 'hard-gates explicabile' not in js

version = re.search(r'consultant-workspace-v3\.js\?v=([^"\']+)', index)
assert version and version.group(1) == '20260816-0931', f'unexpected consultant cache version: {version.group(1) if version else None}'

print('Consultant runtime v6 handoff + CRUD + Romanian UX: PASS')
