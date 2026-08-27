#!/usr/bin/env python3
"""Fail-closed canonical staging admission for reconciled Funding & Tenders direct calls.

Consumes only staging-ready direct-call rows from the Funding & Tenders semantic
reconciliation receipt, maps them into the existing deterministic P11 candidate
staging contract, and emits an immutable admission receipt. Portal-only/cascade
rows remain quarantined and are never staged by this adapter.

This adapter never mutates opportunity_bundle.json, staging_candidates.json,
staging_ledger.json, or the public projection. Programme reference codes remain
provenance only; no human programme label is inferred from topic identifiers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from typing import Any

from candidate_staging import stage_candidates, validate_staging_ledger

SCHEMA = "PARTENER_EU_FUNDING_TENDERS_CANONICAL_STAGING_ADMISSION_V1"
INPUT_SCHEMA = "PARTENER_EU_FUNDING_TENDERS_RECONCILIATION_RECEIPT_V1"
SOURCE_FAMILY = "EU_DIRECT"
PROGRAMME_FAMILY = "BRUSSELS"
AUTHORITY_CLASS = "EU_COMMISSION_FUNDING_TENDERS"
# Machine-facing holding identity only. A programme reference is preserved separately
# and cannot become a public programme label before an authoritative resolution gate.
STAGING_PROGRAMME = "EU_DIRECT::FUNDING_TENDERS"
DIRECT_CALL_TYPES = {"1", "2"}
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
    identifier = record.get("identifier")
    if not isinstance(identifier, str) or not identifier.strip():
        _fail("staging-ready Funding & Tenders row is missing exact identifier")
    facts = record.get("material_facts")
    if not isinstance(facts, dict):
        _fail(f"{identifier}: material_facts missing")
    title = facts.get("title")
    if not isinstance(title, str) or not title.strip():
        _fail(f"{identifier}: title missing")
    source_url = record.get("authority_url")
    if not isinstance(source_url, str) or not source_url.startswith("https://ec.europa.eu/"):
        _fail(f"{identifier}: official EC authority URL missing")
    return {
        "source_url": source_url,
        "programme": STAGING_PROGRAMME,
        "code": identifier.strip(),
        "title": title.strip(),
        "source_id": AUTHORITY_CLASS,
    }


def _validate_quarantine(rows: Any) -> list[dict[str, Any]]:
    if rows is None:
        return []
    if not isinstance(rows, list):
        _fail("quarantined_records must be a list")
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            _fail("quarantined Funding & Tenders row must be an object")
        identifier = row.get("identifier")
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            _fail(f"invalid/duplicate quarantined identifier {identifier!r}")
        seen.add(identifier)
        if row.get("ready_for_staging") or row.get("material_fact_use") or row.get("publish_authorized"):
            _fail(f"{identifier}: quarantined row became authorizing")
        if row.get("reconciliation_status") != "REVIEW_REQUIRED":
            _fail(f"{identifier}: quarantined row must remain REVIEW_REQUIRED")
        reasons = row.get("reasons")
        if not isinstance(reasons, list) or not reasons:
            _fail(f"{identifier}: quarantine reasons missing")
        out.append(row)
    return out


def build_staging_admission(
    reconciliation: dict[str, Any],
    bundle: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(reconciliation, dict) or reconciliation.get("schema") != INPUT_SCHEMA:
        _fail(f"input schema must be {INPUT_SCHEMA}")
    if reconciliation.get("source_family") != SOURCE_FAMILY:
        _fail("source_family mismatch")
    if reconciliation.get("programme_family") != PROGRAMME_FAMILY:
        _fail("programme_family mismatch")
    if reconciliation.get("authority_class") != AUTHORITY_CLASS:
        _fail("authority_class mismatch")
    if reconciliation.get("publication_effect") != "NONE" or reconciliation.get("publish_authorized"):
        _fail("reconciliation receipt must remain non-publishing")
    if reconciliation.get("canonical_corpus_mutation") or reconciliation.get("material_fact_action") != "NONE":
        _fail("reconciliation receipt attempted canonical mutation/material action")
    if not reconciliation.get("material_fact_use") or not reconciliation.get("ready_for_staging"):
        _fail("reconciliation receipt has no staging-ready direct calls")
    if reconciliation.get("missing_proofs") != EXPECTED_INPUT_MISSING_PROOFS:
        _fail("receipt downstream proof contract drift")

    stats = reconciliation.get("stats")
    records = reconciliation.get("records")
    if not isinstance(stats, dict) or not isinstance(records, list) or not records:
        _fail("reconciliation receipt missing stats/staging-ready records")
    quarantined = _validate_quarantine(reconciliation.get("quarantined_records"))
    if stats.get("ready_for_staging") != len(records):
        _fail("ready_for_staging stats mismatch")
    if stats.get("review_required") != len(quarantined):
        _fail("review_required stats mismatch")
    if stats.get("normalized_records") != len(records) + len(quarantined):
        _fail("normalized_records stats mismatch")

    candidate_by_id: dict[str, dict[str, Any]] = {}
    source_by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            _fail("staging-ready Funding & Tenders row must be an object")
        identifier = record.get("identifier")
        if not isinstance(identifier, str) or not identifier or identifier in source_by_id:
            _fail(f"invalid/duplicate staging-ready identifier {identifier!r}")
        if record.get("reconciliation_status") != "PASS" or not record.get("ready_for_staging") or not record.get("material_fact_use"):
            _fail(f"{identifier}: row did not pass reconciliation")
        if record.get("publish_authorized") or record.get("canonical_corpus_mutation"):
            _fail(f"{identifier}: unsafe publish/corpus state")
        if record.get("material_fact_action") != "NONE" or record.get("publication_effect") != "NONE":
            _fail(f"{identifier}: material/publication action must remain NONE")
        if record.get("missing_proofs") != EXPECTED_INPUT_MISSING_PROOFS:
            _fail(f"{identifier}: downstream proof contract drift")
        raw_types = record.get("raw_search_types")
        if not isinstance(raw_types, list) or not raw_types or not set(map(str, raw_types)) <= DIRECT_CALL_TYPES:
            _fail(f"{identifier}: non-direct Search type reached staging")
        if record.get("observation_state") not in {"OPEN_CALL", "FORTHCOMING_CALL"}:
            _fail(f"{identifier}: unresolved/non-material observation state")
        if not record.get("source_run_id") or not record.get("fetched_at") or not record.get("raw_hash") or not record.get("semantic_fingerprint"):
            _fail(f"{identifier}: provenance is incomplete")
        candidate = _candidate(record)
        candidate_by_id[identifier] = candidate
        source_by_id[identifier] = record

    quarantine_ids = {str(row.get("identifier")) for row in quarantined}
    overlap = quarantine_ids.intersection(source_by_id)
    if overlap:
        _fail(f"identifier appears in ready and quarantine sets: {sorted(overlap)}")

    observed_at = str(reconciliation.get("reconciled_at") or reconciliation.get("source_fetched_at") or "")
    if not observed_at:
        _fail("reconciliation timestamp missing")
    ledger = stage_candidates(bundle, candidate_by_id.values(), observed_at)
    validate_staging_ledger(ledger)
    summary = ledger.get("summary") or {}
    if summary.get("unique_candidates") != len(records):
        _fail("candidate staging did not preserve one deterministic identity per direct call")
    if summary.get("ambiguous_review"):
        _fail("ambiguous canonical identity blocks staging admission")
    if summary.get("published") != 0:
        _fail("candidate staging attempted publication")

    rows_by_candidate_id = {
        str(row.get("candidate_id")): row
        for row in ledger.get("rows") or []
        if isinstance(row, dict) and row.get("candidate_id")
    }
    staged_by_identifier: dict[str, dict[str, Any]] = {}
    for identifier, candidate in candidate_by_id.items():
        expected = stage_candidates({"opportunities": [], "evidence": []}, [candidate], observed_at)["rows"][0]["candidate_id"]
        staged = rows_by_candidate_id.get(expected)
        if not staged:
            _fail(f"{identifier}: deterministic staging row missing")
        staged_by_identifier[identifier] = staged

    admitted: list[dict[str, Any]] = []
    for identifier in sorted(source_by_id):
        source = source_by_id[identifier]
        staged = staged_by_identifier[identifier]
        if staged.get("disposition") not in {"NEW_CANDIDATE", "CANONICAL_MATCH"}:
            _fail(f"{identifier}: unsafe staging disposition {staged.get('disposition')}")
        admitted.append({
            "identifier": identifier,
            "call_identifier": source.get("call_identifier"),
            "programme_reference": source.get("programme_reference"),
            "programme_label_authorized": False,
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
            "publication_effect": "NONE",
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
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "staging_programme_identity": STAGING_PROGRAMME,
        "programme_label_authorized": False,
        "p11_staging_ledger_sha256": ledger.get("ledger_sha256"),
        "records": admitted,
        "quarantined_identifiers_preserved": sorted(quarantine_ids),
        "stats": {
            "reconciled_ready": len(records),
            "staging_admitted": len(admitted),
            "review_required_preserved": len(quarantined),
            "new_candidates": summary.get("new_candidates", 0),
            "canonical_matches": summary.get("canonical_matches", 0),
            "ambiguous_review": 0,
            "admission_errors": 0,
        },
        "canonical_staging_admission": "PASS",
        "material_fact_use": True,
        "canonical_corpus_mutation": False,
        "publish_authorized": False,
        "publication_effect": "NONE",
        "material_fact_action": "NONE",
        "missing_proofs": OUTPUT_MISSING_PROOFS,
        "rollback": "Discard this admission receipt; P11 canonical corpus, tracked staging files, and public projection remain unchanged.",
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
        "review_required_preserved": receipt["stats"]["review_required_preserved"],
        "new_candidates": receipt["stats"]["new_candidates"],
        "canonical_matches": receipt["stats"]["canonical_matches"],
        "programme_label_authorized": receipt["programme_label_authorized"],
        "publish_authorized": receipt["publish_authorized"],
        "publication_effect": receipt["publication_effect"],
        "missing_proofs": receipt["missing_proofs"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
