#!/usr/bin/env python3
"""Read-only public-projection quality gate for Funding & Tenders direct calls.

Consumes the exact live evidence, semantic reconciliation, canonical staging admission,
and authoritative programme-resolution receipts. The gate is all-or-nothing and
emits projection-ready records only when all provenance and semantic bindings remain
intact. It never mutates the P11 corpus or public projection and never publishes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
from typing import Any

SCHEMA = "PARTENER_EU_FUNDING_TENDERS_PUBLIC_PROJECTION_QUALITY_GATE_V1"
EVIDENCE_SCHEMA = "PARTENER_EU_FUNDING_TENDERS_LIVE_EVIDENCE_V1"
RECONCILIATION_SCHEMA = "PARTENER_EU_FUNDING_TENDERS_RECONCILIATION_RECEIPT_V1"
STAGING_SCHEMA = "PARTENER_EU_FUNDING_TENDERS_CANONICAL_STAGING_ADMISSION_V1"
PROGRAMME_SCHEMA = "PARTENER_EU_FUNDING_TENDERS_PROGRAMME_RESOLUTION_V1"
SOURCE_FAMILY = "EU_DIRECT"
PROGRAMME_FAMILY = "BRUSSELS"
AUTHORITY_CLASS = "EU_COMMISSION_FUNDING_TENDERS"
EXPECTED_INPUT_MISSING_PROOFS = ["PUBLIC_PROJECTION_QUALITY_GATE"]
ALLOWED_STATUSES = {"OPEN", "FORTHCOMING"}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _fail(message: str) -> None:
    raise ValueError(message)


def _parse_ts(value: Any, field: str) -> dt.datetime:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{field}: timestamp required")
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field}: invalid timestamp {value!r}") from exc
    if parsed.tzinfo is None:
        _fail(f"{field}: timezone required")
    return parsed.astimezone(dt.timezone.utc)


def _index(records: Any, key: str, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(records, list) or not records:
        _fail(f"{label}: records missing")
    out: dict[str, dict[str, Any]] = {}
    for row in records:
        if not isinstance(row, dict):
            _fail(f"{label}: record must be object")
        identity = row.get(key)
        if not isinstance(identity, str) or not identity or identity in out:
            _fail(f"{label}: invalid/duplicate {key} {identity!r}")
        out[identity] = row
    return out


def _safe_envelope(value: dict[str, Any], label: str) -> None:
    if value.get("source_family") != SOURCE_FAMILY:
        _fail(f"{label}: source_family mismatch")
    if value.get("authority_class") != AUTHORITY_CLASS:
        _fail(f"{label}: authority_class mismatch")
    if value.get("publish_authorized") is not False or value.get("publication_effect") != "NONE":
        _fail(f"{label}: must remain non-publishing")
    if value.get("canonical_corpus_mutation") is not False:
        _fail(f"{label}: canonical corpus mutation is forbidden")


def build_projection_quality_gate(
    evidence: dict[str, Any],
    reconciliation: dict[str, Any],
    staging: dict[str, Any],
    programme_resolution: dict[str, Any],
    *,
    evaluated_at: str | None = None,
) -> dict[str, Any]:
    if not isinstance(evidence, dict) or evidence.get("schema") != EVIDENCE_SCHEMA:
        _fail(f"evidence schema must be {EVIDENCE_SCHEMA}")
    if not isinstance(reconciliation, dict) or reconciliation.get("schema") != RECONCILIATION_SCHEMA:
        _fail(f"reconciliation schema must be {RECONCILIATION_SCHEMA}")
    if not isinstance(staging, dict) or staging.get("schema") != STAGING_SCHEMA:
        _fail(f"staging schema must be {STAGING_SCHEMA}")
    if not isinstance(programme_resolution, dict) or programme_resolution.get("schema") != PROGRAMME_SCHEMA:
        _fail(f"programme schema must be {PROGRAMME_SCHEMA}")

    for value, label in (
        (evidence, "evidence"),
        (reconciliation, "reconciliation"),
        (staging, "staging"),
        (programme_resolution, "programme_resolution"),
    ):
        _safe_envelope(value, label)

    if reconciliation.get("programme_family") != PROGRAMME_FAMILY:
        _fail("reconciliation: programme_family mismatch")
    if staging.get("programme_family") != PROGRAMME_FAMILY:
        _fail("staging: programme_family mismatch")
    if programme_resolution.get("programme_family") != PROGRAMME_FAMILY:
        _fail("programme_resolution: programme_family mismatch")

    evidence_hash = _sha256(evidence)
    reconciliation_hash = _sha256(reconciliation)
    staging_hash = _sha256(staging)
    if reconciliation.get("source_evidence_hash") != evidence_hash:
        _fail("reconciliation does not bind supplied live evidence")
    if staging.get("source_evidence_hash") != evidence_hash:
        _fail("staging does not bind supplied live evidence")
    if staging.get("source_reconciliation_hash") != reconciliation_hash:
        _fail("staging does not bind supplied reconciliation")
    if programme_resolution.get("source_evidence_hash") != evidence_hash:
        _fail("programme resolution does not bind supplied live evidence")
    if programme_resolution.get("source_staging_hash") != staging_hash:
        _fail("programme resolution does not bind supplied staging receipt")

    if staging.get("canonical_staging_admission") != "PASS":
        _fail("canonical staging admission is not PASS")
    if programme_resolution.get("programme_resolution_gate") != "PASS":
        _fail("programme resolution gate is not PASS")
    if staging.get("missing_proofs") != EXPECTED_INPUT_MISSING_PROOFS:
        _fail("staging downstream proof contract drift")
    if programme_resolution.get("missing_proofs") != EXPECTED_INPUT_MISSING_PROOFS:
        _fail("programme downstream proof contract drift")

    reconciled = _index(reconciliation.get("records"), "identifier", "reconciliation")
    staged = _index(staging.get("records"), "identifier", "staging")
    resolved = _index(programme_resolution.get("records"), "identifier", "programme_resolution")
    if set(reconciled) != set(staged) or set(reconciled) != set(resolved):
        _fail("record identity set drift across reconciliation/staging/programme receipts")

    readbacks = evidence.get("authority_readbacks")
    if not isinstance(readbacks, dict):
        _fail("live evidence authority_readbacks missing")
    evaluated = _parse_ts(evaluated_at or dt.datetime.now(dt.timezone.utc).isoformat(), "evaluated_at")

    projection_records: list[dict[str, Any]] = []
    projection_ids: set[str] = set()
    for identifier in sorted(reconciled):
        source = reconciled[identifier]
        stage = staged[identifier]
        programme = resolved[identifier]

        if source.get("reconciliation_status") != "PASS" or source.get("ready_for_staging") is not True:
            _fail(f"{identifier}: reconciliation not staging-ready")
        if source.get("material_fact_use") is not True or source.get("publish_authorized") is not False:
            _fail(f"{identifier}: unsafe reconciliation authorization state")
        if stage.get("staging_admission") != "PASS" or stage.get("publish_authorized") is not False:
            _fail(f"{identifier}: staging admission not safely PASS")
        if programme.get("programme_resolution") != "PASS" or programme.get("programme_label_authorized") is not True:
            _fail(f"{identifier}: programme identity not authoritatively resolved")
        if stage.get("missing_proofs") != EXPECTED_INPUT_MISSING_PROOFS or programme.get("missing_proofs") != EXPECTED_INPUT_MISSING_PROOFS:
            _fail(f"{identifier}: downstream proof contract drift")

        for field in ("authority_url", "source_run_id", "fetched_at", "raw_hash", "semantic_fingerprint"):
            if source.get(field) != stage.get(field) or source.get(field) != programme.get(field):
                _fail(f"{identifier}: {field} provenance drift across receipts")

        facts = source.get("material_facts")
        if not isinstance(facts, dict):
            _fail(f"{identifier}: material_facts missing")
        if stage.get("material_facts_sha256") != _sha256(facts) or programme.get("material_facts_sha256") != _sha256(facts):
            _fail(f"{identifier}: material_facts hash drift")

        authority_url = source.get("authority_url")
        readback = readbacks.get(identifier)
        if not isinstance(readback, dict) or readback.get("verified") is not True:
            _fail(f"{identifier}: exact official topic readback not verified")
        if readback.get("url") != authority_url or readback.get("final_url") != authority_url:
            _fail(f"{identifier}: exact official topic URL drift")
        if int(readback.get("http_status") or 0) != 200:
            _fail(f"{identifier}: exact official topic HTTP status is not 200")
        if not readback.get("body_sha256"):
            _fail(f"{identifier}: exact official topic body hash missing")

        status = facts.get("status")
        if status not in ALLOWED_STATUSES:
            _fail(f"{identifier}: projection status {status!r} is not OPEN/FORTHCOMING")
        deadline = _parse_ts(facts.get("deadline"), f"{identifier}.deadline")
        if status == "OPEN" and deadline < evaluated:
            _fail(f"{identifier}: OPEN deadline elapsed before projection gate")

        title = facts.get("title")
        if not isinstance(title, str) or not title.strip():
            _fail(f"{identifier}: title missing")
        programme_identity = programme.get("programme_identity")
        programme_label = programme.get("programme_label")
        if not isinstance(programme_identity, str) or not programme_identity.startswith("EU_DIRECT::"):
            _fail(f"{identifier}: invalid programme identity")
        if not isinstance(programme_label, str) or not programme_label.strip():
            _fail(f"{identifier}: programme label missing")

        projection_key = {
            "identifier": identifier,
            "programme_identity": programme_identity,
            "authority_url": authority_url,
            "semantic_fingerprint": source.get("semantic_fingerprint"),
        }
        projection_id = "EU-PROJ-" + _sha256(projection_key)[:20].upper()
        if projection_id in projection_ids:
            _fail(f"{identifier}: duplicate projection identity")
        projection_ids.add(projection_id)

        record = {
            "projection_id": projection_id,
            "identifier": identifier,
            "call_identifier": source.get("call_identifier"),
            "candidate_id": stage.get("candidate_id"),
            "programme_identity": programme_identity,
            "programme_label": programme_label,
            "programme_authority": programme.get("programme_authority"),
            "title": title.strip(),
            "status": status,
            "deadline": deadline.isoformat(),
            "authority_url": authority_url,
            "source_family": SOURCE_FAMILY,
            "authority_class": AUTHORITY_CLASS,
            "source_run_id": source.get("source_run_id"),
            "observed_at": source.get("fetched_at"),
            "raw_hash": source.get("raw_hash"),
            "semantic_fingerprint": source.get("semantic_fingerprint"),
            "confidence": "HIGH",
            "confidence_basis": "OFFICIAL_EC_SEARCH_FACET_PLUS_EXACT_TOPIC_READBACK",
            "missing_to_confirm_call": [],
            "projection_quality": "PASS",
            "material_fact_use": True,
            "canonical_corpus_mutation": False,
            "publish_authorized": False,
            "publication_effect": "NONE",
            "material_fact_action": "NONE",
            "missing_proofs": [],
        }
        if facts.get("budget_eur") is not None:
            record["budget_eur"] = facts.get("budget_eur")
        projection_records.append(record)

    return {
        "schema": SCHEMA,
        "source_evidence_schema": EVIDENCE_SCHEMA,
        "source_evidence_hash": evidence_hash,
        "source_reconciliation_schema": RECONCILIATION_SCHEMA,
        "source_reconciliation_hash": reconciliation_hash,
        "source_staging_schema": STAGING_SCHEMA,
        "source_staging_hash": staging_hash,
        "source_programme_schema": PROGRAMME_SCHEMA,
        "source_programme_hash": _sha256(programme_resolution),
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "evaluated_at": evaluated.isoformat(),
        "records": projection_records,
        "stats": {
            "reconciled_records": len(reconciled),
            "projection_ready": len(projection_records),
            "unique_projection_ids": len(projection_ids),
            "quality_errors": 0,
        },
        "public_projection_quality_gate": "PASS",
        "projection_ready": True,
        "material_fact_use": True,
        "canonical_corpus_mutation": False,
        "publish_authorized": False,
        "publication_effect": "NONE",
        "material_fact_action": "NONE",
        "missing_proofs": [],
        "rollback": "Discard this read-only quality receipt; canonical corpus and public projection remain unchanged.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=pathlib.Path)
    parser.add_argument("reconciliation", type=pathlib.Path)
    parser.add_argument("staging", type=pathlib.Path)
    parser.add_argument("programme_resolution", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()

    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    reconciliation = json.loads(args.reconciliation.read_text(encoding="utf-8"))
    staging = json.loads(args.staging.read_text(encoding="utf-8"))
    programme_resolution = json.loads(args.programme_resolution.read_text(encoding="utf-8"))
    receipt = build_projection_quality_gate(evidence, reconciliation, staging, programme_resolution)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "projection_ready": receipt["stats"]["projection_ready"],
        "public_projection_quality_gate": receipt["public_projection_quality_gate"],
        "publish_authorized": receipt["publish_authorized"],
        "publication_effect": receipt["publication_effect"],
        "missing_proofs": receipt["missing_proofs"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
