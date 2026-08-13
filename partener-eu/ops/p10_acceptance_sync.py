#!/usr/bin/env python3
"""Synchronize the persistent P10 acceptance ledger without closing P10.

The ledger counts only distinct UTC dates containing qualifying live validation
runs. Public content, HTTPS, recovery/state integrity, no-credential monitors,
and external authentication dependencies are recorded as separate closure gates.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
VALIDATION = ROOT / "validation"
HISTORY = VALIDATION / "history"
ACCEPTANCE = ROOT / "P10_ACCEPTANCE.json"
DEPLOYMENT = VALIDATION / "deployment.json"
MONITORS = VALIDATION / "external-monitors.json"
PAGES_DEPLOYMENT = ROOT / "deployment" / "latest.json"
MINIMUM_DISTINCT_DAYS = 30


def load(path: pathlib.Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def qualifies(report: Any) -> bool:
    """Canonical distinct-day qualification rule retained for historical runs."""
    if not isinstance(report, dict) or not report.get("live"):
        return False
    summary = report.get("summary") or {}
    frontend = report.get("frontend_checks") or []
    if summary.get("critical_fail"):
        return False
    if not frontend or not all(bool(x.get("pass")) for x in frontend):
        return False
    return True


def endpoint_summary(deployment: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for endpoint in deployment.get("endpoints") or []:
        rows.append({
            "id": endpoint.get("id"),
            "http_status": endpoint.get("http_status"),
            "final_url": endpoint.get("final_url"),
            "redirect_chain": endpoint.get("redirect_chain") or [],
            "content_verified": bool(endpoint.get("content_verified")),
            "marker_ok": bool(endpoint.get("marker_ok")),
            "critical_assets_ok": bool(endpoint.get("critical_assets_ok")),
            "legacy_origin_detected": bool(endpoint.get("legacy_origin_detected")),
            "error": endpoint.get("error"),
        })
    return rows


def run() -> None:
    acceptance = load(ACCEPTANCE, {}) or {}
    qualified: list[dict[str, Any]] = []
    for path in sorted(HISTORY.glob("*.json")):
        report = load(path)
        if qualifies(report):
            qualified.append(report)

    dates = sorted({r.get("run_started", "")[:10] for r in qualified if r.get("run_started")})
    latest = qualified[-1] if qualified else None

    acceptance["checkpoint"] = (latest or {}).get("checkpoint") or acceptance.get("checkpoint") or "PARTENER-EU-CIVORA-P10-0020"
    acceptance["phase"] = "P10 Production Validation"
    # Never close from this synchronizer. Closure is a separate controlled decision
    # after every gate, including 30 distinct UTC days, has durable evidence.
    acceptance["status"] = "VALIDATION_RUNNING_NOT_CLOSED"
    req = acceptance.setdefault("requirements", {})
    req["minimum_distinct_days"] = MINIMUM_DISTINCT_DAYS
    req["current_qualifying_days"] = len(dates)
    req["persistent_validation_ledger"] = "LIVE"
    req["source_change_fail_closed"] = "IMPLEMENTED"
    req["scheduled_validation"] = "ACTIVE_6_HOURLY_PLUS_WORKFLOW_RUN_MONITOR_TRIGGERS"
    req["autonomous_update_evidence"] = "COLLECTION_ACTIVE_NOT_YET_SUFFICIENT_FOR_CLOSURE"

    if latest:
        summary = latest.get("summary") or {}
        quarantined = [s for s in latest.get("sources", []) if s.get("quarantined")]
        frontend = latest.get("frontend_checks") or []
        acceptance["latest_qualifying_run"] = {
            "utc": latest.get("run_started"),
            "source_pass": summary.get("source_pass", 0),
            "source_degraded": summary.get("source_degraded", 0),
            "source_fail": summary.get("source_fail", 0),
            "source_quarantined": summary.get("source_quarantined", 0),
            "critical_fail": bool(summary.get("critical_fail")),
            "frontend_pass": sum(bool(x.get("pass")) for x in frontend),
            "frontend_total": len(frontend),
            "quarantined_source": "; ".join(
                f"{s.get('id')} — {s.get('name')}; dependent material facts blocked fail-closed"
                for s in quarantined
            ) or None,
        }
        req["frontend_regression"] = f"{sum(bool(x.get('pass')) for x in frontend)}/{len(frontend)}_PASS_LATEST"

    monitors = load(MONITORS, {}) or {}
    integrity = monitors.get("integrity") or {}
    monitor_summary = monitors.get("summary") or {}
    integrity_ok = bool(
        integrity.get("latest_history_equal")
        and integrity.get("source_state_checkpoint_equal")
        and integrity.get("frontend_regression_pass")
    )
    if monitors:
        req["atomic_state_and_recovery"] = "PASS" if integrity_ok else "FAIL"
        registry_health = str((monitors.get("source_registry") or {}).get("health") or "UNKNOWN")
        req["source_monitoring"] = "LIVE_AND_PERSISTING" if registry_health == "PASS" else f"{registry_health}_FAIL_CLOSED"
        acceptance["monitor_evidence"] = {
            "utc": monitors.get("observed_at"),
            "validation_run_started": monitors.get("validation_run_started"),
            "integrity": integrity,
            "source_registry": monitors.get("source_registry"),
            "afir": monitors.get("afir"),
            "peo_calendar": monitors.get("peo_calendar"),
            "mipe": monitors.get("mipe"),
            "mff_2028_2034": monitors.get("mff_2028_2034"),
            "autonomous_orchestration": monitors.get("autonomous_orchestration"),
            "integrations": monitors.get("integrations"),
            "summary": monitor_summary,
        }
    else:
        req["atomic_state_and_recovery"] = req.get("atomic_state_and_recovery") or "PENDING_EVIDENCE"
        req["source_monitoring"] = req.get("source_monitoring") or "PENDING_EVIDENCE"

    deployment = load(DEPLOYMENT, {}) or {}
    pages_deployment = load(PAGES_DEPLOYMENT, {}) or {}
    deployment_ok = False
    if deployment:
        public_content = bool(deployment.get("public_content_verified") or deployment.get("marker_ok"))
        https_verified = bool(deployment.get("https_verified"))
        deployment_ok = bool(https_verified and deployment.get("status") == "PASS")
        if deployment_ok:
            req["public_deployment"] = "VERIFIED_HTTPS_CONTENT"
        elif public_content:
            req["public_deployment"] = "VERIFIED_HTTP_CONTENT_HTTPS_PENDING"
        else:
            req["public_deployment"] = "PUBLIC_DEPLOYMENT_NOT_VERIFIED"

        acceptance["deployment_evidence"] = {
            "utc": deployment.get("observed_at"),
            "status": deployment.get("status"),
            "public_content_verified": public_content,
            "https_verified": https_verified,
            "secure_transport_verified": bool(deployment.get("secure_transport_verified")),
            "http_redirects_to_https": bool(deployment.get("http_redirects_to_https")),
            "pages_https_preserved": bool(deployment.get("pages_https_preserved")),
            "http_content_verified": bool(deployment.get("http_content_verified")),
            "content_origin": deployment.get("content_origin"),
            "http_status": deployment.get("http_status"),
            "final_url": deployment.get("final_url"),
            "title": deployment.get("title"),
            "required_markers_present": bool(deployment.get("marker_ok")),
            "critical_assets_ok": bool(deployment.get("critical_assets_ok")),
            "old_origin_detected": bool(deployment.get("old_origin_detected")),
            "https_closure_gate": deployment.get("https_closure_gate") or ("PASS" if deployment_ok else "PENDING_VALID_CERTIFICATE_AND_HTTPS_VERIFICATION"),
            "endpoints": endpoint_summary(deployment),
            "pages_workflow": {
                "status": pages_deployment.get("status"),
                "page_url": pages_deployment.get("page_url"),
                "git_sha": pages_deployment.get("git_sha"),
                "observed_at": pages_deployment.get("observed_at"),
                "configure_outcome": pages_deployment.get("configure_outcome"),
                "upload_outcome": pages_deployment.get("upload_outcome"),
                "deploy_outcome": pages_deployment.get("deploy_outcome"),
                "https_control": pages_deployment.get("https_control"),
            },
            "error": deployment.get("error"),
        }
    else:
        req["public_deployment"] = "PUBLIC_DEPLOYMENT_NOT_VERIFIED"

    days_ok = len(dates) >= MINIMUM_DISTINCT_DAYS
    recovery_ok = req.get("atomic_state_and_recovery") == "PASS"
    autonomous_evidence_ok = False  # becomes true only after the controlled 30-day evidence window is complete
    acceptance["closure_evaluation"] = {
        "eligible": False,
        "minimum_distinct_days_pass": days_ok,
        "public_https_deployment_pass": deployment_ok,
        "recovery_state_integrity_pass": recovery_ok,
        "autonomous_update_evidence_pass": autonomous_evidence_ok,
        "p10_closed": False,
        "civora_v1_production_baseline_closed": False,
    }
    acceptance["closure_rule"] = (
        "P10 and CIVORA v1.0 may close only after >=30 distinct UTC dates with qualifying production validation "
        "plus fully verified public HTTPS deployment, recovery/state-integrity evidence, and sufficient autonomous-update evidence."
    )
    acceptance["social_integrations"] = (
        "Facebook/LinkedIn/Reddit and other authenticated systems remain external authentication/access dependencies; no access is fabricated."
    )

    ACCEPTANCE.write_text(json.dumps(acceptance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "qualifying_utc_dates": dates,
        "count": len(dates),
        "latest": latest.get("run_started") if latest else None,
        "deployment_gate": req.get("public_deployment"),
        "recovery_gate": req.get("atomic_state_and_recovery"),
        "status": acceptance["status"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    run()
