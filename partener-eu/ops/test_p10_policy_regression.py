#!/usr/bin/env python3
"""Static guard for P10 orchestration and fail-closed publication policy."""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PARTENER = REPO / "partener-eu"
WORKFLOWS = REPO / ".github" / "workflows"

validation = (WORKFLOWS / "partener-eu-validation.yml").read_text(encoding="utf-8")
peo_workflow = (WORKFLOWS / "partener-eu-peo-calendar.yml").read_text(encoding="utf-8")
pages_workflow = (WORKFLOWS / "partener-eu-pages.yml").read_text(encoding="utf-8")
auto_deploy_path = WORKFLOWS / "partener-eu-auto-deploy.yml"
go_live_workflow = (WORKFLOWS / "partener-eu-go-live.yml").read_text(encoding="utf-8")
tasks = (PARTENER / "ops" / "p10_resolution_tasks.py").read_text(encoding="utf-8")
monitor = (PARTENER / "ops" / "p10_monitor_integrity.py").read_text(encoding="utf-8")
deployment = (PARTENER / "ops" / "check_public_site.py").read_text(encoding="utf-8")
acceptance = (PARTENER / "ops" / "p10_acceptance_sync.py").read_text(encoding="utf-8")
recovery = (PARTENER / "ops" / "test_recovery.py").read_text(encoding="utf-8")
afir = (PARTENER / "ingest" / "afir_ingest.py").read_text(encoding="utf-8")
validator = (PARTENER / "ops" / "p10_validate.py").read_text(encoding="utf-8")

errors = []

for marker in [
    "workflow_run:",
    "PARTENER.EU AFIR Ingestion",
    "PARTENER.EU Decision Products",
    "PARTENER.EU Verified Source Registry",
    "PARTENER.EU MFF 2028-2034 Monitor",
    "PARTENER.EU Pages",
    "p10_monitor_integrity.py",
    "test_afir_ingest_policy.py",
]:
    if marker not in validation:
        errors.append(f"production validation orchestration missing: {marker}")

if "cancel-in-progress: false" not in validation:
    errors.append("production validation ledger writers are not serialized")
if "ref: main" not in validation:
    errors.append("queued production validation can check out a stale workflow event SHA")
if "github.event.workflow_run.conclusion == 'success'" not in validation:
    errors.append("production validation runs after unsuccessful upstream workflows")

# A successful source workflow that already feeds the canonical Pages deployment
# must have exactly one post-deploy validation path. Subscribing Production
# Validation to the same source workflow creates a redundant pre-deploy ledger,
# then Pages completion creates the intended post-deploy ledger.
for upstream in ["PARTENER.EU MIPE Ingestion", "PARTENER.EU PEO Calendar"]:
    workflow_line = f"      - '{upstream}'"
    if workflow_line not in pages_workflow:
        errors.append(f"canonical Pages handoff missing for: {upstream}")
    if workflow_line in validation:
        errors.append(f"redundant direct validation handoff duplicates Pages: {upstream}")

# There must be one automatic Pages writer. The former Auto Deploy workflow
# duplicated web/** pushes and deploy-pages with PARTENER.EU Pages.
if auto_deploy_path.exists():
    errors.append("redundant PARTENER.EU Auto Deploy workflow still exists")
for marker in [
    "recover_decision_products_lkg.py",
    "test_public_language.py",
    "step-lll-dossier-bridge-v2.js",
]:
    if marker not in pages_workflow:
        errors.append(f"canonical Pages fail-closed preflight missing: {marker}")

# LKG recovery intentionally mutates generated files in the deployment workspace.
# Before the workflow rebases/pushes the deployment ledger, those ephemeral
# mutations must be discarded so evidence persistence cannot fail on a dirty tree
# or accidentally publish generated product changes back to main.
for marker in [
    "/tmp/partener-pages-latest.json",
    "/tmp/partener-pages-last-attempt.json",
    "git reset --hard HEAD",
]:
    if marker not in pages_workflow:
        errors.append(f"Pages evidence isolation missing: {marker}")
reset_at = pages_workflow.find("git reset --hard HEAD")
pull_at = pages_workflow.find("git pull --rebase origin main")
if reset_at < 0 or pull_at < 0 or reset_at > pull_at:
    errors.append("Pages evidence writer does not clean preflight mutations before rebase")

def has_exact_yaml_scalar(workflow: str, key: str, value: str) -> bool:
    return bool(re.search(
        rf"(?m)^[ \\t]*{re.escape(key)}:[ \\t]*{re.escape(value)}[ \\t]*(?:#.*)?$",
        workflow,
    ))

for workflow_name, workflow in [
    ("PARTENER.EU Pages", pages_workflow),
    ("PARTENER.EU Go Live", go_live_workflow),
]:
    if "uses: actions/deploy-pages@v4" not in workflow:
        errors.append(f"{workflow_name} no longer exposes its expected Pages deployment step")
    if not has_exact_yaml_scalar(workflow, "group", "partener-eu-pages"):
        errors.append(f"{workflow_name} does not share the exact repository-wide Pages deployment lock")
    if not has_exact_yaml_scalar(workflow, "cancel-in-progress", "false"):
        errors.append(f"{workflow_name} can cancel an in-flight Pages deployment")
    if not has_exact_yaml_scalar(workflow, "name", "github-pages"):
        errors.append(f"{workflow_name} does not use the canonical GitHub Pages environment")

if "git add partener-eu/web/peo-calendar.js" in peo_workflow:
    errors.append("PEO workflow auto-publishes public material calendar data")
if "cp partener-eu/web/peo-calendar.js" in peo_workflow:
    errors.append("PEO workflow carries generated public feed across reset")
if "peo_calendar_state.json" not in peo_workflow or "candidate state" not in peo_workflow.lower():
    errors.append("PEO workflow does not explicitly persist candidate state fail-closed")

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

for marker in [
    "https://partener.eu/",
    'id="boot-fallback"',
    "Ai o investiție în minte?",
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
