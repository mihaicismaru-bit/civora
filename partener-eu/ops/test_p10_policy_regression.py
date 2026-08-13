#!/usr/bin/env python3
"""Static guard for P10 orchestration and fail-closed publication policy."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PARTENER = REPO / "partener-eu"
WORKFLOWS = REPO / ".github" / "workflows"

validation = (WORKFLOWS / "partener-eu-validation.yml").read_text(encoding="utf-8")
peo_workflow = (WORKFLOWS / "partener-eu-peo-calendar.yml").read_text(encoding="utf-8")
tasks = (PARTENER / "ops" / "p10_resolution_tasks.py").read_text(encoding="utf-8")
monitor = (PARTENER / "ops" / "p10_monitor_integrity.py").read_text(encoding="utf-8")
deployment = (PARTENER / "ops" / "check_public_site.py").read_text(encoding="utf-8")
acceptance = (PARTENER / "ops" / "p10_acceptance_sync.py").read_text(encoding="utf-8")
recovery = (PARTENER / "ops" / "test_recovery.py").read_text(encoding="utf-8")
afir = (PARTENER / "ingest" / "afir_ingest.py").read_text(encoding="utf-8")
validator = (PARTENER / "ops" / "p10_validate.py").read_text(encoding="utf-8")

errors = []

# Ingestion bot commits made with GITHUB_TOKEN do not reliably emit downstream
# push runs. Validation must therefore subscribe to completed monitor workflows.
for marker in [
    "workflow_run:",
    "PARTENER.EU MIPE Ingestion",
    "PARTENER.EU AFIR Ingestion",
    "PARTENER.EU Verified Source Registry",
    "PARTENER.EU PEO Calendar",
    "PARTENER.EU MFF 2028-2034 Monitor",
    "PARTENER.EU Pages",
    "p10_monitor_integrity.py",
    "test_afir_ingest_policy.py",
]:
    if marker not in validation:
        errors.append(f"production validation orchestration missing: {marker}")

# Validation runs write the same ledger and checkpoint files. They must be
# serialized instead of cancelling an active writer; cancellation can overlap
# long enough for two runs to commit and then conflict during pull --rebase.
if "cancel-in-progress: false" not in validation:
    errors.append("production validation ledger writers are not serialized")
if "ref: main" not in validation:
    errors.append("queued production validation can check out a stale workflow event SHA")

# Scheduled PEO calendar changes are candidate evidence only during P10. The
# workflow may persist state but must not update the public JS feed automatically.
if "git add partener-eu/web/peo-calendar.js" in peo_workflow:
    errors.append("PEO workflow auto-publishes public material calendar data")
if "cp partener-eu/web/peo-calendar.js" in peo_workflow:
    errors.append("PEO workflow carries generated public feed across reset")
if "peo_calendar_state.json" not in peo_workflow or "candidate state" not in peo_workflow.lower():
    errors.append("PEO workflow does not explicitly persist candidate state fail-closed")

# Every non-core monitor hash change must have a durable resolution-task route.
for marker in [
    "SRC-AFIR-CORPUS",
    "SRC-PEO-CALENDAR",
    "automatic_material_fact_update_allowed",
    "blocked_fact_classes",
]:
    if marker not in tasks:
        errors.append(f"resolution-task guard missing: {marker}")

for marker in [
    "latest_history_equal",
    "source_state_checkpoint_equal",
    "source_registry_health.json",
    "hash_change_action",
    "RESOLUTION_TASK_ONLY",
]:
    if marker not in monitor:
        errors.append(f"monitor-integrity evidence missing: {marker}")

# A successful HTTP shell with almost no semantic text must not be allowed to
# manufacture a hash-change confirmation. It remains DEGRADED and blocks its
# dependent material facts until a high-information observation returns.
for marker in [
    "MIN_SEMANTIC_CHARS",
    "MIN_HTML_BYTES_FOR_LOW_INFO",
    "observation_content_quality",
    "LOW_INFORMATION_HTML_SHELL",
    "observed_semantic=obs.get('semantic_sha256') if content_quality_ok else None",
    "dependent_material_facts_publishable':(not quarantined and content_quality_ok)",
]:
    if marker not in validator:
        errors.append(f"low-information source guard missing: {marker}")

# Deployment validation must test the current nonblank shell and critical assets,
# not the obsolete pre-hotfix copy marker that created false DEGRADED results.
for marker in [
    "https://partener.eu/",
    'id="boot-fallback"',
    "Găsește finanțarea potrivită",
    "critical_assets_ok",
    "legacy_origin_detected",
]:
    if marker not in deployment:
        errors.append(f"deployment probe missing: {marker}")
if '"Funding Intelligence"' in deployment:
    errors.append("deployment probe still requires obsolete Funding Intelligence marker")

for marker in [
    "MINIMUM_DISTINCT_DAYS = 30",
    "VALIDATION_RUNNING_NOT_CLOSED",
    "VERIFIED_HTTPS_CONTENT",
    "autonomous_update_evidence_pass",
    "civora_v1_production_baseline_closed",
]:
    if marker not in acceptance:
        errors.append(f"P10 acceptance closure guard missing: {marker}")

for marker in ["AUTH_OR_ACCESS_DEPENDENT", "accessDependencies", "AUTH_PATH_MARKERS", "no access was fabricated"]:
    if marker not in afir:
        errors.append(f"AFIR authentication boundary missing: {marker}")

for marker in ["recover_state", "corrupt_state_checkpoint_recovery"]:
    if marker not in recovery:
        errors.append(f"recovery regression evidence missing: {marker}")

if errors:
    raise SystemExit("FAIL P10 policy regression guard: " + "; ".join(errors))
print("PASS P10 policy regression guard")
