#!/usr/bin/env python3
"""Deterministic public-boot budget guard for PARTENER.EU."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
LOADER = (WEB / "consultant-loader-v1.js").read_text(encoding="utf-8")

CONSULTANT_ASSETS = (
    "consultant-workspace-v3.js",
    "consultant-workspace-v3.css",
    "consultant-onboarding-v3.js",
    "consultant-onboarding-v3.css",
    "consultant-mysmis-v1.js",
    "consultant-mysmis-v1.css",
)

errors = []
for asset in CONSULTANT_ASSETS:
    if asset in INDEX:
        errors.append(f"consultant-only asset remains on public eager path: {asset}")
    if asset not in LOADER:
        errors.append(f"lazy loader is missing consultant asset: {asset}")

if 'src="consultant-loader-v1.js' not in INDEX:
    errors.append("public index does not load consultant-loader-v1.js")
if "document.addEventListener('click'" not in LOADER:
    errors.append("consultant suite is not gated behind user interaction")
if "window.PARTENER_LOAD_CONSULTANT=loadConsultantSuite" not in LOADER:
    errors.append("explicit consultant loading hook is missing")

saved_bytes = sum((WEB / asset).stat().st_size for asset in CONSULTANT_ASSETS)
if saved_bytes < 80_000:
    errors.append(f"consultant lazy-load saving unexpectedly small: {saved_bytes} bytes")

app_pos = INDEX.find('src="app.js')
loader_pos = INDEX.find('src="consultant-loader-v1.js')
if app_pos < 0 or loader_pos < 0 or loader_pos < app_pos:
    errors.append("consultant loader must remain outside and after the critical app boot path")

if errors:
    raise SystemExit("FAIL PARTENER public boot performance: " + "; ".join(errors))

print(f"PASS PARTENER public boot performance: {saved_bytes} consultant-only bytes removed from initial document dependency graph")
