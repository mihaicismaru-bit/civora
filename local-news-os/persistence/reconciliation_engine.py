#!/usr/bin/env python3
"""Deterministic, fail-closed reconciliation for CIVORA persistence state.

This engine consumes normalized Drive/repository/external snapshots and produces
advisory reconciled decisions, capabilities, backlog gaps and persistence health.
It never mutates Google Drive, GitHub, external accounts or publication state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
IMPLEMENTATION_STATES = {
    "MERGED",
    "OPEN_PR",
    "DRAFT_PR",
    "CLOSED_UNMERGED",
    "ABSENT",
    "SUPERSEDED",
}
DECISION_STATES = {
    "ACTIVE_UNIMPLEMENTED",
    "PARTIAL",
    "IMPLEMENTED",
    "BLOCKED_EXTERNAL",
    "SUPERSEDED",
    "DEPRECATED",
    "CANCELLED",
}
CONFIRMED_EXTERNAL_STATES = {
    "CONFIRMED",
    "LIVE_CONFIRMED",
    "REMOTE_PUBLICATION_EVIDENCE_PRESENT",
    "VERIFIED_PUBLISHING_ACCESS",
    "CONFIRMED_HTTP_HEALTHY",
    "NOT_APPLICABLE",
}
DIRECT_RUNTIME_STATES = {"DIRECT", "DIRECT_NATIVE", "DIRECT_NATIVE_FAIL_CLOSED"}
GATED_RUNTIME_STATES = {"GATED_DIRECT", "DIRECT_NATIVE_GATED"}
OUTBOX_RUNTIME_STATES = {"OUTBOX_ONLY", "DURABLE_OUTBOX_ONLY", "NO_DIRECT_ADAPTER"}
REQUIRED_FRESH_GATES = (
    "history_index_complete",
    "external_snapshot_valid",
    "active_binding_pass",
    "writer_lease_all_writers",
    "clean_interleaved_cycle",
    "scope_drift_pass",
    "cold_resume_pass",
    "idempotency_pass",
    "reconciliation_engine_pass",
)
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


class ReconciliationError(RuntimeError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _as_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReconciliationError(f"{label} must be an object")
    return value


def _as_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ReconciliationError(f"{label} must be an array")
    return value


def _index_by(rows: list[Any], key: str, label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(rows):
        row = _as_object(raw, f"{label}[{index}]")
        identity = str(row.get(key) or "").strip()
        if not identity:
            raise ReconciliationError(f"{label}[{index}] missing {key}")
        if identity in result:
            raise ReconciliationError(f"duplicate {label} {key}={identity}")
        result[identity] = row
    return result


def _external_confirmed(state: str) -> bool:
    return state in CONFIRMED_EXTERNAL_STATES


def _normalize_direct(runtime_state: str) -> str:
    if runtime_state in DIRECT_RUNTIME_STATES:
        return "DIRECT"
    if runtime_state in GATED_RUNTIME_STATES:
        return "GATED_DIRECT"
    if runtime_state in OUTBOX_RUNTIME_STATES:
        return "OUTBOX_ONLY"
    return "UNKNOWN"


def _decision_status(
    persisted: dict[str, Any],
    repository: dict[str, Any],
    external_state: str,
) -> str:
    superseded_by = str(persisted.get("superseded_by") or repository.get("superseded_by") or "").strip()
    if superseded_by:
        return "SUPERSEDED"
    persisted_status = str(persisted.get("status") or "ACTIVE_UNIMPLEMENTED")
    if persisted_status in {"DEPRECATED", "CANCELLED"}:
        return persisted_status
    implementation_state = str(repository.get("implementation_state") or "ABSENT")
    if implementation_state not in IMPLEMENTATION_STATES:
        raise ReconciliationError(f"unknown implementation_state={implementation_state}")
    if implementation_state == "SUPERSEDED":
        return "SUPERSEDED"
    if implementation_state != "MERGED":
        if bool(repository.get("partial_evidence")):
            return "PARTIAL"
        return "ACTIVE_UNIMPLEMENTED"
    requires_external = bool(persisted.get("requires_external") or repository.get("requires_external"))
    if not requires_external:
        return "IMPLEMENTED"
    if _external_confirmed(external_state):
        return "IMPLEMENTED"
    if str(persisted.get("blocker") or repository.get("blocker") or "").strip():
        return "BLOCKED_EXTERNAL"
    return "PARTIAL"


def _reconcile_decisions(
    persisted_rows: list[Any],
    repository_layer: dict[str, Any],
    external_layer: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    persisted = _index_by(persisted_rows, "decision_id", "decisions")
    repo_map = _as_object(repository_layer.get("decisions", {}), "repository.decisions")
    external_map = _as_object(external_layer.get("decisions", {}), "external.decisions")
    output: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    for decision_id in sorted(persisted):
        prior = persisted[decision_id]
        repo = _as_object(repo_map.get(decision_id, {}), f"repository.decisions.{decision_id}")
        external = _as_object(external_map.get(decision_id, {}), f"external.decisions.{decision_id}")
        external_state = str(external.get("external_state") or "UNCONFIRMED")
        prior_status = str(prior.get("status") or "ACTIVE_UNIMPLEMENTED")
        if prior_status not in DECISION_STATES:
            raise ReconciliationError(f"decision {decision_id} has invalid persisted status {prior_status}")
        current_status = _decision_status(prior, repo, external_state)
        row = deepcopy(prior)
        row["decision_id"] = decision_id
        row["status"] = current_status
        row["implementation_state"] = str(repo.get("implementation_state") or "ABSENT")
        row["external_state"] = external_state
        effective_superseded_by = str(prior.get("superseded_by") or repo.get("superseded_by") or "").strip()
        if effective_superseded_by:
            row["superseded_by"] = effective_superseded_by
        row["implementation_evidence"] = list(repo.get("evidence", prior.get("implementation_evidence", [])) or [])
        row["runtime_evidence"] = list(external.get("evidence", prior.get("runtime_evidence", [])) or [])
        output.append(row)

        if prior_status in {"ACTIVE_UNIMPLEMENTED", "PARTIAL", "BLOCKED_EXTERNAL"} and current_status == "IMPLEMENTED":
            diagnostics.append({
                "kind": "FALSE_NEGATIVE_PERSISTENCE",
                "decision_id": decision_id,
                "persisted_status": prior_status,
                "reconciled_status": current_status,
            })
        if prior_status == "IMPLEMENTED" and current_status != "IMPLEMENTED":
            diagnostics.append({
                "kind": "FALSE_POSITIVE_PERSISTENCE",
                "decision_id": decision_id,
                "persisted_status": prior_status,
                "reconciled_status": current_status,
            })
        if current_status == "SUPERSEDED" and prior_status != "SUPERSEDED":
            diagnostics.append({
                "kind": "SUPERSEDED_WORK",
                "decision_id": decision_id,
                "persisted_status": prior_status,
                "reconciled_status": current_status,
                "superseded_by": str(row.get("superseded_by") or repo.get("superseded_by") or ""),
            })
    return output, diagnostics


def _capability_status(
    desired_state: str,
    code_state: str,
    runtime_state: str,
    external_state: str,
) -> tuple[str, str, str | None]:
    direct_mode = _normalize_direct(runtime_state)
    desired_upper = desired_state.upper()
    code_ready = code_state in {"READY", "IMPLEMENTED", "ACTIVE"}
    if not code_ready:
        return "ACTIVE_UNIMPLEMENTED", direct_mode, "CODE_GAP"
    if "DIRECT" in desired_upper and direct_mode == "OUTBOX_ONLY":
        return "PARTIAL", direct_mode, "DIRECT_ADAPTER_OR_ACCESS_GAP"
    if "DIRECT" in desired_upper and direct_mode == "GATED_DIRECT":
        return "PARTIAL", direct_mode, "DIRECT_EXTERNAL_GATE"
    if any(token in desired_upper for token in ("LIVE", "EXTERNAL", "DIRECT")) and not _external_confirmed(external_state):
        return "PARTIAL", direct_mode, "EXTERNAL_CONFIRMATION_GAP"
    return "IMPLEMENTED", direct_mode, None


def _reconcile_capabilities(
    persisted_rows: list[Any],
    repository_layer: dict[str, Any],
    external_layer: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    persisted = _index_by(persisted_rows, "capability_id", "capabilities")
    repo_map = _as_object(repository_layer.get("capabilities", {}), "repository.capabilities")
    external_map = _as_object(external_layer.get("capabilities", {}), "external.capabilities")
    output: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for capability_id in sorted(persisted):
        prior = persisted[capability_id]
        repo = _as_object(repo_map.get(capability_id, {}), f"repository.capabilities.{capability_id}")
        external = _as_object(external_map.get(capability_id, {}), f"external.capabilities.{capability_id}")
        desired_state = str(prior.get("desired_state") or "READY")
        code_state = str(repo.get("code_state") or prior.get("code_state") or "UNKNOWN")
        runtime_state = str(repo.get("runtime_state") or prior.get("runtime_state") or "UNKNOWN")
        external_state = str(external.get("external_state") or "UNCONFIRMED")
        status, direct_mode, gap = _capability_status(desired_state, code_state, runtime_state, external_state)
        row = deepcopy(prior)
        row.update({
            "capability_id": capability_id,
            "status": status,
            "desired_state": desired_state,
            "code_state": code_state,
            "runtime_state": runtime_state,
            "external_state": external_state,
            "direct_or_outbox": direct_mode,
            "gap": gap,
            "evidence_refs": sorted({
                *[str(v) for v in prior.get("evidence_refs", []) or []],
                *[str(v) for v in repo.get("evidence", []) or []],
                *[str(v) for v in external.get("evidence", []) or []],
            }),
        })
        output.append(row)

        prior_direct = str(prior.get("direct_or_outbox") or "UNKNOWN")
        prior_external = str(prior.get("external_state") or "UNCONFIRMED")
        if prior_direct == "DIRECT" and direct_mode != "DIRECT":
            diagnostics.append({
                "kind": "FALSE_POSITIVE_PERSISTENCE",
                "capability_id": capability_id,
                "field": "direct_or_outbox",
                "persisted": prior_direct,
                "reconciled": direct_mode,
            })
        if _external_confirmed(prior_external) and not _external_confirmed(external_state):
            diagnostics.append({
                "kind": "FALSE_POSITIVE_PERSISTENCE",
                "capability_id": capability_id,
                "field": "external_state",
                "persisted": prior_external,
                "reconciled": external_state,
            })
    return output, diagnostics


def _priority_key(row: dict[str, Any]) -> tuple[int, str, str]:
    priority = str(row.get("priority") or "P2").upper()
    return (PRIORITY_ORDER.get(priority, 99), str(row.get("backlog_id") or ""), str(row.get("source_id") or ""))


def _reconcile_backlog(
    persisted_rows: list[Any],
    decisions: list[dict[str, Any]],
    capabilities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    persisted = _index_by(persisted_rows, "backlog_id", "backlog")
    active: list[dict[str, Any]] = []
    resolved_decisions = {str(row["decision_id"]): row for row in decisions}
    resolved_capabilities = {str(row["capability_id"]): row for row in capabilities}

    for backlog_id in sorted(persisted):
        row = deepcopy(persisted[backlog_id])
        state = str(row.get("state") or "TODO")
        decision_id = str(row.get("decision_id") or "")
        capability_id = str(row.get("capability_id") or "")
        if decision_id and decision_id in resolved_decisions:
            decision_status = str(resolved_decisions[decision_id].get("status"))
            if decision_status in {"IMPLEMENTED", "SUPERSEDED", "DEPRECATED", "CANCELLED"}:
                row["state"] = "DONE" if decision_status == "IMPLEMENTED" else "SUPERSEDED"
                continue
        if capability_id and capability_id in resolved_capabilities:
            capability = resolved_capabilities[capability_id]
            if capability.get("status") == "IMPLEMENTED" and not capability.get("gap"):
                row["state"] = "DONE"
                continue
        if state not in {"DONE", "SUPERSEDED"}:
            active.append(row)

    existing_decisions = {str(row.get("decision_id") or "") for row in active}
    existing_capabilities = {str(row.get("capability_id") or "") for row in active}
    for row in decisions:
        decision_id = str(row["decision_id"])
        if row.get("status") in {"ACTIVE_UNIMPLEMENTED", "PARTIAL", "BLOCKED_EXTERNAL"} and decision_id not in existing_decisions:
            active.append({
                "backlog_id": f"decision:{decision_id}",
                "priority": str(row.get("priority") or "P1"),
                "decision_id": decision_id,
                "exact_action": str(row.get("next_action") or "reconcile decision gap"),
                "dependency": str(row.get("blocker") or ""),
                "acceptance_test": str(row.get("acceptance_test") or "evidence-backed implementation state"),
                "rollback": str(row.get("rollback") or "restore previous accepted state"),
                "state": "BLOCKED" if row.get("status") == "BLOCKED_EXTERNAL" else "TODO",
                "source_id": decision_id,
            })
    for row in capabilities:
        capability_id = str(row["capability_id"])
        if row.get("gap") and capability_id not in existing_capabilities:
            active.append({
                "backlog_id": f"capability:{capability_id}",
                "priority": str(row.get("priority") or "P1"),
                "capability_id": capability_id,
                "exact_action": str(row.get("next_action") or row.get("gap")),
                "dependency": str(row.get("blocker") or ""),
                "acceptance_test": str(row.get("acceptance_test") or "capability gap closed with evidence"),
                "rollback": str(row.get("rollback") or "restore previous accepted state"),
                "state": "TODO",
                "source_id": capability_id,
            })
    active.sort(key=_priority_key)
    return active


def _health(
    repository_layer: dict[str, Any],
    health_gates: dict[str, Any],
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    drift_class = str(repository_layer.get("scope_classification") or "UNKNOWN")
    missing_gates = [gate for gate in REQUIRED_FRESH_GATES if health_gates.get(gate) is not True]
    blocking_diagnostics = [
        item for item in diagnostics
        if item.get("kind") in {"FALSE_POSITIVE_PERSISTENCE", "FALSE_NEGATIVE_PERSISTENCE"}
    ]
    if health_gates.get("persistence_blocked") is True:
        state = "PERSISTENCE_BLOCKED"
    elif drift_class == "STRUCTURAL_RECONCILIATION" or missing_gates or blocking_diagnostics:
        state = "RECONCILIATION_REQUIRED"
    else:
        state = "PERSISTENCE_FRESH"
    return {
        "state": state,
        "scope_classification": drift_class,
        "missing_fresh_gates": missing_gates,
        "blocking_diagnostic_count": len(blocking_diagnostics),
        "fresh_gate_count": len(REQUIRED_FRESH_GATES) - len(missing_gates),
        "fresh_gate_total": len(REQUIRED_FRESH_GATES),
    }


def reconcile(payload: dict[str, Any]) -> dict[str, Any]:
    payload = _as_object(payload, "input")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ReconciliationError(f"schema_version must be {SCHEMA_VERSION}")
    persisted = _as_object(payload.get("persisted", {}), "persisted")
    repository = _as_object(payload.get("repository", {}), "repository")
    external = _as_object(payload.get("external", {}), "external")
    health_gates = _as_object(payload.get("health_gates", {}), "health_gates")
    decisions, decision_diagnostics = _reconcile_decisions(
        _as_list(persisted.get("decisions", []), "persisted.decisions"), repository, external
    )
    capabilities, capability_diagnostics = _reconcile_capabilities(
        _as_list(persisted.get("capabilities", []), "persisted.capabilities"), repository, external
    )
    diagnostics = sorted(
        [*decision_diagnostics, *capability_diagnostics],
        key=lambda item: (
            str(item.get("kind") or ""),
            str(item.get("decision_id") or ""),
            str(item.get("capability_id") or ""),
            str(item.get("field") or ""),
        ),
    )
    backlog = _reconcile_backlog(
        _as_list(persisted.get("backlog", []), "persisted.backlog"), decisions, capabilities
    )
    output: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "contract": "CIVORA_PERSISTENCE_RECONCILIATION_V1",
        "scope_id": str(payload.get("scope_id") or "").strip(),
        "instance_id": str(payload.get("instance_id") or "").strip(),
        "input_fingerprint_sha256": _fingerprint(payload),
        "decisions": decisions,
        "capabilities": capabilities,
        "development_backlog": backlog,
        "diagnostics": diagnostics,
        "persistence_health": _health(repository, health_gates, diagnostics),
    }
    output["output_fingerprint_sha256"] = _fingerprint(output)
    return output


def _base_health_gates(value: bool) -> dict[str, bool]:
    return {gate: value for gate in REQUIRED_FRESH_GATES}


def self_test() -> None:
    payload = {
        "schema_version": 1,
        "scope_id": "synthetic-product",
        "instance_id": "synthetic-instance",
        "persisted": {
            "decisions": [
                {"decision_id": "D-MERGED", "status": "ACTIVE_UNIMPLEMENTED", "priority": "P0"},
                {"decision_id": "D-OPEN", "status": "IMPLEMENTED", "priority": "P0"},
                {"decision_id": "D-OLD", "status": "ACTIVE_UNIMPLEMENTED", "superseded_by": "D-NEW"},
            ],
            "capabilities": [
                {
                    "capability_id": "C-OUTBOX",
                    "desired_state": "DIRECT_LIVE",
                    "code_state": "READY",
                    "runtime_state": "DIRECT",
                    "external_state": "CONFIRMED",
                    "direct_or_outbox": "DIRECT",
                },
                {
                    "capability_id": "C-UNCONFIRMED",
                    "desired_state": "LIVE",
                    "code_state": "READY",
                    "runtime_state": "DIRECT",
                    "external_state": "CONFIRMED",
                },
            ],
            "backlog": [],
        },
        "repository": {
            "scope_classification": "RUNTIME_REFRESH_ONLY",
            "decisions": {
                "D-MERGED": {"implementation_state": "MERGED", "evidence": ["commit:1"]},
                "D-OPEN": {"implementation_state": "OPEN_PR", "evidence": ["pr:2"]},
                "D-OLD": {"implementation_state": "SUPERSEDED", "superseded_by": "D-NEW"},
            },
            "capabilities": {
                "C-OUTBOX": {"code_state": "READY", "runtime_state": "OUTBOX_ONLY"},
                "C-UNCONFIRMED": {"code_state": "READY", "runtime_state": "DIRECT"},
            },
        },
        "external": {
            "decisions": {},
            "capabilities": {
                "C-OUTBOX": {"external_state": "OUTBOX_ONLY"},
                "C-UNCONFIRMED": {"external_state": "UNCONFIRMED"},
            },
        },
        "health_gates": _base_health_gates(False),
    }
    first = reconcile(payload)
    second = reconcile(deepcopy(payload))
    assert first == second
    by_decision = {row["decision_id"]: row for row in first["decisions"]}
    by_capability = {row["capability_id"]: row for row in first["capabilities"]}
    assert by_decision["D-MERGED"]["status"] == "IMPLEMENTED"
    assert by_decision["D-OPEN"]["status"] == "ACTIVE_UNIMPLEMENTED"
    assert by_decision["D-OLD"]["status"] == "SUPERSEDED"
    assert by_capability["C-OUTBOX"]["direct_or_outbox"] == "OUTBOX_ONLY"
    assert by_capability["C-OUTBOX"]["status"] == "PARTIAL"
    assert by_capability["C-UNCONFIRMED"]["external_state"] == "UNCONFIRMED"
    assert by_capability["C-UNCONFIRMED"]["status"] == "PARTIAL"
    kinds = {(row["kind"], row.get("decision_id"), row.get("capability_id")) for row in first["diagnostics"]}
    assert ("FALSE_NEGATIVE_PERSISTENCE", "D-MERGED", None) in kinds
    assert ("FALSE_POSITIVE_PERSISTENCE", "D-OPEN", None) in kinds
    assert ("SUPERSEDED_WORK", "D-OLD", None) in kinds
    assert ("FALSE_POSITIVE_PERSISTENCE", None, "C-OUTBOX") in kinds
    assert first["persistence_health"]["state"] == "RECONCILIATION_REQUIRED"
    assert first["output_fingerprint_sha256"] == second["output_fingerprint_sha256"]

    healthy = {
        "schema_version": 1,
        "scope_id": "synthetic-product",
        "instance_id": "synthetic-instance",
        "persisted": {
            "decisions": [{"decision_id": "D-OK", "status": "IMPLEMENTED"}],
            "capabilities": [{
                "capability_id": "C-OK",
                "desired_state": "LIVE",
                "code_state": "READY",
                "runtime_state": "DIRECT",
                "external_state": "CONFIRMED",
            }],
            "backlog": [],
        },
        "repository": {
            "scope_classification": "NO_SCOPE_CHANGE",
            "decisions": {"D-OK": {"implementation_state": "MERGED"}},
            "capabilities": {"C-OK": {"code_state": "READY", "runtime_state": "DIRECT"}},
        },
        "external": {
            "decisions": {},
            "capabilities": {"C-OK": {"external_state": "CONFIRMED"}},
        },
        "health_gates": _base_health_gates(True),
    }
    fresh = reconcile(healthy)
    assert fresh["persistence_health"]["state"] == "PERSISTENCE_FRESH"
    structural = deepcopy(healthy)
    structural["repository"]["scope_classification"] = "STRUCTURAL_RECONCILIATION"
    assert reconcile(structural)["persistence_health"]["state"] == "RECONCILIATION_REQUIRED"

    invalid = deepcopy(healthy)
    invalid["repository"]["decisions"]["D-OK"]["implementation_state"] = "MAYBE"
    try:
        reconcile(invalid)
    except ReconciliationError:
        pass
    else:
        raise AssertionError("unknown implementation state must fail closed")
    print("CIVORA_PERSISTENCE_RECONCILIATION_SELF_TEST_PASS")


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReconciliationError(f"cannot read {path}: {exc}") from exc
    return _as_object(value, str(path))


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile normalized CIVORA persistence snapshots deterministically.")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.input is None:
        parser.error("--input is required unless --self-test is used")
    result = reconcile(_load(args.input))
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
