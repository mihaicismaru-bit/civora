#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'partener-eu'/'ops'/'ux-mobile-density-v3-browser-proof.json'
SHOTS=ROOT/'partener-eu'/'ops'/'ux-mobile-density-v3-screenshots'
BASE='http://127.0.0.1:4175/index.html'
SHOTS.mkdir(parents=True,exist_ok=True)

SPECS=[
    ('open','#ux-v2-open','.diDossierCard'),
    ('prepare','#ux-v2-prepare','.diDossierCard'),
    ('changes','#ux-v2-changes','.diNewsCard'),
]


def page_overflow(page):
    return page.evaluate('document.documentElement.scrollWidth-document.documentElement.clientWidth')

def card_state(page,section,card):
    cards=page.locator(f'{section} {card}')
    total=cards.count()
    hidden=sum(1 for i in range(total) if cards.nth(i).is_hidden())
    return {'total':total,'hidden':hidden,'visible':total-hidden}


def desktop_audit(browser):
    page=browser.new_page(viewport={'width':1365,'height':900})
    page.emulate_media(reduced_motion='reduce')
    console=[];failed=[]
    page.on('console',lambda m: console.append(m.text) if m.type=='error' else None)
    page.on('pageerror',lambda e: console.append(str(e)))
    page.on('response',lambda r: failed.append({'status':r.status,'url':r.url}) if r.status>=400 else None)
    page.goto(BASE,wait_until='networkidle',timeout=60000);page.wait_for_timeout(900)
    states={key:card_state(page,section,card) for key,section,card in SPECS}
    errors=[]
    if page.locator('.uxV3More').count()!=0: errors.append('desktop shows mobile disclosure controls')
    if any(v['hidden'] for v in states.values()): errors.append(f'desktop hidden cards={states}')
    overflow=page_overflow(page)
    if overflow>2: errors.append(f'desktop page overflow={overflow}px')
    result={'viewport':'1365x900','states':states,'toggleCount':page.locator('.uxV3More').count(),'pageHorizontalOverflowPx':overflow,'failedResponses':failed,'consoleErrors':console,'errors':errors}
    page.close();return result


def mobile_audit(browser):
    page=browser.new_page(viewport={'width':390,'height':844})
    page.emulate_media(reduced_motion='reduce')
    console=[];failed=[]
    page.on('console',lambda m: console.append(m.text) if m.type=='error' else None)
    page.on('pageerror',lambda e: console.append(str(e)))
    page.on('response',lambda r: failed.append({'status':r.status,'url':r.url}) if r.status>=400 else None)
    page.goto(BASE,wait_until='networkidle',timeout=60000);page.wait_for_timeout(900)
    errors=[]
    compact={key:card_state(page,section,card) for key,section,card in SPECS}
    compact_height=page.evaluate('document.documentElement.scrollHeight')
    toggles=page.locator('.uxV3More')
    toggle_count=toggles.count()
    expected_toggles=sum(1 for v in compact.values() if v['total']>3)
    if toggle_count!=expected_toggles: errors.append(f'toggle count={toggle_count}, expected={expected_toggles}')
    for key,state in compact.items():
        expected_hidden=max(0,state['total']-3)
        if state['hidden']!=expected_hidden: errors.append(f'{key} hidden={state["hidden"]}, expected={expected_hidden}')
        if state['visible']>3: errors.append(f'{key} visible={state["visible"]} > 3')
    heights=[]
    for i in range(toggle_count):
        box=toggles.nth(i).bounding_box()
        if box: heights.append(round(box['height'],2))
    if heights and min(heights)<43.5: errors.append(f'mobile disclosure target below 44px={min(heights)}')
    overflow_before=page_overflow(page)
    if overflow_before>2: errors.append(f'mobile compact overflow={overflow_before}px')

    page.locator('a[data-ux-v2-key="open"]').click();page.wait_for_timeout(80)
    compact_shot=SHOTS/'mobile-open-compact.png';page.screenshot(path=str(compact_shot),full_page=False)

    for key,section,_card in SPECS:
        button=page.locator(f'{section} .uxV3More')
        if button.count(): button.click();page.wait_for_timeout(60)
    expanded={key:card_state(page,section,card) for key,section,card in SPECS}
    expanded_height=page.evaluate('document.documentElement.scrollHeight')
    height_saved=expanded_height-compact_height
    if any(v['hidden'] for v in expanded.values()): errors.append(f'expanded state still hides cards={expanded}')
    if height_saved<1000: errors.append(f'compact mode saves only {height_saved}px; expected >=1000px')
    expanded_buttons=page.locator('.uxV3More[aria-expanded="true"]').count()
    if expanded_buttons!=toggle_count: errors.append(f'expanded aria buttons={expanded_buttons}/{toggle_count}')
    overflow_after=page_overflow(page)
    if overflow_after>2: errors.append(f'mobile expanded overflow={overflow_after}px')

    page.locator('a[data-ux-v2-key="open"]').click();page.wait_for_timeout(80)
    expanded_shot=SHOTS/'mobile-open-expanded.png';page.screenshot(path=str(expanded_shot),full_page=False)

    open_button=page.locator('#ux-v2-open .uxV3More')
    collapse_ok=None
    if open_button.count():
        open_button.click();page.wait_for_timeout(100)
        state=card_state(page,'#ux-v2-open','.diDossierCard')
        collapse_ok=open_button.get_attribute('aria-expanded')=='false' and state['hidden']==max(0,state['total']-3)
        if not collapse_ok: errors.append(f'open section did not collapse correctly: {state}')

    result={
        'viewport':'390x844',
        'compactStates':compact,
        'expandedStates':expanded,
        'toggleCount':toggle_count,
        'toggleTouchTargetHeights':heights,
        'compactScrollHeightPx':compact_height,
        'expandedScrollHeightPx':expanded_height,
        'initialHeightReductionPx':height_saved,
        'collapseRoundTripPass':collapse_ok,
        'pageHorizontalOverflowCompactPx':overflow_before,
        'pageHorizontalOverflowExpandedPx':overflow_after,
        'failedResponses':failed,
        'consoleErrors':console,
        'errors':errors,
        'screenshots':[compact_shot.relative_to(ROOT).as_posix(),expanded_shot.relative_to(ROOT).as_posix()]
    }
    page.close();return result


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True,args=['--no-sandbox'])
        desktop=desktop_audit(browser);mobile=mobile_audit(browser);browser.close()
    errors=[f'desktop: {e}' for e in desktop['errors']]+[f'mobile: {e}' for e in mobile['errors']]
    console=[f'desktop: {e}' for e in desktop['consoleErrors']]+[f'mobile: {e}' for e in mobile['consoleErrors']]
    failed=[f'desktop: {e}' for e in desktop['failedResponses']]+[f'mobile: {e}' for e in mobile['failedResponses']]
    status='PASS' if not errors and not console and not failed else 'FAIL'
    proof={'schema':'PARTENER_UX_MOBILE_DENSITY_BROWSER_PROOF_V3','status':status,'baseUrl':BASE,'desktop':desktop,'mobile':mobile,'errors':errors,'consoleErrors':console,'failedResponses':failed,'policy':'PASS requires desktop full visibility; mobile <=3 initial cards per populated decision section with explicit 44px expand controls; complete expansion/collapse round-trip; >=1000px initial height reduction; zero page overflow, failed resources and console errors.'}
    OUT.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(proof,ensure_ascii=False,indent=2))
    return 0 if status=='PASS' else 1

if __name__=='__main__': raise SystemExit(main())
