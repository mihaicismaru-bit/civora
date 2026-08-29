#!/usr/bin/env python3
"""Probe the two official public MySMIS reporting transports without publication.

This diagnostic exists to decide whether the historical DWH host can safely act
as an acquisition fallback for the canonical MySMIS public-reporting surface.
It never authorizes OPEN_CALL or any other material fact. Even a semantically
aligned alternate remains discovery/availability evidence until a separate
canonical ingestion change is reviewed and reconciled.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import ssl
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from mipe_discovery_ingest import parse_mysmis

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(
    os.getenv(
        "MYSMIS_SCOUT_OUT",
        ROOT / "partener-eu" / "ingest" / "state" / "mysmis_reporting_transport_scout.json",
    )
)
PARSER_VERSION = "MYSMIS_REPORTING_TRANSPORT_SCOUT_V1"
CANONICAL_URL = (
    "https://reporting.mysmis2021.gov.ro/ords/repo_bo/r/"
    "mysmis-2021/finantari-programe-2021-2027"
)
OFFICIAL_ALTERNATE_URL = (
    "https://dwh4smis.fonduri-ue.ro/ords/repo_bo/r/"
    "mysmis-2021/finantari-programe-2021-2027"
)
EXPECTED_PATH = "/ords/repo_bo/r/mysmis-2021/finantari-programe-2021-2027"
UA = "PARTENER.EU-CIVORA-MySMIS-ReportingScout/1.0 (+https://partener.eu)"
MAX_BYTES = 4_000_000

TRANSPORTS = (
    ("CANONICAL_PRIMARY", CANONICAL_URL, "reporting.mysmis2021.gov.ro"),
    ("OFFICIAL_ALTERNATE", OFFICIAL_ALTERNATE_URL, "dwh4smis.fonduri-ue.ro"),
)


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def run_id() -> str:
    return (
        os.getenv("GITHUB_RUN_ID")
        or os.getenv("GITHUB_SHA")
        or f"local-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )


def semantic_signature(total: int | None, rows: dict[str, Any]) -> str:
    """Hash parsed report semantics, not volatile APEX HTML."""
    normalized = {
        "validatedCallCount": total,
        "rows": rows,
    }
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def official_final_url(url: str, expected_host: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() == expected_host
        and parsed.path.rstrip("/") == EXPECTED_PATH.rstrip("/")
    )


def probe(role: str, url: str, expected_host: str, timeout: int = 25) -> dict[str, Any]:
    result: dict[str, Any] = {
        "role": role,
        "requestedUrl": url,
        "authorityClass": "T1_OFFICIAL_MYSMIS_REPORTING",
        "sourceFamily": "ROMANIA_MIPE_MYSMIS",
        "programmeFamily": "MULTI_PROGRAMME_2021_2027",
        "observationState": "REPORT_TRANSPORT_DIAGNOSTIC",
        "parserVersion": PARSER_VERSION,
        "materialFactUse": False,
        "openCallAuthorized": False,
        "publishAuthorized": False,
        "deadlineAuthorized": False,
        "budgetAuthorized": False,
        "eligibilityAuthorized": False,
    }
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ro,en;q=0.7",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(
            req,
            timeout=timeout,
            context=ssl.create_default_context(),
        ) as response:
            status = getattr(response, "status", 200)
            final_url = response.geturl()
            raw_bytes = response.read(MAX_BYTES)
            content_type = response.headers.get("Content-Type", "")
        if not (200 <= status < 400):
            raise RuntimeError(f"unexpected HTTP status {status}")
        if not official_final_url(final_url, expected_host):
            raise RuntimeError(f"redirected outside exact official report transport: {final_url}")
        if "html" not in content_type.lower():
            raise RuntimeError(f"unexpected content type: {content_type}")
        raw = raw_bytes.decode("utf-8", errors="ignore")
        total, rows, statuses = parse_mysmis(raw)
        result.update(
            {
                "ok": True,
                "status": status,
                "finalUrl": final_url,
                "fetchedAt": now(),
                "contentType": content_type,
                "bytesRead": len(raw_bytes),
                "rawSha256": hashlib.sha256(raw_bytes).hexdigest(),
                "semanticSha256": semantic_signature(total, rows),
                "validatedCallCount": total,
                "visibleRowCount": len(rows),
                "explicitStatuses": statuses,
            }
        )
    except Exception as exc:  # noqa: BLE001 - evidence must record transport failures
        result.update(
            {
                "ok": False,
                "fetchedAt": now(),
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    return result


def classify(primary: dict[str, Any], alternate: dict[str, Any]) -> dict[str, Any]:
    primary_ok = primary.get("ok") is True
    alternate_ok = alternate.get("ok") is True
    semantic_match = (
        primary_ok
        and alternate_ok
        and primary.get("semanticSha256") == alternate.get("semanticSha256")
        and primary.get("validatedCallCount") == alternate.get("validatedCallCount")
    )
    if semantic_match:
        state = "BOTH_AVAILABLE_SEMANTICALLY_ALIGNED"
    elif primary_ok and alternate_ok:
        state = "BOTH_AVAILABLE_SEMANTICALLY_DIVERGENT"
    elif primary_ok:
        state = "CANONICAL_PRIMARY_ONLY"
    elif alternate_ok:
        state = "OFFICIAL_ALTERNATE_ONLY"
    else:
        state = "NO_OFFICIAL_REPORT_TRANSPORT_AVAILABLE"

    # Hard boundary: this diagnostic does not authorize a fallback for material
    # facts. Divergence is particularly important because the two hosts may be
    # on different refresh cycles.
    return {
        "state": state,
        "semanticMatch": semantic_match,
        "canonicalPrimaryAvailable": primary_ok,
        "officialAlternateAvailable": alternate_ok,
        "alternateEligibleForDiscoveryOnly": alternate_ok,
        "alternateAuthorizedForMaterialFacts": False,
        "openCallAuthorized": False,
        "publishAuthorized": False,
        "requiresSemanticReconciliation": bool(alternate_ok and not semantic_match),
        "missingForMaterialFallback": [
            "explicit canonical transport policy accepting the alternate",
            "semantic equivalence for the relevant snapshot",
            "exact-call evidence for any material call fact",
            "successful canonical PARTENER reconciliation",
        ],
    }


def build_payload(probes: list[dict[str, Any]]) -> dict[str, Any]:
    by_role = {item["role"]: item for item in probes}
    primary = by_role["CANONICAL_PRIMARY"]
    alternate = by_role["OFFICIAL_ALTERNATE"]
    return {
        "schema": "CIVORA_MYSMIS_REPORTING_TRANSPORT_MATRIX_V1",
        "observedAt": now(),
        "runId": run_id(),
        "parserVersion": PARSER_VERSION,
        "canonicalIdentity": CANONICAL_URL,
        "authorityClass": "T1_OFFICIAL_MYSMIS_REPORTING",
        "sourceFamily": "ROMANIA_MIPE_MYSMIS",
        "programmeFamily": "MULTI_PROGRAMME_2021_2027",
        "observationState": "REPORT_TRANSPORT_DIAGNOSTIC",
        "materialFactUse": False,
        "openCallAuthorized": False,
        "publishAuthorized": False,
        "transports": probes,
        "comparison": classify(primary, alternate),
    }


def validate_payload(payload: dict[str, Any]) -> None:
    assert payload.get("schema") == "CIVORA_MYSMIS_REPORTING_TRANSPORT_MATRIX_V1"
    assert payload.get("canonicalIdentity") == CANONICAL_URL
    assert payload.get("materialFactUse") is False
    assert payload.get("openCallAuthorized") is False
    assert payload.get("publishAuthorized") is False
    transports = payload.get("transports")
    assert isinstance(transports, list) and len(transports) == 2
    assert {row.get("role") for row in transports} == {
        "CANONICAL_PRIMARY",
        "OFFICIAL_ALTERNATE",
    }
    for row in transports:
        assert row.get("materialFactUse") is False
        assert row.get("openCallAuthorized") is False
        assert row.get("publishAuthorized") is False
        assert row.get("deadlineAuthorized") is False
        assert row.get("budgetAuthorized") is False
        assert row.get("eligibilityAuthorized") is False
        if row.get("ok"):
            assert row.get("requestedUrl", "").startswith("https://")
            assert row.get("finalUrl", "").startswith("https://")
            assert len(row.get("rawSha256", "")) == 64
            assert len(row.get("semanticSha256", "")) == 64
            assert row.get("visibleRowCount", 0) > 0
    comparison = payload.get("comparison") or {}
    assert comparison.get("alternateAuthorizedForMaterialFacts") is False
    assert comparison.get("openCallAuthorized") is False
    assert comparison.get("publishAuthorized") is False


def main() -> int:
    probes = [probe(*spec) for spec in TRANSPORTS]
    payload = build_payload(probes)
    validate_payload(payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "state": payload["comparison"]["state"],
                "canonicalPrimaryAvailable": payload["comparison"]["canonicalPrimaryAvailable"],
                "officialAlternateAvailable": payload["comparison"]["officialAlternateAvailable"],
                "semanticMatch": payload["comparison"]["semanticMatch"],
                "alternateAuthorizedForMaterialFacts": False,
                "output": str(OUT),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
