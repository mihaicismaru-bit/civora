#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / "eucons" / "opportunities" / "unified_source_work_queue.py"
CONTRACT_PATH = ROOT / "eucons" / "opportunities" / "unified_source_work_queue_contract.json"
FRESHNESS_CONTRACT_PATH = ROOT / "eucons" / "opportunities" / "source_freshness_recovery_contract.json"
OFFICIAL_CONTRACT_PATH = ROOT / "eucons" / "opportunities" / "official_source_operator_queue_contract.json"
SOURCE_SHA = "a" * 64


def load_engine():
    spec = importlib.util.spec_from_file_location("eucons_unified_source_work_queue", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load unified source work queue engine")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def must_fail(label: str, fn) -> None:
    try:
        fn()
    except ValueError:
        return
    raise AssertionError(f"{label} failed open")


def freshness_queue(*, held: bool, reason: str | None = None) -> dict:
    tasks = []
    freshness_state = "FRESH"
    if held:
        reason = reason or "DISCOVERY_SOURCE_STALE"
        if reason == "DISCOVERY_TIMESTAMP_INTEGRITY_HOLD":
            priority = "P0"
            action = "REVIEW_DISCOVERY_TIMESTAMP_INTEGRITY"
            freshness_state = "INVALID_TIME"
            age_hours = None
        else:
            priority = "P1"
            action = "REQUEST_DISCOVERY_REFRESH_REVIEW"
            freshness_state = "STALE"
            age_hours = 96.0
        tasks = [{
            "task_id": "b" * 64,
            "priority": priority,
            "reason_code": reason,
            "operator_action": action,
            "source_product": "PARTENER.EU",
            "source_role": "DISCOVERY_ONLY",
            "freshness_state": freshness_state,
            "age_hours": age_hours,
            "max_age_hours": 72,
            "official_authority_inferred": False,
            "external_action_authorized": False,
        }]
    return {
        "schema_version": 1,
        "engine_id": "EUCONS_E09_SOURCE_FRESHNESS_RECOVERY_QUEUE",
        "state": "READ_ONLY_SOURCE_FRESHNESS_RECOVERY",
        "read_only": True,
        "source_projection_sha256": SOURCE_SHA,
        "source_product": "PARTENER.EU",
        "source_role": "DISCOVERY_ONLY",
        "summary": {
            "freshness_state": freshness_state,
            "bridge_state": "STALE_SOURCE_HOLD" if held else "READY",
            "source_held": held,
            "recovery_tasks": len(tasks),
        },
        "tasks": tasks,
        "boundaries": {
            "network_fetch": False,
            "crm_write": False,
            "provider_write": False,
            "mysmis_write": False,
            "outreach": False,
            "message_send": False,
            "offer_send": False,
            "publication": False,
            "deployment": False,
        },
        "queue_id": "c" * 64,
    }


def official_task(opportunity_id: str, priority: str) -> dict:
    mapping = {
        "P0": ("BLOCKED_SOURCE_CONFLICT", "OFFICIAL_SOURCE_CONFLICT", "RESOLVE_OFFICIAL_SOURCE_CONFLICT"),
        "P1": ("WAITING_SOURCE", "REQUIRED_OFFICIAL_BINDING_MISSING", "VERIFY_REQUIRED_OFFICIAL_FACTS"),
        "P2": ("OFFICIAL_SOURCE_VERIFIED", "OPTIONAL_MATCHING_FACT_BINDINGS_INCOMPLETE", "ENRICH_OFFICIAL_MATERIAL_FACT_BINDINGS"),
    }
    authority_state, reason, action = mapping[priority]
    missing = ["deadline"] if priority == "P1" else []
    unbound = ["budget"] if priority == "P2" else []
    return {
        "opportunity_id": opportunity_id,
        "title": f"Opportunity {opportunity_id}",
        "programme": "TEST PROGRAMME",
        "priority": priority,
        "authority_state": authority_state,
        "reason_code": reason,
        "operator_action": action,
        "required_candidate_fact_classes": ["deadline", "status"],
        "verified_fact_classes": ["status"] if priority == "P1" else ["deadline", "status"],
        "missing_candidate_fact_classes": missing,
        "unbound_material_fact_classes": unbound,
        "official_source_count": 1,
        "discovery_context": {
            "source_product": "PARTENER.EU",
            "role": "DISCOVERY_ONLY",
            "source_as_of": "2026-08-29T10:00:00Z",
        },
        "external_action_authorized": False,
    }


def official_queue(tasks: list[dict], *, source_sha: str = SOURCE_SHA) -> dict:
    return {
        "schema_version": 1,
        "engine_id": "EUCONS_E10_OFFICIAL_SOURCE_OPERATOR_QUEUE",
        "state": "READ_ONLY_OPERATOR_QUEUE",
        "read_only": True,
        "source_projection_sha256": source_sha,
        "official_registry_state": "READ_ONLY_OFFICIAL_SOURCE_RECEIPTS",
        "summary": {
            "eligible_actionable_records": len(tasks),
            "operator_tasks": len(tasks),
            "blocked_conflicts": sum(1 for row in tasks if row["priority"] == "P0"),
            "waiting_required_bindings": sum(1 for row in tasks if row["priority"] == "P1"),
            "enrichment_bindings": sum(1 for row in tasks if row["priority"] == "P2"),
            "resolved_records_omitted": 0,
            "non_actionable_or_held_records_skipped": 0,
        },
        "tasks": tasks,
        "boundaries": {
            "network_fetch": False,
            "crm_write": False,
            "provider_write": False,
            "mysmis_write": False,
            "outreach": False,
            "message_send": False,
            "offer_send": False,
            "publication": False,
            "deployment": False,
        },
        "queue_id": "d" * 64,
    }


def main() -> None:
    engine = load_engine()
    contract = engine.load_json(CONTRACT_PATH)
    freshness_contract = engine.load_json(FRESHNESS_CONTRACT_PATH)
    official_contract = engine.load_json(OFFICIAL_CONTRACT_PATH)
    engine.validate_contract(contract, freshness_contract, official_contract)

    stale = freshness_queue(held=True)
    held_result = engine.build_unified_queue(stale, None, contract, freshness_contract, official_contract)
    assert held_result["state"] == "READ_ONLY_UNIFIED_SOURCE_WORK_QUEUE"
    assert held_result["summary"] == {
        "source_held": True,
        "operator_work_items": 1,
        "p0_items": 0,
        "p1_items": 1,
        "p2_items": 0,
        "discovery_source_items": 1,
        "official_authority_items": 0,
    }
    held_work = held_result["work_items"][0]
    assert held_work["domain"] == "DISCOVERY_SOURCE"
    assert held_work["priority"] == "P1"
    assert held_work["operator_action"] == "REQUEST_DISCOVERY_REFRESH_REVIEW"
    assert held_work["official_authority_inferred"] is False
    assert held_work["human_review_required"] is True
    assert held_result["official_queue_id"] is None
    assert held_result["official_registry_state"] == "NOT_EVALUATED_SOURCE_HELD"

    timestamp = engine.build_unified_queue(
        freshness_queue(held=True, reason="DISCOVERY_TIMESTAMP_INTEGRITY_HOLD"),
        None,
        contract,
        freshness_contract,
        official_contract,
    )
    assert timestamp["work_items"][0]["priority"] == "P0"
    assert timestamp["work_items"][0]["operator_action"] == "REVIEW_DISCOVERY_TIMESTAMP_INTEGRITY"

    ready = freshness_queue(held=False)
    authority = official_queue([
        official_task("OP-C", "P2"),
        official_task("OP-A", "P0"),
        official_task("OP-B", "P1"),
    ])
    ready_result = engine.build_unified_queue(ready, authority, contract, freshness_contract, official_contract)
    assert [row["opportunity_id"] for row in ready_result["work_items"]] == ["OP-A", "OP-B", "OP-C"]
    assert [row["priority"] for row in ready_result["work_items"]] == ["P0", "P1", "P2"]
    assert all(row["domain"] == "OFFICIAL_AUTHORITY" for row in ready_result["work_items"])
    assert all(row["source_role"] == "DISCOVERY_ONLY" for row in ready_result["work_items"])
    assert ready_result["summary"]["source_held"] is False
    assert ready_result["summary"]["official_authority_items"] == 3
    assert ready_result["freshness_queue_id"] == "c" * 64
    assert ready_result["official_queue_id"] == "d" * 64

    reversed_result = engine.build_unified_queue(
        copy.deepcopy(ready),
        official_queue(list(reversed(authority["tasks"]))),
        contract,
        freshness_contract,
        official_contract,
    )
    assert reversed_result["work_items"] == ready_result["work_items"]
    assert reversed_result["work_queue_id"] == ready_result["work_queue_id"]

    rendered = json.dumps(ready_result, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "material_facts",
        "verified_fact_hashes",
        "source_document_sha256",
        "source_url",
        "requested_grant_eur",
        "eligibility_conclusion",
        "award_probability",
    ):
        assert f'"{forbidden}"' not in rendered
    assert all(value is False for value in ready_result["boundaries"].values())

    must_fail(
        "official work while discovery held",
        lambda: engine.build_unified_queue(stale, authority, contract, freshness_contract, official_contract),
    )
    must_fail(
        "missing official queue when discovery ready",
        lambda: engine.build_unified_queue(ready, None, contract, freshness_contract, official_contract),
    )
    mismatch = official_queue([official_task("OP-X", "P1")], source_sha="e" * 64)
    must_fail(
        "parent source projection mismatch",
        lambda: engine.build_unified_queue(ready, mismatch, contract, freshness_contract, official_contract),
    )

    bad_freshness = freshness_queue(held=True)
    bad_freshness["source_role"] = "OFFICIAL_AUTHORITY"
    must_fail(
        "PARTENER authority promotion in freshness parent",
        lambda: engine.build_unified_queue(bad_freshness, None, contract, freshness_contract, official_contract),
    )

    bad_authority = official_queue([official_task("OP-Y", "P1")])
    bad_authority["tasks"][0]["discovery_context"]["role"] = "AUTHORITY"
    must_fail(
        "PARTENER authority promotion in official parent",
        lambda: engine.build_unified_queue(ready, bad_authority, contract, freshness_contract, official_contract),
    )

    bad_action = official_queue([official_task("OP-Z", "P0")])
    bad_action["tasks"][0]["operator_action"] = "AUTO_RESOLVE"
    must_fail(
        "official parent action drift",
        lambda: engine.build_unified_queue(ready, bad_action, contract, freshness_contract, official_contract),
    )

    bad_boundary = official_queue([official_task("OP-W", "P1")])
    bad_boundary["boundaries"]["crm_write"] = True
    must_fail(
        "parent CRM boundary",
        lambda: engine.build_unified_queue(ready, bad_boundary, contract, freshness_contract, official_contract),
    )

    drifted_contract = copy.deepcopy(contract)
    drifted_contract["input"]["required_source_role"] = "OFFICIAL_AUTHORITY"
    must_fail(
        "unified contract source role drift",
        lambda: engine.validate_contract(drifted_contract, freshness_contract, official_contract),
    )

    drifted_contract = copy.deepcopy(contract)
    drifted_contract["boundaries"]["network_fetch"] = True
    must_fail(
        "unified network boundary",
        lambda: engine.validate_contract(drifted_contract, freshness_contract, official_contract),
    )

    drifted_parent = copy.deepcopy(freshness_contract)
    drifted_parent["boundaries"]["network_fetch"] = True
    must_fail(
        "freshness parent network boundary",
        lambda: engine.validate_contract(contract, drifted_parent, official_contract),
    )

    with tempfile.TemporaryDirectory() as td:
        engine.ensure_output_outside_repo(Path(td) / "unified-source-work.json")
    must_fail(
        "repository output path",
        lambda: engine.ensure_output_outside_repo(ROOT / "eucons" / "opportunities" / "runtime-unified-source-work.json"),
    )

    print("PASS: unified source work queue serializes discovery recovery before official authority work without weakening fail-closed boundaries")


if __name__ == "__main__":
    main()
