#!/usr/bin/env python3
"""Deterministic guard for PARTENER.EU public frontpage resilience and clarity.

The public page must keep a visible HTML fallback, render its critical app path
before progressive enhancements, and explain the product to a first-time visitor
without requiring knowledge of programme names.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
index = (WEB / "index.html").read_text(encoding="utf-8")
public_copy = (WEB / "public-product-copy-v1.js").read_text(encoding="utf-8")
home_novice = (WEB / "home-novice-v1.js").read_text(encoding="utf-8")
home_goto = (WEB / "home-go-to-v2.js").read_text(encoding="utf-8")

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
    "Ai o investiție în minte?",
    "Nu trebuie să știi programul",
    "eligibilitate, bani, termene, documente și următorul pas",
):
    if marker not in index:
        errors.append(f"intent-first boot fallback missing: {marker}")

# First-time discovery remains available even before the go-to-market layer.
for required in (
    "Nu trebuie să știi numele programului",
    "Cine ești?",
    "Ce vrei să finanțezi?",
    "Vezi apelurile deschise",
    "Surse oficiale",
    "Necunoscutele sunt marcate",
):
    if required not in home_novice:
        errors.append(f"novice homepage entry missing: {required}")

# The go-to layer must expose natural-language discovery, freshness and a path
# for returning visitors without replacing fail-closed product semantics.
for required in (
    "Caută finanțări",
    "Poți scrie în limbaj normal",
    "apeluri confirmate deschise",
    "Vezi ce s-a schimbat de la ultima verificare",
    "Necunoscutele sunt marcate, nu inventate",
):
    if required not in home_goto:
        errors.append(f"go-to homepage utility missing: {required}")

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
home_novice_pos = index.find('src="home-novice-v1.js')
home_goto_pos = index.find('src="home-go-to-v2.js')
if min(decision_data_pos, decision_ui_pos, home_novice_pos, home_goto_pos) < 0 or not (
    app_pos < decision_data_pos < decision_ui_pos < home_novice_pos < home_goto_pos
):
    errors.append("decision products, novice homepage and go-to layer must load after app.js in order")

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

if errors:
    raise SystemExit("FAIL frontend regression guard: " + "; ".join(errors))
print("PASS frontend regression guard")
