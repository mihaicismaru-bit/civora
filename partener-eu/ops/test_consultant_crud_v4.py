#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
js = (ROOT / 'partener-eu/web/consultant-workspace-v3.js').read_text(encoding='utf-8')
css = (ROOT / 'partener-eu/web/consultant-workspace-v3.css').read_text(encoding='utf-8')

required = [
    'data-cw3-new-client',
    '＋ Adaugă firmă / organizație',
    "form.onsubmit=async",
    'await persistNow()',
    'Consultant client save failed',
    'Consultant client delete failed',
    'Document cleanup skipped',
    'Șterge din portofoliu',
    'globalThis.crypto?.randomUUID?.()',
]
for token in required:
    assert token in js, f'missing CRUD contract: {token}'

assert "form.onsubmit=e=>" not in js, 'legacy non-atomic client save handler remains'
assert "for(const doc of await idbListDocuments(client.id))" not in js, 'document cleanup can still abort deletion'
assert '.cw3AddClient{' in css, 'explicit add-client button has no styling'
print('Consultant CRUD v4 regression: PASS')
