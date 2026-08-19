#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "eucons" / "ops" / "github_automation_contract.json"
CHECKPOINT_PATH = ROOT / "eucons" / "ops" / "checkpoint.json"
HEALTH_PATH = ROOT / "eucons" / "ops" / "health.json"
RECEIPTS_DIR = ROOT / "eucons" / "ops" / "receipts"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_receipt(output: Path, payload: dict[str, Any]) -> None:
    payload = dict(payload)
    payload["receipt_hash"] = canonical_hash(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def phase_receipt_index() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for path in sorted(RECEIPTS_DIR.glob("E[0-9][0-9]_*.json")):
        phase = path.name[:3]
        result.setdefault(phase, []).append(path.name)
    return result


def reconcile() -> dict[str, Any]:
    checkpoint = load_json(CHECKPOINT_PATH)
    health = load_json(HEALTH_PATH)
    receipt_index = phase_receipt_index()
    completed = list(checkpoint["completed_phases"])
    current = str(checkpoint["current_phase"])
    missing = [phase for phase in completed if not receipt_index.get(phase)]
    failures: list[str] = []
    if missing:
        failures.append("MISSING_ACCEPTANCE_RECEIPT:" + ",".join(missing))
    if current in completed:
        failures.append("CURRENT_PHASE_ALREADY_COMPLETED")
    if health.get("critical_failures"):
        failures.append("HEALTH_HAS_CRITICAL_FAILURES")
    if checkpoint.get("development_state") not in {"IN_PROGRESS", "PRODUCTION_READY", "BLOCKED_EXTERNAL_ONLY"}:
        failures.append("UNKNOWN_DEVELOPMENT_STATE")
    return {
        "engine_id": "EUCONS_E22_GITHUB_AUTOMATION",
        "operation": "RECONCILIATION",
        "status": "PASS" if not failures else "FAIL",
        "current_phase": current,
        "completed_phase_count": len(completed),
        "receipt_phase_count": len(receipt_index),
        "missing_receipt_phases": missing,
        "critical_failures": failures,
        "canonical_state_mutated": False,
    }


def health_check() -> dict[str, Any]:
    contract = load_json(CONTRACT_PATH)
    checkpoint = load_json(CHECKPOINT_PATH)
    health = load_json(HEALTH_PATH)
    checks = health.get("checks", {})
    failures: list[str] = []
    if health.get("overall") != contract["health"]["overall_required"] and checkpoint.get("development_state") == "IN_PROGRESS":
        failures.append("OVERALL_HEALTH_NOT_GREEN_DEVELOPMENT")
    if health.get("critical_failures"):
        failures.append("CRITICAL_FAILURES_PRESENT")

    closed_gate_keys = [
        "crm_production_persistence",
        "offer_automatic_send",
        "knowledge_runtime_publication",
        "editorial_runtime_publication",
        "seo_preview_indexing",
        "linkedin_direct_publication",
        "facebook_direct_publication",
        "email_direct_sending",
        "analytics_direct_transport",
        "production_personal_data_collection",
    ]
    open_gates: list[str] = []
    for key in closed_gate_keys:
        value = str(checks.get(key, "MISSING"))
        if not value.startswith("DISABLED"):
            open_gates.append(f"{key}={value}")
    if open_gates:
        failures.append("PRODUCTION_GATE_OPEN_OR_MISSING:" + ";".join(open_gates))

    return {
        "engine_id": "EUCONS_E22_GITHUB_AUTOMATION",
        "operation": "HEALTH",
        "status": "PASS" if not failures else "FAIL",
        "development_state": checkpoint.get("development_state"),
        "current_phase": checkpoint.get("current_phase"),
        "overall_health": health.get("overall"),
        "production_gates_checked": len(closed_gate_keys),
        "open_or_missing_production_gates": open_gates,
        "critical_failures": failures,
        "external_side_effects": False,
    }


def directory_manifest(path: Path) -> dict[str, Any]:
    if not path.is_dir():
        raise ValueError(f"build directory missing: {path}")
    files: list[dict[str, Any]] = []
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        rel = item.relative_to(path).as_posix()
        digest = hashlib.sha256(item.read_bytes()).hexdigest()
        files.append({"path": rel, "sha256": digest, "bytes": item.stat().st_size})
    if not files:
        raise ValueError("build directory is empty")
    return {
        "files": files,
        "file_count": len(files),
        "manifest_hash": canonical_hash(files),
    }


def scheduler_receipt(reference_time: str) -> dict[str, Any]:
    checkpoint = load_json(CHECKPOINT_PATH)
    health = health_check()
    reconcile_result = reconcile()
    failures = []
    if health["status"] != "PASS":
        failures.append("HEALTH_GATE_FAILED")
    if reconcile_result["status"] != "PASS":
        failures.append("RECONCILIATION_GATE_FAILED")
    return {
        "engine_id": "EUCONS_E22_GITHUB_AUTOMATION",
        "operation": "SCHEDULER_DRY_RUN",
        "status": "PASS" if not failures else "FAIL",
        "reference_time": reference_time,
        "current_phase": checkpoint.get("current_phase"),
        "health_status": health["status"],
        "reconciliation_status": reconcile_result["status"],
        "network_access_required": False,
        "provider_credentials_used": False,
        "external_publication": False,
        "canonical_state_mutated": False,
        "critical_failures": failures,
    }


def stamped(payload: dict[str, Any], generated_at: str | None) -> dict[str, Any]:
    value = dict(payload)
    if generated_at:
        value["generated_at"] = generated_at
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="EUCONS E22 read-only GitHub automation helper")
    sub = parser.add_subparsers(dest="command", required=True)

    p_reconcile = sub.add_parser("reconcile")
    p_reconcile.add_argument("--output", type=Path, required=True)
    p_reconcile.add_argument("--generated-at")

    p_health = sub.add_parser("health")
    p_health.add_argument("--output", type=Path, required=True)
    p_health.add_argument("--generated-at")

    p_schedule = sub.add_parser("schedule")
    p_schedule.add_argument("--output", type=Path, required=True)
    p_schedule.add_argument("--reference-time", required=True)
    p_schedule.add_argument("--generated-at")

    p_build = sub.add_parser("build-receipt")
    p_build.add_argument("--build-dir", type=Path, required=True)
    p_build.add_argument("--output", type=Path, required=True)
    p_build.add_argument("--generated-at")

    args = parser.parse_args()
    if args.command == "reconcile":
        payload = reconcile()
    elif args.command == "health":
        payload = health_check()
    elif args.command == "schedule":
        payload = scheduler_receipt(args.reference_time)
    else:
        manifest = directory_manifest(args.build_dir)
        payload = {
            "engine_id": "EUCONS_E22_GITHUB_AUTOMATION",
            "operation": "BUILD",
            "status": "PASS",
            "manifest": manifest,
            "deployment_performed": False,
            "external_side_effects": False,
        }
    payload = stamped(payload, getattr(args, "generated_at", None))
    write_receipt(args.output, payload)
    print(json.dumps({"status": payload["status"], "operation": payload["operation"], "output": str(args.output)}, sort_keys=True))
    if payload["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
