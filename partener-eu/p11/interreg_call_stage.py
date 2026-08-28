#!/usr/bin/env python3
"""Fail-closed canonical staging admission for reconciled INTERREG_CALL_V1 rows.

Consumes only the semantic reconciliation receipt. This adapter never parses web
pages, never mutates the canonical opportunity bundle/staging ledger, and never
publishes. It preserves upstream quarantine, deduplicates exact call identities by
(call identifier, programme, authority URL), and blocks semantic drift before
mapping eligible observations into the existing deterministic P11 candidate
staging contract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
from typing import Any

from candidate_staging import normalize_url, stage_candidates, validate_staging_ledger

SCHEMA = "PARTENER_EU_INTERREG_CALL_CANONICAL_STAGING_ADMISSION_V1"
INPUT_SCHEMA = "PARTENER_EU_INTERREG_CALL_RECONCILIATION_RECEIPT_V1"
SOURCE_FAMILY = "INTERREG"
AUTHORITY_CLASS = "OFFICIAL_INTERREG_PROGRAMME_AUTHORITY"
ADMISSIBLE_STATES = {"OPEN_CALL", "FORTHCOMING_CALL"}
EXPECTED_INPUT_MISSING_PROOFS = ["CANONICAL_STAGING_ADMISSION", "PUBLIC_PROJECTION_QUALITY_GATE"]
OUTPUT_MISSING_PROOFS = ["PUBLIC_PROJECTION_QUALITY_GATE"]
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _fail(message: str) -> None:
    raise ValueError(message)


def _text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        _fail(f"{field} required")
    return text


def _identity_payload(record: dict[str, Any]) -> dict[str, str]:
    return {
        "call_identifier": _text(record.get("call_identifier"), "call_identifier"),
        "programme": _text(record.get("programme"), "programme"),
        "authority_url": normalize_url(_text(record.get("authority_url"), "authority_url")),
    }


def _validate_quarantine(rows: Any) -> list[dict[str, Any]]:
    if rows is None:
        return []
    if not isinstance(rows, list):
        _fail("quarantined_records must be a list")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            _fail("quarantined Interreg row must be an object")
        probe_id = str(row.get("probe_id") or f"row-{index}")
        stable_key = f"{probe_id}|{row.get('call_identifier')}|{row.get('authority_url')}"
        if stable_key in seen:
            _fail(f"duplicate quarantined row {probe_id}")
        seen.add(stable_key)
        if row.get("reconciliation_status") != "REVIEW_REQUIRED" or row.get("ready_for_staging"):
            _fail(f"{probe_id}: quarantined row escaped review")
        if row.get("material_fact_use") or row.get("publish_authorized") or row.get("canonical_corpus_mutation"):
            _fail(f"{probe_id}: quarantined row became authorizing")
        if row.get("publication_effect") != "NONE" or row.get("material_fact_action") != "NONE":
            _fail(f"{probe_id}: quarantined row attempted material/publication action")
        reasons = row.get("reasons")
        if not isinstance(reasons, list) or not reasons:
            _fail(f"{probe_id}: quarantine reasons missing")
        out.append(row)
    return out


def _validate_ready(record: dict[str, Any]) -> tuple[str, str, dict[str, str]]:
    call_id = _text(record.get("call_identifier"), "call_identifier")
    programme = _text(record.get("programme"), f"{call_id}.programme")
    if record.get("reconciliation_status") != "PASS" or record.get("ready_for_staging") is not True:
        _fail(f"{call_id}: row did not pass semantic reconciliation")
    if record.get("material_fact_use") is not True:
        _fail(f"{call_id}: reconciled material facts are not staging-eligible")
    if record.get("publish_authorized") or record.get("canonical_corpus_mutation"):
        _fail(f"{call_id}: unsafe publish/corpus state")
    if record.get("publication_effect") != "NONE" or record.get("material_fact_action") != "NONE":
        _fail(f"{call_id}: material/publication action must remain NONE")
    if record.get("missing_proofs") != EXPECTED_INPUT_MISSING_PROOFS:
        _fail(f"{call_id}: downstream proof contract drift")
    state = record.get("observation_state")
    if state not in ADMISSIBLE_STATES:
        _fail(f"{call_id}: non-admissible observation state reached staging")

    authority_url = _text(record.get("authority_url"), f"{call_id}.authority_url")
    if not authority_url.startswith("https://") or normalize_url(authority_url) != authority_url.rstrip("/"):
        _fail(f"{call_id}: authority URL is not canonical HTTPS")
    for field in ("source_run_id", "fetched_at", "raw_hash", "semantic_fingerprint", "identity_fingerprint"):
        value = _text(record.get(field), f"{call_id}.{field}")
        if field in {"raw_hash", "semantic_fingerprint", "identity_fingerprint"} and not HEX64_RE.fullmatch(value):
            _fail(f"{call_id}: {field} must be sha256")

    identity = _identity_payload(record)
    if _sha256(identity) != record.get("identity_fingerprint"):
        _fail(f"{call_id}: identity fingerprint drift before staging")

    facts = record.get("material_facts")
    if not isinstance(facts, dict):
        _fail(f"{call_id}: material_facts missing")
    expected_status = "OPEN" if state == "OPEN_CALL" else "FORTHCOMING"
    expected = {
        "call_identifier": call_id,
        "programme": programme,
        "title": _text(record.get("title"), f"{call_id}.title"),
        "status": expected_status,
        "deadline": record.get("deadline"),
        "authority_url": authority_url,
    }
    if facts != expected:
        _fail(f"{call_id}: material_facts drift from reconciled observation")
    return call_id, programme, identity


def build_staging_admission(reconciliation: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(reconciliation, dict) or reconciliation.get("schema") != INPUT_SCHEMA:
        _fail(f"input schema must be {INPUT_SCHEMA}")
    if reconciliation.get("source_family") != SOURCE_FAMILY or reconciliation.get("authority_class") != AUTHORITY_CLASS:
        _fail("source/authority mismatch")
    if reconciliation.get("publish_authorized") is not False or reconciliation.get("canonical_corpus_mutation") is not False:
        _fail("reconciliation receipt must remain non-publishing")
    if reconciliation.get("publication_effect") != "NONE" or reconciliation.get("material_fact_action") != "NONE":
        _fail("reconciliation receipt attempted material/publication action")

    records = reconciliation.get("records")
    stats = reconciliation.get("stats")
    if not isinstance(records, list) or not isinstance(stats, dict):
        _fail("reconciliation receipt missing records/stats")
    quarantined = _validate_quarantine(reconciliation.get("quarantined_records"))
    if stats.get("ready_for_staging") != len(records):
        _fail("ready_for_staging stats mismatch")
    if stats.get("review_required") != len(quarantined):
        _fail("review_required stats mismatch")
    if stats.get("input_rows") != len(records) + len(quarantined):
        _fail("input_rows stats mismatch")

    has_ready = bool(records)
    if reconciliation.get("ready_for_staging") is not has_ready or reconciliation.get("material_fact_use") is not has_ready:
        _fail("receipt ready/material flags drift from record set")
    expected_missing = EXPECTED_INPUT_MISSING_PROOFS if has_ready else []
    if reconciliation.get("missing_proofs") != expected_missing:
        _fail("receipt downstream proof contract drift")

    # Fail if the same exact call identity carries multiple semantic fingerprints.
    # Identical repeat observations collapse deterministically before P11 staging.
    by_identity: dict[str, dict[str, Any]] = {}
    semantic_by_identity: dict[str, str] = {}
    occurrences_by_identity: dict[str, int] = {}
    for record in records:
        if not isinstance(record, dict):
            _fail("staging-ready Interreg row must be an object")
        call_id, programme, identity = _validate_ready(record)
        identity_fp = str(record["identity_fingerprint"])
        semantic_fp = str(record["semantic_fingerprint"])
        if identity_fp in semantic_by_identity and semantic_by_identity[identity_fp] != semantic_fp:
            _fail(f"{call_id}: semantic conflict for identical call identity")
        semantic_by_identity[identity_fp] = semantic_fp
        occurrences_by_identity[identity_fp] = occurrences_by_identity.get(identity_fp, 0) + 1
        if identity_fp not in by_identity:
            by_identity[identity_fp] = record
        else:
            prior = by_identity[identity_fp]
            if _canonical_json(prior.get("material_facts")) != _canonical_json(record.get("material_facts")):
                _fail(f"{call_id}: duplicate identity material facts diverged")
            if _identity_payload(prior) != identity:
                _fail(f"{call_id}: identity payload drift")
            if str(prior.get("programme")) != programme:
                _fail(f"{call_id}: programme drift")

    observed_at = str(reconciliation.get("reconciled_at") or reconciliation.get("source_created_at") or "").strip()
    if not observed_at:
        _fail("reconciliation timestamp missing")

    candidate_by_identity: dict[str, dict[str, Any]] = {}
    for identity_fp, record in by_identity.items():
        call_id = str(record["call_identifier"])
        programme = str(record["programme"])
        candidate_by_identity[identity_fp] = {
            "source_url": str(record["authority_url"]),
            "programme": f"INTERREG::{programme}",
            "code": call_id,
            "title": str(record["title"]),
            "source_id": AUTHORITY_CLASS,
        }

    ledger = stage_candidates(bundle, candidate_by_identity.values(), observed_at)
    validate_staging_ledger(ledger)
    summary = ledger.get("summary") or {}
    if summary.get("unique_candidates") != len(candidate_by_identity):
        _fail("candidate staging did not preserve one deterministic row per exact call identity")
    if summary.get("ambiguous_review"):
        _fail("ambiguous canonical identity blocks staging admission")
    if summary.get("published") != 0:
        _fail("candidate staging attempted publication")

    # Candidate IDs are deterministically recomputed from each deduplicated input.
    ledger_rows = {str(row.get("candidate_id")): row for row in ledger.get("rows") or []}
    admitted: list[dict[str, Any]] = []
    for identity_fp in sorted(candidate_by_identity):
        record = by_identity[identity_fp]
        candidate = candidate_by_identity[identity_fp]
        single = stage_candidates({"opportunities": [], "evidence": []}, [candidate], observed_at)
        candidate_id = str(single["rows"][0]["candidate_id"])
        staged = ledger_rows.get(candidate_id)
        call_id = str(record["call_identifier"])
        if not staged:
            _fail(f"{call_id}: deterministic staging row missing")
        if staged.get("disposition") not in {"NEW_CANDIDATE", "CANONICAL_MATCH"}:
            _fail(f"{call_id}: unsafe staging disposition {staged.get('disposition')}")
        admitted.append({
            "call_identifier": call_id,
            "programme": record.get("programme"),
            "programme_label_authorized": False,
            "authority_url": record.get("authority_url"),
            "candidate_id": candidate_id,
            "staging_disposition": staged.get("disposition"),
            "canonical_match_id": staged.get("canonical_match_id"),
            "identity_keys": staged.get("identity_keys"),
            "identity_fingerprint": identity_fp,
            "semantic_fingerprint": record.get("semantic_fingerprint"),
            "duplicate_observations_collapsed": occurrences_by_identity[identity_fp],
            "source_run_id": record.get("source_run_id"),
            "fetched_at": record.get("fetched_at"),
            "raw_hash": record.get("raw_hash"),
            "material_facts_sha256": _sha256(record.get("material_facts")),
            "staging_admission": "PASS",
            "material_fact_use": True,
            "canonical_corpus_mutation": False,
            "publish_authorized": False,
            "publication_effect": "NONE",
            "material_fact_action": "NONE",
            "missing_proofs": OUTPUT_MISSING_PROOFS,
        })

    quarantine_keys = sorted(
        f"{row.get('probe_id') or ''}|{row.get('call_identifier') or ''}|{row.get('authority_url') or ''}"
        for row in quarantined
    )
    output_missing = OUTPUT_MISSING_PROOFS if admitted else []
    return {
        "schema": SCHEMA,
        "source_reconciliation_schema": INPUT_SCHEMA,
        "source_reconciliation_hash": _sha256(reconciliation),
        "source_evidence_hash": reconciliation.get("source_evidence_hash"),
        "source_run_id": reconciliation.get("source_run_id"),
        "source_created_at": reconciliation.get("source_created_at"),
        "reconciled_at": reconciliation.get("reconciled_at"),
        "source_family": SOURCE_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "programme_label_authorized": False,
        "p11_staging_ledger_sha256": ledger.get("ledger_sha256"),
        "records": admitted,
        "quarantined_rows_preserved": quarantine_keys,
        "stats": {
            "input_rows": stats.get("input_rows"),
            "reconciled_ready_occurrences": len(records),
            "deduplicated_ready": len(candidate_by_identity),
            "duplicate_observations_collapsed": len(records) - len(candidate_by_identity),
            "staging_admitted": len(admitted),
            "review_required_preserved": len(quarantined),
            "new_candidates": summary.get("new_candidates", 0),
            "canonical_matches": summary.get("canonical_matches", 0),
            "ambiguous_review": summary.get("ambiguous_review", 0),
            "admission_errors": 0,
        },
        "canonical_staging_admission": "PASS",
        "material_fact_use": bool(admitted),
        "canonical_corpus_mutation": False,
        "publish_authorized": False,
        "publication_effect": "NONE",
        "material_fact_action": "NONE",
        "missing_proofs": output_missing,
        "rollback": "Discard this admission receipt; the canonical P11 bundle, tracked staging ledgers, public projection, LKG and upstream evidence remain unchanged.",
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
        "duplicates_collapsed": receipt["stats"]["duplicate_observations_collapsed"],
        "publish_authorized": receipt["publish_authorized"],
        "publication_effect": receipt["publication_effect"],
        "missing_proofs": receipt["missing_proofs"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
