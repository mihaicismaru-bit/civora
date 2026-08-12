#!/usr/bin/env python3
"""P10 integrity and no-credential monitor aggregation.

Runs after resolution-task maintenance. It verifies that the current validation
report is durably mirrored in history, checkpoint/state are identical, all
T1/T1B hash changes remain fail-closed behind resolution tasks, and auxiliary
MIPE/AFIR/PEO/MFF monitors are represented without promoting material facts.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import tempfile
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
VALIDATION = ROOT / "validation"
INGEST_STATE = ROOT / "ingest" / "state"
LATEST = VALIDATION / "latest.json"
HISTORY = VALIDATION / "history"
STATE = VALIDATION / "source_state.json"
CHECKPOINT = VALIDATION / "source_state.checkpoint.json"
TASKS = VALIDATION / "resolution-tasks"
OUT = VALIDATION / "external-monitors.json"
INTEGRATIONS = ROOT / "ops" / "integrations.json"
REPO_ROOT = ROOT.parent
VALIDATION_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "partener-eu-validation.yml"
PEO_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "partener-eu-peo-calendar.yml"
MAX_REGISTRY_AGE_SECONDS = 8 * 3600


def load(path: pathlib.Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def atomic_json(path: pathlib.Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def nowz() -> str:
    return now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except Exception:
        return None


def age_seconds(value: Any) -> int | None:
    parsed = parse_utc(value)
    if not parsed:
        return None
    return max(0, int((now() - parsed).total_seconds()))


def canonical_sha(obj: Any) -> str:
    body = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def history_path(report: dict[str, Any]) -> pathlib.Path | None:
    started = report.get("run_started")
    if not started:
        return None
    stamp = str(started).replace(":", "").replace("-", "")
    return HISTORY / f"{stamp}.json"


def task_is_fail_closed(path: pathlib.Path) -> bool:
    task = load(path, {}) or {}
    allowed = task.get("automatic_material_fact_update_allowed")
    if allowed is None:
        allowed = task.get("material_fact_autoupdate_allowed")
    return bool(task) and allowed is False


def main() -> int:
    observed_at = nowz()
    errors: list[str] = []

    latest = load(LATEST, {}) or {}
    hist_path = history_path(latest)
    history_copy = load(hist_path, {}) if hist_path else {}
    state = load(STATE, {}) or {}
    checkpoint = load(CHECKPOINT, {}) or {}
    frontend = latest.get("frontend_checks") or []

    latest_history_equal = bool(latest and history_copy and canonical_sha(latest) == canonical_sha(history_copy))
    state_checkpoint_equal = bool(state and checkpoint and canonical_sha(state) == canonical_sha(checkpoint))
    frontend_ok = bool(frontend) and all(bool(x.get("pass")) for x in frontend)
    if not latest_history_equal:
        errors.append("latest validation report is not identically persisted in history")
    if not state_checkpoint_equal:
        errors.append("source state and recovery checkpoint diverge")
    if not frontend_ok:
        errors.append("latest frontend regression evidence is not fully passing")

    registry = load(INGEST_STATE / "source_registry_health.json", {}) or {}
    registry_rows = registry.get("sources") or []
    registry_observed = registry.get("observed_at")
    registry_age = age_seconds(registry_observed)
    registry_stale = registry_age is None or registry_age > MAX_REGISTRY_AGE_SECONDS
    changed_rows = [x for x in registry_rows if x.get("semantic_hash_changed") and x.get("material_fact_use")]
    missing_registry_tasks: list[str] = []
    unsafe_registry_updates: list[str] = []
    for row in changed_rows:
        source_id = row.get("id")
        if not source_id:
            continue
        task_path = TASKS / f"{source_id}.json"
        if not task_is_fail_closed(task_path):
            missing_registry_tasks.append(source_id)
        if row.get("publish_material_fact_update") is not False:
            unsafe_registry_updates.append(source_id)
    if missing_registry_tasks:
        errors.append("registry hash changes lack fail-closed tasks: " + ", ".join(sorted(missing_registry_tasks)))
    if unsafe_registry_updates:
        errors.append("registry permits unsafe material update: " + ", ".join(sorted(unsafe_registry_updates)))

    tier_counts: dict[str, dict[str, int]] = {}
    for tier in ("T1", "T1B"):
        rows = [x for x in registry_rows if x.get("tier") == tier]
        tier_counts[tier] = {
            "total": len(rows),
            "pass": sum(x.get("health") == "PASS" for x in rows),
            "degraded": sum(x.get("health") == "DEGRADED" for x in rows),
            "fail": sum(x.get("health") == "FAIL" for x in rows),
            "quarantined": sum(bool(x.get("quarantined")) for x in rows),
            "hash_changes": sum(bool(x.get("semantic_hash_changed")) for x in rows),
        }
    registry_summary = registry.get("summary") or {}
    registry_health = "PASS"
    if registry_stale or registry_summary.get("degraded") or registry_summary.get("fail"):
        registry_health = "DEGRADED"
    if missing_registry_tasks or unsafe_registry_updates:
        registry_health = "FAIL_POLICY"

    afir_state = load(INGEST_STATE / "afir_state.json", {}) or {}
    afir_corpus = load(INGEST_STATE / "afir_corpus.json", {}) or {}
    afir_changed = [x for x in (afir_corpus.get("items") or []) if x.get("changedFromPrevious")]
    afir_material = [x for x in afir_changed if x.get("materialChangeCandidate")]
    afir_auth_dependencies = afir_corpus.get("accessDependencies") or []
    afir_task_required = bool(afir_changed)
    afir_task_ok = not afir_task_required or task_is_fail_closed(TASKS / "SRC-AFIR-CORPUS.json")
    afir_auto_promoted = bool((afir_corpus.get("policy") or {}).get("materialFactsAutoPromoted"))
    if not afir_task_ok:
        errors.append("AFIR hash changes lack consolidated fail-closed resolution task")
    if afir_auto_promoted:
        errors.append("AFIR corpus permits automatic material-fact promotion")

    peo = load(INGEST_STATE / "peo_calendar_state.json", {}) or {}
    peo_last = peo.get("lastRun") or {}
    peo_change_count = int(peo_last.get("changes") or 0)
    peo_task_required = peo_change_count > 0
    peo_task_ok = not peo_task_required or task_is_fail_closed(TASKS / "SRC-PEO-CALENDAR.json")
    if not peo_task_ok:
        errors.append("PEO calendar changes lack fail-closed resolution task")

    mipe = load(INGEST_STATE / "mipe_state.json", {}) or {}
    mipe_last = mipe.get("lastRun") or {}
    mipe_status = mipe.get("status") or mipe_last.get("status") or "UNKNOWN"

    mff = load(INGEST_STATE / "mff_2028_health.json", {}) or {}
    mff_rows = mff.get("sources") or []
    mff_changed = [x.get("id") for x in mff_rows if x.get("semantic_hash_changed")]
    mff_unsafe = [x.get("id") for x in mff_rows if x.get("auto_promote_legislative_stage")]
    if mff_unsafe:
        errors.append("MFF monitor permits automatic stage promotion: " + ", ".join(x for x in mff_unsafe if x))

    validation_workflow_text = VALIDATION_WORKFLOW.read_text(encoding="utf-8", errors="ignore") if VALIDATION_WORKFLOW.exists() else ""
    peo_workflow_text = PEO_WORKFLOW.read_text(encoding="utf-8", errors="ignore") if PEO_WORKFLOW.exists() else ""
    monitored_workflows = [
        "PARTENER.EU MIPE Ingestion",
        "PARTENER.EU AFIR Ingestion",
        "PARTENER.EU Verified Source Registry",
        "PARTENER.EU PEO Calendar",
        "PARTENER.EU MFF 2028-2034 Monitor",
        "PARTENER.EU Pages",
    ]
    workflow_run_integrated = "workflow_run:" in validation_workflow_text and all(
        name in validation_workflow_text for name in monitored_workflows
    )
    scheduled_validation_configured = "schedule:" in validation_workflow_text and "17 */6 * * *" in validation_workflow_text
    peo_candidate_state_only = (
        "peo_calendar_state.json" in peo_workflow_text
        and "git add partener-eu/web/peo-calendar.js" not in peo_workflow_text
        and "cp partener-eu/web/peo-calendar.js" not in peo_workflow_text
    )
    if not workflow_run_integrated:
        errors.append("autonomous monitor workflow_run integration is incomplete")
    if not scheduled_validation_configured:
        errors.append("scheduled production validation is not configured")
    if not peo_candidate_state_only:
        errors.append("PEO scheduled calendar workflow is not candidate-state-only")

    integrations = load(INTEGRATIONS, {}) or {}
    auth_dependencies = [
        {"id": x.get("id"), "status": x.get("status"), "auth": x.get("auth")}
        for x in (integrations.get("adapters") or [])
        if "DEPENDENT" in str(x.get("status") or "")
    ]

    report = {
        "schema_version": "1.0",
        "checkpoint": latest.get("checkpoint"),
        "observed_at": observed_at,
        "validation_run_started": latest.get("run_started"),
        "integrity": {
            "latest_history_equal": latest_history_equal,
            "latest_sha256": canonical_sha(latest) if latest else None,
            "history_sha256": canonical_sha(history_copy) if history_copy else None,
            "history_path": str(hist_path.relative_to(ROOT)) if hist_path and hist_path.exists() else None,
            "source_state_checkpoint_equal": state_checkpoint_equal,
            "source_state_sha256": canonical_sha(state) if state else None,
            "checkpoint_sha256": canonical_sha(checkpoint) if checkpoint else None,
            "frontend_regression_pass": frontend_ok,
            "frontend_pass": sum(bool(x.get("pass")) for x in frontend),
            "frontend_total": len(frontend),
            "recovery_state_integrity": "PASS" if latest_history_equal and state_checkpoint_equal else "FAIL",
        },
        "source_registry": {
            "observed_at": registry_observed,
            "age_seconds": registry_age,
            "stale_after_seconds": MAX_REGISTRY_AGE_SECONDS,
            "stale": registry_stale,
            "health": registry_health,
            "summary": registry_summary,
            "tier_counts": tier_counts,
            "changed_source_ids": [x.get("id") for x in changed_rows],
            "missing_resolution_tasks": sorted(missing_registry_tasks),
            "unsafe_material_updates": sorted(unsafe_registry_updates),
            "fail_closed": not missing_registry_tasks and not unsafe_registry_updates,
        },
        "afir": {
            "observed_at": afir_state.get("checkedAt") or afir_corpus.get("generatedAt"),
            "status": afir_state.get("status") or afir_corpus.get("status"),
            "item_count": afir_state.get("itemCount", len(afir_corpus.get("items") or [])),
            "error_count": afir_state.get("errorCount", len(afir_corpus.get("errors") or [])),
            "hash_change_candidates": len(afir_changed),
            "material_signal_candidates": len(afir_material),
            "auth_dependency_count": len(afir_auth_dependencies),
            "auth_dependencies": afir_auth_dependencies[:100],
            "resolution_task_required": afir_task_required,
            "resolution_task_present_fail_closed": afir_task_ok,
            "material_facts_auto_promoted": afir_auto_promoted,
        },
        "peo_calendar": {
            "observed_at": peo_last.get("observedAt"),
            "status": peo.get("status"),
            "source": peo.get("retrievalSource"),
            "source_class": peo.get("retrievalSourceClass"),
            "canonical_container": peo.get("canonicalContainer"),
            "direct_mipe_verified": bool(peo.get("directMipeVerified")),
            "sha256": peo_last.get("sha256"),
            "item_count": peo_last.get("itemCount"),
            "change_count": peo_change_count,
            "resolution_task_required": peo_task_required,
            "resolution_task_present_fail_closed": peo_task_ok,
            "publication_policy": "candidate-state-only; web material facts are not auto-promoted on scheduled hash changes",
        },
        "mipe": {
            "observed_at": mipe_last.get("observedAt"),
            "status": mipe_status,
            "source_available": bool(mipe_last.get("sourceAvailable")),
            "candidate_count": mipe_last.get("candidateCount"),
            "parsed_relevant_count": mipe_last.get("parsedRelevantCount"),
            "published_item_count": mipe_last.get("publishedItemCount"),
            "last_known_good_preserved": mipe_status == "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED",
            "health": "DEGRADED_FAIL_CLOSED" if mipe_status == "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED" else "PASS",
        },
        "mff_2028_2034": {
            "observed_at": mff.get("observed_at"),
            "summary": mff.get("summary") or {},
            "hash_changed_source_ids": [x for x in mff_changed if x],
            "unsafe_auto_promotions": [x for x in mff_unsafe if x],
            "fail_closed": not mff_unsafe,
        },
        "autonomous_orchestration": {
            "scheduled_validation_configured": scheduled_validation_configured,
            "workflow_run_integration_configured": workflow_run_integrated,
            "monitored_workflows": monitored_workflows,
            "peo_candidate_state_only": peo_candidate_state_only,
            "evidence_status": "CONFIGURED_AND_COLLECTING; NOT_SUFFICIENT_FOR_CLOSURE_BEFORE_30_DISTINCT_UTC_DAYS",
        },
        "integrations": {
            "ready_without_credentials": [
                x.get("id") for x in (integrations.get("adapters") or [])
                if x.get("status") == "READY" and x.get("auth") in (None, "NONE")
            ],
            "external_auth_dependencies": auth_dependencies,
            "fabricated_access": False,
        },
        "policy": {
            "material_fact_autoupdate_allowed": False,
            "hash_change_action": "RESOLUTION_TASK_ONLY",
            "blocked_fact_classes": ["deadline", "eligibility", "budget", "scoring", "beneficiaries", "material_call_status", "other_material_facts"],
        },
        "summary": {
            "integrity_pass": latest_history_equal and state_checkpoint_equal and frontend_ok,
            "registry_health": registry_health,
            "registry_hash_changes": len(changed_rows),
            "afir_hash_changes": len(afir_changed),
            "peo_calendar_changes": peo_change_count,
            "mipe_health": "DEGRADED_FAIL_CLOSED" if mipe_status == "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED" else "PASS",
            "autonomous_orchestration_configured": workflow_run_integrated and scheduled_validation_configured and peo_candidate_state_only,
            "policy_errors": errors,
            "critical_policy_fail": bool(errors),
        },
    }
    atomic_json(OUT, report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
