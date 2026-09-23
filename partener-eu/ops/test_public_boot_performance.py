#!/usr/bin/env python3
"""Deterministic public-boot budget guard for PARTENER.EU."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
CONSULTANT_LOADER = (WEB / "consultant-loader-v1.js").read_text(encoding="utf-8")
HEAVY_LOADER = (WEB / "public-heavy-loader-v1.js").read_text(encoding="utf-8")

CONSULTANT_ASSETS = (
    "consultant-workspace-v3.js",
    "consultant-workspace-v3.css",
    "consultant-onboarding-v3.js",
    "consultant-onboarding-v3.css",
    "consultant-mysmis-v1.js",
    "consultant-mysmis-v1.css",
)

PUBLIC_HEAVY_ASSETS = (
    "decision-products.js",
    "mipe-canonical-calls.js",
    "mipe-news.js",
    "call-lifecycle.js",
    "decision-intelligence-v2.js",
    "ask-partener-v2.js",
    "step-lll-dossier-bridge-v2.js",
    "home-freshness-guard-v1.js",
    "call-lifecycle-ui.js",
)
PUBLIC_HEAVY_STYLES = (
    "decision-intelligence-v2.css",
    "ask-partener-v2.css",
    "call-lifecycle-ui.css",
)

errors = []
for asset in CONSULTANT_ASSETS:
    if asset in INDEX:
        errors.append(f"consultant-only asset remains on public eager path: {asset}")
    if asset not in CONSULTANT_LOADER:
        errors.append(f"lazy loader is missing consultant asset: {asset}")

if 'src="consultant-loader-v1.js' not in INDEX:
    errors.append("public index does not load consultant-loader-v1.js")
if "document.addEventListener('click'" not in CONSULTANT_LOADER:
    errors.append("consultant suite is not gated behind user interaction")
if "window.PARTENER_LOAD_CONSULTANT=loadConsultantSuite" not in CONSULTANT_LOADER:
    errors.append("explicit consultant loading hook is missing")

for asset in PUBLIC_HEAVY_ASSETS:
    if f'src="{asset}' in INDEX:
        errors.append(f"heavy public asset remains on eager path: {asset}")
    if asset not in HEAVY_LOADER:
        errors.append(f"heavy public loader is missing asset: {asset}")
for asset in PUBLIC_HEAVY_STYLES:
    if f'href="{asset}' in INDEX:
        errors.append(f"heavy public stylesheet remains on eager path: {asset}")
    if asset not in HEAVY_LOADER:
        errors.append(f"heavy public loader is missing stylesheet: {asset}")

for marker in (
    'src="public-heavy-loader-v1.js',
    'src="home-public-data.js',
    'src="home-concierge-vnext.js',
):
    if marker not in INDEX:
        errors.append(f"optimized home boot marker missing: {marker}")

for marker in (
    "window.PARTENER_LOAD_DECISION_HUB=loadDecisionHub",
    "window.PARTENER_LOAD_ASK=loadAskSuite",
    "window.PARTENER_LOAD_LIFECYCLE=loadLifecycleSuite",
    "window.PARTENER_LOAD_MIPE_NEWS=loadMipeNews",
    "document.addEventListener('click'",
):
    if marker not in HEAVY_LOADER:
        errors.append(f"heavy-loader interaction contract missing: {marker}")

consultant_saved = sum((WEB / asset).stat().st_size for asset in CONSULTANT_ASSETS)
heavy_saved = sum((WEB / asset).stat().st_size for asset in PUBLIC_HEAVY_ASSETS)
if consultant_saved < 80_000:
    errors.append(f"consultant lazy-load saving unexpectedly small: {consultant_saved} bytes")
if heavy_saved < 7_500_000:
    errors.append(f"public heavy lazy-load saving unexpectedly small: {heavy_saved} bytes")

app_pos = INDEX.find('src="app.js')
consultant_pos = INDEX.find('src="consultant-loader-v1.js')
heavy_pos = INDEX.find('src="public-heavy-loader-v1.js')
home_data_pos = INDEX.find('src="home-public-data.js')
concierge_pos = INDEX.find('src="home-concierge-vnext.js')
if min(app_pos, consultant_pos, heavy_pos, home_data_pos, concierge_pos) < 0:
    errors.append("optimized boot path is incomplete")
elif not (app_pos < consultant_pos < heavy_pos < home_data_pos < concierge_pos):
    errors.append("optimized boot order must be app, consultant loader, heavy loader, compact home data, concierge")

# Checked-in eager JS/CSS should remain small. Generated home-public-data.js is
# excluded because it is a deploy-time projection and is size-gated separately.
asset_refs = re.findall(r'(?:src|href)="([^"?]+)', INDEX)
eager_bytes = 0
for ref in asset_refs:
    path = WEB / ref
    if path.exists() and path.is_file():
        eager_bytes += path.stat().st_size
if eager_bytes > 1_000_000:
    errors.append(f"checked-in eager public asset graph too large: {eager_bytes} bytes")

if errors:
    raise SystemExit("FAIL PARTENER public boot performance: " + "; ".join(errors))

print(
    "PASS PARTENER public boot performance: "
    f"{heavy_saved} heavy public bytes + {consultant_saved} consultant bytes "
    f"removed from eager graph; checked-in eager graph={eager_bytes} bytes"
)
