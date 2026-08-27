#!/usr/bin/env python3
"""Bounded, fail-closed live acquisition for EC Funding & Tenders Search/Facet APIs.

This module performs *evidence acquisition only*. It calls the public European
Commission corporate Search and Facet APIs, resolves reference-code labels from
Facet evidence, performs a bounded readback of exact topic pages, and then feeds
the existing ``funding_tenders_api.py`` normalizer.

It never mutates the canonical opportunity corpus or public projection. The raw
Search/Facet JSON responses are retained in the evidence directory for replay.
No status code is translated from a local lookup table: a human-readable status
must be present in the official Facet response before it can contribute to
OPEN/FORTHCOMING classification.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import pathlib
import re
import secrets
import sys
from typing import Any, Iterable, Mapping
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, build_opener

from funding_tenders_api import PARSER_VERSION as NORMALIZER_VERSION
from funding_tenders_api import normalize_payload

SEARCH_ENDPOINT = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
FACET_ENDPOINT = "https://api.tech.ec.europa.eu/search-api/prod/rest/facet"
PORTAL_ORIGIN = "https://ec.europa.eu"
PORTAL_REFERER = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/"
TOPIC_BASE = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/"
LIVE_SCHEMA = "PARTENER_EU_FUNDING_TENDERS_LIVE_EVIDENCE_V1"
FETCHER_VERSION = "FUNDING_TENDERS_LIVE_FETCH_V1"
MAX_API_BYTES = 8 * 1024 * 1024
MAX_TOPIC_BYTES = 2 * 1024 * 1024
DEFAULT_PAGE_SIZE = 5
ALLOWED_API_HOST = "api.tech.ec.europa.eu"
ALLOWED_TOPIC_HOST = "ec.europa.eu"
STATUS_CODES_OF_INTEREST = ("31094501", "31094502")
CALL_TYPES = ("1", "2", "8")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def default_query() -> dict[str, Any]:
    """Official Search-API query shape for open/forthcoming grant-like records.

    The reference codes are used only as *search filters*. They are not translated
    locally into semantic statuses; semantic labels must be resolved via Facet.
    """
    return {
        "bool": {
            "must": [
                {"terms": {"type": list(CALL_TYPES)}},
                {"terms": {"status": list(STATUS_CODES_OF_INTEREST)}},
                {"term": {"programmePeriod": "2021 - 2027"}},
            ]
        }
    }


def _multipart_json(parts: Mapping[str, Any]) -> tuple[bytes, str]:
    boundary = "----PARTENER" + secrets.token_hex(16)
    out = bytearray()
    for name, value in parts.items():
        out.extend(f"--{boundary}\r\n".encode("ascii"))
        out.extend(
            f'Content-Disposition: form-data; name="{name}"; filename="blob"\r\n'.encode("ascii")
        )
        out.extend(b"Content-Type: application/json\r\n\r\n")
        out.extend(canonical_json(value))
        out.extend(b"\r\n")
    out.extend(f"--{boundary}--\r\n".encode("ascii"))
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def _request_headers(*, accept: str, content_type: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": accept,
        "User-Agent": "Mozilla/5.0 (compatible; PARTNER-EU-Funding-Intelligence/1.0)",
        "Referer": PORTAL_REFERER,
        "Origin": PORTAL_ORIGIN,
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _safe_json_post(endpoint: str, *, text: str, page_size: int, page_number: int,
                    parts: Mapping[str, Any], max_bytes: int = MAX_API_BYTES,
                    opener=None) -> tuple[Any, bytes, dict[str, Any]]:
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_API_HOST:
        raise ValueError(f"unsafe Funding & Tenders API endpoint: {endpoint}")
    query = urlencode({
        "apiKey": "SEDIA",
        "text": text,
        "pageSize": str(page_size),
        "pageNumber": str(page_number),
    })
    url = endpoint + "?" + query
    body, content_type = _multipart_json(parts)
    req = Request(
        url,
        data=body,
        method="POST",
        headers=_request_headers(accept="application/json, text/plain, */*", content_type=content_type),
    )
    op = opener or build_opener()
    with op.open(req, timeout=30) as response:
        final_url = response.geturl()
        final = urlparse(final_url)
        if final.scheme != "https" or final.hostname != ALLOWED_API_HOST:
            raise ValueError(f"Funding & Tenders API redirected outside official host: {final_url}")
        status = getattr(response, "status", response.getcode())
        if status != 200:
            raise ValueError(f"Funding & Tenders API HTTP {status}: {final_url}")
        ctype = (response.headers.get("Content-Type") or "").lower()
        if "json" not in ctype:
            raise ValueError(f"Funding & Tenders API non-JSON content type {ctype!r}")
        raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError("Funding & Tenders API response exceeds bounded evidence limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Funding & Tenders API returned invalid UTF-8 JSON") from exc
    receipt = {
        "url": url,
        "final_url": final_url,
        "http_status": 200,
        "content_type": ctype,
        "bytes": len(raw),
        "sha256": sha256_bytes(raw),
    }
    return payload, raw, receipt


def _scalar(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = next((item for item in value if item not in (None, "")), None)
    if isinstance(value, dict):
        for key in ("value", "id", "code", "key", "label", "name"):
            if value.get(key) not in (None, ""):
                return _scalar(value.get(key))
        return None
    text = str(value).strip()
    return text or None


def flatten_search_payload(payload: Any) -> list[dict[str, Any]]:
    """Flatten corporate-search wrappers to records accepted by the normalizer."""
    if isinstance(payload, list):
        out: list[dict[str, Any]] = []
        for child in payload:
            out.extend(flatten_search_payload(child))
        return out
    if not isinstance(payload, dict):
        return []

    # The corporate Search API commonly wraps each hit as metadata + content + url.
    if isinstance(payload.get("metadata"), dict):
        flat = copy.deepcopy(payload["metadata"])
        if payload.get("content") not in (None, ""):
            flat.setdefault("title", payload.get("content"))
        if payload.get("url") not in (None, ""):
            flat.setdefault("url", payload.get("url"))
        if isinstance(payload.get("_source"), dict):
            for key, value in payload["_source"].items():
                flat.setdefault(key, value)
        return [flat]

    # Already-flat call/topic record.
    if any(payload.get(key) not in (None, "", [], {}) for key in (
        "identifier", "topicIdentifier", "topicAbbreviation", "callIdentifier"
    )):
        return [copy.deepcopy(payload)]

    out: list[dict[str, Any]] = []
    for key in ("results", "items", "documents", "hits", "data"):
        child = payload.get(key)
        if isinstance(child, (list, dict)):
            out.extend(flatten_search_payload(child))
    source = payload.get("_source")
    if isinstance(source, dict):
        out.extend(flatten_search_payload(source))
    return out


def _walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def resolve_reference_label(facet_payloads: Iterable[Any], code: str) -> str | None:
    """Resolve one reference code only from official Facet response payloads."""
    wanted = str(code).strip()
    if not wanted:
        return None
    code_fields = ("code", "id", "key", "value", "refCode", "referenceCode")
    label_fields = ("label", "name", "description", "displayValue", "text", "title")
    for payload in facet_payloads:
        for node in _walk(payload):
            if not isinstance(node, dict):
                continue
            # Some Facet shapes are simple {"31094502": "Open"} mappings.
            direct = node.get(wanted)
            if isinstance(direct, str) and direct.strip() and direct.strip() != wanted:
                return direct.strip()
            matched = False
            for key in code_fields:
                candidate = _scalar(node.get(key))
                if candidate == wanted:
                    matched = True
                    break
            if not matched:
                continue
            for key in label_fields:
                label = _scalar(node.get(key))
                if label and label != wanted and not label.isdigit():
                    return label
    return None


def topic_url(identifier: str) -> str:
    value = str(identifier or "").strip()
    if not value or len(value) > 240 or not re.fullmatch(r"[A-Za-z0-9._:/-]+", value):
        raise ValueError(f"unsafe Funding & Tenders topic identifier: {identifier!r}")
    return TOPIC_BASE + quote(value, safe="-._~:")


def _topic_readback(url: str, *, max_bytes: int = MAX_TOPIC_BYTES, opener=None) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_TOPIC_HOST or "/topic-details/" not in parsed.path:
        raise ValueError(f"unsafe Funding & Tenders topic URL: {url}")
    req = Request(url, method="GET", headers=_request_headers(accept="text/html,application/xhtml+xml"))
    op = opener or build_opener()
    try:
        with op.open(req, timeout=25) as response:
            final_url = response.geturl()
            final = urlparse(final_url)
            status = getattr(response, "status", response.getcode())
            ctype = (response.headers.get("Content-Type") or "").lower()
            raw = response.read(max_bytes + 1)
    except Exception as exc:  # network/readback failure is evidence, not authority
        return {
            "url": url,
            "verified": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    if len(raw) > max_bytes:
        return {"url": url, "final_url": final_url, "http_status": status, "verified": False, "error": "response too large"}
    verified = (
        status == 200
        and final.scheme == "https"
        and final.hostname == ALLOWED_TOPIC_HOST
        and "/topic-details/" in final.path
        and "html" in ctype
    )
    return {
        "url": url,
        "final_url": final_url,
        "http_status": status,
        "content_type": ctype,
        "bytes": len(raw),
        "body_sha256": sha256_bytes(raw),
        "verified": bool(verified),
    }


def _record_identifier(record: Mapping[str, Any]) -> str | None:
    for key in ("identifier", "topicAbbreviation", "topicIdentifier", "callIdentifier"):
        value = _scalar(record.get(key))
        if value:
            return value
    return None


def _record_status_code(record: Mapping[str, Any]) -> str | None:
    value = _scalar(record.get("status"))
    return value if value and value.isdigit() else None


def assemble_evidence(search_payload: Any, facet_payloads: Mapping[str, Any], *, fetched_at: str,
                      run_id: str, search_receipt: Mapping[str, Any], facet_receipts: Mapping[str, Any],
                      readbacks: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    rows = flatten_search_payload(search_payload)
    enriched: list[dict[str, Any]] = []
    verified_urls: list[str] = []
    resolution: dict[str, str | None] = {}
    all_facet_payloads = list(facet_payloads.values())

    for source in rows:
        record = copy.deepcopy(source)
        code = _record_status_code(record)
        if code:
            label = resolve_reference_label(all_facet_payloads, code)
            resolution.setdefault(code, label)
            if label:
                record["statusLabel"] = label
        identifier = _record_identifier(record)
        if identifier:
            url = topic_url(identifier)
            record["authorityUrl"] = url
            if (readbacks.get(identifier) or {}).get("verified"):
                verified_urls.append(url)
        enriched.append(record)

    batch = normalize_payload(
        enriched,
        fetched_at=fetched_at,
        run_id=run_id,
        verified_authority_urls=verified_urls,
    )
    for row in batch.get("records", []):
        row["material_fact_use"] = False
        row["publish_authorized"] = False

    return {
        "schema": LIVE_SCHEMA,
        "fetcher_version": FETCHER_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "source_family": "EU_DIRECT",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS",
        "fetched_at": fetched_at,
        "run_id": run_id,
        "search_receipt": dict(search_receipt),
        "facet_receipts": dict(facet_receipts),
        "status_resolution": resolution,
        "authority_readbacks": dict(readbacks),
        "batch": batch,
        "stats": {
            "search_records": len(rows),
            "normalized_records": batch.get("stats", {}).get("normalized_records", 0),
            "open_calls": sum(r.get("observation_state") == "OPEN_CALL" for r in batch.get("records", [])),
            "forthcoming_calls": sum(r.get("observation_state") == "FORTHCOMING_CALL" for r in batch.get("records", [])),
            "unknown": sum(r.get("observation_state") == "UNKNOWN" for r in batch.get("records", [])),
            "verified_topic_readbacks": sum(bool(v.get("verified")) for v in readbacks.values()),
            "unresolved_status_codes": sorted(code for code, label in resolution.items() if not label),
            "conflicts": len(batch.get("conflicts", [])),
        },
        "material_fact_use": False,
        "publish_authorized": False,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
        "rollback": "Discard this evidence directory; no canonical corpus or public projection was mutated.",
    }


def collect_live(*, page_size: int, output_dir: pathlib.Path) -> dict[str, Any]:
    if page_size < 1 or page_size > 25:
        raise ValueError("page_size must be between 1 and 25")
    output_dir.mkdir(parents=True, exist_ok=True)
    fetched_at = utc_now()
    run_id = "FT-LIVE-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    query = default_query()
    common_parts = {
        "query": query,
        "languages": ["en"],
        "sort": {"field": "sortStatus", "order": "ASC"},
    }

    search_payload, search_raw, search_receipt = _safe_json_post(
        SEARCH_ENDPOINT,
        text="***",
        page_size=page_size,
        page_number=1,
        parts=common_parts,
    )
    (output_dir / "search-response.json").write_bytes(search_raw)
    rows = flatten_search_payload(search_payload)
    codes = sorted({code for row in rows if (code := _record_status_code(row))})

    facet_payloads: dict[str, Any] = {}
    facet_receipts: dict[str, Any] = {}
    # First capture broad facets using the exact same query, then narrow unresolved codes.
    broad_payload, broad_raw, broad_receipt = _safe_json_post(
        FACET_ENDPOINT,
        text="***",
        page_size=page_size,
        page_number=1,
        parts={"query": query, "languages": ["en"]},
    )
    facet_payloads["broad"] = broad_payload
    facet_receipts["broad"] = broad_receipt
    (output_dir / "facet-response-broad.json").write_bytes(broad_raw)

    for code in codes:
        if resolve_reference_label(facet_payloads.values(), code):
            continue
        payload, raw, receipt = _safe_json_post(
            FACET_ENDPOINT,
            text=code,
            page_size=page_size,
            page_number=1,
            parts={"query": query, "languages": ["en"]},
        )
        facet_payloads[code] = payload
        facet_receipts[code] = receipt
        (output_dir / f"facet-response-{code}.json").write_bytes(raw)

    readbacks: dict[str, dict[str, Any]] = {}
    for row in rows:
        identifier = _record_identifier(row)
        if not identifier or identifier in readbacks:
            continue
        readbacks[identifier] = _topic_readback(topic_url(identifier))

    evidence = assemble_evidence(
        search_payload,
        facet_payloads,
        fetched_at=fetched_at,
        run_id=run_id,
        search_receipt=search_receipt,
        facet_receipts=facet_receipts,
        readbacks=readbacks,
    )
    (output_dir / "authority-readbacks.json").write_text(
        json.dumps(readbacks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return evidence


def validate_live_evidence(evidence: Mapping[str, Any]) -> None:
    if evidence.get("schema") != LIVE_SCHEMA:
        raise ValueError("Funding & Tenders live evidence schema mismatch")
    if evidence.get("publication_effect") != "NONE" or evidence.get("publish_authorized") is not False:
        raise ValueError("Funding & Tenders evidence attempted publication")
    if evidence.get("canonical_corpus_mutation") is not False or evidence.get("material_fact_use") is not False:
        raise ValueError("Funding & Tenders evidence crossed canonical/material-fact boundary")
    stats = evidence.get("stats") or {}
    if stats.get("search_records", 0) < 1 or stats.get("normalized_records", 0) < 1:
        raise ValueError("Funding & Tenders live search returned no normalizable evidence")
    for row in (evidence.get("batch") or {}).get("records", []):
        if row.get("publish_authorized") is not False or row.get("material_fact_use") is not False:
            raise ValueError(f"unsafe Funding & Tenders record {row.get('identifier')}")
        if row.get("observation_state") in {"OPEN_CALL", "FORTHCOMING_CALL"} and not row.get("authority_url_verified"):
            raise ValueError(f"unverified topic classified as {row.get('observation_state')}: {row.get('identifier')}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    args = parser.parse_args()
    evidence = collect_live(page_size=args.page_size, output_dir=args.output_dir)
    validate_live_evidence(evidence)
    print(json.dumps(evidence.get("stats", {}), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL Funding & Tenders live evidence: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
