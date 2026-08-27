#!/usr/bin/env python3
"""Fail-closed canonical staging admission for reconciled EEA CSF Romania calls.

Consumes only a PASS reconciliation receipt, maps each exact official call to the
existing deterministic P11 candidate-staging contract, and emits an immutable
admission receipt. It never mutates opportunity_bundle.json, staging_candidates.json,
staging_ledger.json, or the public projection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from typing import Any

from candidate_staging import stage_candidates, validate_staging_ledger

SCHEMA = "PARTENER_EU_EEA_CSF_CANONICAL_STAGING_ADMISSION_V1"
INPUT_SCHEMA = "PARTENER_EU_EEA_CSF_RECONCILIATION_RECEIPT_V1"
PROGRAMME = "EEA Civil Society Fund Romania 2021-2028"
SOURCE_FAMILY = "EEA_NORWAY"
AUTHORITY_CLASS = "EEA_FMO_CIVIL_SOCIETY_FUND_ROMANIA"
EXPECTED_INPUT_MISSING_PROOFS = [
    "CANONICAL_STAGING_ADMISSION",
    "PUBLIC_PROJECTION_QUALITY_GATE",
]
OUTPUT_MISSING_PROOFS = ["PUBLIC_PROJECTION_QUALITY_GATE"]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _fail(message: str) -> None:
    raise ValueError(message)


def _candidate(record: dict[str, Any]) -> dict[str, Any]:
    facts = record.get("material_facts")
    if not isinstance(facts, dict):
        _fail(f"{record.get('call_identifier')}: material_facts missing")
    title = facts.get("title")
    if not isinstance(title, str) or not title.strip():
        _fail(f"{record.get('call_identifier')}: title missing")
    return {
        "source_url": record.get("authority_url"),
        "programme": PROGRAMME,
        "code": record.get("call_identifier"),
        "title": title.strip(),
        "source_id": record.get("authority_class"),
    }


def build_staging_admission(
    reconciliation: dict[str, Any],
    bundle: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(reconciliation, dict) or reconciliation.get("schema") != INPUT_SCHEMA:
        _fail(f"input schema must be {INPUT_SCHEMA}")
    if reconciliation.get("programme_family") != PROGRAMME:
        _fail("programme_family mismatch")
    if reconciliation.get("source_family") != SOURCE_FAMILY:
        _fail("source_family mismatch")
    if reconciliation.get("authority_class") != AUTHORITY_CLASS:
        _fail("authority_class mismatch")
    if reconciliation.get("publication_effect") != "NONE" or reconciliation.get("publish_authorized"):
        _fail("reconciliation receipt must remain non-publishing")
    if not reconciliation.get("material_fact_use") or not reconciliation.get("ready_for_staging"):
        _fail("reconciliation receipt is not staging-ready")
    stats = reconciliation.get("stats")
    records = reconciliation.get("records")
    if not isinstance(stats, dict) or not isinstance(records, list) or not records:
        _fail("reconciliation receipt missing stats/records")
    if stats.get("errors") or stats.get("conflicts"):
        _fail(f"reconciliation receipt contains errors/conflicts: {stats}")
    if stats.get("reconciled_calls") != len(records) or stats.get("material_fact_ready_for_staging") != len(records):
        _fail("reconciliation batch is incomplete")

    candidate_by_code: dict[str, dict[str, Any]] = {}
    record_by_code: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            _fail("reconciled call row must be object")
        code = record.get("call_identifier")
        if not isinstance(code, str) or not code or code in record_by_code:
            _fail(f"invalid/duplicate call identifier {code!r}")
        if record.get("programme_family") != PROGRAMME or record.get("source_family") != SOURCE_FAMILY or record.get("authority_class") != AUTHORITY_CLASS:
            _fail(f"{code}: authority/programme drift")
        if record.get("reconciliation_status") != "PASS" or not record.get("ready_for_staging") or not record.get("material_fact_use"):
            _fail(f"{code}: call did not pass reconciliation")
        if record.get("publish_authorized") or record.get("requires_reconcile"):
            _fail(f"{code}: unsafe publish/reconcile state")
        if record.get("missing_proofs") != EXPECTED_INPUT_MISSING_PROOFS:
            _fail(f"{code}: downstream proof contract drift")
        if not record.get("raw_hash") or not record.get("semantic_fingerprint") or not record.get("source_run_id") or not record.get("fetched_at"):
            _fail(f"{code}: provenance is incomplete")
        candidate = _candidate(record)
        candidate_by_code[code] = candidate
        record_by_code[code] = record

    observed_at = str(reconciliation.get("reconciled_at") or reconciliation.get("source_fetched_at") or "")
    if not observed_at:
        _fail("reconciliation timestamp missing")
    ledger = stage_candidates(bundle, candidate_by_code.values(), observed_at)
    validate_staging_ledger(ledger)
    if ledger.get("summary", {}).get("unique_candidates") != len(records):
        _fail("candidate staging did not preserve one deterministic identity per reconciled call")
    if ledger.get("summary", {}).get("ambiguous_review"):
        _fail("ambiguous canonical identity blocks staging admission")
    if ledger.get("summary", {}).get("published") != 0:
        _fail("candidate staging attempted publication")

    staged_by_code: dict[str, dict[str, Any]] = {}
    for row in ledger["rows"]:
        programme_code = str((row.get("identity_keys") or {}).get("programme_code") or "")
        matches = [code for code in record_by_code if programme_code.endswith("|" + code.lower().replace("-", " "))]
        if len(matches) != 1:
            # candidate_staging normalizes punctuation to spaces; compare against the same normalized form indirectly.
            for code, candidate in candidate_by_code.items():
                expected = stage_candidates({"opportunities": [], "evidence": []}, [candidate], observed_at)["rows"][0]["candidate_id"]
                if expected == row.get("candidate_id"):
                    matches = [code]
                    break
        if len(matches) != 1:
            _fail(f"cannot bind staged candidate to reconciled call: {row.get('candidate_id')}")
        code = matches[0]
        if code in staged_by_code:
            _fail(f"duplicate staged binding for {code}")
        staged_by_code[code] = row

    admitted_records: list[dict[str, Any]] = []
    for code in sorted(record_by_code):
        source = record_by_code[code]
        staged = staged_by_code.get(code)
        if not staged:
            _fail(f"{code}: staging row missing")
        if staged.get("disposition") not in {"NEW_CANDIDATE", "CANONICAL_MATCH"}:
            _fail(f"{code}: unsafe staging disposition {staged.get('disposition')}")
        admitted_records.append({
            "call_identifier": code,
            "candidate_id": staged.get("candidate_id"),
            "staging_disposition": staged.get("disposition"),
            "canonical_match_id": staged.get("canonical_match_id"),
            "identity_keys": staged.get("identity_keys"),
            "authority_url": source.get("authority_url"),
            "source_run_id": source.get("source_run_id"),
            "fetched_at": source.get("fetched_at"),
            "raw_hash": source.get("raw_hash"),
            "semantic_fingerprint": source.get("semantic_fingerprint"),
            "material_facts_sha256": _sha256(source.get("material_facts")),
            "staging_admission": "PASS",
            "material_fact_use": True,
            "canonical_corpus_mutation": False,
            "publish_authorized": False,
            "material_fact_action": "NONE",
            "missing_proofs": OUTPUT_MISSING_PROOFS,
        })

    return {
        "schema": SCHEMA,
        "source_reconciliation_schema": INPUT_SCHEMA,
        "source_reconciliation_hash": _sha256(reconciliation),
        "source_evidence_hash": reconciliation.get("source_evidence_hash"),
        "source_run_id": reconciliation.get("source_run_id"),
        "source_fetched_at": reconciliation.get("source_fetched_at"),
        "reconciled_at": reconciliation.get("reconciled_at"),
        "programme_family": PROGRAMME,
        "source_family": SOURCE_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "p11_staging_ledger_sha256": ledger.get("ledger_sha256"),
        "records": admitted_records,
        "stats": {
            "reconciled_calls": len(records),
            "staging_admitted": len(admitted_records),
            "new_candidates": ledger["summary"]["new_candidates"],
            "canonical_matches": ledger["summary"]["canonical_matches"],
            "ambiguous_review": 0,
            "errors": 0,
            "conflicts": 0,
        },
        "canonical_staging_admission": "PASS",
        "material_fact_use": True,
        "canonical_corpus_mutation": False,
        "publish_authorized": False,
        "publication_effect": "NONE",
        "material_fact_action": "NONE",
        "missing_proofs": OUTPUT_MISSING_PROOFS,
        "rollback": "Discard this admission receipt; P11 canonical corpus, staging files, and public projection remain unchanged.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reconciliation", type=pathlib.Path)
    parser.add_argument("--bundle", type=pathlib.Path, default=pathlib.Path(__file__).with_name("opportunity_bundle.json"))
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    reconciliation = json.loads(args.reconciliation.read_text(encoding="utf-8"))
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    receipt = build_staging_admission(reconciliation, bundle)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "staging_admitted": receipt["stats"]["staging_admitted"],
        "new_candidates": receipt["stats"]["new_candidates"],
        "canonical_matches": receipt["stats"]["canonical_matches"],
        "publish_authorized": receipt["publish_authorized"],
        "publication_effect": receipt["publication_effect"],
        "missing_proofs": receipt["missing_proofs"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
