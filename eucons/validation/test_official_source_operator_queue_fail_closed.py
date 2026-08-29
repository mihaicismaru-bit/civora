#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUEUE_PATH = ROOT / "eucons" / "opportunities" / "official_source_operator_queue.py"
MATCHING_PATH = ROOT / "eucons" / "opportunities" / "match_opportunities.py"
QUEUE_CONTRACT_PATH = ROOT / "eucons" / "opportunities" / "official_source_operator_queue_contract.json"
MATCHING_CONTRACT_PATH = ROOT / "eucons" / "opportunities" / "matching_contract.json"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


queue = load_module(QUEUE_PATH, "eucons_official_source_operator_queue")
matching = load_module(MATCHING_PATH, "eucons_match_opportunities_for_queue_test")
QUEUE_CONTRACT = json.loads(QUEUE_CONTRACT_PATH.read_text(encoding="utf-8"))
MATCHING_CONTRACT = json.loads(MATCHING_CONTRACT_PATH.read_text(encoding="utf-8"))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record(opportunity_id: str, *, actionable: bool = True) -> dict:
    return {
        "id": opportunity_id,
        "title": f"Opportunity {opportunity_id}",
        "programme": "TEST PROGRAMME",
        "commercial_state": "VERIFIED_AVAILABLE",
        "actionable": actionable,
        "material_facts": {
            "status": {"value": "OPEN"},
            "deadline": {"value": "2026-10-01"},
            "budget": {"value": 1000000},
        },
        "provenance": {
            "source_product": "PARTENER.EU",
            "source_as_of": "2026-08-29T05:00:00Z",
        },
    }


def projection(rows: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "product": "EUCONS_COMMERCIAL_OS",
        "bridge_id": "PARTENER_P11_TO_EUCONS_E09",
        "generated_at": "2026-08-29T05:01:00Z",
        "bridge_state": "READY",
        "read_only": True,
        "source_mutation_allowed": False,
        "source": {
            "product": "PARTENER.EU",
            "path": "partener-eu/web/p11-public-data.js",
            "schema_version": 1,
            "as_of": "2026-08-29T05:00:00Z",
            "sha256": "a" * 64,
            "policy_accepted": True,
        },
        "freshness": {"state": "FRESH"},
        "summary": {},
        "opportunities": rows,
    }


def receipt(op: dict, fact_classes: list[str], *, state: str = "VERIFIED_OFFICIAL_SOURCE", product: str = "MIPE") -> dict:
    hashes = {fact: matching.canonical_hash(op["material_facts"][fact]) for fact in fact_classes}
    return {
        "receipt_id": sha(op["id"] + state + product + ",".join(fact_classes)),
        "opportunity_id": op["id"],
        "verification_state": state,
        "verification_method": "OFFICIAL_SOURCE_READBACK",
        "source_product": product,
        "source_authority": "OFFICIAL TEST AUTHORITY",
        "source_url": f"https://official.example/{op['id']}",
        "source_document_sha256": sha("document-" + op["id"] + product),
        "verified_at": "2026-08-29T05:00:00Z",
        "verified_fact_hashes": hashes,
    }


def registry(receipts: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "state": "READ_ONLY_OFFICIAL_SOURCE_RECEIPTS",
        "receipts": receipts,
    }


def must_fail(label: str, fn) -> None:
    try:
        fn()
    except ValueError:
        return
    raise AssertionError(f"{label} failed open")


def main() -> None:
    waiting = record("OP-A")
    enrich = record("OP-B")
    blocked = record("OP-C")
    resolved = record("OP-D")
    skipped = record("OP-E", actionable=False)

    receipts = [
        receipt(waiting, ["status"]),
        receipt(enrich, ["status", "deadline"]),
        receipt(blocked, [], state="BLOCKED_SOURCE_CONFLICT"),
        receipt(resolved, ["status", "deadline", "budget"]),
    ]
    source_projection = projection([enrich, skipped, resolved, waiting, blocked])
    result = queue.build_queue(source_projection, registry(receipts), QUEUE_CONTRACT, MATCHING_CONTRACT)

    assert result["state"] == "READ_ONLY_OPERATOR_QUEUE"
    assert result["read_only"] is True
    assert [row["opportunity_id"] for row in result["tasks"]] == ["OP-C", "OP-A", "OP-B"]
    assert [row["priority"] for row in result["tasks"]] == ["P0", "P1", "P2"]
    assert result["tasks"][0]["operator_action"] == "RESOLVE_OFFICIAL_SOURCE_CONFLICT"
    assert result["tasks"][1]["missing_candidate_fact_classes"] == ["deadline"]
    assert result["tasks"][2]["missing_candidate_fact_classes"] == []
    assert result["tasks"][2]["unbound_material_fact_classes"] == ["budget"]
    assert result["summary"] == {
        "eligible_actionable_records": 4,
        "operator_tasks": 3,
        "blocked_conflicts": 1,
        "waiting_required_bindings": 1,
        "enrichment_bindings": 1,
        "resolved_records_omitted": 1,
        "non_actionable_or_held_records_skipped": 1,
    }
    assert all(value is False for value in result["boundaries"].values())
    rendered = json.dumps(result, ensure_ascii=False, sort_keys=True)
    for forbidden in ("material_facts", "verified_fact_hashes", "source_document_sha256", "requested_grant_eur", "eligibility_conclusion", "award_probability"):
        assert f'"{forbidden}"' not in rendered

    reversed_result = queue.build_queue(
        projection(list(reversed(source_projection["opportunities"]))),
        registry(list(reversed(receipts))),
        QUEUE_CONTRACT,
        MATCHING_CONTRACT,
    )
    assert reversed_result["tasks"] == result["tasks"]
    assert reversed_result["queue_id"] == result["queue_id"]

    absent = queue.build_queue(projection([record("OP-Z")]), None, QUEUE_CONTRACT, MATCHING_CONTRACT)
    assert absent["official_registry_state"] == "ABSENT"
    assert absent["tasks"][0]["authority_state"] == "WAITING_SOURCE"
    assert absent["tasks"][0]["missing_candidate_fact_classes"] == ["deadline", "status"]

    mismatch_op = record("OP-M")
    mismatch_receipt = receipt(mismatch_op, ["status", "deadline"])
    mismatch_receipt["verified_fact_hashes"]["deadline"] = "f" * 64
    mismatch = queue.build_queue(
        projection([mismatch_op]), registry([mismatch_receipt]), QUEUE_CONTRACT, MATCHING_CONTRACT
    )
    assert mismatch["tasks"][0]["priority"] == "P0"
    assert mismatch["tasks"][0]["authority_state"] == "BLOCKED_SOURCE_CONFLICT"

    partner_receipt = receipt(record("OP-P"), ["status", "deadline"], product="PARTENER.EU")
    must_fail(
        "PARTENER official authority",
        lambda: queue.build_queue(projection([record("OP-P")]), registry([partner_receipt]), QUEUE_CONTRACT, MATCHING_CONTRACT),
    )

    stale_projection = projection([record("OP-S")])
    stale_projection["bridge_state"] = "STALE_SOURCE_HOLD"
    must_fail(
        "stale discovery projection",
        lambda: queue.build_queue(stale_projection, None, QUEUE_CONTRACT, MATCHING_CONTRACT),
    )

    mutated_projection = projection([record("OP-X")])
    mutated_projection["source_mutation_allowed"] = True
    must_fail(
        "source mutation enabled",
        lambda: queue.build_queue(mutated_projection, None, QUEUE_CONTRACT, MATCHING_CONTRACT),
    )

    drifted_contract = copy.deepcopy(QUEUE_CONTRACT)
    drifted_contract["boundaries"]["crm_write"] = True
    must_fail(
        "CRM write boundary",
        lambda: queue.build_queue(projection([record("OP-Y")]), None, drifted_contract, MATCHING_CONTRACT),
    )

    drifted_matching = copy.deepcopy(MATCHING_CONTRACT)
    drifted_matching["official_source_guards"]["partener_role"] = "AUTHORITY"
    must_fail(
        "PARTENER matching authority drift",
        lambda: queue.build_queue(projection([record("OP-Q")]), None, QUEUE_CONTRACT, drifted_matching),
    )

    with tempfile.TemporaryDirectory() as td:
        outside = Path(td) / "queue.json"
        queue.ensure_output_outside_repo(outside)
    must_fail(
        "repository output path",
        lambda: queue.ensure_output_outside_repo(ROOT / "eucons" / "opportunities" / "runtime-queue.json"),
    )

    print("PASS: official-source operator queue prioritizes conflicts, required bindings and enrichment without leaking material facts")


if __name__ == "__main__":
    main()
