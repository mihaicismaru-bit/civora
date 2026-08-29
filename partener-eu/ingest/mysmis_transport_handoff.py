#!/usr/bin/env python3
"""Build an immutable, non-authorizing handoff from MySMIS transport evidence.

This module deliberately does not parse alternate reporting transports into call
facts. It carries acquisition evidence from SURFACEMC into PARTENER Engine while
preserving the canonical reporting identity and the fail-closed material-fact
boundary.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any

SCHEMA = "CIVORA_MYSMIS_TRANSPORT_HANDOFF_V1"
MATRIX_SCHEMA = "CIVORA_MYSMIS_REPORTING_TRANSPORT_MATRIX_V2"
CANONICAL_IDENTITY = "https://reporting.mysmis2021.gov.ro/ords/repo_bo/r/mysmis-2021/finantari-programe-2021-2027"
EXPECTED_ROLES = {
    "CANONICAL_PRIMARY",
    "OFFICIAL_RESOURCES",
    "OFFICIAL_DWH_LEGACY",
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def validate_matrix(matrix: dict[str, Any]) -> None:
    if matrix.get("schema") != MATRIX_SCHEMA:
        raise ValueError("unexpected MySMIS transport matrix schema")
    if matrix.get("canonicalIdentity") != CANONICAL_IDENTITY:
        raise ValueError("canonical MySMIS reporting identity changed")
    for key in ("materialFactUse", "openCallAuthorized", "publishAuthorized"):
        if matrix.get(key) is not False:
            raise ValueError(f"transport matrix must keep {key}=false")
    transports = matrix.get("transports")
    if not isinstance(transports, list) or len(transports) != 3:
        raise ValueError("transport matrix must contain exactly three official transports")
    roles = {row.get("role") for row in transports if isinstance(row, dict)}
    if roles != EXPECTED_ROLES:
        raise ValueError("transport role set changed")
    for row in transports:
        if not isinstance(row, dict):
            raise ValueError("invalid transport row")
        for key in (
            "materialFactUse",
            "openCallAuthorized",
            "publishAuthorized",
            "deadlineAuthorized",
            "budgetAuthorized",
            "eligibilityAuthorized",
        ):
            if row.get(key) is not False:
                raise ValueError(f"transport row must keep {key}=false")
        if row.get("ok") is True:
            if not str(row.get("requestedUrl", "")).startswith("https://"):
                raise ValueError("successful transport lacks HTTPS requested URL")
            if not str(row.get("finalUrl", "")).startswith("https://"):
                raise ValueError("successful transport lacks HTTPS final URL")
            if len(str(row.get("rawSha256", ""))) != 64:
                raise ValueError("successful transport lacks raw SHA-256")
            if len(str(row.get("semanticSha256", ""))) != 64:
                raise ValueError("successful transport lacks semantic SHA-256")
    comparison = matrix.get("comparison") or {}
    for key in ("alternateAuthorizedForMaterialFacts", "openCallAuthorized", "publishAuthorized"):
        if comparison.get(key) is not False:
            raise ValueError(f"transport comparison must keep {key}=false")


def _transport_receipt(row: dict[str, Any]) -> dict[str, Any]:
    receipt = {
        "role": row.get("role"),
        "available": row.get("ok") is True,
        "requestedUrl": row.get("requestedUrl"),
        "fetchedAt": row.get("fetchedAt"),
        "authorityClass": row.get("authorityClass"),
        "sourceFamily": row.get("sourceFamily"),
        "programmeFamily": row.get("programmeFamily"),
        "observationState": row.get("observationState"),
        "parserVersion": row.get("parserVersion"),
        "materialFactUse": False,
        "openCallAuthorized": False,
        "publishAuthorized": False,
        "deadlineAuthorized": False,
        "budgetAuthorized": False,
        "eligibilityAuthorized": False,
    }
    if row.get("ok") is True:
        receipt.update(
            {
                "finalUrl": row.get("finalUrl"),
                "rawSha256": row.get("rawSha256"),
                "semanticSha256": row.get("semanticSha256"),
                "validatedCallCount": row.get("validatedCallCount"),
                "visibleRowCount": row.get("visibleRowCount"),
                "explicitStatuses": row.get("explicitStatuses") or [],
            }
        )
    else:
        receipt["error"] = row.get("error")
    return receipt


def build_handoff(
    matrix: dict[str, Any],
    *,
    observed_at: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Convert a verified scout matrix to immutable acquisition evidence.

    The handoff intentionally contains no call records or material changes. An
    alternate transport can improve diagnostics/freshness visibility but cannot
    replace the canonical report for material publication.
    """
    validate_matrix(matrix)
    comparison = matrix.get("comparison") or {}
    receipts = [_transport_receipt(row) for row in matrix["transports"]]
    available_roles = [row["role"] for row in receipts if row["available"]]
    alternate_roles = [role for role in available_roles if role != "CANONICAL_PRIMARY"]
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "observedAt": observed_at or utc_now(),
        "runId": run_id or matrix.get("runId") or os.getenv("GITHUB_RUN_ID") or "local",
        "canonicalIdentity": CANONICAL_IDENTITY,
        "matrixSha256": sha256_json(matrix),
        "authorityClass": "T1_OFFICIAL_MYSMIS_REPORTING",
        "sourceFamily": "ROMANIA_MIPE_MYSMIS",
        "programmeFamily": "MULTI_PROGRAMME_2021_2027",
        "observationState": "TRANSPORT_EVIDENCE_HANDOFF",
        "canonicalPrimaryAvailable": comparison.get("canonicalPrimaryAvailable") is True,
        "availableTransportRoles": available_roles,
        "alternateEvidenceAvailable": bool(alternate_roles),
        "requiresSemanticReconciliation": comparison.get("requiresSemanticReconciliation") is True,
        "transports": receipts,
        "materialFactUse": False,
        "openCallAuthorized": False,
        "publishAuthorized": False,
        "deadlineAuthorized": False,
        "budgetAuthorized": False,
        "eligibilityAuthorized": False,
        "materialChanges": [],
        "publicationEffect": "NONE",
        "fallbackPolicy": (
            "alternate official transports are acquisition evidence only; "
            "they never replace canonical material authority without exact-call evidence "
            "and successful PARTENER semantic reconciliation"
        ),
    }
    payload["handoffSha256"] = sha256_json(payload)
    validate_handoff(payload)
    return payload


def validate_handoff(payload: dict[str, Any]) -> None:
    if payload.get("schema") != SCHEMA:
        raise ValueError("unexpected handoff schema")
    if payload.get("canonicalIdentity") != CANONICAL_IDENTITY:
        raise ValueError("handoff canonical identity changed")
    if len(str(payload.get("matrixSha256", ""))) != 64:
        raise ValueError("handoff lacks source matrix digest")
    for key in (
        "materialFactUse",
        "openCallAuthorized",
        "publishAuthorized",
        "deadlineAuthorized",
        "budgetAuthorized",
        "eligibilityAuthorized",
    ):
        if payload.get(key) is not False:
            raise ValueError(f"handoff must keep {key}=false")
    if payload.get("materialChanges") != [] or payload.get("publicationEffect") != "NONE":
        raise ValueError("transport handoff cannot carry publication changes")
    receipts = payload.get("transports")
    if not isinstance(receipts, list) or {row.get("role") for row in receipts} != EXPECTED_ROLES:
        raise ValueError("handoff transport receipts are incomplete")
    supplied = payload.get("handoffSha256")
    unsigned = dict(payload)
    unsigned.pop("handoffSha256", None)
    if supplied != sha256_json(unsigned):
        raise ValueError("handoff digest mismatch")


def write_immutable(path: Path, payload: dict[str, Any]) -> None:
    """Create a handoff once; refuse to overwrite replay evidence."""
    validate_handoff(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("matrix", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    payload = build_handoff(matrix)
    write_immutable(args.output, payload)
    print(
        json.dumps(
            {
                "canonicalPrimaryAvailable": payload["canonicalPrimaryAvailable"],
                "alternateEvidenceAvailable": payload["alternateEvidenceAvailable"],
                "requiresSemanticReconciliation": payload["requiresSemanticReconciliation"],
                "materialFactUse": False,
                "publicationEffect": "NONE",
                "handoffSha256": payload["handoffSha256"],
                "output": str(args.output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
