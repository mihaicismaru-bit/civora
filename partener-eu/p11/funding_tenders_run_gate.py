#!/usr/bin/env python3
"""Classify Funding & Tenders reconciliation receipts for workflow orchestration."""
from __future__ import annotations
import json
from pathlib import Path

INPUT_SCHEMA = "PARTENER_EU_FUNDING_TENDERS_RECONCILIATION_RECEIPT_V1"

def classify_reconciliation(receipt):
    if not isinstance(receipt, dict) or receipt.get("schema") != INPUT_SCHEMA:
        raise ValueError("input schema mismatch")
    if receipt.get("publication_effect") != "NONE" or receipt.get("publish_authorized"):
        raise ValueError("receipt must remain non-publishing")
    if receipt.get("canonical_corpus_mutation") or receipt.get("material_fact_action") != "NONE":
        raise ValueError("receipt attempted canonical mutation/material action")
    records = receipt.get("records")
    quarantined = receipt.get("quarantined_records")
    stats = receipt.get("stats")
    if not isinstance(records, list) or not isinstance(quarantined, list) or not isinstance(stats, dict):
        raise ValueError("receipt missing records/quarantine/stats")
    if stats.get("ready_for_staging") != len(records):
        raise ValueError("ready_for_staging stats mismatch")
    if stats.get("review_required") != len(quarantined):
        raise ValueError("review_required stats mismatch")
    if stats.get("normalized_records") != len(records) + len(quarantined):
        raise ValueError("normalized_records stats mismatch")
    for row in quarantined:
        if row.get("reconciliation_status") != "REVIEW_REQUIRED":
            raise ValueError("quarantined row must remain REVIEW_REQUIRED")
        if row.get("ready_for_staging") or row.get("material_fact_use") or row.get("publish_authorized"):
            raise ValueError("quarantined row became authorizing")
        if not row.get("reasons"):
            raise ValueError("quarantined row must preserve reasons")
    if records:
        if not receipt.get("ready_for_staging") or not receipt.get("material_fact_use"):
            raise ValueError("staging-ready rows exist but receipt-level authorization is missing")
        return {"ready": True, "mode": "READY", "ready_for_staging": len(records), "review_required": len(quarantined)}
    if receipt.get("ready_for_staging") or receipt.get("material_fact_use"):
        raise ValueError("zero-ready receipt cannot authorize staging/material facts")
    if receipt.get("missing_proofs") not in ([], None):
        raise ValueError("zero-ready receipt cannot advertise downstream proofs")
    return {"ready": False, "mode": "NO_DIRECT_CALLS_FAIL_CLOSED", "ready_for_staging": 0, "review_required": len(quarantined)}

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = classify_reconciliation(json.loads(args.receipt.read_text(encoding="utf-8")))
    if args.output:
        args.output.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
