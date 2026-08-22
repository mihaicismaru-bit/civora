#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'partener-eu'/'ops'/'ux-card-scannability-v4-browser-proof.json'
SHOTS=ROOT/'partener-eu'/'ops'/'ux-card-scannability-v4-screenshots'
BASE='http://127.0.0.1:4176/index.html'
SHOTS.mkdir(parents=True,exist_ok=True)


def metrics(page):
    return page.evaluate('''() => ({
      scrollHeight: document.documentElement.scrollHeight,
      overflow: document.documentElement.scrollWidth-document.documentElement.clientWidth,
      dossierCards: document.querySelectorAll('.diHome .diDossierCard').length,
      hiddenDossierCards: Array.from(document.querySelectorAll('.diHome .diDossierCard')).filter(x=>x.hidden).length,
      newsCards: document.querySelectorAll('.diHome .diNewsCard').length,
      hiddenNewsCards: Array.from(document.querySelectorAll('.diHome .diNewsCard')).filter(x=>x.hidden).length,
      footerText: Array.from(document.querySelectorAll('.diHome .diDossierCard .diCardFoot>span')).map(x=>x.textContent),
      newsText: Array.from(document.querySelectorAll('.diHome .diNewsCard>p')).map(x=>x.textContent),
      clampedFooters: Array.from(document.querySelectorAll('.diHome .diDossierCard .diCardFoot>span')).filter(x=>x.scrollHeight>x.clientHeight+1).length,
      clampedNews: Array.from(document.querySelectorAll('.diHome .diNewsCard>p')).filter(x=>x.scrollHeight>x.clientHeight+1).length
    })''')


def audit(browser,name,width,height,mobile=False):
    page=browser.new_page(viewport={'width':width,'height':height})
    page.emulate_media(reduced_motion='reduce')
    console=[];failed=[]
    page.on('console',lambda m: console.append(m.text) if m.type=='error' else None)
    page.on('pageerror',lambda e: console.append(str(e)))
    page.on('response',lambda r: failed.append({'status':r.status,'url':r.url}) if r.status>=400 else None)
    page.goto(BASE,wait_until='networkidle',timeout=60000);page.wait_for_timeout(900)
    errors=[]
    link=page.locator('link[href*="ux-card-scannability-v4.css"]')
    if link.count()!=1: errors.append(f'v4 stylesheet count={link.count()}')
    active=metrics(page)
    if active['overflow']>2: errors.append(f'active page overflow={active["overflow"]}px')
    if mobile:
        if active['clampedFooters']<1: errors.append('no long dossier footer was visually clamped on mobile')
        if active['clampedNews']<1: errors.append('no news standfirst was visually clamped on mobile')

    page.evaluate("document.querySelector('link[href*=\"ux-card-scannability-v4.css\"]').disabled=true")
    page.wait_for_timeout(120)
    baseline=metrics(page)
    saved=baseline['scrollHeight']-active['scrollHeight']
    if active['footerText']!=baseline['footerText']: errors.append('dossier footer DOM text changed when stylesheet toggled')
    if active['newsText']!=baseline['newsText']: errors.append('news DOM text changed when stylesheet toggled')
    if active['dossierCards']!=baseline['dossierCards'] or active['newsCards']!=baseline['newsCards']: errors.append('card counts changed')
    if active['hiddenDossierCards']!=baseline['hiddenDossierCards'] or active['hiddenNewsCards']!=baseline['hiddenNewsCards']: errors.append('v4 changed v3 disclosure state')
    if mobile and saved<400: errors.append(f'visual compaction saves only {saved}px; expected >=400px')

    page.evaluate("document.querySelector('link[href*=\"ux-card-scannability-v4.css\"]').disabled=false")
    page.wait_for_timeout(120)
    restored=metrics(page)
    if restored['scrollHeight']!=active['scrollHeight']: errors.append(f'stylesheet round-trip height mismatch {restored["scrollHeight"]}!={active["scrollHeight"]}')
    if restored['overflow']>2: errors.append(f'restored page overflow={restored["overflow"]}px')

    if mobile:
        page.locator('a[data-ux-v2-key="open"]').click();page.wait_for_timeout(80)
    shot=SHOTS/f'{name}.png';page.screenshot(path=str(shot),full_page=False)
    result={
        'viewport':{'name':name,'width':width,'height':height},
        'active':active,
        'withoutV4':baseline,
        'heightReductionPx':saved,
        'roundTripHeightPx':restored['scrollHeight'],
        'failedResponses':failed,
        'consoleErrors':console,
        'errors':errors,
        'screenshot':shot.relative_to(ROOT).as_posix()
    }
    page.close();return result


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True,args=['--no-sandbox'])
        desktop=audit(browser,'desktop-1365x900',1365,900,False)
        mobile=audit(browser,'mobile-390x844',390,844,True)
        browser.close()
    errors=[f'desktop: {e}' for e in desktop['errors']]+[f'mobile: {e}' for e in mobile['errors']]
    console=[f'desktop: {e}' for e in desktop['consoleErrors']]+[f'mobile: {e}' for e in mobile['consoleErrors']]
    failed=[f'desktop: {e}' for e in desktop['failedResponses']]+[f'mobile: {e}' for e in mobile['failedResponses']]
    status='PASS' if not errors and not console and not failed else 'FAIL'
    proof={'schema':'PARTENER_UX_CARD_SCANNABILITY_BROWSER_PROOF_V4','status':status,'baseUrl':BASE,'desktop':desktop,'mobile':mobile,'errors':errors,'consoleErrors':console,'failedResponses':failed,'policy':'PASS requires homepage-only visual clipping with unchanged DOM text/card/disclosure state, mobile clamping of long dossier/news text, >=400px mobile height reduction, CSS disable/enable round-trip, zero page overflow, failed resources and console errors.'}
    OUT.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(proof,ensure_ascii=False,indent=2))
    return 0 if status=='PASS' else 1

if __name__=='__main__': raise SystemExit(main())
