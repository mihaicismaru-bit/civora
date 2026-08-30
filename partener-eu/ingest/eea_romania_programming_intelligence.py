#!/usr/bin/env python3
"""Normalize official Romania EEA/Norway 2021-2028 programming into non-authorizing watch evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PARSER_VERSION = "EEA_ROMANIA_PROGRAMMING_INTELLIGENCE_V1"
EXPECTED_SOURCE_URL = "https://eeagrants.org/en/fmo/news/renewed-cooperation-romania"
EXPECTED_PUBLISHED_DATE = "2026-05-12"
EXPECTED_FAMILY = "EEA_NORWAY"
EXPECTED_AUTHORITY = "T1_EEA_OFFICIAL_FMO"
EXPECTED_OBSERVATION_STATE = "PROGRAMMING_PIPELINE"
EXPECTED_PROGRAMME_COUNT = 9
EXPECTED_HOST = "eeagrants.org"
EXPECTED_PATH = "/en/fmo/news/renewed-cooperation-romania"

FORBIDDEN_PROGRAMME_KEYS = {
    "status",
    "deadline",
    "budget",
    "eligibility",
    "callidentifier",
    "topicidentifier",
    "callstatus",
    "opencall",
    "open",
}

MISSING_TO_CONFIRMED_CALL = [
    "CURRENT_OFFICIAL_OPERATOR_OR_CALL_ENDPOINT",
    "EXACT_CALL_OR_TOPIC_IDENTIFIER",
    "CURRENT_OFFICIAL_CALL_STATUS",
    "SEMANTIC_RECONCILIATION",
]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _validate_source(source: dict[str, Any]) -> None:
    expected = {
        "sourceUrl": EXPECTED_SOURCE_URL,
        "publishedDate": EXPECTED_PUBLISHED_DATE,
        "programmeFamily": EXPECTED_FAMILY,
        "authorityClass": EXPECTED_AUTHORITY,
        "observationState": EXPECTED_OBSERVATION_STATE,
    }
    for key, wanted in expected.items():
        if source.get(key) != wanted:
            raise ValueError(f"source {key} drift: expected {wanted!r}, got {source.get(key)!r}")

    source_id = str(source.get("sourceId") or "").strip()
    if not source_id:
        raise ValueError("source sourceId is required")

    parsed = urlparse(str(source.get("sourceUrl") or ""))
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != EXPECTED_HOST or parsed.path.rstrip("/") != EXPECTED_PATH:
        raise ValueError("sourceUrl must remain the exact official Financial Mechanism Office programming page")


def _validate_programmes(programmes: Any) -> list[dict[str, str]]:
    if not isinstance(programmes, list) or len(programmes) != EXPECTED_PROGRAMME_COUNT:
        raise ValueError(f"expected exactly {EXPECTED_PROGRAMME_COUNT} official programme rows")

    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    validated: list[dict[str, str]] = []
    for index, row in enumerate(programmes, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"programme row {index} must be an object")

        normalized_keys = {str(key).replace("_", "").replace("-", "").lower() for key in row}
        forbidden = sorted(normalized_keys & FORBIDDEN_PROGRAMME_KEYS)
        if forbidden:
            raise ValueError(f"programme row {index} contains forbidden call/material fields: {', '.join(forbidden)}")

        programme_id = str(row.get("programmeId") or "").strip()
        programme = str(row.get("programme") or "").strip()
        operator = str(row.get("programmeOperator") or "").strip()
        if not programme_id or not programme or not operator:
            raise ValueError(f"programme row {index} requires programmeId, programme and programmeOperator")
        if programme_id in seen_ids:
            raise ValueError(f"duplicate programmeId: {programme_id}")
        if programme.casefold() in seen_names:
            raise ValueError(f"duplicate programme: {programme}")
        seen_ids.add(programme_id)
        seen_names.add(programme.casefold())
        validated.append({"programmeId": programme_id, "programme": programme, "programmeOperator": operator})
    return validated


def normalize_registry(registry: dict[str, Any], *, observed_at: str, run_id: str) -> dict[str, Any]:
    if registry.get("schemaVersion") != "1.0":
        raise ValueError("unsupported registry schemaVersion")
    if not observed_at or not run_id:
        raise ValueError("observed_at and run_id are required for provenance")

    source = registry.get("source")
    if not isinstance(source, dict):
        raise ValueError("source object is required")
    _validate_source(source)
    programmes = _validate_programmes(registry.get("programmes"))

    snapshot_payload = {"schemaVersion": registry["schemaVersion"], "source": source, "programmes": programmes}
    source_snapshot_sha256 = _sha256(snapshot_payload)

    records: list[dict[str, Any]] = []
    for row in programmes:
        semantic_fingerprint = _sha256(
            {
                "programmeId": row["programmeId"],
                "programme": row["programme"],
                "programmeOperator": row["programmeOperator"],
                "sourceUrl": source["sourceUrl"],
                "observationState": EXPECTED_OBSERVATION_STATE,
            }
        )
        records.append(
            {
                "programmeId": row["programmeId"],
                "programme": row["programme"],
                "programmeOperator": row["programmeOperator"],
                "programmeFamily": EXPECTED_FAMILY,
                "geography": "Romania",
                "authorityClass": EXPECTED_AUTHORITY,
                "observationState": EXPECTED_OBSERVATION_STATE,
                "watchPurpose": "OFFICIAL_OPERATOR_SOURCE_DISCOVERY",
                "sourceId": source["sourceId"],
                "sourceUrl": source["sourceUrl"],
                "sourcePublishedDate": source["publishedDate"],
                "observedAt": observed_at,
                "fetchedAt": observed_at,
                "sourcePayloadSha256": source_snapshot_sha256,
                "semanticFingerprint": semantic_fingerprint,
                "parserVersion": PARSER_VERSION,
                "runId": run_id,
                "materialFactUse": False,
                "openCallAuthorized": False,
                "deadlineAuthorized": False,
                "budgetAuthorized": False,
                "eligibilityAuthorized": False,
                "publishAuthorized": False,
                "distributionAuthorized": False,
                "requiresReconciliation": True,
                "publicationEffect": "NONE",
                "missingToBecomeConfirmedCall": list(MISSING_TO_CONFIRMED_CALL),
            }
        )

    return {
        "schemaVersion": "1.0",
        "parserVersion": PARSER_VERSION,
        "programmeFamily": EXPECTED_FAMILY,
        "authorityClass": EXPECTED_AUTHORITY,
        "observationState": EXPECTED_OBSERVATION_STATE,
        "observedAt": observed_at,
        "fetchedAt": observed_at,
        "runId": run_id,
        "sourceId": source["sourceId"],
        "sourceUrl": source["sourceUrl"],
        "sourcePublishedDate": source["publishedDate"],
        "sourcePayloadSha256": source_snapshot_sha256,
        "recordCount": len(records),
        "records": records,
        "materialFactUse": False,
        "openCallAuthorized": False,
        "publishAuthorized": False,
        "distributionAuthorized": False,
        "requiresReconciliation": True,
        "publicationEffect": "NONE",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path(__file__).with_name("eea_romania_programming_registry.json"),
        help="official programming snapshot registry",
    )
    parser.add_argument("--observed-at", required=True, help="observation timestamp, preserved verbatim")
    parser.add_argument("--run-id", required=True, help="run/checkpoint identifier")
    parser.add_argument("--output", type=Path, help="optional output JSON path")
    args = parser.parse_args()

    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    output = normalize_registry(registry, observed_at=args.observed_at, run_id=args.run_id)
    rendered = json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
