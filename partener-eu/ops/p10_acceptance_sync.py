#!/usr/bin/env python3
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
VALIDATION = ROOT / "validation"
HISTORY = VALIDATION / "history"
ACCEPTANCE = ROOT / "P10_ACCEPTANCE.json"
DEPLOYMENT = VALIDATION / "deployment.json"


def load(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def qualifies(report):
    if not isinstance(report, dict) or not report.get("live"):
        return False
    summary = report.get("summary") or {}
    frontend = report.get("frontend_checks") or []
    if summary.get("critical_fail"):
        return False
    if not frontend or not all(bool(x.get("pass")) for x in frontend):
        return False
    return True


def run():
    acceptance = load(ACCEPTANCE, {}) or {}
    qualified = []
    for path in sorted(HISTORY.glob("*.json")):
        report = load(path)
        if qualifies(report):
            qualified.append(report)

    dates = sorted({r.get("run_started", "")[:10] for r in qualified if r.get("run_started")})
    latest = qualified[-1] if qualified else None
    req = acceptance.setdefault("requirements", {})
    req["minimum_distinct_days"] = 30
    req["current_qualifying_days"] = len(dates)

    if latest:
        summary = latest.get("summary") or {}
        quarantined = [s for s in latest.get("sources", []) if s.get("quarantined")]
        acceptance["latest_qualifying_run"] = {
            "utc": latest.get("run_started"),
            "source_pass": summary.get("source_pass", 0),
            "source_degraded": summary.get("source_degraded", 0),
            "source_fail": summary.get("source_fail", 0),
            "source_quarantined": summary.get("source_quarantined", 0),
            "critical_fail": bool(summary.get("critical_fail")),
            "quarantined_source": "; ".join(
                f"{s.get('id')} — {s.get('name')}; dependent material facts blocked fail-closed"
                for s in quarantined
            ) or None,
        }

    deployment = load(DEPLOYMENT, {}) or {}
    if deployment:
        evidence = acceptance.setdefault("deployment_evidence", {})
        evidence.update({
            "utc": deployment.get("observed_at"),
            "status": deployment.get("status"),
            "http_status": deployment.get("http_status"),
            "final_url": deployment.get("final_url"),
            "title": deployment.get("title"),
            "required_markers_present": bool(deployment.get("marker_ok")),
        })
        # Do not infer HTTPS closure from a redirected HTTP endpoint.
        if str(deployment.get("final_url") or "").startswith("https://") and deployment.get("status") == "PASS":
            req["public_deployment"] = "VERIFIED_HTTPS_CONTENT"
            evidence["https_closure_gate"] = "PASS"
        else:
            req["public_deployment"] = "VERIFIED_HTTP_CONTENT_HTTPS_PENDING"
            evidence["https_closure_gate"] = "PENDING_VALID_CERTIFICATE_AND_HTTPS_VERIFICATION"

    ACCEPTANCE.write_text(json.dumps(acceptance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"qualifying_utc_dates": dates, "count": len(dates), "latest": latest.get("run_started") if latest else None}, ensure_ascii=False))


if __name__ == "__main__":
    run()
