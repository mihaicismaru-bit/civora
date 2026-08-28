#!/usr/bin/env python3
"""Bounded acquisition-only readback for the European Solidarity Corps annual call.

This fetcher reads only the official European Youth Portal annual call page and
passes the immutable response hash to ESC_ACTION_ROUTER_V1. It never infers
current OPEN status from an annual call notice, an action label or a deadline.
The output is evidence for semantic reconciliation only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import ssl
import sys
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

MODULE_PATH = Path(__file__).with_name("esc_action_router.py")
spec = importlib.util.spec_from_file_location("esc_action_router", MODULE_PATH)
router = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(router)

FETCHER_VERSION = "ESC_ACTION_LIVE_FETCH_V1"
DEFAULT_URL = "https://youth.europa.eu/solidarity/organisations/calls-for-proposals_en"
OFFICIAL_HOST = "youth.europa.eu"
ALLOWED_PATHS = {
    "/solidarity/organisations/calls-for-proposals_en",
    "/solidarity/organisations/calls-for-proposals_ro",
}
MAX_BYTES = 4_000_000
USER_AGENT = "PARTENER.EU source-intelligence/1.0 (+https://partener.eu)"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def official_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host != OFFICIAL_HOST:
        raise ValueError(f"non-official European Youth Portal URL: {url}")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError(f"unexpected authority components in ESC URL: {url}")
    path = (parsed.path or "/").rstrip("/") or "/"
    if path not in ALLOWED_PATHS:
        raise ValueError(f"not the official ESC annual-call page: {url}")
    return urlunparse(("https", host, path, "", "", ""))


def fetch_url(url: str, *, timeout: float = 25.0) -> dict[str, Any]:
    requested_url = official_url(url)
    request = Request(
        requested_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        },
    )
    context = ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:
        status = int(response.getcode() or 0)
        final_url = official_url(response.geturl())
        content_type = response.headers.get("Content-Type", "")
        raw = response.read(MAX_BYTES + 1)
    if status != 200:
        raise RuntimeError(f"HTTP {status} for {requested_url}")
    if len(raw) > MAX_BYTES:
        raise RuntimeError(f"ESC annual-call response exceeds {MAX_BYTES} bytes")
    lowered = content_type.lower()
    if "text/html" not in lowered and "application/xhtml+xml" not in lowered:
        raise RuntimeError(f"unexpected content type {content_type!r} for {requested_url}")
    return {
        "requested_url": requested_url,
        "final_url": final_url,
        "status": status,
        "content_type": content_type,
        "raw": raw,
    }


def collect_live(*, authority_url: str = DEFAULT_URL, run_id: str, fetched_at: str | None = None,
                 fetcher: Callable[[str], Mapping[str, Any]] = fetch_url) -> dict[str, Any]:
    fetched_at = fetched_at or utc_now()
    requested_url = official_url(authority_url)
    response = dict(fetcher(requested_url))
    final_url = official_url(str(response.get("final_url") or requested_url))
    if official_url(str(response.get("requested_url") or requested_url)) != requested_url:
        raise ValueError("ESC acquisition receipt requested URL drift")
    if int(response.get("status") or 0) != 200:
        raise RuntimeError(f"ESC annual-call fetch returned HTTP {response.get('status')}")
    content_type = str(response.get("content_type") or "")
    if "html" not in content_type.lower():
        raise RuntimeError(f"ESC annual-call fetch returned non-HTML content: {content_type!r}")
    raw = response.get("raw")
    if not isinstance(raw, (bytes, bytearray)):
        raise ValueError("ESC acquisition receipt missing raw bytes")
    raw = bytes(raw)
    if len(raw) > MAX_BYTES:
        raise RuntimeError("ESC acquisition receipt exceeded bounded evidence size")
    raw_hash = sha256_bytes(raw)

    batch = router.normalize_framework(
        raw,
        authority_url=final_url,
        fetched_at=fetched_at,
        run_id=run_id,
        raw_hash=raw_hash,
    )
    router.validate_framework_batch(batch)

    evidence = {
        "schema": "PARTENER_EU_ESC_LIVE_EVIDENCE_V1",
        "fetcher_version": FETCHER_VERSION,
        "parser_version": router.PARSER_VERSION,
        "source_family": router.SOURCE_FAMILY,
        "programme_family": router.PROGRAMME_FAMILY,
        "authority_class": router.AUTHORITY_CLASS,
        "authority_url": final_url,
        "fetched_at": fetched_at,
        "run_id": run_id,
        "receipt": {
            "requested_url": requested_url,
            "final_url": final_url,
            "http_status": 200,
            "content_type": content_type,
            "bytes": len(raw),
            "raw_hash": raw_hash,
        },
        "batch": batch,
        "stats": {
            "framework_call_identifier_present": bool(batch.get("framework_call_identifier")),
            "action_rows": batch.get("record_count", 0),
            "open_call_authorized": sum(bool(row.get("open_call_authorized")) for row in batch.get("records", [])),
            "records_requiring_exact_action_evidence": sum(bool(row.get("requires_exact_action_evidence")) for row in batch.get("records", [])),
        },
        "material_fact_use": False,
        "publish_authorized": False,
        "open_call_authorized": False,
        "requires_reconcile": True,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
        "rollback": "Discard this evidence artifact and raw page; no canonical corpus or public projection was mutated.",
    }
    validate_live_evidence(evidence)
    return evidence


def validate_live_evidence(evidence: Mapping[str, Any]) -> None:
    if evidence.get("schema") != "PARTENER_EU_ESC_LIVE_EVIDENCE_V1":
        raise ValueError("ESC live evidence schema mismatch")
    if evidence.get("publication_effect") != "NONE" or evidence.get("canonical_corpus_mutation") is not False:
        raise ValueError("ESC live evidence crossed canonical/public boundary")
    if evidence.get("material_fact_use") is not False or evidence.get("publish_authorized") is not False:
        raise ValueError("ESC live evidence became material/publishing")
    if evidence.get("open_call_authorized") is not False:
        raise ValueError("ESC annual framework attempted OPEN authorization")
    stats = evidence.get("stats") or {}
    if not stats.get("framework_call_identifier_present"):
        raise ValueError("ESC official page did not expose a framework call identifier")
    if int(stats.get("action_rows") or 0) < 4:
        raise ValueError("ESC official page did not expose the expected action framework")
    if int(stats.get("open_call_authorized") or 0) != 0:
        raise ValueError("ESC action framework leaked OPEN authorization")
    if int(stats.get("records_requiring_exact_action_evidence") or 0) != int(stats.get("action_rows") or 0):
        raise ValueError("ESC action framework lost exact-evidence gates")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--raw-out", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args()

    requested_url = official_url(args.url)
    response = fetch_url(requested_url)
    raw = bytes(response["raw"])

    def replay_fetch(_: str) -> Mapping[str, Any]:
        return response

    evidence = collect_live(
        authority_url=requested_url,
        run_id=args.run_id,
        fetcher=replay_fetch,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.raw_out:
        args.raw_out.parent.mkdir(parents=True, exist_ok=True)
        args.raw_out.write_bytes(raw)
    print(json.dumps(evidence.get("stats", {}), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL ESC live evidence: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
