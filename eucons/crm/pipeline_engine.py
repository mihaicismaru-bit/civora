#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "crm" / "pipeline_contract.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _iso(value: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return parsed


def _text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} required")
    return text


def _id(namespace: str, value: str) -> str:
    return f"{namespace.upper()}-{hashlib.sha256(f'{namespace}|{value}'.encode()).hexdigest()[:24]}"


def _copy(value: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(value)


def _assert_no_forbidden_keys(value: Any, forbidden: set[str]) -> None:
    if isinstance(value, dict):
        overlap = forbidden & {str(key).casefold() for key in value}
        if overlap:
            raise ValueError(f"raw personal data forbidden in pipeline: {sorted(overlap)}")
        for child in value.values():
            _assert_no_forbidden_keys(child, forbidden)
    elif isinstance(value, list):
        for child in value:
            _assert_no_forbidden_keys(child, forbidden)


def validate_contract(contract: dict[str, Any]) -> None:
    if contract.get("id") != "R10-PIPELINE-001" or contract.get("status") != "CANONICAL":
        raise ValueError("R10 pipeline contract drift")
    if contract.get("production_persistence_enabled") is not False:
        raise ValueError("production persistence failed open")
    if contract.get("entry_lanes") != ["INBOUND", "PROSPECT_DISCOVERY"]:
        raise ValueError("pipeline entry lanes drift")
    lifecycle = set(contract.get("lifecycle") or [])
    if set((contract.get("allowed_transitions") or {}).keys()) != lifecycle:
        raise ValueError("transition graph does not cover lifecycle")
    for source, targets in contract["allowed_transitions"].items():
        if any(target not in lifecycle for target in targets):
            raise ValueError(f"unknown transition target from {source}")
    if contract["upstream_gates"]["R07_MATCH_RECORD"]["eligibility_state"] != "NOT_ASSESSED":
        raise ValueError("R07 eligibility boundary failed open")
    if contract["upstream_gates"]["R08_ACTION_PACK"]["maximum_state"] != "READY_FOR_APPROVAL":
        raise ValueError("R08 approval boundary failed open")
    contact = contract.get("contact_gate") or {}
    if any(contact.get(key) is not False for key in ("automatic_approval", "automatic_send", "person_targeting_default")):
        raise ValueError("contact boundary failed open")
    if not all(contact.get(key) is True for key in ("suppression_must_be_clear", "lawful_basis_must_be_human_reviewed", "business_contact_surface_must_be_verified", "contact_receipt_required_after_external_action")):
        raise ValueError("contact approval prerequisite missing")
    commercial = contract.get("commercial_gate") or {}
    if commercial.get("automatic_offer") is not False or commercial.get("binding_price_generation") is not False:
        raise ValueError("commercial boundary failed open")
    outputs = contract.get("outputs") or {}
    if outputs.get("eligibility_state") != "NOT_ASSESSED" or any(outputs.get(key) is not False for key in ("external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled")):
        raise ValueError("pipeline output boundary failed open")
    if contract.get("repository_policy", {}).get("runtime_output_under_repository_root_forbidden") is not True:
        raise ValueError("repository runtime boundary missing")


def empty_state(reference_time: str, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = contract or load_json(DEFAULT_CONTRACT)
    validate_contract(contract)
    _iso(reference_time)
    return {
        "schema_version": 1,
        "engine_id": contract["engine_id"],
        "revision": 0,
        "reference_time": reference_time,
        "records": {},
        "tasks": {},
        "evidence_receipts": {},
        "request_receipts": {},
        "audit": [],
        "eligibility_state": contract["outputs"]["eligibility_state"],
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
    }


def _append_audit(state: dict[str, Any], event_type: str, record_id: str, at: str, details: dict[str, Any]) -> None:
    state["audit"].append({
        "sequence": len(state["audit"]) + 1,
        "event_type": event_type,
        "record_id": record_id,
        "at": at,
        "details": _copy(details),
    })


def _validate_attribution(attribution: dict[str, Any], lane: str, contract: dict[str, Any]) -> dict[str, Any]:
    required = set(contract["attribution"]["required_fields"])
    if set(attribution) != required:
        raise ValueError("attribution fields must match contract exactly")
    if attribution.get("origin") != lane:
        raise ValueError("attribution origin must equal entry lane")
    _text(attribution.get("first_touch_ref"), "first-touch reference")
    if not isinstance(attribution.get("source_refs"), list) or not attribution["source_refs"]:
        raise ValueError("attribution source references required")
    if not isinstance(attribution.get("assisted_content_refs"), list):
        raise ValueError("assisted content references must be a list")
    return _copy(attribution)


def _new_task(state: dict[str, Any], record_id: str, action: str, due_at: str, owner: str, at: str) -> str:
    action = _text(action, "next action")
    owner = _text(owner, "task owner")
    _iso(due_at)
    if _iso(due_at) < _iso(at):
        raise ValueError("task due_at cannot precede creation")
    task_id = _id("task", f"{record_id}|{action}|{due_at}")
    existing = state["tasks"].get(task_id)
    if existing and existing["status"] == "OPEN":
        return task_id
    state["tasks"][task_id] = {
        "task_id": task_id,
        "record_id": record_id,
        "action": action,
        "due_at": due_at,
        "owner": owner,
        "status": "OPEN",
        "created_at": at,
    }
    return task_id


def _close_open_task(state: dict[str, Any], record: dict[str, Any], at: str) -> None:
    task_id = record.get("next_action_task_id")
    if task_id and state["tasks"].get(task_id, {}).get("status") == "OPEN":
        state["tasks"][task_id]["status"] = "DONE"
        state["tasks"][task_id]["completed_at"] = at


def ingest(
    state: dict[str, Any],
    request_id: str,
    lane: str,
    source_ref: str,
    organization_key: str,
    attribution: dict[str, Any],
    *,
    contact_reference: str | None = None,
    next_action: str,
    due_at: str,
    owner: str = "UNASSIGNED",
    at: str,
    evidence_label: str = "NON_EVIDENCE",
    contract: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    contract = contract or load_json(DEFAULT_CONTRACT)
    validate_contract(contract)
    assert_state(state, contract)
    _iso(at)
    lane = _text(lane, "entry lane")
    if lane not in contract["entry_lanes"]:
        raise ValueError("unsupported entry lane")
    source_ref = _text(source_ref, "source reference")
    organization_key = _text(organization_key, "organization key")
    if lane == "PROSPECT_DISCOVERY" and contact_reference is not None:
        raise ValueError("prospect discovery cannot start with a personal contact reference")
    if lane == "INBOUND" and not _text(contact_reference, "contact reference"):
        raise ValueError("inbound lane requires an opaque contact reference")
    request_id = _text(request_id, "request id")
    request_fingerprint = canonical_hash({
        "lane": lane,
        "source_ref": source_ref,
        "organization_key": organization_key,
        "attribution": attribution,
        "contact_reference": contact_reference,
        "next_action": next_action,
        "due_at": due_at,
        "owner": owner,
        "at": at,
        "evidence_label": evidence_label,
    })
    if request_id in state.get("request_receipts", {}):
        receipt = state["request_receipts"][request_id]
        if receipt["fingerprint"] != request_fingerprint:
            raise ValueError("idempotency conflict")
        return _copy(state), receipt["record_id"]
    forbidden = set(contract["privacy"]["forbidden_keys"])
    _assert_no_forbidden_keys(attribution, forbidden)
    normalized_attribution = _validate_attribution(attribution, lane, contract)
    record_id = _id("pipeline", f"{lane}|{source_ref}")
    out = _copy(state)
    if record_id in out["records"]:
        out["request_receipts"][request_id] = {"fingerprint": request_fingerprint, "record_id": record_id}
        _append_audit(out, "SOURCE_SEEN_AGAIN", record_id, at, {"source_ref": source_ref, "lane": lane})
        out["revision"] += 1
        return out, record_id
    stage = contract["entry_stage_by_lane"][lane]
    task_id = _new_task(out, record_id, next_action, due_at, owner, at)
    out["records"][record_id] = {
        "record_id": record_id,
        "entry_lane": lane,
        "source_ref": source_ref,
        "organization_key": organization_key,
        "contact_reference": contact_reference,
        "attribution": normalized_attribution,
        "stage": stage,
        "stage_entered_at": at,
        "last_activity_at": at,
        "owner": owner,
        "next_action_task_id": task_id,
        "prior_stage": None,
        "evidence_label": evidence_label,
        "suppression_state": "UNKNOWN" if lane == "PROSPECT_DISCOVERY" else "NOT_APPLICABLE_UNTIL_CONTACT_REVIEW",
        "eligibility_state": "NOT_ASSESSED",
    }
    out["request_receipts"][request_id] = {"fingerprint": request_fingerprint, "record_id": record_id}
    _append_audit(out, "PIPELINE_RECORD_CREATED", record_id, at, {"lane": lane, "stage": stage, "source_ref": source_ref, "task_id": task_id})
    out["revision"] += 1
    return out, record_id


def _validate_receipt(receipt: dict[str, Any], target: str, contract: dict[str, Any]) -> dict[str, Any]:
    required = {"receipt_id", "kind", "at", "actor", "artifact_ref", "automated", "details"}
    if set(receipt) != required:
        raise ValueError("evidence receipt fields must match contract exactly")
    receipt_id = _text(receipt.get("receipt_id"), "receipt id")
    kind = _text(receipt.get("kind"), "receipt kind")
    _iso(_text(receipt.get("at"), "receipt timestamp"))
    _text(receipt.get("actor"), "receipt actor")
    _text(receipt.get("artifact_ref"), "receipt artifact reference")
    if not isinstance(receipt.get("details"), dict):
        raise ValueError("receipt details must be an object")
    allowed_kinds = contract["transition_evidence"]["RESUME" if target == "RESUME" else target]
    if kind not in allowed_kinds:
        raise ValueError(f"{target} requires evidence kind {allowed_kinds}")
    if kind in contract["human_gated_receipts"] and receipt.get("automated") is not False:
        raise ValueError("human-gated receipt cannot be automated")
    _assert_no_forbidden_keys(receipt, set(contract["privacy"]["forbidden_keys"]))
    return _copy(receipt)


def _validate_upstream(receipt: dict[str, Any], target: str, contract: dict[str, Any]) -> None:
    details = receipt["details"]
    if target == "MATCHED":
        gate = contract["upstream_gates"]["R07_MATCH_RECORD"]
        if details.get("engine_id") != gate["engine_id"] or details.get("state") != gate["required_state"]:
            raise ValueError("R07 match gate not satisfied")
        if details.get("eligibility_state") != gate["eligibility_state"] or details.get("maximum_next_state") != gate["maximum_next_state"]:
            raise ValueError("R07 safety boundary not satisfied")
        if not details.get("opportunity_id") or not details.get("service_id") or not details.get("source_provenance_ref"):
            raise ValueError("R07 match lineage incomplete")
    elif target == "OUTREACH_PREPARED":
        gate = contract["upstream_gates"]["R08_ACTION_PACK"]
        if details.get("engine_id") != gate["engine_id"] or details.get("state") != gate["required_state"]:
            raise ValueError("R08 action-pack gate not satisfied")
        if details.get("eligibility_state") != gate["eligibility_state"] or details.get("maximum_state") != gate["maximum_state"]:
            raise ValueError("R08 safety boundary not satisfied")
        if not details.get("action_pack_id"):
            raise ValueError("R08 action-pack lineage incomplete")
    elif target == "CONTACT_APPROVED":
        required = {"lawful_basis_reviewed", "business_contact_surface_verified", "suppression_clear", "opt_out_ready", "channel"}
        if not required <= set(details) or not all(details.get(key) is True for key in required - {"channel"}):
            raise ValueError("contact approval governance incomplete")
        _text(details.get("channel"), "approved contact channel")
    elif target == "CONTACTED":
        if details.get("sent") is not True or not details.get("channel") or not details.get("external_action_id"):
            raise ValueError("external contact receipt incomplete")
    elif target == "OFFER":
        if details.get("human_approved") is not True or details.get("binding") is not False:
            raise ValueError("offer approval boundary not satisfied")
    elif target == "WON":
        if details.get("accepted") is not True or not details.get("acceptance_reference"):
            raise ValueError("won state requires acceptance evidence")
    elif target == "CASE_STUDY_CANDIDATE":
        if details.get("publication_state") != contract["outputs"]["case_study_publication_state"]:
            raise ValueError("case-study publication must remain under review")


def transition(
    state: dict[str, Any],
    record_id: str,
    target_stage: str,
    receipt: dict[str, Any],
    *,
    next_action: str | None = None,
    due_at: str | None = None,
    owner: str | None = None,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_json(DEFAULT_CONTRACT)
    validate_contract(contract)
    assert_state(state, contract)
    if record_id not in state.get("records", {}):
        raise ValueError("unknown pipeline record")
    target_stage = _text(target_stage, "target stage")
    record = state["records"][record_id]
    current = record["stage"]
    receipt_id = _text(receipt.get("receipt_id"), "receipt id")
    existing_receipt = state.get("evidence_receipts", {}).get(receipt_id)
    if existing_receipt is not None:
        expected = {**receipt, "record_id": record_id, "target_stage": target_stage}
        if canonical_hash(existing_receipt) != canonical_hash(expected):
            raise ValueError("evidence receipt idempotency conflict")
        if current != target_stage:
            raise ValueError("evidence receipt replay does not match current stage")
        if contract["allowed_transitions"].get(target_stage):
            task = state.get("tasks", {}).get(record.get("next_action_task_id")) or {}
            replay_owner = owner if owner is not None else record.get("owner")
            if task.get("action") != next_action or task.get("due_at") != due_at or task.get("owner") != replay_owner:
                raise ValueError("evidence receipt replay conflicts with next-action task")
        return _copy(state)
    if target_stage not in contract["allowed_transitions"].get(current, []):
        raise ValueError(f"invalid pipeline transition {current}->{target_stage}")
    receipt_target = "RESUME" if current == "ON_HOLD" else target_stage
    checked_receipt = _validate_receipt(receipt, receipt_target, contract)
    if _iso(checked_receipt["at"]) < _iso(record["last_activity_at"]):
        raise ValueError("evidence receipt cannot precede the record's last activity")
    if current == "ON_HOLD" and target_stage != record.get("prior_stage"):
        raise ValueError("ON_HOLD can resume only to prior stage")
    _validate_upstream(checked_receipt, target_stage, contract)
    receipt_id = checked_receipt["receipt_id"]
    terminal = not contract["allowed_transitions"].get(target_stage)
    new_owner = owner if owner is not None else record.get("owner", contract["ownership_and_tasks"]["default_owner"])
    if target_stage in {"CONTACT_APPROVED", "CONTACTED", "DISCOVERY", "OFFER", "WON", "CLIENT", "PROJECT", "CASE_STUDY_CANDIDATE"} and new_owner == contract["ownership_and_tasks"]["default_owner"]:
        raise ValueError("explicit owner required before contact approval and downstream stages")
    if not terminal and (not next_action or not due_at):
        raise ValueError("next action task required for non-terminal stage")
    out = _copy(state)
    changed = out["records"][record_id]
    _close_open_task(out, changed, checked_receipt["at"])
    prior_stage = current if target_stage == "ON_HOLD" else (None if current == "ON_HOLD" else changed.get("prior_stage"))
    changed.update({
        "stage": target_stage,
        "stage_entered_at": checked_receipt["at"],
        "last_activity_at": checked_receipt["at"],
        "owner": new_owner,
        "prior_stage": prior_stage,
        "next_action_task_id": None,
    })
    if target_stage == "CONTACT_APPROVED":
        changed["suppression_state"] = "CLEAR_AT_APPROVAL"
    if target_stage == "CASE_STUDY_CANDIDATE":
        changed["case_study_publication_state"] = contract["outputs"]["case_study_publication_state"]
    if not terminal:
        changed["next_action_task_id"] = _new_task(out, record_id, next_action or "", due_at or "", new_owner, checked_receipt["at"])
    stored_receipt = {**checked_receipt, "record_id": record_id, "target_stage": target_stage}
    out["evidence_receipts"][receipt_id] = stored_receipt
    _append_audit(out, "PIPELINE_STAGE_CHANGED", record_id, checked_receipt["at"], {"from": current, "to": target_stage, "receipt_id": receipt_id, "task_id": changed.get("next_action_task_id")})
    out["revision"] += 1
    return out


def stale_report(state: dict[str, Any], reference_time: str, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = contract or load_json(DEFAULT_CONTRACT)
    validate_contract(contract)
    now = _iso(reference_time)
    rows = []
    for record_id, record in sorted((state.get("records") or {}).items()):
        threshold = contract["stale_after_days"].get(record["stage"])
        if threshold is None:
            continue
        age_days = (now - _iso(record["last_activity_at"])).total_seconds() / 86400
        if age_days > threshold:
            rows.append({
                "record_id": record_id,
                "stage": record["stage"],
                "age_days": round(age_days, 3),
                "threshold_days": threshold,
                "next_action_task_id": record.get("next_action_task_id"),
                "state": "STALE_REQUIRES_HUMAN_FOLLOW_UP",
            })
    return {"reference_time": reference_time, "stale_count": len(rows), "records": rows, "automatic_contact_enabled": False}


def assert_state(state: dict[str, Any], contract: dict[str, Any] | None = None) -> None:
    contract = contract or load_json(DEFAULT_CONTRACT)
    validate_contract(contract)
    if state.get("engine_id") != contract["engine_id"]:
        raise ValueError("pipeline engine mismatch")
    if any(state.get(key) is not False for key in ("external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled")):
        raise ValueError("pipeline state opened an automatic external action")
    required_audit = set(contract["audit"]["required_fields"])
    sequences = []
    forbidden = set(contract["privacy"]["forbidden_keys"])
    _assert_no_forbidden_keys(state, forbidden)
    for row in state.get("audit") or []:
        if not required_audit <= set(row):
            raise ValueError("audit row incomplete")
        sequences.append(row["sequence"])
    if sequences != list(range(1, len(sequences) + 1)):
        raise ValueError("audit sequence is not append-only contiguous")
    for record in (state.get("records") or {}).values():
        if record["stage"] not in contract["lifecycle"]:
            raise ValueError("unknown lifecycle stage in state")
        terminal = not contract["allowed_transitions"].get(record["stage"])
        if not terminal:
            task = state.get("tasks", {}).get(record.get("next_action_task_id"))
            if not task or task.get("status") != "OPEN":
                raise ValueError("non-terminal record lacks open next-action task")


def assert_output_path_safe(path: Path) -> None:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return
    raise ValueError("runtime pipeline state cannot be written under repository root")


def main() -> None:
    parser = argparse.ArgumentParser(description="EUCONS unified commercial pipeline")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--reference-time", required=True)
    parser.add_argument("--stale-report", type=Path, required=True)
    args = parser.parse_args()
    state = load_json(args.state)
    assert_state(state)
    assert_output_path_safe(args.stale_report)
    report = stale_report(state, args.reference_time)
    args.stale_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "records": len(state["records"]), "stale": report["stale_count"]}, sort_keys=True))


if __name__ == "__main__":
    main()
