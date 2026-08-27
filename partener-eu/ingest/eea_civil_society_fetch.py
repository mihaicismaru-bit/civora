#!/usr/bin/env python3
"""Live, non-publishing acquisition for EEA Civil Society Fund Romania call pages.

The call index is discovery only. Exact call-detail pages on eeagrants.org are fetched
individually, hashed, parsed, and passed to EEA_CSF_ROMANIA_CALLS_V1. No record is
authorized for publication here; material facts remain reconciliation candidates.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import re
import ssl
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

MODULE_PATH = Path(__file__).with_name("eea_civil_society_calls.py")
spec = importlib.util.spec_from_file_location("eea_csf_adapter", MODULE_PATH)
adapter = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(adapter)

PARSER_VERSION = "EEA_CSF_ROMANIA_LIVE_FETCH_V1"
INDEX_URL = "https://eeagrants.org/en/eea-civil-society-fund-romania/calls"
OFFICIAL_HOSTS = {"eeagrants.org", "www.eeagrants.org"}
MAX_BYTES = 4_000_000
USER_AGENT = "PARTENER.EU source-intelligence/1.0 (+https://partener.eu)"
CALL_PATH_RE = re.compile(
    r"^/(?:en|ro)/eea-civil-society-fund-romania/calls/(?P<slug>[^/?#]+)/?$",
    re.IGNORECASE,
)
INDEX_PATH_RE = re.compile(
    r"^/(?:en|ro)/eea-civil-society-fund-romania/calls/?$",
    re.IGNORECASE,
)
DATE_RE = r"\d{2}/\d{2}/\d{4}"
AMOUNT_RE = r"(?:€|EUR)\s*\d[\d.,]*"


class _DocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.texts: list[str] = []
        self.h1_parts: list[str] = []
        self._in_h1 = False
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag == "h1":
            self._in_h1 = True
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if tag == "h1":
            self._in_h1 = False

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        value = " ".join(data.split())
        if not value:
            return
        self.texts.append(value)
        if self._in_h1:
            self.h1_parts.append(value)


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _official_url(url: str, *, call_detail: bool | None = None) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in OFFICIAL_HOSTS:
        raise ValueError(f"non-official EEA URL: {url}")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError(f"unexpected authority components in URL: {url}")
    path = parsed.path or "/"
    if call_detail is True and not CALL_PATH_RE.match(path):
        raise ValueError(f"not an exact EEA CSF call-detail URL: {url}")
    if call_detail is False and not INDEX_PATH_RE.match(path):
        raise ValueError(f"not the EEA CSF call index URL: {url}")
    return urlunparse(("https", host, path.rstrip("/") or "/", "", "", ""))


def fetch_url(url: str, *, timeout: float = 20.0) -> dict[str, Any]:
    requested_url = _official_url(url)
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
        final_url = _official_url(response.geturl())
        content_type = response.headers.get("Content-Type", "")
        raw = response.read(MAX_BYTES + 1)
    if status != 200:
        raise RuntimeError(f"HTTP {status} for {requested_url}")
    if len(raw) > MAX_BYTES:
        raise RuntimeError(f"response exceeds {MAX_BYTES} bytes for {requested_url}")
    if "text/html" not in content_type.lower() and "application/xhtml+xml" not in content_type.lower():
        raise RuntimeError(f"unexpected content type {content_type!r} for {requested_url}")
    return {
        "requested_url": requested_url,
        "final_url": final_url,
        "status": status,
        "content_type": content_type,
        "raw": raw,
    }


def _parse_document(raw: bytes) -> _DocumentParser:
    parser = _DocumentParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    parser.close()
    return parser


def discover_call_urls(raw: bytes, *, base_url: str = INDEX_URL) -> list[str]:
    base_url = _official_url(base_url, call_detail=False)
    parser = _parse_document(raw)
    discovered: dict[tuple[int, str], str] = {}
    for href in parser.links:
        candidate = urljoin(base_url + "/", href)
        try:
            candidate = _official_url(candidate, call_detail=True)
        except ValueError:
            continue
        match = CALL_PATH_RE.match(urlparse(candidate).path)
        if not match:
            continue
        slug = match.group("slug")
        number_match = re.match(r"call-(\d+)-", slug, flags=re.IGNORECASE)
        if not number_match:
            continue
        number = int(number_match.group(1))
        language = urlparse(candidate).path.split("/", 2)[1].lower()
        discovered[(number, language)] = candidate

    by_number: dict[int, tuple[int, str]] = {}
    for (number, language), url in discovered.items():
        rank = 0 if language == "en" else 1
        previous = by_number.get(number)
        if previous is None or rank < previous[0]:
            by_number[number] = (rank, url)
    return [by_number[number][1] for number in sorted(by_number)]


def _flat_text(parser: _DocumentParser) -> str:
    return " ".join(parser.texts)


def _extract_label_value(flat: str, labels: tuple[str, ...], pattern: str) -> str | None:
    for label in labels:
        match = re.search(rf"{re.escape(label)}\s*:?\s*({pattern})", flat, flags=re.IGNORECASE)
        if match:
            return " ".join(match.group(1).split())
    return None


def _call_number_from_url(url: str) -> str | None:
    match = CALL_PATH_RE.match(urlparse(url).path)
    if not match:
        return None
    number_match = re.match(r"call-(\d+)-", match.group("slug"), flags=re.IGNORECASE)
    return number_match.group(1) if number_match else None


def _status_label(flat: str) -> str | None:
    pairs = (
        (r"\bCall for projects\s+Open\b", "Open"),
        (r"\bCall for projects\s+Closed\b", "Closed"),
        (r"\bCall for projects\s+(?:Forthcoming|Upcoming)\b", "Forthcoming"),
        (r"\bApeluri? de proiecte\s+Deschis\b", "Open"),
        (r"\bApeluri? de proiecte\s+Închis\b", "Closed"),
        (r"\bApeluri? de proiecte\s+(?:Viitor|În pregătire)\b", "Forthcoming"),
    )
    for pattern, value in pairs:
        if re.search(pattern, flat, flags=re.IGNORECASE):
            return value
    return None


def parse_call_page(raw: bytes, *, authority_url: str) -> dict[str, Any]:
    authority_url = _official_url(authority_url, call_detail=True)
    parser = _parse_document(raw)
    flat = _flat_text(parser)
    call_number = _call_number_from_url(authority_url)
    title = " ".join(parser.h1_parts).strip() or None

    eligible = None
    eligible_match = re.search(
        r"(?:Eligible Applicants|Solicitanții eligibili)\s+(.*?)\s+(?:Call details|Detalii apel|Call number|Numărul Apelului)",
        flat,
        flags=re.IGNORECASE,
    )
    if eligible_match:
        eligible = " ".join(eligible_match.group(1).split())[:1600] or None

    return {
        "callNumber": call_number,
        "title": title,
        "status": _status_label(flat),
        "authorityUrl": authority_url,
        "publicationDate": _extract_label_value(
            flat,
            ("Publication date", "Data publicării"),
            DATE_RE,
        ),
        "submissionDeadline": _extract_label_value(
            flat,
            ("Submission Deadline", "Data limită de depunere a Cererilor de finanțare"),
            DATE_RE,
        ),
        "questionsDeadline": _extract_label_value(
            flat,
            ("Questions deadline date", "Data limită pentru adresarea de întrebări"),
            DATE_RE,
        ),
        "amountAvailable": _extract_label_value(
            flat,
            ("Amount available", "Sumă disponibilă"),
            AMOUNT_RE,
        ),
        "grantAmountFrom": _extract_label_value(
            flat,
            ("Grant amount from", "Valoarea minimă a grantului"),
            AMOUNT_RE,
        ),
        "grantAmountTo": _extract_label_value(
            flat,
            ("Grant amount to", "Valoarea maximă a grantului"),
            AMOUNT_RE,
        ),
        "eligibleApplicants": eligible,
    }


def collect_live(
    *,
    index_url: str = INDEX_URL,
    run_id: str,
    fetched_at: str | None = None,
    minimum_calls: int = 1,
    fetcher: Callable[[str], dict[str, Any]] = fetch_url,
) -> dict[str, Any]:
    fetched_at = fetched_at or _utc_now()
    index = fetcher(index_url)
    index_final = _official_url(str(index["final_url"]), call_detail=False)
    index_raw = bytes(index["raw"])
    call_urls = discover_call_urls(index_raw, base_url=index_final)
    if len(call_urls) < minimum_calls:
        raise RuntimeError(
            f"discovered {len(call_urls)} call-detail URLs, below minimum {minimum_calls}"
        )

    records: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for requested_url in call_urls:
        try:
            response = fetcher(requested_url)
            final_url = _official_url(str(response["final_url"]), call_detail=True)
            raw = bytes(response["raw"])
            record = parse_call_page(raw, authority_url=final_url)
            normalized = adapter.normalize_record(
                record,
                fetched_at=fetched_at,
                run_id=run_id,
                raw_hash=_sha256(raw),
                verified_authority_urls=[final_url],
            )
            if normalized is None:
                raise RuntimeError("call-detail page did not yield a stable call identifier")
            records.append(normalized)
            pages.append(
                {
                    "requested_url": _official_url(requested_url, call_detail=True),
                    "final_url": final_url,
                    "http_status": int(response["status"]),
                    "content_type": str(response["content_type"]),
                    "raw_hash": _sha256(raw),
                    "bytes": len(raw),
                    "call_identifier": normalized["call_identifier"],
                    "observation_state": normalized["observation_state"],
                }
            )
        except Exception as exc:
            errors.append({"url": requested_url, "error": f"{type(exc).__name__}: {exc}"})

    unique_records: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    for record in records:
        key = (
            record["call_identifier"],
            record["programme_family"],
            record["authority_url"],
        )
        previous = unique_records.get(key)
        if previous is None:
            unique_records[key] = record
            continue
        if previous["semantic_fingerprint"] != record["semantic_fingerprint"]:
            previous["requires_reconcile"] = True
            record["requires_reconcile"] = True
            conflicts.append(
                {
                    "call_identifier": record["call_identifier"],
                    "programme_family": record["programme_family"],
                    "authority_url": record["authority_url"],
                    "fingerprints": sorted(
                        {
                            previous["semantic_fingerprint"],
                            record["semantic_fingerprint"],
                        }
                    ),
                }
            )

    normalized_records = list(unique_records.values())
    return {
        "schema": "PARTENER_EU_EEA_CSF_LIVE_EVIDENCE_V1",
        "source_family": adapter.SOURCE_FAMILY,
        "programme_family": adapter.PROGRAMME_FAMILY,
        "authority_class": adapter.AUTHORITY_CLASS,
        "source_index": {
            "url": index_final,
            "http_status": int(index["status"]),
            "content_type": str(index["content_type"]),
            "raw_hash": _sha256(index_raw),
            "bytes": len(index_raw),
        },
        "fetched_at": fetched_at,
        "parser_version": PARSER_VERSION,
        "adapter_version": adapter.PARSER_VERSION,
        "run_id": run_id,
        "pages": pages,
        "records": normalized_records,
        "conflicts": conflicts,
        "errors": errors,
        "stats": {
            "discovered_call_urls": len(call_urls),
            "fetched_call_pages": len(pages),
            "normalized_records": len(normalized_records),
            "open_call_evidence": sum(
                1 for item in normalized_records if item["observation_state"] == "OPEN_CALL"
            ),
            "forthcoming_call_evidence": sum(
                1 for item in normalized_records if item["observation_state"] == "FORTHCOMING_CALL"
            ),
            "closed_call_evidence": sum(
                1 for item in normalized_records if item["observation_state"] == "CLOSED_CALL"
            ),
            "unknown_evidence": sum(
                1 for item in normalized_records if item["observation_state"] == "UNKNOWN"
            ),
            "errors": len(errors),
            "conflicts": len(conflicts),
        },
        "material_fact_use": False,
        "publish_authorized": False,
        "publication_effect": "NONE",
        "requires_reconcile": bool(normalized_records or conflicts),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index-url", default=INDEX_URL)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--fetched-at", default=None)
    parser.add_argument("--minimum-calls", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    run_id = args.run_id or f"EEA-CSF-LIVE-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    evidence = collect_live(
        index_url=args.index_url,
        run_id=run_id,
        fetched_at=args.fetched_at,
        minimum_calls=args.minimum_calls,
    )
    payload = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")

    if evidence["stats"]["errors"] or evidence["stats"]["conflicts"]:
        return 2
    if evidence["stats"]["fetched_call_pages"] < args.minimum_calls:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
