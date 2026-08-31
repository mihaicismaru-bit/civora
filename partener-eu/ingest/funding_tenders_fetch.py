#!/usr/bin/env python3
"""Bounded, fail-closed live acquisition for EC Funding & Tenders Search/Facet APIs.

This module performs *evidence acquisition only*. It calls the public European
Commission corporate Search and Facet APIs, resolves reference-code labels from
Facet evidence, performs both an exact structured Topic Details readback and a
bounded HTML topic-page reachability check, and then feeds the existing
``funding_tenders_api.py`` normalizer.

The structured Topic Details readback is the semantic identity/status gate. The
HTML readback is only an additional official topic-page reachability proof. OPEN
or FORTHCOMING classification requires both. The module never mutates the
canonical opportunity corpus or public projection. Raw Search/Facet/exact-topic
JSON responses are retained in the evidence directory for replay.
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
FETCHER_VERSION = "FUNDING_TENDERS_LIVE_FETCH_V2"
MAX_API_BYTES = 8 * 1024 * 1024
MAX_TOPIC_BYTES = 2 * 1024 * 1024
DEFAULT_PAGE_SIZE = 5
STRUCTURED_TOPIC_PAGE_SIZE = 10
ALLOWED_API_HOST = "api.tech.ec.europa.eu"
ALLOWED_TOPIC_HOST = "ec.europa.eu"
STATUS_CODES_OF_INTEREST = ("31094501", "31094502")
CALL_TYPES = ("1", "2", "8")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def default_query() -> dict[str, Any]:
    """Official Search-API query shape for open/forthcoming grant-like records.

    Reference codes are used only as search filters. Their semantic labels must
    still be resolved from official Facet evidence.
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


def normalize_official_status_label(label: str | None) -> str | None:
    """Normalize official Facet wording without assigning meaning to raw codes."""
    if not label:
        return None
    raw = re.sub(r"\s+", " ", label.strip())
    token = raw.upper()
    if token in {"OPEN", "OPEN FOR SUBMISSION"}:
        return "Open"
    if token in {"FORTHCOMING", "FORTHCOMING CALL"}:
        return "Forthcoming"
    if token in {"CLOSED", "CLOSED FOR SUBMISSION"}:
        return "Closed"
    return raw


def resolve_reference_label(facet_payloads: Iterable[Any], code: str) -> str | None:
    """Resolve one reference code only from official Facet response payloads."""
    wanted = str(code).strip()
    if not wanted:
        return None
    code_fields = ("rawValue", "code", "id", "key", "refCode", "referenceCode")
    label_fields = ("value", "label", "name", "description", "displayValue", "text", "title")
    for payload in facet_payloads:
        for node in _walk(payload):
            if not isinstance(node, dict):
                continue
            direct = node.get(wanted)
            if isinstance(direct, str) and direct.strip() and direct.strip() != wanted:
                return normalize_official_status_label(direct)
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
                    return normalize_official_status_label(label)
    return None


def topic_url(identifier: str) -> str:
    value = str(identifier or "").strip()
    if not value or len(value) > 240 or not re.fullmatch(r"[A-Za-z0-9._:/-]+", value):
        raise ValueError(f"unsafe Funding & Tenders topic identifier: {identifier!r}")
    return TOPIC_BASE + quote(value, safe="-._~:")


def _topic_readback(url: str, *, max_bytes: int = MAX_TOPIC_BYTES, opener=None) -> dict[str, Any]:
    """Bounded HTML reachability proof for the exact official topic page."""
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
    except Exception as exc:
        return {"url": url, "verified": False, "error": f"{type(exc).__name__}: {exc}"}
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


def _record_call_identifier(record: Mapping[str, Any]) -> str | None:
    return _scalar(record.get("callIdentifier"))


def _record_type(record: Mapping[str, Any]) -> str | None:
    return _scalar(record.get("type"))


def _structured_topic_filename(identifier: str) -> str:
    digest = sha256_bytes(identifier.encode("utf-8"))[:20]
    return f"structured-topic-{digest}.json"


def _structured_topic_readback(identifier: str, *, page_size: int = STRUCTURED_TOPIC_PAGE_SIZE,
                               opener=None) -> tuple[dict[str, Any], bytes]:
    """Read one topic back from the official structured Topic Details search.

    EC's public API documentation defines Topic Details through the Search service
    using the exact topic identifier as the ``text`` parameter. We still fail
    closed: only exact identifier rows count, and conflicting exact status/call
    identities make the receipt non-verified.
    """
    topic_url(identifier)  # validate identifier before placing it in the query
    page_size = max(1, min(int(page_size), 25))
    exact_text = f'"{identifier}"'
    parts = {
        "query": {"bool": {"must": [{"terms": {"type": list(CALL_TYPES)}}]}},
        "languages": ["en"],
    }
    try:
        payload, raw, search_receipt = _safe_json_post(
            SEARCH_ENDPOINT,
            text=exact_text,
            page_size=page_size,
            page_number=1,
            parts=parts,
            opener=opener,
        )
    except Exception as exc:
        return ({
            "identifier": identifier,
            "query_text": exact_text,
            "verified": False,
            "error": f"{type(exc).__name__}: {exc}",
        }, b"")

    rows = flatten_search_payload(payload)
    matched_identifiers = sorted({value for row in rows if (value := _record_identifier(row))})
    exact_rows = [row for row in rows if _record_identifier(row) == identifier]
    status_codes = sorted({value for row in exact_rows if (value := _record_status_code(row))})
    call_identifiers = sorted({value for row in exact_rows if (value := _record_call_identifier(row))})
    raw_types = sorted({value for row in exact_rows if (value := _record_type(row))})

    # Identity is authoritative only when the exact topic is present and its
    # current structured status is unambiguous. Call identifier may be absent, but
    # if present it must also be unambiguous.
    verified = bool(exact_rows) and len(status_codes) == 1 and len(call_identifiers) <= 1
    return ({
        "identifier": identifier,
        "query_text": exact_text,
        "api_url": search_receipt.get("final_url"),
        "http_status": search_receipt.get("http_status"),
        "content_type": search_receipt.get("content_type"),
        "bytes": search_receipt.get("bytes"),
        "raw_sha256": search_receipt.get("sha256"),
        "matched_identifiers": matched_identifiers,
        "exact_match_count": len(exact_rows),
        "status_codes": status_codes,
        "call_identifiers": call_identifiers,
        "raw_types": raw_types,
        "verified": bool(verified),
    }, raw)


def _structured_receipt_confirms_record(record: Mapping[str, Any], receipt: Mapping[str, Any] | None) -> bool:
    if not isinstance(receipt, Mapping) or receipt.get("verified") is not True:
        return False
    identifier = _record_identifier(record)
    if not identifier or receipt.get("identifier") != identifier:
        return False
    if identifier not in set(receipt.get("matched_identifiers") or []):
        return False
    status_code = _record_status_code(record)
    if not status_code or status_code not in set(receipt.get("status_codes") or []):
        return False
    call_identifier = _record_call_identifier(record)
    structured_calls = set(receipt.get("call_identifiers") or [])
    if call_identifier and structured_calls and call_identifier not in structured_calls:
        return False
    raw_hash = str(receipt.get("raw_sha256") or "")
    if not HEX64_RE.fullmatch(raw_hash):
        return False
    api_url = str(receipt.get("api_url") or "")
    parsed = urlparse(api_url)
    return parsed.scheme == "https" and parsed.hostname == ALLOWED_API_HOST and parsed.path.endswith("/rest/search")


def assemble_evidence(search_payload: Any, facet_payloads: Mapping[str, Any], *, fetched_at: str,
                      run_id: str, search_receipt: Mapping[str, Any], facet_receipts: Mapping[str, Any],
                      readbacks: Mapping[str, Mapping[str, Any]],
                      structured_readbacks: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
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
            html_ok = (readbacks.get(identifier) or {}).get("verified") is True
            structured_ok = _structured_receipt_confirms_record(record, structured_readbacks.get(identifier))
            if html_ok and structured_ok:
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
        "structured_topic_readbacks": dict(structured_readbacks),
        "batch": batch,
        "stats": {
            "search_records": len(rows),
            "normalized_records": batch.get("stats", {}).get("normalized_records", 0),
            "open_calls": sum(r.get("observation_state") == "OPEN_CALL" for r in batch.get("records", [])),
            "forthcoming_calls": sum(r.get("observation_state") == "FORTHCOMING_CALL" for r in batch.get("records", [])),
            "unknown": sum(r.get("observation_state") == "UNKNOWN" for r in batch.get("records", [])),
            "verified_topic_readbacks": sum(bool(v.get("verified")) for v in readbacks.values()),
            "verified_structured_topic_readbacks": sum(bool(v.get("verified")) for v in structured_readbacks.values()),
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
    structured_readbacks: dict[str, dict[str, Any]] = {}
    for row in rows:
        identifier = _record_identifier(row)
        if not identifier or identifier in readbacks:
            continue
        readbacks[identifier] = _topic_readback(topic_url(identifier))
        structured, structured_raw = _structured_topic_readback(identifier)
        if structured_raw:
            raw_file = _structured_topic_filename(identifier)
            (output_dir / raw_file).write_bytes(structured_raw)
            structured["raw_file"] = raw_file
        structured_readbacks[identifier] = structured

    evidence = assemble_evidence(
        search_payload,
        facet_payloads,
        fetched_at=fetched_at,
        run_id=run_id,
        search_receipt=search_receipt,
        facet_receipts=facet_receipts,
        readbacks=readbacks,
        structured_readbacks=structured_readbacks,
    )
    (output_dir / "authority-readbacks.json").write_text(
        json.dumps(readbacks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "structured-topic-readbacks.json").write_text(
        json.dumps(structured_readbacks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
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
    html_readbacks = evidence.get("authority_readbacks") or {}
    structured_readbacks = evidence.get("structured_topic_readbacks") or {}
    if not isinstance(html_readbacks, Mapping) or not isinstance(structured_readbacks, Mapping):
        raise ValueError("Funding & Tenders live evidence missing exact readback maps")
    for row in (evidence.get("batch") or {}).get("records", []):
        if row.get("publish_authorized") is not False or row.get("material_fact_use") is not False:
            raise ValueError(f"unsafe Funding & Tenders record {row.get('identifier')}")
        if row.get("observation_state") in {"OPEN_CALL", "FORTHCOMING_CALL"}:
            identifier = str(row.get("identifier") or "")
            if not row.get("authority_url_verified"):
                raise ValueError(f"unverified topic classified as {row.get('observation_state')}: {identifier}")
            if (html_readbacks.get(identifier) or {}).get("verified") is not True:
                raise ValueError(f"topic-page readback missing for {identifier}")
            structured = structured_readbacks.get(identifier)
            if not isinstance(structured, Mapping) or structured.get("verified") is not True:
                raise ValueError(f"structured topic readback missing for {identifier}")
            if str(row.get("raw_status") or "") not in set(structured.get("status_codes") or []):
                raise ValueError(f"structured topic status mismatch for {identifier}")
            if not HEX64_RE.fullmatch(str(structured.get("raw_sha256") or "")):
                raise ValueError(f"structured topic raw hash missing for {identifier}")


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
