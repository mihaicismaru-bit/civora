#!/usr/bin/env python3
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
js = (ROOT / 'partener-eu/web/consultant-workspace-v3.js').read_text(encoding='utf-8')
css = (ROOT / 'partener-eu/web/consultant-workspace-v3.css').read_text(encoding='utf-8')
index = (ROOT / 'partener-eu/web/index.html').read_text(encoding='utf-8')

required = [
    'data-cw3-new-client',
    '＋ Adaugă firmă / organizație',
    "form.onsubmit=async",
    'await persistNow()',
    'Consultant client save failed',
    'Consultant client delete failed',
    'Document cleanup skipped during client deletion',
    'Șterge din portofoliu',
    'globalThis.crypto?.randomUUID?.()',
    'deletedClientIds',
    'deleted.has(raw.id)',
]
for token in required:
    assert token in js, f'missing CRUD contract: {token}'

assert "form.onsubmit=e=>" not in js, 'legacy non-atomic client save handler remains'
assert "for(const doc of await idbListDocuments(client.id))" not in js, 'document cleanup can still abort deletion'
assert "state.deletedClientIds=[...new Set" in js, 'deletions do not create persistent tombstones'
assert "state.clients=state.clients.filter(c=>c.id!==removedId)" in js
assert "state.selectedClientId=client.id" in js
assert '.cw3AddClient{' in css, 'explicit add-client button has no styling'

match = re.search(r'consultant-workspace-v3\.js\?v=([^"\']+)', index)
assert match, 'Consultant runtime has no cache-busting version'
assert match.group(1) not in {'20260815-1006','20260815-2020'}, 'stale Consultant runtime cache version remains'
assert re.search(r'consultant-workspace-v3\.css\?v=([^"\']+)', index), 'Consultant CSS has no cache-busting version'
print(f"Consultant CRUD v4 regression: PASS (runtime {match.group(1)})")
