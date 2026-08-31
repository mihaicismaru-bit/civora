#!/usr/bin/env python3
"""Bounded acquisition-only readback for the official EC culture funding index.

The Commission page can legitimately expose its call cards through a rendered
client-side layer. A successful HTTP readback with zero explicit `CREA-*`
references is therefore persisted as a degraded discovery observation rather
than being converted into facts or silently treated as healthy. Exact Creative
Europe call verification is handled separately through the structured Funding
& Tenders path.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import ssl
import sys
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

MODULE_PATH = Path(__file__).with_name("creative_europe_call_index.py")
spec = importlib.util.spec_from_file_location("creative_europe_call_index", MODULE_PATH)
indexer = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(indexer)

FETCHER_VERSION = "CREATIVE_EUROPE_CALL_INDEX_LIVE_FETCH_V2"
DEFAULT_URL = "https://culture.ec.europa.eu/funding/calls"
OFFICIAL_HOST = "culture.ec.europa.eu"
PATH_RE = re.compile(r"^/(?:[a-z]{2}(?:-[a-z]{2})?/)?funding/calls/?$", re.IGNORECASE)
MAX_BYTES = 8_000_000
USER_AGENT = "PARTENER.EU source-intelligence/1.0 (+https://partener.eu)"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def official_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host != OFFICIAL_HOST:
        raise ValueError(f"non-official Creative Europe culture URL: {url}")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError(f"unexpected Creative Europe authority components: {url}")
    path = parsed.path or "/"
    if not PATH_RE.fullmatch(path):
        raise ValueError(f"not a bounded EC culture funding-index path: {url}")
    if parsed.query or parsed.fragment:
        raise ValueError(f"Creative Europe index URL must not carry query/fragment: {url}")
    normalized_path = path.rstrip("/") or "/"
    return urlunparse(("https", host, normalized_path, "", "", ""))


def fetch_url(url: str, *, timeout: float = 30.0) -> dict[str, Any]:
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
        content_type = str(response.headers.get("Content-Type", ""))
        raw = response.read(MAX_BYTES + 1)
    if status != 200:
        raise RuntimeError(f"HTTP {status} for {requested_url}")
    if len(raw) > MAX_BYTES:
        raise RuntimeError(f"Creative Europe response exceeds {MAX_BYTES} bytes")
    lowered = content_type.lower()
    if "text/html" not in lowered and "application/xhtml+xml" not in lowered:
        raise RuntimeError(f"unexpected Creative Europe content type {content_type!r}")
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
        raise ValueError("Creative Europe acquisition receipt requested URL drift")
    if int(response.get("status") or 0) != 200:
        raise RuntimeError(f"Creative Europe index returned HTTP {response.get('status')}")
    content_type = str(response.get("content_type") or "")
    if "html" not in content_type.lower():
        raise RuntimeError(f"Creative Europe index returned non-HTML content: {content_type!r}")
    raw = response.get("raw")
    if not isinstance(raw, (bytes, bytearray)):
        raise ValueError("Creative Europe acquisition receipt missing raw bytes")
    raw = bytes(raw)
    if len(raw) > MAX_BYTES:
        raise RuntimeError("Creative Europe evidence exceeded bounded size")
    raw_hash = indexer.sha256_bytes(raw)

    batch = indexer.normalize_call_index(
        raw,
        authority_url=final_url,
        fetched_at=fetched_at,
        run_id=run_id,
        raw_hash=raw_hash,
    )
    indexer.validate_call_index_batch(batch)
    count = int(batch.get("record_count") or 0)
    source_health = "HEALTHY" if count else "DEGRADED_EMPTY_RENDERED_INDEX"

    evidence = {
        "schema": "PARTENER_EU_CREATIVE_EUROPE_CALL_INDEX_LIVE_EVIDENCE_V1",
        "fetcher_version": FETCHER_VERSION,
        "adapter_id": indexer.ADAPTER_ID,
        "parser_version": indexer.PARSER_VERSION,
        "source_family": indexer.SOURCE_FAMILY,
        "programme_family": indexer.PROGRAMME_FAMILY,
        "authority_class": indexer.AUTHORITY_CLASS,
        "authority_url": final_url,
        "fetched_at": fetched_at,
        "run_id": run_id,
        "source_health": source_health,
        "lkg_required": count == 0,
        "receipt": {
            "requested_url": requested_url,
            "final_url": final_url,
            "http_status": 200,
            "content_type": content_type,
            "bytes": len(raw),
            "raw_sha256": raw_hash,
        },
        "batch": batch,
        "stats": {
            "exact_crea_reference_candidates": count,
            "visible_open_candidates": sum(
                row.get("status_candidate") == "open" for row in batch.get("records", [])
            ),
            "open_call_authorized": sum(
                bool(row.get("open_call_authorized")) for row in batch.get("records", [])
            ),
            "records_requiring_ft_reconcile": sum(
                bool(row.get("requires_funding_tenders_structured_reconcile"))
                for row in batch.get("records", [])
            ),
        },
        "market_intelligence_only": True,
        "material_fact_use": False,
        "open_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
        "missing_for_material_use": (
            ["server/readback exposes no explicit CREA-* rows; use structured F&T exact-topic evidence"]
            if count == 0 else
            ["exact current Funding & Tenders topic readback", "semantic reconciliation"]
        ),
        "rollback": "Discard this evidence artifact/raw index; no canonical corpus or public projection was mutated.",
    }
    validate_live_evidence(evidence)
    return evidence


def validate_live_evidence(evidence: Mapping[str, Any]) -> None:
    if evidence.get("schema") != "PARTENER_EU_CREATIVE_EUROPE_CALL_INDEX_LIVE_EVIDENCE_V1":
        raise ValueError("Creative Europe live evidence schema mismatch")
    if evidence.get("market_intelligence_only") is not True:
        raise ValueError("Creative Europe live evidence left intelligence-only boundary")
    if evidence.get("publication_effect") != "NONE" or evidence.get("canonical_corpus_mutation") is not False:
        raise ValueError("Creative Europe live evidence crossed canonical/public boundary")
    for key in (
        "material_fact_use", "open_call_authorized", "deadline_authorized", "budget_authorized",
        "eligibility_authorized", "publish_authorized", "distribution_authorized",
    ):
        if evidence.get(key) is not False:
            raise ValueError(f"Creative Europe live evidence became authorizing: {key}")
    stats = evidence.get("stats") or {}
    count = int(stats.get("exact_crea_reference_candidates") or 0)
    if int(stats.get("open_call_authorized") or 0) != 0:
        raise ValueError("Creative Europe index leaked OPEN authorization")
    if int(stats.get("records_requiring_ft_reconcile") or 0) != count:
        raise ValueError("Creative Europe index lost Funding & Tenders reconcile gates")
    health = evidence.get("source_health")
    if count:
        if health != "HEALTHY" or evidence.get("lkg_required") is not False:
            raise ValueError("Creative Europe populated index has incorrect source health")
    else:
        if health != "DEGRADED_EMPTY_RENDERED_INDEX" or evidence.get("lkg_required") is not True:
            raise ValueError("Creative Europe empty rendered index must degrade and require LKG")


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
    print(json.dumps({
        **evidence.get("stats", {}),
        "source_health": evidence.get("source_health"),
        "lkg_required": evidence.get("lkg_required"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL Creative Europe live evidence: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
