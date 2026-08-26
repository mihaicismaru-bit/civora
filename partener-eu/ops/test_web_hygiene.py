#!/usr/bin/env python3
"""Fail-closed hygiene guard for the PARTENER.EU public web tree."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
V3 = (WEB / "consultant-workspace-v3.js").read_text(encoding="utf-8")

errors = []

# v2 was superseded by v3. The runtime must not regress to loading or tracking
# the obsolete implementation, but v3 must retain the one-way local-state
# migration so existing browser data is not stranded.
for stale in ("consultant-workspace-v2.js", "consultant-workspace-v2.css"):
    if (WEB / stale).exists():
        errors.append(f"obsolete tracked asset remains: {stale}")
    if stale in INDEX:
        errors.append(f"obsolete asset is still referenced by index.html: {stale}")

for current in ("consultant-workspace-v3.js", "consultant-workspace-v3.css"):
    if not (WEB / current).exists():
        errors.append(f"current consultant asset missing: {current}")
    if current not in INDEX:
        errors.append(f"current consultant asset is not referenced by index.html: {current}")

for migration_marker in (
    "const V2_KEY='partener_consultant_v2_state';",
    "function migrateV2(v2)",
):
    if migration_marker not in V3:
        errors.append(f"v2 state migration contract missing: {migration_marker}")

if errors:
    raise SystemExit("FAIL PARTENER web hygiene: " + "; ".join(errors))

print("PASS PARTENER web hygiene: obsolete v2 runtime removed; v3 migration preserved")
