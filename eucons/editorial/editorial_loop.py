#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "editorial" / "editorial_loop_contract.json"


class EditorialError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def editorial_id(record: dict[str, Any]) -> str:
    rid = str(record.get("id") or "").strip()
    return "EDT-" + hashlib.sha256(rid.encode("utf-8")).hexdigest()[:24]


def receipt_id(subject_id: str, content_hash: str, decision: str) -> str:
    basis = f"{subject_id}|{content_hash}|{decision}"
    return "RCP-E15-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


def duplicate_key(record: dict[str, Any]) -> str:
    return f"{str(record.get('type') or '').strip()}|{str(record.get('source_ref') or '').strip()}"


def fact_kernel(record: dict[str, Any]) -> dict[str, Any]:
    kernel = {
        "knowledge_id": record.get("id"),
        "type": record.get("type"),
        "source_ref": record.get("source_ref"),
        "semantics": record.get("semantics"),
        "provenance": copy.deepcopy(record.get("provenance") or {}),
    }
    if record.get("type") == "OPPORTUNITY":
        kernel["material_facts"] = copy.deepcopy(record.get("material_facts") or {})
        kernel["verified_fact_classes"] = copy.deepcopy(record.get("verified_fact_classes") or [])
    elif record.get("type") in {"GUIDE", "ANALYSIS", "FAQ"}:
        kernel["sections"] = copy.deepcopy(record.get("sections") or {})
        if record.get("type") == "ANALYSIS":
            kernel["analysis_label"] = record.get("analysis_label")
    elif record.get("type") == "CASE":
        kernel["claim_refs"] = copy.deepcopy((record.get("provenance") or {}).get("claim_refs") or [])
    kernel["content_hash"] = sha256_json(
        {
            "title": record.get("title"),
            "summary": record.get("summary"),
            "kernel": {k: v for k, v in kernel.items() if k != "content_hash"},
        }
    )
    return kernel


def qa_reasons(record: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    allowed_types = set(contract["input"]["allowed_types"])
    rid = str(record.get("id") or "").strip()
    rtype = str(record.get("type") or "").strip()
    source_ref = str(record.get("source_ref") or "").strip()
    title = str(record.get("title") or "").strip()
    summary = str(record.get("summary") or "").strip()
    provenance = record.get("provenance") or {}

    if record.get("publication_state") != contract["input"]["required_publication_state"]:
        reasons.append("INPUT_NOT_PUBLISHABLE")
    if not rid:
        reasons.append("MISSING_KNOWLEDGE_ID")
    if rtype not in allowed_types:
        reasons.append("UNKNOWN_TYPE")
    if not source_ref:
        reasons.append("MISSING_SOURCE_REF")
    if not title:
        reasons.append("MISSING_TITLE")
    if not summary:
        reasons.append("MISSING_SUMMARY")
    if contract["qa"]["provenance_required"] and not provenance:
        reasons.append("MISSING_PROVENANCE")

    if rtype in {"GUIDE", "FAQ"}:
        if record.get("semantics") != "CANONICAL_SERVICE_DESCRIPTION":
            reasons.append("INVALID_SERVICE_SEMANTICS")
        if provenance.get("source_kind") != "E02_SERVICE_REGISTRY":
            reasons.append("INVALID_SERVICE_PROVENANCE")
        if not provenance.get("claim_ids") or not provenance.get("evidence_ids"):
            reasons.append("MISSING_SERVICE_EVIDENCE")

    if rtype == "ANALYSIS":
        if record.get("semantics") != "OPERATIONAL_INTERPRETATION_NOT_FUNDING_FACT":
            reasons.append("INVALID_ANALYSIS_SEMANTICS")
        if contract["qa"]["analysis_label_required"] and not str(record.get("analysis_label") or "").strip():
            reasons.append("MISSING_ANALYSIS_LABEL")
        if provenance.get("source_kind") != "E02_SERVICE_REGISTRY":
            reasons.append("INVALID_ANALYSIS_PROVENANCE")
        if not provenance.get("claim_ids") or not provenance.get("evidence_ids"):
            reasons.append("MISSING_ANALYSIS_EVIDENCE")

    if rtype == "OPPORTUNITY":
        facts = record.get("material_facts") or {}
        verified = record.get("verified_fact_classes") or []
        if record.get("semantics") != "VERIFIED_FUNDING_FACTS_FROM_E09":
            reasons.append("INVALID_OPPORTUNITY_SEMANTICS")
        if not isinstance(facts, dict) or not facts:
            reasons.append("MISSING_MATERIAL_FACTS")
        if not isinstance(verified, list) or not verified:
            reasons.append("MISSING_VERIFIED_FACT_CLASSES")
        if provenance.get("source_product") != "PARTENER.EU":
            reasons.append("INVALID_OPPORTUNITY_SOURCE")
        if provenance.get("source_opportunity_id") != source_ref:
            reasons.append("OPPORTUNITY_PROVENANCE_MISMATCH")
        if not provenance.get("verification_evidence"):
            reasons.append("MISSING_OPPORTUNITY_EVIDENCE")

    if rtype == "CASE":
        if record.get("semantics") != "VERIFIED_CASE_REGISTRY":
            reasons.append("INVALID_CASE_SEMANTICS")
        if provenance.get("source_kind") != "E05_CASE_REGISTRY":
            reasons.append("INVALID_CASE_PROVENANCE")
        if not provenance.get("claim_refs"):
            reasons.append("MISSING_CASE_CLAIMS")

    return sorted(set(reasons))


def select_and_decide(knowledge: dict[str, Any], contract: dict[str, Any]) -> list[dict[str, Any]]:
    if knowledge.get("product") != contract["input"]["required_product"]:
        raise EditorialError("unknown knowledge product")
    if knowledge.get("engine_id") != contract["input"]["required_engine_id"]:
        raise EditorialError("unknown knowledge engine")
    if knowledge.get("runtime_publication_enabled") is not False:
        raise EditorialError("E15 requires E14 runtime publication disabled")

    records = list(knowledge.get("records") or [])
    priority = {name: index for index, name in enumerate(contract["selection"]["type_priority"])}
    ordered = sorted(
        records,
        key=lambda row: (
            priority.get(str(row.get("type") or ""), len(priority)),
            str(row.get("source_ref") or ""),
            str(row.get("id") or ""),
        ),
    )
    seen_keys: set[str] = set()
    ready_count = 0
    decisions: list[dict[str, Any]] = []
    max_candidates = int(contract["selection"]["max_ready_per_cycle"])

    for rank, record in enumerate(ordered, start=1):
        reasons = qa_reasons(record, contract)
        key = duplicate_key(record)
        if key in seen_keys:
            reasons.append("DUPLICATE_SOURCE_RECORD")
        else:
            seen_keys.add(key)

        if not reasons and ready_count >= max_candidates:
            reasons.append("CYCLE_CAPACITY_REACHED")

        decision = "HOLD" if reasons else "READY"
        if decision == "READY":
            ready_count += 1

        kernel = fact_kernel(record)
        decisions.append(
            {
                "editorial_id": editorial_id(record),
                "knowledge_id": record.get("id"),
                "type": record.get("type"),
                "source_ref": record.get("source_ref"),
                "rank": rank,
                "decision": decision,
                "hold_reasons": sorted(set(reasons)),
                "duplicate_key": key,
                "fact_kernel": kernel,
                "dispatch_state": "DISABLED_RUNTIME_GATE",
                "published": False,
            }
        )
    return decisions


def build_receipts(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    receipts = []
    for decision in decisions:
        body = {
            "schema_version": 1,
            "subject_id": decision["editorial_id"],
            "knowledge_id": decision["knowledge_id"],
            "content_hash": decision["fact_kernel"]["content_hash"],
            "decision": decision["decision"],
            "hold_reasons": decision["hold_reasons"],
            "dispatch_state": decision["dispatch_state"],
            "published": False,
        }
        body["receipt_id"] = receipt_id(body["subject_id"], body["content_hash"], body["decision"])
        body["receipt_hash"] = sha256_json(body)
        receipts.append(body)
    return receipts


def reconcile_receipts(current: list[dict[str, Any]], previous: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prev_by_subject: dict[str, dict[str, Any]] = {}
    for row in previous:
        subject = str(row.get("subject_id") or "").strip()
        if not subject or subject in prev_by_subject:
            raise EditorialError("previous receipts contain duplicate or missing subject_id")
        prev_by_subject[subject] = row

    current_by_subject: dict[str, dict[str, Any]] = {}
    reconciliation: list[dict[str, Any]] = []
    for row in current:
        subject = str(row.get("subject_id") or "").strip()
        if not subject or subject in current_by_subject:
            raise EditorialError("current receipts contain duplicate or missing subject_id")
        current_by_subject[subject] = row
        previous_row = prev_by_subject.get(subject)
        if previous_row is None:
            state = "NEW"
        elif (
            previous_row.get("content_hash") == row.get("content_hash")
            and previous_row.get("decision") == row.get("decision")
            and previous_row.get("dispatch_state") == row.get("dispatch_state")
        ):
            state = "UNCHANGED"
        else:
            state = "SUPERSEDED"
        reconciliation.append(
            {
                "subject_id": subject,
                "state": state,
                "current_receipt_id": row.get("receipt_id"),
                "previous_receipt_id": previous_row.get("receipt_id") if previous_row else None,
            }
        )

    for subject, previous_row in sorted(prev_by_subject.items()):
        if subject not in current_by_subject:
            reconciliation.append(
                {
                    "subject_id": subject,
                    "state": "WITHDRAWN",
                    "current_receipt_id": None,
                    "previous_receipt_id": previous_row.get("receipt_id"),
                }
            )
    return sorted(reconciliation, key=lambda row: (row["subject_id"], row["state"]))


def build_cycle(
    knowledge: dict[str, Any],
    contract: dict[str, Any],
    previous_receipts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    decisions = select_and_decide(knowledge, contract)
    receipts = build_receipts(decisions)
    reconciliation = reconcile_receipts(receipts, previous_receipts or [])
    return {
        "schema_version": contract["output"]["schema_version"],
        "product": contract["output"]["product"],
        "engine_id": contract["engine_id"],
        "runtime_publication_enabled": contract["output"]["runtime_publication_enabled"],
        "dispatch_enabled": contract["output"]["dispatch_enabled"],
        "summary": {
            "records_considered": len(decisions),
            "ready": sum(row["decision"] == "READY" for row in decisions),
            "held": sum(row["decision"] == "HOLD" for row in decisions),
            "published": 0,
            "new_receipts": sum(row["state"] == "NEW" for row in reconciliation),
            "unchanged_receipts": sum(row["state"] == "UNCHANGED" for row in reconciliation),
            "superseded_receipts": sum(row["state"] == "SUPERSEDED" for row in reconciliation),
            "withdrawn_receipts": sum(row["state"] == "WITHDRAWN" for row in reconciliation),
        },
        "decisions": decisions,
        "receipts": receipts,
        "reconciliation": reconciliation,
    }


def assert_output_path_safe(path: Path) -> None:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return
    raise EditorialError("runtime editorial output cannot be written under repository root")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--knowledge", required=True)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--previous-receipts", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    previous = []
    if args.previous_receipts:
        previous_payload = json.loads(Path(args.previous_receipts).read_text(encoding="utf-8"))
        if isinstance(previous_payload, dict):
            previous = list(previous_payload.get("receipts") or [])
        elif isinstance(previous_payload, list):
            previous = list(previous_payload)
        else:
            raise EditorialError("previous receipts payload must be object or list")

    result = build_cycle(load_json(Path(args.knowledge)), load_json(Path(args.contract)), previous)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        assert_output_path_safe(output)
        output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
