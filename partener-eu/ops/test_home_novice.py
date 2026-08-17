#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
WEB=ROOT/'partener-eu'/'web'
index=(WEB/'index.html').read_text(encoding='utf-8')
js=(WEB/'home-novice-v1.js').read_text(encoding='utf-8')
css=(WEB/'home-novice-v1.css').read_text(encoding='utf-8')
decision=(WEB/'decision-intelligence-v2.js').read_text(encoding='utf-8')

for token in ('home-novice-v1.css','home-novice-v1.js','decision-intelligence-v2.js'):
    assert token in index, f'missing novice homepage asset: {token}'
assert 'Funding intelligence' not in index
assert 'Ce finanțare poți accesa' in decision
assert 'Finanțări europene · decizie și acțiune' in decision

for label in ('firmă / IMM','ONG / asociație','școală / universitate','primărie / instituție','fermă / agricultură','formare profesională'):
    assert label in js, f'missing visitor profile: {label}'
for phrase in ('Vezi finanțările deschise','Găsește după profilul meu','Nu trebuie să știi numele programului','cine poate aplica','câți bani','ce faci acum'):
    assert phrase in js, f'missing novice copy: {phrase}'
for phrase in ('Dosar ${raw}','Gradul de completare al informațiilor din dosar, nu probabilitatea de finanțare','Sesiunea este confirmată ca deschisă pentru depunere'):
    assert phrase in js, f'missing explanatory behavior: {phrase}'
assert 'noviceProfiles' in css and '@media(max-width:800px)' in css
print('PARTENER.EU novice homepage regression: PASS')
