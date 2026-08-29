#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "opportunities" / "source_freshness_recovery_contract.json"
DEFAULT_BRIDGE_CONTRACT = EUCONS / "opportunities" / "bridge_contract.json"
HEX64 = set("0123456789abcdef")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def is_hex64(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value).issubset(HEX64)


def validate_contract(contract: dict[str, Any], bridge_contract: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 1, "source freshness recovery schema drift")
    require(contract.get("engine_id") == "EUCONS_E09_SOURCE_FRESHNESS_RECOVERY_QUEUE", "engine id drift")
    inputs = contract.get("input") or {}
    require(inputs.get("required_projection_product") == "EUCONS_COMMERCIAL_OS", "projection product drift")
    require(inputs.get("required_bridge_id") == bridge_contract.get("bridge_id") == "PARTENER_P11_TO_EUCONS_E09", "bridge id drift")
    require(inputs.get("required_source_product") == bridge_contract.get("source", {}).get("product") == "PARTENER.EU", "source product drift")
    require(inputs.get("required_source_role") == "DISCOVERY_ONLY", "PARTENER role must remain discovery-only")
    require(inputs.get("allowed_bridge_states") == ["READY", "STALE_SOURCE_HOLD"], "allowed bridge states drift")
    require(inputs.get("require_read_only") is True, "recovery queue must remain read-only")
    require(inputs.get("require_source_mutation_disabled") is True, "source mutation guard drift")

    freshness = contract.get("freshness") or {}
    bridge_freshness = bridge_contract.get("freshness") or {}
    require(freshness.get("max_age_hours") == bridge_freshness.get("max_age_hours") == 72, "freshness max-age drift")
    require(freshness.get("future_skew_tolerance_minutes") == bridge_freshness.get("future_skew_tolerance_minutes") == 15, "future skew drift")
    require(freshness.get("fresh_state") == "FRESH", "fresh state drift")
    require(freshness.get("stale_state") == "STALE", "stale state drift")
    require(freshness.get("invalid_time_state") == "INVALID_TIME", "invalid-time state drift")
    require(freshness.get("future_time_state") == "FUTURE_TIME", "future-time state drift")
    require(freshness.get("fresh_bridge_state") == "READY", "fresh bridge-state drift")
    require(freshness.get("held_bridge_state") == bridge_contract.get("output", {}).get("stale_record_state", "").replace("HOLD_STALE_SOURCE", "STALE_SOURCE_HOLD"), "held bridge-state drift")

    triage = contract.get("triage") or {}
    require(triage.get("priority_order") == ["P0", "P1"], "priority order drift")
    require(triage.get("timestamp_integrity_priority") == "P0", "timestamp priority drift")
    require(triage.get("stale_refresh_priority") == "P1", "stale refresh priority drift")
    require(triage.get("deterministic_sort") == ["priority_asc", "task_id_asc"], "sort contract drift")

    output = contract.get("output") or {}
    for key in (
        "fresh_source_emits_no_task",
        "opportunity_material_facts_forbidden",
        "official_authority_inference_forbidden",
        "eligibility_conclusion_forbidden",
        "person_level_fields_forbidden",
        "repository_runtime_output_forbidden",
    ):
        require(output.get(key) is True, f"output boundary failed open: {key}")
    require(output.get("external_action_authorized") is False, "recovery queue cannot authorize external action")
    boundaries = contract.get("boundaries") or {}
    require(boundaries and all(value is False for value in boundaries.values()), "external boundary enabled")


def validate_projection(projection: dict[str, Any], contract: dict[str, Any]) -> None:
    inputs = contract["input"]
    require(projection.get("schema_version") == 1, "projection schema drift")
    require(projection.get("product") == inputs["required_projection_product"], "projection product mismatch")
    require(projection.get("bridge_id") == inputs["required_bridge_id"], "projection bridge mismatch")
    require(projection.get("bridge_state") in inputs["allowed_bridge_states"], "projection bridge state is not freshness-recoverable")
    require(projection.get("read_only") is True, "projection must remain read-only")
    require(projection.get("source_mutation_allowed") is False, "projection source mutation must remain disabled")
    source = projection.get("source") or {}
    require(source.get("product") == inputs["required_source_product"], "projection source product mismatch")
    require(source.get("policy_accepted") is True, "source policy rejection is not a freshness-recovery case")
    require(is_hex64(source.get("sha256")), "projection source hash invalid")
    freshness = projection.get("freshness") or {}
    require(freshness.get("state") in {"FRESH", "STALE", "INVALID_TIME", "FUTURE_TIME"}, "projection freshness state invalid")
    require(freshness.get("max_age_seconds") == int(contract["freshness"]["max_age_hours"]) * 3600, "projection freshness max-age mismatch")
    age = freshness.get("age_seconds")
    if freshness.get("state") in {"FRESH", "STALE"}:
        require(isinstance(age, int) and age >= 0, "fresh/stale age must be a non-negative integer")
    else:
        require(age is None or isinstance(age, int), "invalid/future age shape drift")

    state = freshness["state"]
    if state == contract["freshness"]["fresh_state"]:
        require(projection.get("bridge_state") == contract["freshness"]["fresh_bridge_state"], "fresh projection must remain READY")
    else:
        require(projection.get("bridge_state") == contract["freshness"]["held_bridge_state"], "non-fresh projection must remain fail-closed")


def validate_safe_output(value: Any) -> None:
    forbidden_keys = {
        "opportunities",
        "material_facts",
        "verified_fact_classes",
        "verification_evidence",
        "publication_decision",
        "source_path",
        "title",
        "programme",
        "code",
        "budget",
        "grant",
        "beneficiaries",
        "eligibility",
        "scoring",
        "deadline",
        "email",
        "phone",
        "address",
        "personal_identifier",
        "award_probability",
        "eligibility_conclusion",
    }
    if isinstance(value, dict):
        overlap = forbidden_keys.intersection(value)
        require(not overlap, f"source freshness recovery leaked forbidden fields: {sorted(overlap)}")
        for child in value.values():
            validate_safe_output(child)
    elif isinstance(value, list):
        for child in value:
            validate_safe_output(child)


def build_recovery_queue(projection: dict[str, Any], contract: dict[str, Any], bridge_contract: dict[str, Any]) -> dict[str, Any]:
    validate_contract(contract, bridge_contract)
    validate_projection(projection, contract)
    freshness = projection["freshness"]
    state = freshness["state"]
    tasks: list[dict[str, Any]] = []
    if state != contract["freshness"]["fresh_state"]:
        timestamp_problem = state in {contract["freshness"]["invalid_time_state"], contract["freshness"]["future_time_state"]}
        priority = contract["triage"]["timestamp_integrity_priority"] if timestamp_problem else contract["triage"]["stale_refresh_priority"]
        action = contract["triage"]["timestamp_integrity_action"] if timestamp_problem else contract["triage"]["stale_refresh_action"]
        reason = "DISCOVERY_TIMESTAMP_INTEGRITY_HOLD" if timestamp_problem else "DISCOVERY_SOURCE_STALE"
        age_seconds = freshness.get("age_seconds")
        task_basis = {
            "engine_id": contract["engine_id"],
            "source_projection_sha256": projection["source"]["sha256"],
            "freshness_state": state,
            "reason_code": reason,
        }
        tasks.append({
            "task_id": canonical_hash(task_basis),
            "priority": priority,
            "reason_code": reason,
            "operator_action": action,
            "source_product": contract["input"]["required_source_product"],
            "source_role": contract["input"]["required_source_role"],
            "freshness_state": state,
            "age_hours": None if age_seconds is None else round(max(age_seconds, 0) / 3600, 2),
            "max_age_hours": contract["freshness"]["max_age_hours"],
            "official_authority_inferred": False,
            "external_action_authorized": False,
        })

    rank = {value: index for index, value in enumerate(contract["triage"]["priority_order"])}
    tasks.sort(key=lambda row: (rank[row["priority"]], row["task_id"]))
    result = {
        "schema_version": contract["schema_version"],
        "engine_id": contract["engine_id"],
        "state": contract["output"]["state"],
        "read_only": True,
        "source_projection_sha256": projection["source"]["sha256"],
        "source_product": contract["input"]["required_source_product"],
        "source_role": contract["input"]["required_source_role"],
        "summary": {
            "freshness_state": state,
            "bridge_state": projection["bridge_state"],
            "source_held": state != contract["freshness"]["fresh_state"],
            "recovery_tasks": len(tasks),
        },
        "tasks": tasks,
        "boundaries": dict(contract["boundaries"]),
    }
    result["queue_id"] = canonical_hash({
        "engine_id": result["engine_id"],
        "source_projection_sha256": result["source_projection_sha256"],
        "summary": result["summary"],
        "tasks": tasks,
    })
    validate_safe_output(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projection", required=True)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--bridge-contract", default=str(DEFAULT_BRIDGE_CONTRACT))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    projection = load_json(Path(args.projection))
    contract = load_json(Path(args.contract))
    bridge_contract = load_json(Path(args.bridge_contract))
    result = build_recovery_queue(projection, contract, bridge_contract)
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        try:
            output.resolve().relative_to(ROOT.resolve())
        except ValueError:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text, encoding="utf-8")
        else:
            raise ValueError("repository runtime output is forbidden")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
