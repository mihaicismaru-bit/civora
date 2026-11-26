#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "opportunities" / "unified_source_work_queue_contract.json"
DEFAULT_FRESHNESS_CONTRACT = EUCONS / "opportunities" / "source_freshness_recovery_contract.json"
DEFAULT_OFFICIAL_CONTRACT = EUCONS / "opportunities" / "official_source_operator_queue_contract.json"
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


def validate_contract(
    contract: dict[str, Any],
    freshness_contract: dict[str, Any],
    official_contract: dict[str, Any],
) -> None:
    require(contract.get("schema_version") == 1, "unified source queue schema drift")
    require(contract.get("engine_id") == "EUCONS_E10_UNIFIED_SOURCE_WORK_QUEUE", "unified source queue engine drift")
    inputs = contract.get("input") or {}
    require(
        inputs.get("freshness_engine_id") == freshness_contract.get("engine_id") == "EUCONS_E09_SOURCE_FRESHNESS_RECOVERY_QUEUE",
        "freshness parent engine drift",
    )
    require(
        inputs.get("freshness_state") == freshness_contract.get("output", {}).get("state") == "READ_ONLY_SOURCE_FRESHNESS_RECOVERY",
        "freshness parent state drift",
    )
    require(
        inputs.get("official_engine_id") == official_contract.get("engine_id") == "EUCONS_E10_OFFICIAL_SOURCE_OPERATOR_QUEUE",
        "official parent engine drift",
    )
    require(
        inputs.get("official_state") == official_contract.get("output", {}).get("state") == "READ_ONLY_OPERATOR_QUEUE",
        "official parent state drift",
    )
    require(inputs.get("required_source_product") == "PARTENER.EU", "source product drift")
    require(inputs.get("required_source_role") == "DISCOVERY_ONLY", "PARTENER role must remain discovery-only")
    for key in (
        "freshness_queue_always_required",
        "official_queue_required_when_source_ready",
        "official_queue_forbidden_when_source_held",
        "require_same_source_projection_sha256",
    ):
        require(inputs.get(key) is True, f"input safety boundary failed open: {key}")

    triage = contract.get("triage") or {}
    require(triage.get("priority_order") == ["P0", "P1", "P2"], "priority order drift")
    require(triage.get("domains") == ["DISCOVERY_SOURCE", "OFFICIAL_AUTHORITY"], "domain order drift")
    require(
        set(triage.get("freshness_reason_codes") or [])
        == {"DISCOVERY_TIMESTAMP_INTEGRITY_HOLD", "DISCOVERY_SOURCE_STALE"},
        "freshness reason-code drift",
    )
    require(
        set(triage.get("official_reason_codes") or [])
        == {"OFFICIAL_SOURCE_CONFLICT", "REQUIRED_OFFICIAL_BINDING_MISSING", "OPTIONAL_MATCHING_FACT_BINDINGS_INCOMPLETE"},
        "official reason-code drift",
    )
    require(
        triage.get("deterministic_sort") == ["priority_asc", "domain_asc", "work_id_asc"],
        "unified queue sort drift",
    )

    output = contract.get("output") or {}
    require(output.get("state") == "READ_ONLY_UNIFIED_SOURCE_WORK_QUEUE", "output state drift")
    for key in (
        "read_only",
        "human_review_required",
        "raw_material_fact_values_forbidden",
        "person_level_fields_forbidden",
        "eligibility_conclusion_forbidden",
        "award_probability_forbidden",
        "official_authority_inference_forbidden",
        "repository_runtime_output_forbidden",
    ):
        require(output.get(key) is True, f"output boundary failed open: {key}")
    require(output.get("external_action_authorized") is False, "unified queue cannot authorize external action")
    boundaries = contract.get("boundaries") or {}
    require(boundaries and all(value is False for value in boundaries.values()), "external boundary enabled")

    freshness_triage = freshness_contract.get("triage") or {}
    official_triage = official_contract.get("triage") or {}
    require(freshness_triage.get("timestamp_integrity_priority") == "P0", "freshness timestamp priority drift")
    require(freshness_triage.get("stale_refresh_priority") == "P1", "freshness stale priority drift")
    require(official_triage.get("blocked_priority") == "P0", "official blocked priority drift")
    require(official_triage.get("waiting_priority") == "P1", "official waiting priority drift")
    require(official_triage.get("enrichment_priority") == "P2", "official enrichment priority drift")
    require(all(value is False for value in (freshness_contract.get("boundaries") or {}).values()), "freshness parent boundary enabled")
    require(all(value is False for value in (official_contract.get("boundaries") or {}).values()), "official parent boundary enabled")


def validate_parent_boundaries(queue: dict[str, Any], label: str) -> None:
    boundaries = queue.get("boundaries") or {}
    require(boundaries and all(value is False for value in boundaries.values()), f"{label} external boundary enabled")


def validate_freshness_queue(
    queue: dict[str, Any],
    contract: dict[str, Any],
    freshness_contract: dict[str, Any],
) -> None:
    inputs = contract["input"]
    require(queue.get("schema_version") == 1, "freshness queue schema drift")
    require(queue.get("engine_id") == inputs["freshness_engine_id"], "freshness queue engine mismatch")
    require(queue.get("state") == inputs["freshness_state"], "freshness queue state mismatch")
    require(queue.get("read_only") is True, "freshness queue must remain read-only")
    require(is_hex64(queue.get("queue_id")), "freshness queue id invalid")
    require(is_hex64(queue.get("source_projection_sha256")), "freshness source projection hash invalid")
    require(queue.get("source_product") == inputs["required_source_product"], "freshness source product mismatch")
    require(queue.get("source_role") == inputs["required_source_role"], "freshness source role mismatch")
    summary = queue.get("summary") or {}
    require(isinstance(summary.get("source_held"), bool), "freshness source-held state missing")
    tasks = queue.get("tasks")
    require(isinstance(tasks, list), "freshness tasks must be a list")
    validate_parent_boundaries(queue, "freshness queue")

    triage = freshness_contract["triage"]
    allowed = {
        "DISCOVERY_TIMESTAMP_INTEGRITY_HOLD": (triage["timestamp_integrity_priority"], triage["timestamp_integrity_action"]),
        "DISCOVERY_SOURCE_STALE": (triage["stale_refresh_priority"], triage["stale_refresh_action"]),
    }
    for task in tasks:
        require(isinstance(task, dict), "freshness task must be an object")
        require(is_hex64(task.get("task_id")), "freshness task id invalid")
        reason = task.get("reason_code")
        require(reason in allowed, f"freshness reason code invalid: {reason}")
        expected_priority, expected_action = allowed[reason]
        require(task.get("priority") == expected_priority, "freshness task priority mismatch")
        require(task.get("operator_action") == expected_action, "freshness task action mismatch")
        require(task.get("source_product") == inputs["required_source_product"], "freshness task source product mismatch")
        require(task.get("source_role") == inputs["required_source_role"], "freshness task source role mismatch")
        require(task.get("official_authority_inferred") is False, "freshness task inferred official authority")
        require(task.get("external_action_authorized") is False, "freshness task authorized external action")

    if summary["source_held"]:
        require(len(tasks) >= 1, "held discovery source must emit recovery work")
    else:
        require(tasks == [], "ready discovery source must not emit freshness work")


def validate_official_queue(
    queue: dict[str, Any],
    contract: dict[str, Any],
    official_contract: dict[str, Any],
) -> None:
    inputs = contract["input"]
    require(queue.get("schema_version") == 1, "official queue schema drift")
    require(queue.get("engine_id") == inputs["official_engine_id"], "official queue engine mismatch")
    require(queue.get("state") == inputs["official_state"], "official queue state mismatch")
    require(queue.get("read_only") is True, "official queue must remain read-only")
    require(is_hex64(queue.get("queue_id")), "official queue id invalid")
    require(is_hex64(queue.get("source_projection_sha256")), "official source projection hash invalid")
    require(isinstance(queue.get("official_registry_state"), str), "official registry state missing")
    tasks = queue.get("tasks")
    require(isinstance(tasks, list), "official tasks must be a list")
    validate_parent_boundaries(queue, "official queue")

    triage = official_contract["triage"]
    allowed = {
        "OFFICIAL_SOURCE_CONFLICT": (triage["blocked_priority"], triage["blocked_action"]),
        "REQUIRED_OFFICIAL_BINDING_MISSING": (triage["waiting_priority"], triage["waiting_action"]),
        "OPTIONAL_MATCHING_FACT_BINDINGS_INCOMPLETE": (triage["enrichment_priority"], triage["enrichment_action"]),
    }
    for task in tasks:
        require(isinstance(task, dict), "official task must be an object")
        opportunity_id = task.get("opportunity_id")
        require(isinstance(opportunity_id, str) and opportunity_id.strip(), "official task opportunity id missing")
        reason = task.get("reason_code")
        require(reason in allowed, f"official reason code invalid: {reason}")
        expected_priority, expected_action = allowed[reason]
        require(task.get("priority") == expected_priority, "official task priority mismatch")
        require(task.get("operator_action") == expected_action, "official task action mismatch")
        require(task.get("external_action_authorized") is False, "official task authorized external action")
        context = task.get("discovery_context") or {}
        require(context.get("source_product") == inputs["required_source_product"], "official task discovery source mismatch")
        require(context.get("role") == inputs["required_source_role"], "official task promoted PARTENER authority")


def validate_safe_output(value: Any) -> None:
    forbidden_keys = {
        "material_facts",
        "verified_fact_hashes",
        "source_url",
        "source_document_sha256",
        "verification_evidence",
        "email",
        "phone",
        "address",
        "personal_identifier",
        "requested_grant_eur",
        "budget",
        "grant",
        "eligibility",
        "eligibility_conclusion",
        "award_probability",
    }
    if isinstance(value, dict):
        overlap = forbidden_keys.intersection(value)
        require(not overlap, f"unified source queue leaked forbidden fields: {sorted(overlap)}")
        for child in value.values():
            validate_safe_output(child)
    elif isinstance(value, list):
        for child in value:
            validate_safe_output(child)


def freshness_work(task: dict[str, Any]) -> dict[str, Any]:
    basis = {"domain": "DISCOVERY_SOURCE", "parent_task_id": task["task_id"]}
    return {
        "work_id": canonical_hash(basis),
        "domain": "DISCOVERY_SOURCE",
        "target_kind": "DISCOVERY_SOURCE",
        "priority": task["priority"],
        "reason_code": task["reason_code"],
        "operator_action": task["operator_action"],
        "source_product": task["source_product"],
        "source_role": task["source_role"],
        "freshness_state": task.get("freshness_state"),
        "age_hours": task.get("age_hours"),
        "max_age_hours": task.get("max_age_hours"),
        "human_review_required": True,
        "official_authority_inferred": False,
        "external_action_authorized": False,
    }


def official_work(task: dict[str, Any]) -> dict[str, Any]:
    basis = {
        "domain": "OFFICIAL_AUTHORITY",
        "opportunity_id": task["opportunity_id"],
        "reason_code": task["reason_code"],
        "operator_action": task["operator_action"],
    }
    return {
        "work_id": canonical_hash(basis),
        "domain": "OFFICIAL_AUTHORITY",
        "target_kind": "OPPORTUNITY",
        "opportunity_id": task["opportunity_id"],
        "title": task.get("title"),
        "programme": task.get("programme"),
        "priority": task["priority"],
        "authority_state": task.get("authority_state"),
        "reason_code": task["reason_code"],
        "operator_action": task["operator_action"],
        "required_candidate_fact_classes": list(task.get("required_candidate_fact_classes") or []),
        "verified_fact_classes": list(task.get("verified_fact_classes") or []),
        "missing_candidate_fact_classes": list(task.get("missing_candidate_fact_classes") or []),
        "unbound_material_fact_classes": list(task.get("unbound_material_fact_classes") or []),
        "official_source_count": int(task.get("official_source_count") or 0),
        "source_product": "PARTENER.EU",
        "source_role": "DISCOVERY_ONLY",
        "human_review_required": True,
        "official_authority_inferred": False,
        "external_action_authorized": False,
    }


def build_unified_queue(
    freshness_queue: dict[str, Any],
    official_queue: dict[str, Any] | None,
    contract: dict[str, Any],
    freshness_contract: dict[str, Any],
    official_contract: dict[str, Any],
) -> dict[str, Any]:
    validate_contract(contract, freshness_contract, official_contract)
    validate_freshness_queue(freshness_queue, contract, freshness_contract)
    held = freshness_queue["summary"]["source_held"]

    if held:
        require(official_queue is None, "official authority work is forbidden while discovery source is held")
        work = [freshness_work(task) for task in freshness_queue["tasks"]]
        official_queue_id = None
        official_registry_state = "NOT_EVALUATED_SOURCE_HELD"
    else:
        require(official_queue is not None, "ready discovery source requires official authority queue")
        validate_official_queue(official_queue, contract, official_contract)
        if contract["input"]["require_same_source_projection_sha256"]:
            require(
                official_queue["source_projection_sha256"] == freshness_queue["source_projection_sha256"],
                "parent queues refer to different source projections",
            )
        work = [official_work(task) for task in official_queue["tasks"]]
        official_queue_id = official_queue["queue_id"]
        official_registry_state = official_queue["official_registry_state"]

    priority_rank = {value: index for index, value in enumerate(contract["triage"]["priority_order"])}
    domain_rank = {value: index for index, value in enumerate(contract["triage"]["domains"])}
    work.sort(key=lambda row: (priority_rank[row["priority"]], domain_rank[row["domain"]], row["work_id"]))
    summary = {
        "source_held": held,
        "operator_work_items": len(work),
        "p0_items": sum(1 for row in work if row["priority"] == "P0"),
        "p1_items": sum(1 for row in work if row["priority"] == "P1"),
        "p2_items": sum(1 for row in work if row["priority"] == "P2"),
        "discovery_source_items": sum(1 for row in work if row["domain"] == "DISCOVERY_SOURCE"),
        "official_authority_items": sum(1 for row in work if row["domain"] == "OFFICIAL_AUTHORITY"),
    }
    result = {
        "schema_version": contract["schema_version"],
        "engine_id": contract["engine_id"],
        "state": contract["output"]["state"],
        "read_only": True,
        "human_review_required": True,
        "source_projection_sha256": freshness_queue["source_projection_sha256"],
        "freshness_queue_id": freshness_queue["queue_id"],
        "official_queue_id": official_queue_id,
        "official_registry_state": official_registry_state,
        "summary": summary,
        "work_items": work,
        "boundaries": dict(contract["boundaries"]),
    }
    result["work_queue_id"] = canonical_hash({
        "engine_id": result["engine_id"],
        "source_projection_sha256": result["source_projection_sha256"],
        "freshness_queue_id": result["freshness_queue_id"],
        "official_queue_id": result["official_queue_id"],
        "summary": result["summary"],
        "work_items": work,
    })
    validate_safe_output(result)
    return result


def ensure_output_outside_repo(path: Path) -> None:
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return
    raise ValueError("repository runtime output is forbidden")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freshness-queue", required=True)
    parser.add_argument("--official-queue", default=None)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--freshness-contract", default=str(DEFAULT_FRESHNESS_CONTRACT))
    parser.add_argument("--official-contract", default=str(DEFAULT_OFFICIAL_CONTRACT))
    parser.add_argument("--output", default=None, help="optional JSON path outside repository; stdout when omitted")
    args = parser.parse_args()

    freshness_queue = load_json(Path(args.freshness_queue))
    official_queue = load_json(Path(args.official_queue)) if args.official_queue else None
    contract = load_json(Path(args.contract))
    freshness_contract = load_json(Path(args.freshness_contract))
    official_contract = load_json(Path(args.official_contract))
    result = build_unified_queue(freshness_queue, official_queue, contract, freshness_contract, official_contract)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        ensure_output_outside_repo(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
