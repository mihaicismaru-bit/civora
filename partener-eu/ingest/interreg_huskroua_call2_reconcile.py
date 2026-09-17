#!/usr/bin/env python3
"""Fail-closed same-identity reconciliation for HUSKROUA Call 2 exact evidence."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import interreg_huskroua_call2_exact as exact

SCHEMA = "PARTENER_EU_INTERREG_HUSKROUA_CALL2_RECONCILIATION_V1"
RECONCILER_VERSION = "INTERREG_HUSKROUA_CALL2_RECONCILE_V1"
MATERIAL_FLAGS = exact.MATERIAL_FLAGS


def sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("HUSKROUA reconciliation timestamps must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def identity(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_family": snapshot.get("source_family"),
        "programme_family": snapshot.get("programme_family"),
        "programme_id": snapshot.get("programme_id"),
        "official_call_identifier": str(snapshot.get("official_call_identifier") or ""),
        "official_call_identifier_kind": snapshot.get("official_call_identifier_kind"),
        "exact_authority_url": snapshot.get("exact_authority_url"),
        "closure_authority_url": snapshot.get("closure_authority_url"),
    }


def semantic_changes(previous: Mapping[str, Any], current: Mapping[str, Any]) -> list[dict[str, Any]]:
    before = dict(previous.get("exact_semantics") or {})
    after = dict(current.get("exact_semantics") or {})
    changes: list[dict[str, Any]] = []
    for field in sorted(set(before) | set(after)):
        if before.get(field) != after.get(field):
            changes.append({"field": field, "before": before.get(field), "after": after.get(field)})
    return changes


def reconcile(current: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    exact.validate_evidence(current)
    current_identity = identity(current)
    current_healthy = current.get("source_health_state") == "HEALTHY"

    previous_valid = False
    previous_healthy = False
    previous_sha = None
    previous_identity_match = None
    changes: list[dict[str, Any]] = []

    if previous is not None:
        exact.validate_evidence(previous)
        previous_identity_match = identity(previous) == current_identity
        if not previous_identity_match:
            raise ValueError("HUSKROUA previous exact receipt identity mismatch")
        if parse_time(str(previous.get("fetched_at"))) >= parse_time(str(current.get("fetched_at"))):
            raise ValueError("HUSKROUA previous exact receipt is not older than current")
        previous_valid = True
        previous_healthy = previous.get("source_health_state") == "HEALTHY"
        previous_sha = sha256_json(previous)

    if not current_healthy:
        state = "CURRENT_SOURCE_HEALTH_DEGRADED_LKG_REQUIRED"
        semantic_reconciliation_passed = False
        source_health_watch_candidate = True
        lkg_reference_required = True
        lkg_reference_available = bool(previous_valid and previous_healthy)
        baseline_captured = False
        material_ready = False
    elif not previous_valid:
        state = "BASELINE_CAPTURED_NON_AUTHORIZING"
        semantic_reconciliation_passed = True
        source_health_watch_candidate = False
        lkg_reference_required = False
        lkg_reference_available = False
        baseline_captured = True
        material_ready = False
    elif not previous_healthy:
        state = "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING"
        semantic_reconciliation_passed = True
        source_health_watch_candidate = True
        lkg_reference_required = False
        lkg_reference_available = False
        baseline_captured = True
        material_ready = False
    else:
        changes = semantic_changes(previous, current)
        state = "NO_CHANGE" if not changes else "HUSKROUA_CALL2_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
        semantic_reconciliation_passed = True
        source_health_watch_candidate = False
        lkg_reference_required = False
        lkg_reference_available = True
        baseline_captured = False
        material_ready = True

    result: dict[str, Any] = {
        "schema": SCHEMA,
        "reconciler_version": RECONCILER_VERSION,
        "source_family": "INTERREG",
        "programme_family": "INTERREG_HUSKROUA_2021_2027",
        "programme_id": "HUSKROUA",
        "official_call_identifier": "2",
        "official_call_identifier_kind": "OFFICIAL_CALL_NUMBER",
        "exact_authority_url": current.get("exact_authority_url"),
        "closure_authority_url": current.get("closure_authority_url"),
        "observation_state": "EXACT_CALL_RECONCILED_NON_AUTHORIZING",
        "current_run_id": current.get("run_id"),
        "current_fetched_at": current.get("fetched_at"),
        "current_evidence_sha256": sha256_json(current),
        "current_exact_semantic_fingerprint": current.get("exact_semantic_fingerprint"),
        "current_source_health_state": current.get("source_health_state"),
        "previous_fetched_at": previous.get("fetched_at") if previous else None,
        "previous_evidence_sha256": previous_sha,
        "previous_exact_semantic_fingerprint": previous.get("exact_semantic_fingerprint") if previous else None,
        "previous_identity_match": previous_identity_match,
        "reconciliation_state": state,
        "semantic_reconciliation_passed": semantic_reconciliation_passed,
        "semantic_change_count": len(changes),
        "semantic_changes": changes,
        "source_health_watch_candidate": source_health_watch_candidate,
        "baseline_captured": baseline_captured,
        "lkg_reference_required": lkg_reference_required,
        "lkg_reference_available": lkg_reference_available,
        "lkg_reference_is_current_truth": False,
        "previous_or_lkg_is_current_truth": False,
        "material_admission_ready_for_downstream_review": material_ready,
        "field_scoped_material_admission_required": True,
        "publication_effect": "NONE",
    }
    for flag in MATERIAL_FLAGS:
        result[flag] = False
    result["reconciliation_fingerprint"] = sha256_json({
        "identity": current_identity,
        "state": state,
        "current_exact_semantic_fingerprint": current.get("exact_semantic_fingerprint"),
        "previous_exact_semantic_fingerprint": previous.get("exact_semantic_fingerprint") if previous else None,
        "current_source_health_state": current.get("source_health_state"),
        "previous_source_health_state": previous.get("source_health_state") if previous else None,
        "semantic_changes": changes,
    })
    validate_reconciliation(result, current=current, previous=previous)
    return result


def validate_reconciliation(
    receipt: Mapping[str, Any], *, current: Mapping[str, Any], previous: Mapping[str, Any] | None = None
) -> None:
    exact.validate_evidence(current)
    if receipt.get("schema") != SCHEMA or receipt.get("reconciler_version") != RECONCILER_VERSION:
        raise ValueError("HUSKROUA reconciliation schema/version drift")
    if receipt.get("source_family") != "INTERREG" or receipt.get("programme_family") != "INTERREG_HUSKROUA_2021_2027":
        raise ValueError("HUSKROUA reconciliation family drift")
    if receipt.get("programme_id") != "HUSKROUA" or str(receipt.get("official_call_identifier")) != "2":
        raise ValueError("HUSKROUA reconciliation call identity drift")
    if receipt.get("official_call_identifier_kind") != "OFFICIAL_CALL_NUMBER":
        raise ValueError("HUSKROUA reconciliation identifier-kind drift")
    if receipt.get("exact_authority_url") != current.get("exact_authority_url") or receipt.get("closure_authority_url") != current.get("closure_authority_url"):
        raise ValueError("HUSKROUA reconciliation authority binding drift")
    if receipt.get("current_evidence_sha256") != sha256_json(current):
        raise ValueError("HUSKROUA reconciliation current evidence binding failed")
    if receipt.get("previous_or_lkg_is_current_truth") is not False or receipt.get("lkg_reference_is_current_truth") is not False:
        raise ValueError("HUSKROUA reconciliation promoted history/LKG to current truth")
    if receipt.get("field_scoped_material_admission_required") is not True or receipt.get("publication_effect") != "NONE":
        raise ValueError("HUSKROUA reconciliation crossed material/publication boundary")
    for flag in MATERIAL_FLAGS:
        if receipt.get(flag) is not False:
            raise ValueError(f"HUSKROUA reconciliation attempted authorization: {flag}")

    current_healthy = current.get("source_health_state") == "HEALTHY"
    if previous is None:
        expected = "BASELINE_CAPTURED_NON_AUTHORIZING" if current_healthy else "CURRENT_SOURCE_HEALTH_DEGRADED_LKG_REQUIRED"
        if receipt.get("reconciliation_state") != expected:
            raise ValueError("HUSKROUA baseline/degraded reconciliation state invalid")
        if receipt.get("previous_evidence_sha256") is not None:
            raise ValueError("HUSKROUA baseline unexpectedly bound previous evidence")
        if receipt.get("material_admission_ready_for_downstream_review") is not False:
            raise ValueError("HUSKROUA baseline/degraded evidence became material-ready")
        return

    exact.validate_evidence(previous)
    if identity(previous) != identity(current):
        raise ValueError("HUSKROUA reconciliation previous identity mismatch")
    if parse_time(str(previous.get("fetched_at"))) >= parse_time(str(current.get("fetched_at"))):
        raise ValueError("HUSKROUA reconciliation previous evidence ordering invalid")
    if receipt.get("previous_evidence_sha256") != sha256_json(previous):
        raise ValueError("HUSKROUA reconciliation previous evidence binding failed")

    previous_healthy = previous.get("source_health_state") == "HEALTHY"
    if not current_healthy:
        if receipt.get("reconciliation_state") != "CURRENT_SOURCE_HEALTH_DEGRADED_LKG_REQUIRED":
            raise ValueError("HUSKROUA degraded current did not fail closed")
        if receipt.get("semantic_reconciliation_passed") is not False:
            raise ValueError("HUSKROUA degraded current cannot pass semantic reconciliation")
        if receipt.get("lkg_reference_required") is not True or receipt.get("lkg_reference_available") is not previous_healthy:
            raise ValueError("HUSKROUA degraded current LKG accounting drift")
        if receipt.get("material_admission_ready_for_downstream_review") is not False:
            raise ValueError("HUSKROUA degraded current became material-ready")
    elif not previous_healthy:
        if receipt.get("reconciliation_state") != "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING":
            raise ValueError("HUSKROUA health recovery did not baseline-refresh")
        if receipt.get("material_admission_ready_for_downstream_review") is not False:
            raise ValueError("HUSKROUA health recovery became material-ready")
    else:
        expected_changes = semantic_changes(previous, current)
        expected = "NO_CHANGE" if not expected_changes else "HUSKROUA_CALL2_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
        if receipt.get("reconciliation_state") != expected:
            raise ValueError("HUSKROUA reconciliation state disagrees with semantic evidence")
        if receipt.get("semantic_change_count") != len(expected_changes) or receipt.get("semantic_changes") != expected_changes:
            raise ValueError("HUSKROUA reconciliation semantic change accounting drift")
        if receipt.get("semantic_reconciliation_passed") is not True:
            raise ValueError("HUSKROUA healthy same-identity semantic reconciliation did not pass")
        if receipt.get("material_admission_ready_for_downstream_review") is not True:
            raise ValueError("HUSKROUA healthy same-identity reconciliation should only become downstream-review ready")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("current")
    parser.add_argument("--previous")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    current = json.loads(Path(args.current).read_text(encoding="utf-8"))
    previous = json.loads(Path(args.previous).read_text(encoding="utf-8")) if args.previous else None
    result = reconcile(current, previous)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "official_call_identifier": result["official_call_identifier"],
        "reconciliation_state": result["reconciliation_state"],
        "semantic_change_count": result["semantic_change_count"],
        "lkg_reference_available": result["lkg_reference_available"],
        "material_admission_ready_for_downstream_review": result["material_admission_ready_for_downstream_review"],
        "publication_effect": result["publication_effect"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
