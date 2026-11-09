#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "opportunities" / "match_operator_explainability_contract.json"
DEFAULT_MATCHING_CONTRACT = EUCONS / "opportunities" / "matching_contract.json"
DEFAULT_QUEUE_CONTRACT = EUCONS / "opportunities" / "official_source_operator_queue_contract.json"

MATCH_RESULT_FIELDS = {
    "opportunity_id",
    "title",
    "programme",
    "score",
    "score_semantics",
    "confidence",
    "state",
    "authority_state",
    "official_fact_classes",
    "official_source_count",
    "explanations",
    "hard_exclusion_reasons",
    "source_provenance",
}
QUEUE_TASK_FIELDS = {
    "opportunity_id",
    "title",
    "programme",
    "priority",
    "authority_state",
    "reason_code",
    "operator_action",
    "required_candidate_fact_classes",
    "verified_fact_classes",
    "missing_candidate_fact_classes",
    "unbound_material_fact_classes",
    "official_source_count",
    "discovery_context",
    "external_action_authorized",
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_contract(
    contract: dict[str, Any],
    matching_contract: dict[str, Any],
    queue_contract: dict[str, Any],
) -> None:
    require(contract.get("schema_version") == 1, "explainability schema drift")
    require(contract.get("engine_id") == "EUCONS_E10_MATCH_OPERATOR_EXPLAINABILITY", "explainability engine drift")
    inputs = contract.get("inputs") or {}
    require(inputs.get("required_matching_engine") == matching_contract.get("engine_id") == "EUCONS_E10_OPPORTUNITY_MATCHING",
            "matching engine binding drift")
    require(inputs.get("required_matching_schema_version") == 2, "matching snapshot schema drift")
    require(inputs.get("required_score_semantics") == matching_contract.get("score_semantics") == "RELEVANCE_NOT_APPROVAL_PROBABILITY",
            "score semantics binding drift")
    require(inputs.get("required_operator_queue_engine") == queue_contract.get("engine_id") == "EUCONS_E10_OFFICIAL_SOURCE_OPERATOR_QUEUE",
            "operator queue engine binding drift")
    require(inputs.get("required_operator_queue_state") == queue_contract.get("output", {}).get("state") == "READ_ONLY_OPERATOR_QUEUE",
            "operator queue state binding drift")
    require(inputs.get("required_partener_role") == matching_contract.get("official_source_guards", {}).get("partener_role") == "DISCOVERY_ONLY",
            "PARTENER role binding drift")

    authority = contract.get("authority") or {}
    matching_guards = matching_contract.get("official_source_guards") or {}
    queue_authority = queue_contract.get("authority") or {}
    require(authority.get("waiting_state") == matching_guards.get("waiting_authority_state") == queue_authority.get("waiting_state") == "WAITING_SOURCE",
            "waiting authority state drift")
    require(authority.get("blocked_state") == matching_guards.get("blocked_authority_state") == queue_authority.get("blocked_state") == "BLOCKED_SOURCE_CONFLICT",
            "blocked authority state drift")
    require(authority.get("verified_state") == matching_guards.get("verified_authority_state") == queue_authority.get("verified_state") == "OFFICIAL_SOURCE_VERIFIED",
            "verified authority state drift")
    queue_triage = queue_contract.get("triage") or {}
    for local_key, queue_key, expected in (
        ("waiting_priority", "waiting_priority", "P1"),
        ("blocked_priority", "blocked_priority", "P0"),
        ("enrichment_priority", "enrichment_priority", "P2"),
        ("waiting_action", "waiting_action", "VERIFY_REQUIRED_OFFICIAL_FACTS"),
        ("blocked_action", "blocked_action", "RESOLVE_OFFICIAL_SOURCE_CONFLICT"),
        ("enrichment_action", "enrichment_action", "ENRICH_OFFICIAL_MATERIAL_FACT_BINDINGS"),
    ):
        require(authority.get(local_key) == queue_triage.get(queue_key) == expected, f"authority triage drift: {local_key}")

    matching = contract.get("matching") or {}
    outputs = matching_contract.get("outputs") or {}
    require(matching.get("candidate_state") == outputs.get("candidate") == "MATCH_CANDIDATE", "candidate state drift")
    require(matching.get("requires_data_state") == outputs.get("insufficient") == "REQUIRES_DATA", "requires-data state drift")
    require(matching.get("excluded_state") == outputs.get("excluded") == "EXCLUDED_KNOWN_RULE", "excluded state drift")
    require(matching.get("held_state") == outputs.get("held") == "HOLD_SOURCE_STATE", "held state drift")
    require(matching.get("confidence_levels") == outputs.get("confidence_levels") == ["LOW", "MEDIUM", "HIGH"], "confidence levels drift")
    require(matching.get("score_min") == 0 and matching.get("score_max") == 100, "score range drift")

    rules = contract.get("rules") or {}
    for key in (
        "queue_alignment_required_for_waiting_or_blocked",
        "verified_enrichment_queue_may_be_present",
        "numeric_score_visible_only_when_authority_verified_and_not_excluded",
        "waiting_or_blocked_score_withheld",
        "excluded_score_withheld",
        "confidence_is_relevance_not_approval_probability",
        "raw_matching_explanations_forbidden",
        "hard_exclusion_detail_forbidden",
        "source_provenance_detail_forbidden",
        "raw_material_fact_values_forbidden",
        "person_level_fields_forbidden",
        "eligibility_conclusion_forbidden",
        "award_probability_forbidden",
        "no_external_fetch_or_write",
    ):
        require(rules.get(key) is True, f"explainability rule failed open: {key}")
    require(rules.get("deterministic_sort") == ["disposition_rank", "score_desc_when_visible", "opportunity_id_asc"],
            "explainability sort drift")
    output = contract.get("output") or {}
    require(output.get("state") == "READ_ONLY_MATCH_EXPLAINABILITY", "output state drift")
    require(output.get("human_review_required") is True, "human review must remain required")
    require(output.get("external_action_authorized") is False, "external action must remain disabled")
    require(output.get("repository_runtime_output_forbidden") is True, "repository runtime output must remain forbidden")
    boundaries = contract.get("boundaries") or {}
    require(boundaries and all(value is False for value in boundaries.values()), "external boundary enabled")


def validate_match_snapshot(snapshot: dict[str, Any], contract: dict[str, Any]) -> list[dict[str, Any]]:
    expected_root = {"schema_version", "engine_id", "profile_id", "score_semantics", "bridge_state", "partener_role", "summary", "results"}
    require(set(snapshot) == expected_root, "matching snapshot root field drift")
    inputs = contract["inputs"]
    require(snapshot.get("schema_version") == inputs["required_matching_schema_version"], "matching snapshot schema mismatch")
    require(snapshot.get("engine_id") == inputs["required_matching_engine"], "matching snapshot engine mismatch")
    require(snapshot.get("score_semantics") == inputs["required_score_semantics"], "matching snapshot score semantics mismatch")
    require(snapshot.get("partener_role") == inputs["required_partener_role"], "matching snapshot PARTENER role drift")
    require(isinstance(snapshot.get("profile_id"), str) and snapshot["profile_id"].strip(), "matching profile id missing")
    require(isinstance(snapshot.get("summary"), dict), "matching summary invalid")
    rows = snapshot.get("results")
    require(isinstance(rows, list), "matching results must be a list")
    seen: set[str] = set()
    allowed_authority = {contract["authority"]["waiting_state"], contract["authority"]["blocked_state"], contract["authority"]["verified_state"]}
    allowed_states = {
        contract["matching"]["candidate_state"],
        contract["matching"]["requires_data_state"],
        contract["matching"]["excluded_state"],
        contract["matching"]["held_state"],
    }
    for row in rows:
        require(isinstance(row, dict) and set(row) == MATCH_RESULT_FIELDS, "matching result field drift")
        opportunity_id = row.get("opportunity_id")
        require(isinstance(opportunity_id, str) and opportunity_id.strip(), "matching opportunity id missing")
        require(opportunity_id not in seen, "duplicate matching opportunity id")
        seen.add(opportunity_id)
        require(row.get("score_semantics") == inputs["required_score_semantics"], "row score semantics drift")
        score = row.get("score")
        require(isinstance(score, int) and not isinstance(score, bool), "row score must be integer")
        require(contract["matching"]["score_min"] <= score <= contract["matching"]["score_max"], "row score out of range")
        require(row.get("confidence") in contract["matching"]["confidence_levels"], "row confidence invalid")
        require(row.get("state") in allowed_states, "row matching state invalid")
        require(row.get("authority_state") in allowed_authority, "row authority state invalid")
        require(isinstance(row.get("official_fact_classes"), list), "official fact classes invalid")
        require(isinstance(row.get("official_source_count"), int) and row["official_source_count"] >= 0, "official source count invalid")
        require(isinstance(row.get("explanations"), list) and all(isinstance(item, str) for item in row["explanations"]), "matching explanations invalid")
        require(isinstance(row.get("hard_exclusion_reasons"), list) and all(isinstance(item, str) for item in row["hard_exclusion_reasons"]), "hard exclusion reasons invalid")
        require(isinstance(row.get("source_provenance"), dict), "source provenance invalid")
        if row["authority_state"] in {contract["authority"]["waiting_state"], contract["authority"]["blocked_state"]}:
            require(row["state"] == contract["matching"]["held_state"], "unverified authority must remain source-held")
            require(score == 0, "unverified authority score must remain zero")
        if row["state"] == contract["matching"]["excluded_state"]:
            require(row["authority_state"] == contract["authority"]["verified_state"], "hard exclusion requires verified authority")
            require(bool(row["hard_exclusion_reasons"]), "hard exclusion reason missing")
    return rows


def validate_queue_snapshot(queue: dict[str, Any], contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    expected_root = {"schema_version", "engine_id", "state", "read_only", "source_projection_sha256", "official_registry_state", "summary", "tasks", "boundaries", "queue_id"}
    require(set(queue) == expected_root, "operator queue root field drift")
    inputs = contract["inputs"]
    require(queue.get("schema_version") == 1, "operator queue schema mismatch")
    require(queue.get("engine_id") == inputs["required_operator_queue_engine"], "operator queue engine mismatch")
    require(queue.get("state") == inputs["required_operator_queue_state"], "operator queue state mismatch")
    require(queue.get("read_only") is True, "operator queue must remain read-only")
    require(isinstance(queue.get("summary"), dict), "operator queue summary invalid")
    require(isinstance(queue.get("boundaries"), dict) and queue["boundaries"] and all(value is False for value in queue["boundaries"].values()),
            "operator queue external boundary enabled")
    require(isinstance(queue.get("queue_id"), str) and len(queue["queue_id"]) == 64, "operator queue id invalid")
    tasks = queue.get("tasks")
    require(isinstance(tasks, list), "operator queue tasks must be a list")
    by_id: dict[str, dict[str, Any]] = {}
    for task in tasks:
        require(isinstance(task, dict) and set(task) == QUEUE_TASK_FIELDS, "operator queue task field drift")
        opportunity_id = task.get("opportunity_id")
        require(isinstance(opportunity_id, str) and opportunity_id.strip(), "operator queue opportunity id missing")
        require(opportunity_id not in by_id, "duplicate operator queue opportunity id")
        require(task.get("external_action_authorized") is False, "operator queue task enabled external action")
        by_id[opportunity_id] = task
    return by_id


def reason_codes_for_match(row: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    reasons = contract["reason_codes"]
    for text in row["explanations"]:
        if text.startswith("officially bound activity-code overlap:"):
            codes.append(reasons["activity_overlap"])
        elif text.startswith("relevance terms found in discovery metadata or officially bound facts:"):
            codes.append(reasons["investment_match"])
        elif text.startswith("organization terms found in discovery metadata or officially bound facts:"):
            codes.append(reasons["organization_match"])
        elif text.startswith("region terms found in discovery metadata or officially bound facts:"):
            codes.append(reasons["region_match"])
        elif text.startswith("requested grant is within officially bound cap"):
            codes.append(reasons["grant_within_cap"])
        elif text == "No sufficiently specific relevance signal was found; more project data is required.":
            codes.append(reasons["insufficient_signal"])
        else:
            raise ValueError(f"unmapped matching explanation for {row['opportunity_id']}")
    return sorted(set(codes))


def exclusion_reason_codes(row: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    reasons = contract["reason_codes"]
    codes: list[str] = []
    for text in row["hard_exclusion_reasons"]:
        if text.startswith("officially bound activity code mismatch:"):
            codes.append(reasons["activity_exclusion"])
        elif text.startswith("requested_grant_eur=") and " exceeds officially_bound_cap_eur=" in text:
            codes.append(reasons["grant_exclusion"])
        else:
            raise ValueError(f"unmapped hard exclusion reason for {row['opportunity_id']}")
    return sorted(set(codes))


def aligned_queue_task(row: dict[str, Any], task: dict[str, Any] | None, contract: dict[str, Any]) -> tuple[bool, str | None]:
    authority = contract["authority"]
    state = row["authority_state"]
    if state == authority["waiting_state"]:
        require(task is not None, f"WAITING_SOURCE result missing operator queue task: {row['opportunity_id']}")
        require(task.get("authority_state") == state, "waiting queue authority mismatch")
        require(task.get("priority") == authority["waiting_priority"], "waiting queue priority mismatch")
        require(task.get("operator_action") == authority["waiting_action"], "waiting queue action mismatch")
        return True, authority["waiting_action"]
    if state == authority["blocked_state"]:
        require(task is not None, f"BLOCKED_SOURCE_CONFLICT result missing operator queue task: {row['opportunity_id']}")
        require(task.get("authority_state") == state, "blocked queue authority mismatch")
        require(task.get("priority") == authority["blocked_priority"], "blocked queue priority mismatch")
        require(task.get("operator_action") == authority["blocked_action"], "blocked queue action mismatch")
        return True, authority["blocked_action"]
    if task is None:
        return False, None
    require(task.get("authority_state") == authority["verified_state"], "verified queue authority mismatch")
    require(task.get("priority") == authority["enrichment_priority"], "verified enrichment queue priority mismatch")
    require(task.get("operator_action") == authority["enrichment_action"], "verified enrichment queue action mismatch")
    return True, authority["enrichment_action"]


def explain_row(row: dict[str, Any], task: dict[str, Any] | None, contract: dict[str, Any]) -> dict[str, Any]:
    authority = contract["authority"]
    matching = contract["matching"]
    dispositions = contract["dispositions"]
    queue_pending, source_followup = aligned_queue_task(row, task, contract)
    state = row["authority_state"]
    if state == authority["waiting_state"]:
        disposition = dispositions["waiting"]
        reason_codes = [contract["reason_codes"]["waiting"]]
        score_visible = False
    elif state == authority["blocked_state"]:
        disposition = dispositions["blocked"]
        reason_codes = [contract["reason_codes"]["blocked"]]
        score_visible = False
    elif row["state"] == matching["excluded_state"]:
        disposition = dispositions["excluded"]
        reason_codes = exclusion_reason_codes(row, contract)
        score_visible = False
    elif row["state"] == matching["candidate_state"]:
        disposition = dispositions["candidate"]
        reason_codes = reason_codes_for_match(row, contract)
        score_visible = True
    elif row["state"] == matching["requires_data_state"]:
        disposition = dispositions["requires_data"]
        reason_codes = reason_codes_for_match(row, contract)
        score_visible = True
    else:
        raise ValueError(f"verified authority produced unsupported matching state for {row['opportunity_id']}: {row['state']}")

    score_display = {
        "visibility": "VISIBLE" if score_visible else "WITHHELD",
        "value": row["score"] if score_visible else None,
        "semantics": contract["inputs"]["required_score_semantics"],
    }
    confidence = {
        "visibility": "VISIBLE" if score_visible else "WITHHELD",
        "level": row["confidence"] if score_visible else None,
        "semantics": "RELEVANCE_CONFIDENCE_NOT_APPROVAL_PROBABILITY",
    }
    return {
        "opportunity_id": row["opportunity_id"],
        "title": row.get("title"),
        "programme": row.get("programme"),
        "disposition": disposition,
        "match_state": row["state"],
        "authority_state": state,
        "score_display": score_display,
        "confidence": confidence,
        "reason_codes": reason_codes,
        "verified_fact_classes": sorted(set(row["official_fact_classes"])),
        "official_source_count": row["official_source_count"],
        "authority_queue_pending": queue_pending,
        "source_followup_action": source_followup,
        "human_review_required": True,
        "external_action_authorized": False,
    }


def validate_safe_output(value: Any) -> None:
    forbidden_keys = {
        "profile_id",
        "source_provenance",
        "explanations",
        "hard_exclusion_reasons",
        "material_facts",
        "verified_fact_hashes",
        "source_url",
        "source_document_sha256",
        "requested_grant_eur",
        "eligibility_conclusion",
        "award_probability",
        "name",
        "email",
        "phone",
        "address",
        "personal_identifier",
    }
    if isinstance(value, dict):
        overlap = forbidden_keys.intersection(value)
        require(not overlap, f"explainability output leaked forbidden fields: {sorted(overlap)}")
        for item in value.values():
            validate_safe_output(item)
    elif isinstance(value, list):
        for item in value:
            validate_safe_output(item)


def build_explainability(
    match_snapshot: dict[str, Any],
    queue_snapshot: dict[str, Any],
    contract: dict[str, Any],
    matching_contract: dict[str, Any],
    queue_contract: dict[str, Any],
) -> dict[str, Any]:
    validate_contract(contract, matching_contract, queue_contract)
    rows = validate_match_snapshot(match_snapshot, contract)
    tasks = validate_queue_snapshot(queue_snapshot, contract)
    row_ids = {row["opportunity_id"] for row in rows}
    unknown_tasks = set(tasks) - row_ids
    require(not unknown_tasks, f"operator queue contains opportunity absent from matching snapshot: {sorted(unknown_tasks)}")

    explained = [explain_row(row, tasks.get(row["opportunity_id"]), contract) for row in rows]
    rank = {
        contract["dispositions"]["blocked"]: 0,
        contract["dispositions"]["waiting"]: 1,
        contract["dispositions"]["candidate"]: 2,
        contract["dispositions"]["requires_data"]: 3,
        contract["dispositions"]["excluded"]: 4,
    }
    explained.sort(key=lambda item: (
        rank[item["disposition"]],
        -(item["score_display"]["value"] if item["score_display"]["value"] is not None else -1),
        item["opportunity_id"],
    ))
    summary = {
        "evaluated": len(explained),
        "blocked_source_conflict": sum(item["disposition"] == contract["dispositions"]["blocked"] for item in explained),
        "waiting_source": sum(item["disposition"] == contract["dispositions"]["waiting"] for item in explained),
        "candidate_for_human_review": sum(item["disposition"] == contract["dispositions"]["candidate"] for item in explained),
        "needs_profile_detail": sum(item["disposition"] == contract["dispositions"]["requires_data"] for item in explained),
        "excluded_by_known_rule": sum(item["disposition"] == contract["dispositions"]["excluded"] for item in explained),
        "authority_queue_pending": sum(item["authority_queue_pending"] for item in explained),
        "numeric_scores_visible": sum(item["score_display"]["visibility"] == "VISIBLE" for item in explained),
    }
    result = {
        "schema_version": contract["schema_version"],
        "engine_id": contract["engine_id"],
        "state": contract["output"]["state"],
        "read_only": True,
        "profile_reference_hash": canonical_hash(match_snapshot["profile_id"]),
        "score_semantics": contract["inputs"]["required_score_semantics"],
        "partener_role": contract["inputs"]["required_partener_role"],
        "summary": summary,
        "results": explained,
        "boundaries": dict(contract["boundaries"]),
    }
    result["explainability_id"] = canonical_hash({
        "engine_id": result["engine_id"],
        "profile_reference_hash": result["profile_reference_hash"],
        "results": explained,
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
    parser.add_argument("--match-snapshot", required=True)
    parser.add_argument("--operator-queue", required=True)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--matching-contract", default=str(DEFAULT_MATCHING_CONTRACT))
    parser.add_argument("--queue-contract", default=str(DEFAULT_QUEUE_CONTRACT))
    parser.add_argument("--output", default=None, help="optional JSON path outside repository; stdout when omitted")
    args = parser.parse_args()

    result = build_explainability(
        load_json(Path(args.match_snapshot)),
        load_json(Path(args.operator_queue)),
        load_json(Path(args.contract)),
        load_json(Path(args.matching_contract)),
        load_json(Path(args.queue_contract)),
    )
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
