#!/usr/bin/env python3
"""Fail-closed authoritative programme resolution for Funding & Tenders staging.

Binds programme reference codes preserved in the non-publishing staging admission
receipt to the human-readable programme label exposed by the official European
Commission Funding & Tenders ``frameworkProgramme`` Facet response.

The gate is all-or-nothing: every staged row must resolve against the exact Facet
bytes whose SHA-256 is recorded in the live evidence envelope. No identifier
prefix heuristics, local lookup tables, or market-research inference can authorize
programme identity. The output remains non-publishing and does not mutate P11.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from typing import Any

SCHEMA = "PARTENER_EU_FUNDING_TENDERS_PROGRAMME_RESOLUTION_V1"
STAGING_SCHEMA = "PARTENER_EU_FUNDING_TENDERS_CANONICAL_STAGING_ADMISSION_V1"
EVIDENCE_SCHEMA = "PARTENER_EU_FUNDING_TENDERS_LIVE_EVIDENCE_V1"
SOURCE_FAMILY = "EU_DIRECT"
PROGRAMME_FAMILY = "BRUSSELS"
AUTHORITY_CLASS = "EU_COMMISSION_FUNDING_TENDERS"
FACET_KEY = "broad"
FACET_NAME = "frameworkProgramme"
EXPECTED_MISSING_PROOFS = ["PUBLIC_PROJECTION_QUALITY_GATE"]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical_json(value))


def _fail(message: str) -> None:
    raise ValueError(message)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split()).strip()
    return text or None


def _framework_programme_map(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        _fail("Facet response must be a JSON object")
    facets = payload.get("facets")
    if not isinstance(facets, list):
        _fail("Facet response is missing facets")
    matches = [facet for facet in facets if isinstance(facet, dict) and facet.get("name") == FACET_NAME]
    if len(matches) != 1:
        _fail(f"expected exactly one {FACET_NAME} facet, found {len(matches)}")
    values = matches[0].get("values")
    if not isinstance(values, list) or not values:
        _fail(f"{FACET_NAME} facet has no values")

    resolved: dict[str, str] = {}
    for row in values:
        if not isinstance(row, dict):
            continue
        code = _clean_text(row.get("rawValue"))
        label = _clean_text(row.get("value"))
        if not code or not label or label == code or label.isdigit():
            continue
        previous = resolved.get(code)
        if previous and previous != label:
            _fail(f"ambiguous official programme label for {code}: {previous!r} vs {label!r}")
        resolved[code] = label
    if not resolved:
        _fail(f"{FACET_NAME} facet yielded no human-readable programme labels")
    return resolved


def resolve_programmes(
    staging: dict[str, Any],
    evidence: dict[str, Any],
    facet_payload: Any,
    *,
    facet_raw_bytes: bytes,
) -> dict[str, Any]:
    if not isinstance(staging, dict) or staging.get("schema") != STAGING_SCHEMA:
        _fail(f"staging schema must be {STAGING_SCHEMA}")
    if not isinstance(evidence, dict) or evidence.get("schema") != EVIDENCE_SCHEMA:
        _fail(f"evidence schema must be {EVIDENCE_SCHEMA}")

    for envelope, name in ((staging, "staging"), (evidence, "evidence")):
        if envelope.get("source_family") != SOURCE_FAMILY:
            _fail(f"{name}: source_family mismatch")
        if envelope.get("authority_class") != AUTHORITY_CLASS:
            _fail(f"{name}: authority_class mismatch")
        if envelope.get("publish_authorized") is not False or envelope.get("publication_effect") != "NONE":
            _fail(f"{name}: must remain non-publishing")
        if envelope.get("canonical_corpus_mutation") is not False:
            _fail(f"{name}: canonical corpus mutation is forbidden")

    if staging.get("programme_family") != PROGRAMME_FAMILY:
        _fail("staging: programme_family mismatch")
    if staging.get("canonical_staging_admission") != "PASS":
        _fail("staging admission is not PASS")
    if staging.get("programme_label_authorized") is not False:
        _fail("programme label must still be unauthorized before this gate")
    if staging.get("missing_proofs") != EXPECTED_MISSING_PROOFS:
        _fail("staging downstream proof contract drift")
    if staging.get("source_evidence_hash") != _sha256_json(evidence):
        _fail("staging source_evidence_hash does not bind the supplied live evidence")

    facet_receipts = evidence.get("facet_receipts")
    if not isinstance(facet_receipts, dict):
        _fail("live evidence is missing facet receipts")
    broad_receipt = facet_receipts.get(FACET_KEY)
    if not isinstance(broad_receipt, dict):
        _fail("live evidence is missing broad Facet receipt")
    raw_sha = _sha256_bytes(facet_raw_bytes)
    if broad_receipt.get("sha256") != raw_sha:
        _fail("broad Facet bytes do not match live evidence receipt")

    labels = _framework_programme_map(facet_payload)
    records = staging.get("records")
    if not isinstance(records, list) or not records:
        _fail("staging admission has no records")

    resolved_rows: list[dict[str, Any]] = []
    used: dict[str, str] = {}
    seen_identifiers: set[str] = set()
    for row in records:
        if not isinstance(row, dict):
            _fail("staging record must be an object")
        identifier = _clean_text(row.get("identifier"))
        if not identifier or identifier in seen_identifiers:
            _fail(f"invalid/duplicate staged identifier {identifier!r}")
        seen_identifiers.add(identifier)
        if row.get("staging_admission") != "PASS":
            _fail(f"{identifier}: staging admission is not PASS")
        if row.get("programme_label_authorized") is not False:
            _fail(f"{identifier}: programme label was pre-authorized")
        if row.get("publish_authorized") is not False or row.get("canonical_corpus_mutation") is not False:
            _fail(f"{identifier}: unsafe publishing/corpus state")
        if row.get("publication_effect") != "NONE" or row.get("material_fact_action") != "NONE":
            _fail(f"{identifier}: material/publication action must remain NONE")
        if row.get("missing_proofs") != EXPECTED_MISSING_PROOFS:
            _fail(f"{identifier}: downstream proof contract drift")

        programme_reference = _clean_text(row.get("programme_reference"))
        if not programme_reference:
            _fail(f"{identifier}: programme reference missing")
        programme_label = labels.get(programme_reference)
        if not programme_label:
            _fail(f"{identifier}: programme reference {programme_reference} unresolved in official {FACET_NAME} facet")
        used[programme_reference] = programme_label
        resolved_rows.append({
            "identifier": identifier,
            "candidate_id": row.get("candidate_id"),
            "call_identifier": row.get("call_identifier"),
            "authority_url": row.get("authority_url"),
            "programme_reference": programme_reference,
            "programme_identity": f"EU_DIRECT::{programme_reference}",
            "programme_label": programme_label,
            "programme_label_authorized": True,
            "programme_authority": "EC_FUNDING_TENDERS_FACET::frameworkProgramme",
            "source_run_id": row.get("source_run_id"),
            "fetched_at": row.get("fetched_at"),
            "raw_hash": row.get("raw_hash"),
            "semantic_fingerprint": row.get("semantic_fingerprint"),
            "material_facts_sha256": row.get("material_facts_sha256"),
            "programme_resolution": "PASS",
            "material_fact_use": bool(row.get("material_fact_use")),
            "canonical_corpus_mutation": False,
            "publish_authorized": False,
            "publication_effect": "NONE",
            "material_fact_action": "NONE",
            "missing_proofs": EXPECTED_MISSING_PROOFS,
        })

    return {
        "schema": SCHEMA,
        "source_staging_schema": STAGING_SCHEMA,
        "source_staging_hash": _sha256_json(staging),
        "source_evidence_schema": EVIDENCE_SCHEMA,
        "source_evidence_hash": _sha256_json(evidence),
        "facet_name": FACET_NAME,
        "facet_response_sha256": raw_sha,
        "facet_receipt_sha256": broad_receipt.get("sha256"),
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "records": resolved_rows,
        "resolved_programmes": [
            {
                "programme_reference": code,
                "programme_identity": f"EU_DIRECT::{code}",
                "programme_label": label,
                "programme_authority": "EC_FUNDING_TENDERS_FACET::frameworkProgramme",
            }
            for code, label in sorted(used.items())
        ],
        "stats": {
            "staging_records": len(records),
            "programme_resolved": len(resolved_rows),
            "unique_programmes": len(used),
            "unresolved": 0,
        },
        "programme_resolution_gate": "PASS",
        "programme_label_authorized": True,
        "canonical_corpus_mutation": False,
        "publish_authorized": False,
        "publication_effect": "NONE",
        "material_fact_action": "NONE",
        "missing_proofs": EXPECTED_MISSING_PROOFS,
        "rollback": "Discard this programme-resolution receipt; staging, canonical corpus, and public projection remain unchanged.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("staging", type=pathlib.Path)
    parser.add_argument("evidence", type=pathlib.Path)
    parser.add_argument("--facet-response", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()

    staging = json.loads(args.staging.read_text(encoding="utf-8"))
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    facet_raw = args.facet_response.read_bytes()
    facet_payload = json.loads(facet_raw.decode("utf-8"))
    receipt = resolve_programmes(staging, evidence, facet_payload, facet_raw_bytes=facet_raw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "programme_resolved": receipt["stats"]["programme_resolved"],
        "unique_programmes": receipt["stats"]["unique_programmes"],
        "programme_label_authorized": receipt["programme_label_authorized"],
        "publish_authorized": receipt["publish_authorized"],
        "publication_effect": receipt["publication_effect"],
        "missing_proofs": receipt["missing_proofs"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
