#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "eucons" / "prospects" / "client_finder_source_authority_queue_contract.json"

DISABLED_ACTION_FLAGS = (
    "external_contact_enabled",
    "automatic_offer_enabled",
    "automatic_send_enabled",
    "crm_write_enabled",
    "pipeline_write_enabled",
)
TASK_FIELDS = {
    "task_type", "organization_key", "prospect_id", "priority_state", "priority_score",
    "opportunity_id", "opportunity_title", "programme", "authority_state",
    "official_fact_classes", "missing_required_official_fact_classes", "official_source_count",
    "task_reason", "operator_next_step", "eligibility_state", "maximum_next_state",
    "human_review_required", *DISABLED_ACTION_FLAGS, "evidence_label",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def recursive_keys(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from recursive_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from recursive_keys(child)


def _assert_no_unsafe_true(value: Any) -> None:
    for key in recursive_keys(value):
        if key in DISABLED_ACTION_FLAGS:
            for container in _containers_with_key(value, key):
                require(container[key] is False, f"unsafe action boundary failed open: {key}")


def _containers_with_key(value: Any, target: str):
    if isinstance(value, dict):
        if target in value:
            yield value
        for child in value.values():
            yield from _containers_with_key(child, target)
    elif isinstance(value, list):
        for child in value:
            yield from _containers_with_key(child, target)


def _assert_no_forbidden_output(value: Any, contract: dict[str, Any]) -> None:
    policy = contract["output_policy"]
    forbidden = set(policy["raw_fields_forbidden"]) | set(policy["inference_fields_forbidden"])
    leaked = forbidden & set(recursive_keys(value))
    require(not leaked, f"forbidden output field leaked: {sorted(leaked)[0] if leaked else ''}")
    _assert_no_unsafe_true(value)


def validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 1, "source authority queue contract schema drift")
    require(contract.get("id") == "EUCONS-R07-CLIENT-FINDER-SOURCE-AUTHORITY-QUEUE-001", "source authority queue contract id drift")
    require(contract.get("status") == "CANONICAL", "source authority queue contract must be canonical")
    source = contract.get("source_view") or {}
    require(source.get("engine_id") == "EUCONS_R07_PROSPECT_OPPORTUNITY_SERVICE_MATCH", "R07 source engine drift")
    require(source.get("match_semantics") == "RESEARCH_RELEVANCE_NOT_ELIGIBILITY_AWARD_OR_BUYING_INTENT", "R07 match semantics failed open")
    require(source.get("partener_role") == "DISCOVERY_ONLY", "PARTENER role failed open")
    require(source.get("ready_bridge_state") == "READY", "ready bridge state drift")
    require(source.get("held_prospect_state") == "HOLD_SOURCE_STATE", "held prospect state drift")

    authority = contract.get("official_authority") or {}
    require(authority.get("waiting_state") == "WAITING_SOURCE", "official waiting state drift")
    require(authority.get("blocked_state") == "BLOCKED_SOURCE_CONFLICT", "official blocked state drift")
    require(authority.get("verified_state") == "OFFICIAL_SOURCE_VERIFIED", "official verified state drift")
    require(set(authority.get("required_fact_classes") or []) == {"status", "deadline"}, "required official fact classes drift")
    allowed = set(authority.get("allowed_fact_classes") or [])
    require({"status", "deadline"}.issubset(allowed), "allowed official fact classes incomplete")
    require(authority.get("discovery_source_product") == "PARTENER.EU", "discovery source product drift")
    minimum = authority.get("minimum_verified_source_count")
    require(isinstance(minimum, int) and not isinstance(minimum, bool) and minimum == 1, "minimum official source count drift")

    boundaries = contract.get("required_boundaries") or {}
    expected = {
        "eligibility_state": "NOT_ASSESSED", "maximum_next_state": "RESEARCH_READY",
        "human_review_required": True, "external_contact_enabled": False,
        "automatic_offer_enabled": False, "automatic_send_enabled": False,
        "crm_write_enabled": False, "pipeline_write_enabled": False,
    }
    require(boundaries == expected, "source authority queue boundary drift")

    output = contract.get("output_policy") or {}
    require(output.get("view_state") == "CLIENT_FINDER_SOURCE_AUTHORITY_QUEUE", "source authority queue view-state drift")
    require(output.get("semantics") == "SOURCE_REVERIFICATION_TASKS_NOT_ELIGIBILITY_OR_OUTREACH", "source authority queue semantics drift")
    rules = contract.get("rules") or {}
    for key in (
        "only_source_held_prospects_generate_tasks", "stale_discovery_precedes_opportunity_authority_review",
        "partener_never_satisfies_official_authority", "required_official_fact_classes_are_labels_only",
        "official_fact_values_never_exposed", "official_conflict_fails_closed",
        "matched_candidates_never_enter_source_queue", "never_infer_eligibility_award_conversion_or_buying_intent",
        "never_generate_person_level_output", "never_enable_external_action_or_persistence",
        "repository_runtime_output_forbidden",
    ):
        require(rules.get(key) is True, f"source authority queue safety rule failed open: {key}")


def _validate_input(match_view: dict[str, Any], contract: dict[str, Any]) -> list[dict[str, Any]]:
    require(isinstance(match_view, dict), "R07 match view must be object")
    source, boundaries = contract["source_view"], contract["required_boundaries"]
    require(match_view.get("engine_id") == source["engine_id"], "unexpected R07 match engine")
    require(match_view.get("match_semantics") == source["match_semantics"], "unexpected R07 match semantics")
    require(match_view.get("partener_role") == source["partener_role"], "PARTENER discovery-only boundary missing")
    require(match_view.get("eligibility_state") == boundaries["eligibility_state"], "R07 eligibility boundary drift")
    require(match_view.get("maximum_next_state") == boundaries["maximum_next_state"], "R07 next-state boundary drift")
    _assert_no_unsafe_true(match_view)
    rows = match_view.get("results")
    require(isinstance(rows, list), "R07 match results must be list")
    return rows


def _base_task(row: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    boundaries = contract["required_boundaries"]
    score = row.get("priority_score")
    require(score is None or (isinstance(score, int) and not isinstance(score, bool)), "priority score must be integer or null")
    require(row.get("eligibility_state") == boundaries["eligibility_state"], "held prospect eligibility boundary drift")
    require(row.get("maximum_next_state") == boundaries["maximum_next_state"], "held prospect next-state boundary drift")
    organization_key = row.get("organization_key")
    prospect_id = row.get("prospect_id")
    require(isinstance(organization_key, str) and organization_key.strip(), "held prospect organization_key missing")
    require(isinstance(prospect_id, str) and prospect_id.strip(), "held prospect prospect_id missing")
    require(row.get("selected_opportunity_id") is None and row.get("selected_service_id") is None, "source-held prospect cannot expose selected opportunity/service")
    return {
        "organization_key": organization_key,
        "prospect_id": prospect_id,
        "priority_state": row.get("priority_state"),
        "priority_score": score,
        "eligibility_state": boundaries["eligibility_state"],
        "maximum_next_state": boundaries["maximum_next_state"],
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
        "evidence_label": row.get("evidence_label"),
    }


def _discovery_refresh_task(row: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    task = _base_task(row, contract)
    task.update({
        "task_type": contract["task_types"]["discovery_freshness"],
        "opportunity_id": None,
        "opportunity_title": None,
        "programme": None,
        "authority_state": "NOT_EVALUATED_DISCOVERY_SOURCE_HOLD",
        "official_fact_classes": [],
        "missing_required_official_fact_classes": [],
        "official_source_count": 0,
        "task_reason": "DISCOVERY_SOURCE_NOT_READY_FOR_AUTHORITY_EVALUATION",
        "operator_next_step": contract["operator_actions"]["discovery_refresh"],
    })
    return task


def _authority_tasks(row: dict[str, Any], contract: dict[str, Any]) -> list[dict[str, Any]]:
    authority = contract["official_authority"]
    required = set(authority["required_fact_classes"])
    allowed = set(authority["allowed_fact_classes"])
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    matches = row.get("opportunity_matches")
    require(isinstance(matches, list), "source-held opportunity_matches must be list")
    for opportunity in matches:
        require(isinstance(opportunity, dict), "source-held opportunity match must be object")
        state = opportunity.get("authority_state")
        if state not in {authority["waiting_state"], authority["blocked_state"]}:
            continue
        opportunity_id = opportunity.get("opportunity_id")
        require(isinstance(opportunity_id, str) and opportunity_id.strip(), "source authority task opportunity_id missing")
        require(opportunity_id not in seen, "duplicate source authority opportunity_id")
        seen.add(opportunity_id)
        provenance = opportunity.get("source_provenance") or {}
        require(provenance.get("source_product") == authority["discovery_source_product"], "source authority task lost PARTENER discovery provenance")
        source_opportunity_id = provenance.get("source_opportunity_id")
        if source_opportunity_id is not None:
            require(str(source_opportunity_id) == opportunity_id, "source authority provenance identity drift")

        classes = opportunity.get("official_fact_classes")
        require(isinstance(classes, list) and all(isinstance(item, str) for item in classes), "official fact classes must be a string list")
        require(len(classes) == len(set(classes)), "official fact classes must be unique")
        class_set = set(classes)
        require(class_set.issubset(allowed), "unsupported official fact class")
        count = opportunity.get("official_source_count")
        require(isinstance(count, int) and not isinstance(count, bool) and count >= 0, "official source count invalid")

        if state == authority["waiting_state"]:
            missing = sorted(required - class_set)
            require(bool(missing), "WAITING_SOURCE has no missing required official fact class")
            reason = "REQUIRED_OFFICIAL_FACT_BINDINGS_MISSING"
            action = contract["operator_actions"]["waiting_source"]
        else:
            require(not class_set, "blocked official conflict must not retain authoritative fact classes")
            missing = sorted(required)
            reason = "OFFICIAL_SOURCE_CONFLICT_BLOCKS_MATCHING"
            action = contract["operator_actions"]["blocked_conflict"]

        task = _base_task(row, contract)
        task.update({
            "task_type": contract["task_types"]["official_authority"],
            "opportunity_id": opportunity_id,
            "opportunity_title": opportunity.get("title"),
            "programme": opportunity.get("programme"),
            "authority_state": state,
            "official_fact_classes": sorted(class_set),
            "missing_required_official_fact_classes": missing,
            "official_source_count": count,
            "task_reason": reason,
            "operator_next_step": action,
        })
        require(set(task) == TASK_FIELDS, "source authority task field allowlist drift")
        tasks.append(task)
    require(tasks, "READY source-held prospect lacks WAITING_SOURCE/BLOCKED authority detail")
    return tasks


def build_queue(match_view: dict[str, Any], contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = contract or load_json(CONTRACT_PATH)
    validate_contract(contract)
    rows = _validate_input(match_view, contract)
    bridge_ready = match_view.get("bridge_state") == contract["source_view"]["ready_bridge_state"]
    held_rows = [row for row in rows if isinstance(row, dict) and row.get("state") == contract["source_view"]["held_prospect_state"]]
    organizations: set[str] = set()
    tasks: list[dict[str, Any]] = []
    for row in held_rows:
        key = row.get("organization_key")
        require(isinstance(key, str) and key not in organizations, "duplicate source-held organization_key")
        organizations.add(key)
        if bridge_ready:
            tasks.extend(_authority_tasks(row, contract))
        else:
            task = _discovery_refresh_task(row, contract)
            require(set(task) == TASK_FIELDS, "discovery refresh task field allowlist drift")
            tasks.append(task)

    type_priority = {contract["task_types"]["discovery_freshness"]: 0, contract["task_types"]["official_authority"]: 1}
    tasks.sort(key=lambda task: (
        type_priority[task["task_type"]],
        task["priority_score"] is None,
        -(task["priority_score"] or 0),
        task["organization_key"],
        task["opportunity_id"] or "",
    ))
    boundaries = contract["required_boundaries"]
    result = {
        "schema_version": 1,
        "contract_id": contract["id"],
        "source_engine_id": contract["source_view"]["engine_id"],
        "view_state": contract["output_policy"]["view_state"],
        "semantics": contract["output_policy"]["semantics"],
        "partener_role": contract["source_view"]["partener_role"],
        "bridge_state": match_view.get("bridge_state"),
        "eligibility_state": boundaries["eligibility_state"],
        "maximum_next_state": boundaries["maximum_next_state"],
        "summary": {
            "source_held_prospects": len(held_rows),
            "tasks": len(tasks),
            "official_authority_tasks": sum(task["task_type"] == contract["task_types"]["official_authority"] for task in tasks),
            "discovery_refresh_tasks": sum(task["task_type"] == contract["task_types"]["discovery_freshness"] for task in tasks),
            "waiting_source": sum(task["authority_state"] == contract["official_authority"]["waiting_state"] for task in tasks),
            "blocked_source_conflict": sum(task["authority_state"] == contract["official_authority"]["blocked_state"] for task in tasks),
        },
        "tasks": tasks,
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }
    _assert_no_forbidden_output(result, contract)
    return result


def assert_output_path_safe(path: Path) -> None:
    root = ROOT.resolve()
    resolved = path.expanduser().resolve()
    require(root != resolved and root not in resolved.parents, "repository runtime output is forbidden")


def write_atomic(path: Path, value: dict[str, Any]) -> None:
    assert_output_path_safe(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="EUCONS Client Finder read-only source authority operator queue")
    parser.add_argument("--match-view", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build_queue(load_json(args.match_view))
    write_atomic(args.output, result)
    print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
