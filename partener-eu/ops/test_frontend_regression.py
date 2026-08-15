#!/usr/bin/env python3
"""Deterministic P10 guard for the public frontpage freeze/blank-page incidents.

The public page must have a visible HTML fallback, render its critical app path
before progressive enhancements, and never reintroduce the global observer loop.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
index = (WEB / "index.html").read_text(encoding="utf-8")
public_copy = (WEB / "public-product-copy-v1.js").read_text(encoding="utf-8")

errors = []

# Experimental UX/copy layers remain in the repository for auditability but
# must not gate or mutate the production first paint until browser acceptance.
if 'src="public-ux-optimization-v1.js' in index:
    errors.append("public-ux-optimization-v1.js is loaded by public index")
if 'href="public-ux-optimization-v1.css' in index:
    errors.append("public-ux-optimization-v1.css is loaded by public index")
if 'src="public-product-copy-v1.js' in index:
    errors.append("public-product-copy-v1.js is loaded by public index")

# Never allow a fully blank document while JavaScript is unavailable, delayed,
# cached inconsistently, or fails before app bootstrap. The fallback copy is a
# product contract and must describe a decision-support service, not a news feed.
if 'id="boot-fallback"' not in index:
    errors.append("visible boot fallback missing")
if "Ce finanțare poți accesa și ce trebuie să faci acum" not in index:
    errors.append("decision-first boot fallback has no meaningful visible content")
if "Apeluri, condiții, documente, schimbări și riscuri" not in index:
    errors.append("boot fallback does not explain the public product")

# Critical path is deliberately bounded: static data, the verified STEP record,
# the generated P11 projection and its adapter, then the renderer. Every visual
# enhancement must execute only after app.js has had a chance to paint.
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

# Decision products are progressive, but both their generated data and renderer
# must be loaded in the correct order after the public app has painted.
decision_data_pos = index.find('src="decision-products.js')
decision_ui_pos = index.find('src="decision-intelligence-v2.js')
if min(decision_data_pos, decision_ui_pos) < 0 or not (app_pos < decision_data_pos < decision_ui_pos):
    errors.append("decision products must load after app.js and before their UI renderer")

active_app = (WEB / "app.js").read_text(encoding="utf-8").casefold()
for stale_public_label in ("pilot", "facts demo", "corpusul canonic demo", "apeluri deschise în pilot"):
    if stale_public_label in active_app:
        errors.append(f"development label remains in active public app: {stale_public_label}")
if "apeluri deschise verificate" not in active_app:
    errors.append("verified open-call metric is missing")

# The quarantined copy-polish implementation must remain finite even while it
# is disconnected from production.
if "new MutationObserver" in public_copy:
    errors.append("public-product-copy-v1.js contains a global MutationObserver")
if "characterData:true" in public_copy.replace(" ", ""):
    errors.append("public-product-copy-v1.js observes characterData")

if errors:
    raise SystemExit("FAIL frontend regression guard: " + "; ".join(errors))
print("PASS frontend regression guard")
