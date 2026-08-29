#!/usr/bin/env python3
"""Guard PARTENER Production Validation against partial/stale canonical writes."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "partener-eu-validation.yml"
text = WORKFLOW.read_text(encoding="utf-8")

required = (
    "ref: main",
    "id: regenerate",
    "continue-on-error: true",
    "steps.validate.outcome == 'success'",
    "steps.validate.outputs.exit_code != ''",
    "git fetch origin main",
    'local_head="$(git rev-parse HEAD)"',
    'remote_main="$(git rev-parse origin/main)"',
    'if [ "$local_head" != "$remote_main" ]; then',
    "FAIL validation persistence escaped allowlist",
    "git push origin HEAD:main",
    "REGENERATE_OUTCOME: ${{ steps.regenerate.outcome }}",
    'if [ "$REGENERATE_OUTCOME" != "success" ]; then FAIL=2; fi',
    "cancel-in-progress: false",
)
for fragment in required:
    if fragment not in text:
        raise SystemExit(f"FAIL Production Validation writer guard missing: {fragment}")

for forbidden in (
    "git pull --rebase origin main",
    "git rebase origin/main",
    "git push --force",
    "git push -f",
):
    if forbidden in text:
        raise SystemExit(f"FAIL unsafe Production Validation writer behavior remains: {forbidden}")

persist_marker = "- name: Persist validation ledger and safe source corrections"
start = text.find(persist_marker)
if start < 0:
    raise SystemExit("FAIL Production Validation persistence step missing")
end = text.find("- name: Enforce fail-closed health after evidence persistence", start)
if end < 0:
    raise SystemExit("FAIL Production Validation final health gate missing")
persist = text[start:end]
for allowed in (
    "partener-eu/validation",
    "partener-eu/P10_ACCEPTANCE.json",
    "partener-eu/ingest/state/intelligence_index.json",
    "partener-eu/p11/opportunity_bundle.json",
    "partener-eu/web/p11-public-data.js",
    "partener-eu/web/consultant-workspace-v3.js",
    "partener-eu/web/mysmis-registry.js",
):
    if allowed not in persist:
        raise SystemExit(f"FAIL canonical validation persistence allowlist lost: {allowed}")

print("PASS Production Validation fail-closed writer isolation")
