#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
WEB=ROOT/'partener-eu'/'web'
INDEX=WEB/'index.html'
CSS=WEB/'ux-card-scannability-v4.css'

index=INDEX.read_text(encoding='utf-8')
css=CSS.read_text(encoding='utf-8')

assert 'ux-card-scannability-v4.css' in index
assert index.index('ux-mobile-density-v3.css') < index.index('ux-card-scannability-v4.css')

for token in (
    '.diHome .diDossierCard .diCardFoot>span',
    '-webkit-line-clamp:3',
    '.diHome .diNewsCard>p',
    '-webkit-line-clamp:4',
    '@media(max-width:720px)',
    '-webkit-line-clamp:2',
):
    assert token in css, token

# The compaction must stay scoped to homepage cards, never dossier/detail/source content.
for forbidden in ('.diDossierDetail', '.diNewsDetail', '.source', '.eligibilityBox', 'display:none'):
    assert forbidden not in css, forbidden

assert '<script src="app.js?' in index
print('PARTENER.EU UX card scannability v4 contract: PASS')
