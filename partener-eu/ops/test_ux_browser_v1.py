#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'partener-eu' / 'ops' / 'ux-browser-proof.json'
SHOT_DIR = ROOT / 'partener-eu' / 'ops' / 'ux-browser-screenshots'
BASE_URL = 'http://127.0.0.1:4173/index.html'
SHOT_DIR.mkdir(parents=True, exist_ok=True)


def audit_viewport(browser, name: str, width: int, height: int) -> dict:
    page = browser.new_page(viewport={"width": width, "height": height})
    errors: list[str] = []
    console_errors: list[str] = []
    failed_responses: list[dict] = []
    page.on('console', lambda msg: console_errors.append(msg.text) if msg.type == 'error' else None)
    page.on('pageerror', lambda exc: console_errors.append(str(exc)))
    page.on('response', lambda response: failed_responses.append({
        'status': response.status,
        'url': response.url,
    }) if response.status >= 400 else None)
    page.goto(BASE_URL, wait_until='networkidle', timeout=60000)
    page.wait_for_timeout(900)

    assert page.locator('html.uxOptimizedV1').count() == 1, 'UX progressive layer did not initialize'
    assert page.locator('.uxSkip').count() == 1, 'skip link missing'
    assert page.locator('main#ux-main[tabindex="-1"]').count() == 1, 'main landmark enhancement missing'
    assert page.locator('.nav[role="navigation"][aria-label="Navigație principală"]').count() == 1, 'navigation landmark missing'

    navlinks = page.locator('.navlinks')
    assert navlinks.count() == 1, 'primary nav links container missing'
    nav_visible = navlinks.is_visible()
    if not nav_visible:
        errors.append('primary navigation is not visible')

    buttons = page.locator('.navlink')
    labels = [buttons.nth(i).inner_text().strip() for i in range(buttons.count())]
    for expected in ('Oportunități', 'Calendar', 'Întreabă PARTENER.EU'):
        if expected not in labels:
            errors.append(f'missing nav action: {expected}')

    nav_heights = []
    for i in range(buttons.count()):
        box = buttons.nth(i).bounding_box()
        if box:
            nav_heights.append(round(box['height'], 2))
    if nav_heights and min(nav_heights) < 43.5:
        errors.append(f'nav touch target below 44px: {min(nav_heights)}')

    body_metrics = page.evaluate('''() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      scrollHeight: document.documentElement.scrollHeight,
      clientHeight: document.documentElement.clientHeight
    })''')
    horizontal_overflow = body_metrics['scrollWidth'] - body_metrics['clientWidth']
    overflow_offenders = page.evaluate('''() => {
      const vw = document.documentElement.clientWidth;
      return Array.from(document.querySelectorAll('body *')).map((el) => {
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height) return null;
        const rightOverflow = Math.max(0, r.right - vw);
        const leftOverflow = Math.max(0, -r.left);
        if (rightOverflow <= 2 && leftOverflow <= 2 && r.width <= vw + 2) return null;
        return {
          tag: el.tagName.toLowerCase(),
          id: el.id || '',
          className: typeof el.className === 'string' ? el.className.slice(0,180) : '',
          left: Math.round(r.left),
          right: Math.round(r.right),
          width: Math.round(r.width),
          rightOverflow: Math.round(rightOverflow),
          leftOverflow: Math.round(leftOverflow),
          text: (el.textContent || '').replace(/\\s+/g,' ').trim().slice(0,120)
        };
      }).filter(Boolean).sort((a,b) => Math.max(b.rightOverflow,b.leftOverflow,b.width-vw) - Math.max(a.rightOverflow,a.leftOverflow,a.width-vw)).slice(0,18);
    }''')
    if horizontal_overflow > 2:
        errors.append(f'page horizontal overflow: {horizontal_overflow}px')

    aria_missing = page.locator('input:not([aria-label]):not([aria-labelledby]), select:not([aria-label]):not([aria-labelledby])').count()

    keyboard_targets = page.locator('[data-ux-keyboard="1"]')
    keyboard_count = keyboard_targets.count()
    if keyboard_count:
        first = keyboard_targets.first
        if first.get_attribute('tabindex') not in ('0', None):
            errors.append('keyboard target has invalid tabindex')

    page.locator('.uxSkip').focus()
    skip_box = page.locator('.uxSkip').bounding_box()
    if not skip_box or skip_box['y'] < -2:
        errors.append('skip link is not visible on focus')

    raw_statuses = page.locator('.badge').all_inner_texts()
    forbidden_raw = {'OPEN', 'EXPECTED', 'PUBLIC CONSULTATION', 'PUBLIC_CONSULTATION', 'DISCOVERED', 'CLOSED'}
    untranslated = [s.strip() for s in raw_statuses if s.strip().upper() in forbidden_raw]
    if untranslated:
        errors.append(f'untranslated status badges remain: {untranslated[:5]}')

    nested_interactive = page.locator('[role="button"] button, [role="button"] a, [role="button"] input, [role="button"] select').count()
    if nested_interactive:
        errors.append(f'nested interactive controls inside role=button: {nested_interactive}')

    shot = SHOT_DIR / f'{name}.png'
    page.screenshot(path=str(shot), full_page=True)

    result = {
        'viewport': {'name': name, 'width': width, 'height': height},
        'primaryNavVisible': nav_visible,
        'navLabels': labels,
        'navTouchTargetHeights': nav_heights,
        'horizontalOverflowPx': horizontal_overflow,
        'overflowOffenders': overflow_offenders,
        'unlabeledFormControls': aria_missing,
        'keyboardTargetCount': keyboard_count,
        'nestedInteractiveInRoleButton': nested_interactive,
        'failedResponses': failed_responses,
        'consoleErrors': console_errors,
        'errors': errors,
        'screenshot': shot.relative_to(ROOT).as_posix(),
    }
    page.close()
    return result


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True, args=['--no-sandbox'])
        results = [
            audit_viewport(browser, 'desktop-1365x900', 1365, 900),
            audit_viewport(browser, 'mobile-390x844', 390, 844),
        ]
        browser.close()

    all_errors = [f"{r['viewport']['name']}: {e}" for r in results for e in r['errors']]
    all_console = [f"{r['viewport']['name']}: {e}" for r in results for e in r['consoleErrors']]
    status = 'PASS' if not all_errors and not all_console else 'FAIL'
    proof = {
        'schema': 'PARTENER_UX_BROWSER_PROOF_V1',
        'status': status,
        'baseUrl': BASE_URL,
        'results': results,
        'errors': all_errors,
        'consoleErrors': all_console,
        'policy': 'PASS requires both desktop and mobile DOM/interaction checks, zero console errors, screenshots, and no page-level horizontal overflow.'
    }
    OUT.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    return 0 if status == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
