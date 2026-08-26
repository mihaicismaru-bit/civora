#!/usr/bin/env python3
"""Fail-closed hygiene guard for the PARTENER.EU public web tree."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
V3 = (WEB / "consultant-workspace-v3.js").read_text(encoding="utf-8")
LOADER = (WEB / "consultant-loader-v1.js").read_text(encoding="utf-8")

errors = []

# v2 was superseded by v3. The runtime must not regress to tracking the obsolete
# implementation, while v3 keeps the one-way browser-state migration contract.
for stale in ("consultant-workspace-v2.js", "consultant-workspace-v2.css"):
    if (WEB / stale).exists():
        errors.append(f"obsolete tracked asset remains: {stale}")
    if stale in INDEX or stale in LOADER:
        errors.append(f"obsolete asset is still referenced: {stale}")

current_assets = (
    "consultant-workspace-v3.js",
    "consultant-workspace-v3.css",
    "consultant-onboarding-v3.js",
    "consultant-onboarding-v3.css",
    "consultant-mysmis-v1.js",
    "consultant-mysmis-v1.css",
)
for current in current_assets:
    if not (WEB / current).exists():
        errors.append(f"current consultant asset missing: {current}")
    if current in INDEX:
        errors.append(f"consultant-only asset is eagerly referenced by index.html: {current}")
    if current not in LOADER:
        errors.append(f"consultant loader does not reference current asset: {current}")

if 'src="consultant-loader-v1.js' not in INDEX:
    errors.append("consultant lazy loader is not referenced by index.html")

for migration_marker in (
    "const V2_KEY='partener_consultant_v2_state';",
    "function migrateV2(v2)",
):
    if migration_marker not in V3:
        errors.append(f"v2 state migration contract missing: {migration_marker}")

if errors:
    raise SystemExit("FAIL PARTENER web hygiene: " + "; ".join(errors))

print("PASS PARTENER web hygiene: obsolete v2 removed; v3 state migration and lazy-load boundary preserved")
