#!/usr/bin/env python3
"""Deterministic guard for PARTENER.EU public frontpage resilience and clarity.

The public page must keep a visible HTML fallback, render its critical app path
before progressive enhancements, and expose one human-first funding concierge
without weakening fail-closed publication semantics.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
index = (WEB / "index.html").read_text(encoding="utf-8")
public_copy = (WEB / "public-product-copy-v1.js").read_text(encoding="utf-8")
concierge = (WEB / "home-concierge-vnext.js").read_text(encoding="utf-8")
p11_adapter = (WEB / "p11-public-adapter.js").read_text(encoding="utf-8")
people_policy = (WEB / "people-policy-v1.js").read_text(encoding="utf-8")

errors = []

if 'src="public-ux-optimization-v1.js' in index:
    errors.append("public-ux-optimization-v1.js is loaded by public index")
if 'href="public-ux-optimization-v1.css' in index:
    errors.append("public-ux-optimization-v1.css is loaded by public index")
if 'src="public-product-copy-v1.js' in index:
    errors.append("public-product-copy-v1.js is loaded by public index")

if 'id="boot-fallback"' not in index:
    errors.append("visible boot fallback missing")
for marker in (
    "Ce vrei să finanțezi?",
    "Descrie investiția în câteva cuvinte",
    "ce știm sigur și ce trebuie să faci mai departe",
):
    if marker not in index:
        errors.append(f"funding-concierge boot fallback missing: {marker}")

# vNext replaces overlapping homepage-only layers rather than stacking another
# enhancement on top of them.
for retired in (
    'daily-brief.js', 'daily-brief.css',
    'home-novice-v1.js', 'home-novice-v1.css',
    'home-go-to-v2.js', 'home-go-to-v2.css',
):
    if retired in index:
        errors.append(f"retired homepage layer remains active: {retired}")

for required in (
    "Găsește finanțări",
    "Deschise acum",
    "Se pregătesc",
    "Ce s-a schimbat",
    "De ce poți avea încredere în PARTENER.EU",
    "confirmed(d,'Status')",
    "confirmed(d,'Termen')",
    "currentStatus(d)!=='OPEN'",
    "parsed.getTime()>=Date.now()",
):
    if required not in concierge:
        errors.append(f"funding concierge contract missing: {required}")

# The static critical-boot projection can lag behind current source state.
# Runtime OPEN must therefore fail closed unless both status/deadline are verified
# and the deadline is still current. This prevents stale legacy OPEN labels from
# resurfacing in the base explorer, search, detail or fallback UI.
for required in (
    "deadlineTimestamp=value=>",
    "verified.includes('status')",
    "verified.includes('deadline')",
    "deadline>=Date.now()",
    "OPEN_FAIL_CLOSED_NO_CURRENT_VERIFIED_DEADLINE",
    "call.status='DISCOVERED'",
):
    if required not in p11_adapter:
        errors.append(f"P11 stale-OPEN fail-closed guard missing: {required}")

# Decision-maker promotion remains a homepage-only, fail-closed decision aid.
for required in (
    'function isHome(){return !!document.querySelector(\'.main [data-decision-home="1"]\')}',
    'if(!isHome()){removePromo();return}',
    'function impactText(x)',
    'x.whyItMatters||x.analysis',
    'genericImpact.test(s)',
    'return !!cleanStatement(x)&&!!impactText(x)',
    '<h2>Ce spun decidenții</h2>',
    '<b>De ce contează:</b>',
    '<b>Ce fapt oficial lipsește:</b>',
):
    if required not in people_policy:
        errors.append(f"decision-maker homepage contract missing: {required}")

# Critical path is deliberately bounded.
data_pos = index.find('src="data.js')
step_pos = index.find('src="step-lll.js')
p11_data_pos = index.find('src="p11-public-data.js')
p11_adapter_pos = index.find('src="p11-public-adapter.js')
app_pos = index.find('src="app.js')
if min(data_pos, step_pos, p11_data_pos, p11_adapter_pos, app_pos) < 0 or not (
    data_pos < step_pos < p11_data_pos < p11_adapter_pos < app_pos
):
    errors.append("critical boot order must be data, STEP, P11 projection, adapter, app")
for script in [
    "peo-calendar.js", "consultant-workspace-v2.js",
    "news-v1-ui.js", "people-policy-v1.js", "mff-2028-2034.js"
]:
    pos = index.find(f'src="{script}')
    if pos >= 0 and pos < app_pos:
        errors.append(f"enhancement {script} gates app.js first paint")

decision_data_pos = index.find('src="decision-products.js')
decision_ui_pos = index.find('src="decision-intelligence-v2.js')
concierge_pos = index.find('src="home-concierge-vnext.js')
if min(decision_data_pos, decision_ui_pos, concierge_pos) < 0 or not (
    app_pos < decision_data_pos < decision_ui_pos < concierge_pos
):
    errors.append("decision products, decision UI and funding concierge must load after app.js in order")

active_app = (WEB / "app.js").read_text(encoding="utf-8").casefold()
for stale_public_label in ("pilot", "facts demo", "corpusul canonic demo", "apeluri deschise în pilot"):
    if stale_public_label in active_app:
        errors.append(f"development label remains in active public app: {stale_public_label}")
if "apeluri deschise verificate" not in active_app:
    errors.append("verified open-call metric is missing")

if "new MutationObserver" in public_copy:
    errors.append("public-product-copy-v1.js contains a global MutationObserver")
if "characterData:true" in public_copy.replace(" ", ""):
    errors.append("public-product-copy-v1.js observes characterData")

# The concierge may read canonical decision products, but it may not become a
# second source of truth or persist inferred user-facing facts.
for forbidden in (
    'fetch(', 'localStorage', 'sessionStorage',
    'window.PARTENER_DATA=', 'window.PARTENER_DECISION_PRODUCTS=',
):
    if forbidden in concierge:
        errors.append(f"funding concierge violates read-only projection rule: {forbidden}")

if errors:
    raise SystemExit("FAIL frontend regression guard: " + "; ".join(errors))
print("PASS frontend regression guard")
