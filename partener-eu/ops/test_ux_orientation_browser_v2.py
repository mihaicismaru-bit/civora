#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'partener-eu'/'ops'/'ux-orientation-v2-browser-proof.json'
SHOTS=ROOT/'partener-eu'/'ops'/'ux-orientation-v2-screenshots'
BASE='http://127.0.0.1:4174/index.html'
SHOTS.mkdir(parents=True,exist_ok=True)

EXPECTED=['Profil','Deschise','Pregătește','Schimbări']


def audit(browser,name,width,height,mobile=False):
    page=browser.new_page(viewport={'width':width,'height':height})
    page.emulate_media(reduced_motion='reduce')
    console=[]
    failed=[]
    page.on('console',lambda msg: console.append(msg.text) if msg.type=='error' else None)
    page.on('pageerror',lambda exc: console.append(str(exc)))
    page.on('response',lambda r: failed.append({'status':r.status,'url':r.url}) if r.status>=400 else None)
    page.goto(BASE,wait_until='networkidle',timeout=60000)
    page.wait_for_timeout(900)

    errors=[]
    rail=page.locator('.uxV2Rail')
    if rail.count()!=1: errors.append(f'orientation rail count={rail.count()}')
    links=page.locator('.uxV2Rail a[data-ux-v2-key]')
    labels=[links.nth(i).locator('span').inner_text().strip() for i in range(links.count())]
    if labels!=EXPECTED: errors.append(f'rail labels={labels}')

    link_heights=[]
    for i in range(links.count()):
        box=links.nth(i).bounding_box()
        if box: link_heights.append(round(box['height'],2))
    if link_heights and min(link_heights)<43.5: errors.append(f'rail target below 44px: {min(link_heights)}')

    sections=page.locator('.diHome .diSection')
    section_count=sections.count()
    hidden_sections=sum(1 for i in range(section_count) if not sections.nth(i).is_visible())
    if section_count<3: errors.append(f'expected >=3 decision sections, got {section_count}')
    if hidden_sections: errors.append(f'material decision sections hidden={hidden_sections}')

    target_ids=['ux-v2-profile','ux-v2-open','ux-v2-prepare','ux-v2-changes']
    missing_targets=[target for target in target_ids if page.locator(f'#{target}').count()!=1]
    if missing_targets: errors.append(f'missing targets={missing_targets}')

    extra=page.locator('.diNewsCard,.diNewsRow,.diResultDossier')
    extra_count=extra.count()
    uncovered=[]
    for i in range(extra_count):
        el=extra.nth(i)
        if el.get_attribute('role')!='button' or el.get_attribute('tabindex')!='0' or el.get_attribute('data-ux-keyboard')!='1':
            uncovered.append(i)
    if uncovered: errors.append(f'decision cards without keyboard contract={uncovered[:10]}')

    hints=page.locator('.diNewsCard .uxV2OpenHint').count()
    news_cards=page.locator('.diNewsCard').count()
    if hints!=news_cards: errors.append(f'news action hints {hints}/{news_cards}')

    metrics=page.evaluate('''() => ({scrollWidth:document.documentElement.scrollWidth,clientWidth:document.documentElement.clientWidth})''')
    overflow=metrics['scrollWidth']-metrics['clientWidth']
    if overflow>2: errors.append(f'page horizontal overflow={overflow}px')

    rail_position=rail.evaluate("el=>getComputedStyle(el).position") if rail.count()==1 else None
    if mobile and rail_position!='sticky': errors.append(f'mobile rail position={rail_position}')

    top_shot=SHOTS/f'{name}-top.png'
    page.screenshot(path=str(top_shot),full_page=False)

    jump_ok=False
    target_top=None
    header_height=None
    if page.locator('a[data-ux-v2-key="changes"]').count()==1:
        page.locator('a[data-ux-v2-key="changes"]').click()
        page.wait_for_timeout(120)
        current=page.locator('a[data-ux-v2-key="changes"]').get_attribute('aria-current')
        target_box=page.locator('#ux-v2-changes').bounding_box()
        header_box=page.locator('.topbar').bounding_box()
        if target_box and header_box:
            target_top=round(target_box['y'],2)
            header_height=round(header_box['height'],2)
            jump_ok=current=='location' and target_top>=header_height-3 and target_top<=header_height+125
        if not jump_ok: errors.append(f'changes jump failed current={current} targetTop={target_top} headerHeight={header_height}')

    jump_shot=SHOTS/f'{name}-changes.png'
    page.screenshot(path=str(jump_shot),full_page=False)

    result={
        'viewport':{'name':name,'width':width,'height':height},
        'railLabels':labels,
        'railTouchTargetHeights':link_heights,
        'railPosition':rail_position,
        'decisionSectionCount':section_count,
        'hiddenDecisionSections':hidden_sections,
        'extraKeyboardTargetCount':extra_count,
        'newsCardActionHints':hints,
        'pageHorizontalOverflowPx':overflow,
        'changesJump':{'ok':jump_ok,'targetTop':target_top,'headerHeight':header_height},
        'failedResponses':failed,
        'consoleErrors':console,
        'errors':errors,
        'screenshots':[top_shot.relative_to(ROOT).as_posix(),jump_shot.relative_to(ROOT).as_posix()]
    }
    page.close()
    return result


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True,args=['--no-sandbox'])
        results=[
            audit(browser,'desktop-1365x900',1365,900,False),
            audit(browser,'mobile-390x844',390,844,True),
        ]
        browser.close()
    errors=[f"{r['viewport']['name']}: {e}" for r in results for e in r['errors']]
    console=[f"{r['viewport']['name']}: {e}" for r in results for e in r['consoleErrors']]
    failed=[f"{r['viewport']['name']}: {x}" for r in results for x in r['failedResponses']]
    status='PASS' if not errors and not console and not failed else 'FAIL'
    proof={
        'schema':'PARTENER_UX_ORIENTATION_BROWSER_PROOF_V2',
        'status':status,
        'baseUrl':BASE,
        'results':results,
        'errors':errors,
        'consoleErrors':console,
        'failedResponses':failed,
        'policy':'PASS requires visible material sections, 44px orientation targets, keyboard coverage for decision cards, working section jump, zero page overflow, zero failed resources and zero console errors.'
    }
    OUT.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(proof,ensure_ascii=False,indent=2))
    return 0 if status=='PASS' else 1

if __name__=='__main__':
    raise SystemExit(main())
