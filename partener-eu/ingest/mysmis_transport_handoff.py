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
import urllib.parse
from pathlib import Path
from typing import Any

SCHEMA = "CIVORA_MYSMIS_TRANSPORT_HANDOFF_V1"
MATRIX_SCHEMA = "CIVORA_MYSMIS_REPORTING_TRANSPORT_MATRIX_V2"
EXPECTED_PATH = "/ords/repo_bo/r/mysmis-2021/finantari-programe-2021-2027"
CANONICAL_IDENTITY = "https://reporting.mysmis2021.gov.ro" + EXPECTED_PATH
ROLE_ORDER = (
    "CANONICAL_PRIMARY",
    "OFFICIAL_RESOURCES",
    "OFFICIAL_DWH_LEGACY",
)
EXPECTED_ROLES = set(ROLE_ORDER)
ROLE_HOSTS = {
    "CANONICAL_PRIMARY": "reporting.mysmis2021.gov.ro",
    "OFFICIAL_RESOURCES": "resurse.mysmis2021.gov.ro",
    "OFFICIAL_DWH_LEGACY": "dwh4smis.fonduri-ue.ro",
}
EXPECTED_AUTHORITY_CLASS = "T1_OFFICIAL_MYSMIS_REPORTING"
EXPECTED_SOURCE_FAMILY = "ROMANIA_MIPE_MYSMIS"
EXPECTED_PROGRAMME_FAMILY = "MULTI_PROGRAMME_2021_2027"
EXPECTED_MATRIX_OBSERVATION_STATE = "REPORT_TRANSPORT_DIAGNOSTIC"
EXPECTED_HANDOFF_OBSERVATION_STATE = "TRANSPORT_EVIDENCE_HANDOFF"
EXPECTED_PARSER_VERSION = "MYSMIS_REPORTING_TRANSPORT_SCOUT_V2"


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


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    if len(text) != 64:
        return False
    try:
        int(text, 16)
    except ValueError:
        return False
    return True


def _expected_url(role: str) -> str:
    return f"https://{ROLE_HOSTS[role]}{EXPECTED_PATH}"


def _is_exact_official_transport(url: Any, role: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(str(url or ""))
        port = parsed.port
    except (ValueError, TypeError):
        return False
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() == ROLE_HOSTS[role]
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
        and parsed.path.rstrip("/") == EXPECTED_PATH.rstrip("/")
    )


def _validate_provenance_fields(value: dict[str, Any], *, observation_state: str) -> None:
    expected = {
        "authorityClass": EXPECTED_AUTHORITY_CLASS,
        "sourceFamily": EXPECTED_SOURCE_FAMILY,
        "programmeFamily": EXPECTED_PROGRAMME_FAMILY,
        "observationState": observation_state,
    }
    for key, wanted in expected.items():
        if value.get(key) != wanted:
            raise ValueError(f"unexpected {key} provenance")
    if observation_state == EXPECTED_MATRIX_OBSERVATION_STATE:
        if value.get("parserVersion") != EXPECTED_PARSER_VERSION:
            raise ValueError("unexpected MySMIS transport parser version")


def validate_matrix(matrix: dict[str, Any]) -> None:
    if matrix.get("schema") != MATRIX_SCHEMA:
        raise ValueError("unexpected MySMIS transport matrix schema")
    if matrix.get("canonicalIdentity") != CANONICAL_IDENTITY:
        raise ValueError("canonical MySMIS reporting identity changed")
    _validate_provenance_fields(matrix, observation_state=EXPECTED_MATRIX_OBSERVATION_STATE)
    for key in ("materialFactUse", "openCallAuthorized", "publishAuthorized"):
        if matrix.get(key) is not False:
            raise ValueError(f"transport matrix must keep {key}=false")

    transports = matrix.get("transports")
    if not isinstance(transports, list) or len(transports) != len(ROLE_ORDER):
        raise ValueError("transport matrix must contain exactly three official transports")
    if not all(isinstance(row, dict) for row in transports):
        raise ValueError("invalid transport row")
    roles = [row.get("role") for row in transports]
    if set(roles) != EXPECTED_ROLES or len(set(roles)) != len(ROLE_ORDER):
        raise ValueError("transport role set changed")

    by_role = {row["role"]: row for row in transports}
    for role in ROLE_ORDER:
        row = by_role[role]
        _validate_provenance_fields(row, observation_state=EXPECTED_MATRIX_OBSERVATION_STATE)
        if row.get("requestedUrl") != _expected_url(role):
            raise ValueError(f"{role} requested URL is not the exact official transport")
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
            if not _is_exact_official_transport(row.get("finalUrl"), role):
                raise ValueError(f"{role} final URL left its exact official transport")
            if not _is_sha256(row.get("rawSha256")):
                raise ValueError("successful transport lacks valid raw SHA-256")
            if not _is_sha256(row.get("semanticSha256")):
                raise ValueError("successful transport lacks valid semantic SHA-256")

    comparison = matrix.get("comparison")
    if not isinstance(comparison, dict):
        raise ValueError("transport comparison missing")
    for key in ("alternateAuthorizedForMaterialFacts", "openCallAuthorized", "publishAuthorized"):
        if comparison.get(key) is not False:
            raise ValueError(f"transport comparison must keep {key}=false")

    primary_ok = by_role["CANONICAL_PRIMARY"].get("ok") is True
    alt_ok = {
        role: by_role[role].get("ok") is True
        for role in ROLE_ORDER
        if role != "CANONICAL_PRIMARY"
    }
    if comparison.get("canonicalPrimaryAvailable") is not primary_ok:
        raise ValueError("comparison canonical availability drift")
    if comparison.get("alternateAvailability") != alt_ok:
        raise ValueError("comparison alternate availability drift")

    aligned = comparison.get("alignedWithCanonical") or []
    divergent = comparison.get("divergentFromCanonical") or []
    if not isinstance(aligned, list) or not isinstance(divergent, list):
        raise ValueError("comparison semantic-role sets must be lists")
    alternate_role_set = set(alt_ok)
    if not set(aligned).issubset(alternate_role_set):
        raise ValueError("comparison aligned roles contain an unknown role")
    if not set(divergent).issubset(alternate_role_set):
        raise ValueError("comparison divergent roles contain an unknown role")
    available_alternates = {role for role, ok in alt_ok.items() if ok}
    if not set(aligned).issubset(available_alternates):
        raise ValueError("comparison aligned roles include unavailable transport")
    if not set(divergent).issubset(available_alternates):
        raise ValueError("comparison divergent roles include unavailable transport")

    expected_reconciliation = bool(
        available_alternates and (not primary_ok or bool(divergent))
    )
    if comparison.get("alternateEligibleForDiscoveryOnly") is not bool(available_alternates):
        raise ValueError("comparison discovery eligibility drift")
    if comparison.get("requiresSemanticReconciliation") is not expected_reconciliation:
        raise ValueError("comparison reconciliation requirement drift")


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
    by_role = {row["role"]: row for row in matrix["transports"]}
    receipts = [_transport_receipt(by_role[role]) for role in ROLE_ORDER]
    available_roles = [row["role"] for row in receipts if row["available"]]
    alternate_roles = [role for role in available_roles if role != "CANONICAL_PRIMARY"]
    comparison = matrix["comparison"]
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "observedAt": observed_at or utc_now(),
        "runId": run_id or matrix.get("runId") or os.getenv("GITHUB_RUN_ID") or "local",
        "canonicalIdentity": CANONICAL_IDENTITY,
        "matrixSha256": sha256_json(matrix),
        "authorityClass": EXPECTED_AUTHORITY_CLASS,
        "sourceFamily": EXPECTED_SOURCE_FAMILY,
        "programmeFamily": EXPECTED_PROGRAMME_FAMILY,
        "observationState": EXPECTED_HANDOFF_OBSERVATION_STATE,
        "canonicalPrimaryAvailable": "CANONICAL_PRIMARY" in available_roles,
        "availableTransportRoles": available_roles,
        "alternateEvidenceAvailable": bool(alternate_roles),
        "requiresSemanticReconciliation": comparison["requiresSemanticReconciliation"],
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
    _validate_provenance_fields(payload, observation_state=EXPECTED_HANDOFF_OBSERVATION_STATE)
    if not _is_sha256(payload.get("matrixSha256")):
        raise ValueError("handoff lacks valid source matrix digest")
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
    if not isinstance(receipts, list) or len(receipts) != len(ROLE_ORDER):
        raise ValueError("handoff transport receipts are incomplete")
    if not all(isinstance(row, dict) for row in receipts):
        raise ValueError("invalid handoff transport receipt")
    roles = [row.get("role") for row in receipts]
    if roles != list(ROLE_ORDER):
        raise ValueError("handoff transport receipt ordering or role set changed")

    available_roles: list[str] = []
    for row in receipts:
        role = row["role"]
        _validate_provenance_fields(row, observation_state=EXPECTED_MATRIX_OBSERVATION_STATE)
        if row.get("requestedUrl") != _expected_url(role):
            raise ValueError(f"{role} handoff requested URL is not the exact official transport")
        for key in (
            "materialFactUse",
            "openCallAuthorized",
            "publishAuthorized",
            "deadlineAuthorized",
            "budgetAuthorized",
            "eligibilityAuthorized",
        ):
            if row.get(key) is not False:
                raise ValueError(f"handoff transport row must keep {key}=false")
        if row.get("available") is True:
            available_roles.append(role)
            if not _is_exact_official_transport(row.get("finalUrl"), role):
                raise ValueError(f"{role} handoff final URL left its exact official transport")
            if not _is_sha256(row.get("rawSha256")):
                raise ValueError("handoff transport lacks valid raw SHA-256")
            if not _is_sha256(row.get("semanticSha256")):
                raise ValueError("handoff transport lacks valid semantic SHA-256")

    if payload.get("availableTransportRoles") != available_roles:
        raise ValueError("handoff available transport roles drift")
    primary_available = "CANONICAL_PRIMARY" in available_roles
    alternate_available = any(role != "CANONICAL_PRIMARY" for role in available_roles)
    if payload.get("canonicalPrimaryAvailable") is not primary_available:
        raise ValueError("handoff canonical availability drift")
    if payload.get("alternateEvidenceAvailable") is not alternate_available:
        raise ValueError("handoff alternate evidence availability drift")
    if not isinstance(payload.get("requiresSemanticReconciliation"), bool):
        raise ValueError("handoff reconciliation flag must be boolean")

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
