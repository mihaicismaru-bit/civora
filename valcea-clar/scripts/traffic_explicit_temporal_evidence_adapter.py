#!/usr/bin/env python3
"""Fail-closed explicit first-party temporal evidence for VÂLCEA CLAR traffic references."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

CONTENT_CONTRACT = "NEWSROOM_TRAFFIC_EXPLICIT_TEMPORAL_EVIDENCE_ONLY"
MAX_REFERENCES = 24
MAX_RESPONSE_BYTES = 2_000_000
USER_AGENT = "VALCEA-CLAR-Traffic-Explicit-Temporal-Evidence/1.0"

SOURCE_FAMILIES = {
    "politiaromana.ro": {
        "family": "INFOTRAFIC",
        "path_re": re.compile(r"^/ro/info-trafic/[a-z0-9-]+/?$"),
    },
    "vl.politiaromana.ro": {
        "family": "IPJ_VALCEA",
        "path_re": re.compile(r"^/ro/stiri-si-media/stiri/[a-z0-9-]+/?$"),
    },
}

ALLOWED_TIMESTAMP_BASES = {
    "FIRST_PARTY_EXPLICIT_DATETIME",
    "FIRST_PARTY_EXPLICIT_PUBLISHED_AT",
}

DISABLED_CAPABILITIES = [
    "incident_detail_extraction",
    "person_or_personal_data_extraction",
    "attachment_fetch",
    "media_fetch",
    "image_ingest",
    "local_timezone_inference",
    "current_state_inference",
    "active_incident_inference",
    "active_traffic_disruption_inference",
    "same_incident_inference",
    "breaking_news_promotion",
    "fact_kernel_mutation",
    "writer",
    "persistence",
    "public_projection",
    "inferred_photo_rights",
]


class TemporalInputError(RuntimeError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_reference_url(url: str) -> tuple[str, str, str]:
    if not isinstance(url, str) or not url.strip() or len(url) > 1000:
        raise TemporalInputError("reference URL is invalid")
    parsed = urlsplit(url.strip())
    if parsed.scheme != "https":
        raise TemporalInputError("reference must use HTTPS")
    if parsed.username or parsed.password:
        raise TemporalInputError("reference credentials are not allowed")
    try:
        port = parsed.port
    except ValueError as exc:
        raise TemporalInputError("invalid reference port") from exc
    if port not in (None, 443):
        raise TemporalInputError("non-default reference port is not allowed")
    host = parsed.hostname or ""
    config = SOURCE_FAMILIES.get(host)
    if config is None:
        raise TemporalInputError("reference escaped allowlisted traffic hosts")
    if parsed.query or parsed.fragment:
        raise TemporalInputError("reference query or fragment is not allowed")
    path = parsed.path.rstrip("/")
    if not config["path_re"].fullmatch(path):
        raise TemporalInputError("reference escaped allowlisted traffic article path")
    return f"https://{host}{path}", host, str(config["family"])


def _aware_timestamp(value: Any) -> tuple[datetime, str] | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw or len(raw) > 100:
        return None
    normalized = raw
    if normalized.endswith(("Z", "z")):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed, parsed.isoformat()


def _attr_map(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
    return {str(key).casefold(): value or "" for key, value in attrs}


class TemporalHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.candidates: list[tuple[str, str, str]] = []
        self.visible_parts: list[str] = []
        self._jsonld_depth = 0
        self._jsonld_parts: list[str] = []
        self.jsonld_blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_key = tag.casefold()
        amap = _attr_map(attrs)
        if tag_key == "meta":
            marker = (amap.get("property") or amap.get("name") or amap.get("itemprop") or "").casefold()
            content = amap.get("content", "").strip()
            if marker in {"article:published_time", "datepublished", "date_published", "pubdate"} and content:
                self.candidates.append(("FIRST_PARTY_EXPLICIT_PUBLISHED_AT", content, f"meta:{marker}"))
        elif tag_key == "time":
            dt_value = amap.get("datetime", "").strip()
            marker = " ".join(
                [amap.get("itemprop", ""), amap.get("class", ""), amap.get("id", ""), amap.get("rel", "")]
            ).casefold()
            if dt_value and any(token in marker for token in ("datepublished", "publish", "posted", "article-date")):
                self.candidates.append(("FIRST_PARTY_EXPLICIT_DATETIME", dt_value, "time:datetime"))
        elif tag_key == "script" and amap.get("type", "").casefold().strip() == "application/ld+json":
            self._jsonld_depth += 1
            self._jsonld_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script" and self._jsonld_depth:
            block = "".join(self._jsonld_parts).strip()
            if block:
                self.jsonld_blocks.append(block)
            self._jsonld_depth = 0
            self._jsonld_parts = []

    def handle_data(self, data: str) -> None:
        if self._jsonld_depth:
            self._jsonld_parts.append(data)
            return
        value = re.sub(r"\s+", " ", data).strip()
        if value:
            self.visible_parts.append(value)


def _walk_jsonld(value: Any, out: list[tuple[str, str, str]]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() == "datepublished" and isinstance(item, str):
                out.append(("FIRST_PARTY_EXPLICIT_PUBLISHED_AT", item, "jsonld:datePublished"))
            else:
                _walk_jsonld(item, out)
    elif isinstance(value, list):
        for item in value:
            _walk_jsonld(item, out)


def extract_temporal(html_bytes: bytes) -> dict[str, Any]:
    try:
        source = html_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TemporalInputError("article HTML is not valid UTF-8") from exc
    parser = TemporalHTMLParser()
    parser.feed(source)
    parser.close()

    raw_candidates = list(parser.candidates)
    for block in parser.jsonld_blocks:
        try:
            parsed = json.loads(block)
        except (json.JSONDecodeError, TypeError):
            continue
        _walk_jsonld(parsed, raw_candidates)

    eligible: list[dict[str, Any]] = []
    rejected_naive = 0
    for basis, raw, extraction_source in raw_candidates:
        parsed = _aware_timestamp(raw)
        if parsed is None:
            rejected_naive += 1
            continue
        dt, normalized = parsed
        eligible.append(
            {
                "basis": basis,
                "timestamp": normalized,
                "instant": dt.astimezone(timezone.utc).isoformat(),
                "extraction_source": extraction_source,
            }
        )

    visible = " ".join(parser.visible_parts)
    date_match = re.search(r"\bData\s*:\s*([^|]{3,60}?)(?=\s+Ora\s*:|$)", visible, flags=re.IGNORECASE)
    time_match = re.search(r"\bOra\s*:\s*([0-2]?\d:[0-5]\d)\b", visible, flags=re.IGNORECASE)
    visible_unzoned = None
    if date_match or time_match:
        visible_unzoned = {
            "date_text": date_match.group(1).strip() if date_match else None,
            "time_text": time_match.group(1).strip() if time_match else None,
            "timestamp_authorized": False,
            "reason": "visible_date_or_time_has_no_explicit_utc_offset",
        }

    instants = sorted({str(item["instant"]) for item in eligible})
    conflict = len(instants) > 1
    selected = None
    if len(instants) == 1:
        priority = {
            "meta:article:published_time": 0,
            "meta:datepublished": 1,
            "jsonld:datePublished": 2,
            "time:datetime": 3,
        }
        selected = sorted(
            eligible,
            key=lambda item: (
                0 if item["basis"] == "FIRST_PARTY_EXPLICIT_PUBLISHED_AT" else 1,
                priority.get(str(item["extraction_source"]), 9),
                str(item["timestamp"]),
            ),
        )[0]

    return {
        "selected": selected,
        "conflict": conflict,
        "eligible_candidate_count": len(eligible),
        "rejected_unzoned_or_invalid_candidate_count": rejected_naive,
        "visible_unzoned_datetime": visible_unzoned,
        "candidate_sources": sorted({str(item["extraction_source"]) for item in eligible}),
    }


def fetch_article(url: str) -> tuple[bytes, str]:
    canonical, host, _family = canonical_reference_url(url)
    parsed = urlsplit(canonical)
    conn = http.client.HTTPSConnection(host, 443, timeout=20)
    try:
        conn.request(
            "GET",
            parsed.path,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html", "Accept-Encoding": "identity"},
        )
        response = conn.getresponse()
        if response.status != 200:
            raise TemporalInputError(f"unexpected HTTP status for {host}: {response.status}")
        if response.getheader("Location"):
            raise TemporalInputError("redirect response is not allowed")
        if "text/html" not in response.getheader("Content-Type", "").lower():
            raise TemporalInputError("traffic article source is not HTML")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise TemporalInputError("traffic article response exceeds byte limit")
        return body, canonical
    finally:
        conn.close()


def build_result(article_pages: list[tuple[str, bytes]]) -> dict[str, Any]:
    if not isinstance(article_pages, list) or not article_pages or len(article_pages) > MAX_REFERENCES:
        raise TemporalInputError("article pages must be a non-empty bounded list")

    seen: set[str] = set()
    entries: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    conflict_count = 0

    for supplied_url, html_bytes in article_pages:
        canonical, _host, family = canonical_reference_url(supplied_url)
        if canonical in seen:
            raise TemporalInputError("duplicate reference URL in temporal evidence request")
        seen.add(canonical)
        extracted = extract_temporal(html_bytes)
        conflict = bool(extracted["conflict"])
        if conflict:
            conflict_count += 1
        selected = extracted["selected"]
        if selected is not None and not conflict:
            entries.append(
                {
                    "url": canonical,
                    "timestamp": selected["timestamp"],
                    "basis": selected["basis"],
                    "timestamp_authorized": True,
                    "source_family": family,
                    "source_html_sha256": sha256(html_bytes),
                    "extraction_source": selected["extraction_source"],
                }
            )
        diagnostics.append(
            {
                "url": canonical,
                "source_family": family,
                "source_html_sha256": sha256(html_bytes),
                "timestamp_authorized": selected is not None and not conflict,
                "conflict": conflict,
                "eligible_candidate_count": extracted["eligible_candidate_count"],
                "rejected_unzoned_or_invalid_candidate_count": extracted[
                    "rejected_unzoned_or_invalid_candidate_count"
                ],
                "visible_unzoned_datetime": extracted["visible_unzoned_datetime"],
                "candidate_sources": extracted["candidate_sources"],
            }
        )

    entries.sort(key=lambda item: str(item["url"]))
    diagnostics.sort(key=lambda item: str(item["url"]))
    evidence = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "state": "CLEAR",
        "reason": "bounded_explicit_first_party_traffic_temporal_evidence",
        "content_contract": CONTENT_CONTRACT,
        "evidence_claim": (
            "Only offset-aware timestamps explicitly encoded by allowlisted first-party traffic article HTML are "
            "authorized. Visible local dates or times without an explicit UTC offset remain diagnostic only. "
            "Temporal evidence does not establish a current or active incident, same-incident identity, or publication authority."
        ),
        "requested_reference_count": len(article_pages),
        "authorized_timestamp_count": len(entries),
        "unresolved_reference_count": len(article_pages) - len(entries),
        "conflict_count": conflict_count,
        "entries": entries,
        "diagnostics": diagnostics,
        "evidence_sha256": sha256(evidence),
        "current_state_authorized": False,
        "active_incident_authorized": False,
        "same_incident_authorized": False,
        "breaking_news_authorized": False,
        "publication_authorized": False,
        "disabled_capabilities": DISABLED_CAPABILITIES,
    }


def _sample_page(*parts: str) -> bytes:
    return ("<!doctype html><html><head>" + "".join(parts) + "</head><body>Data: 1 Septembrie 2026 Ora: 10:00</body></html>").encode("utf-8")


def run_self_test() -> None:
    info_url = "https://politiaromana.ro/ro/info-trafic/judetul-valcea-trafic-oprit-pe-dn-7-test"
    ipj_url = "https://vl.politiaromana.ro/ro/stiri-si-media/stiri/accident-rutier-pe-dn-7-test"
    for bad in (
        "http://politiaromana.ro/ro/info-trafic/test",
        "https://www.politiaromana.ro/ro/info-trafic/test",
        "https://politiaromana.ro/ro/info-trafic/test?x=1",
        "https://politiaromana.ro/ro/stiri/test",
        "https://example.com/ro/info-trafic/test",
    ):
        try:
            canonical_reference_url(bad)
        except TemporalInputError:
            pass
        else:
            raise AssertionError(f"unsafe reference unexpectedly accepted: {bad}")

    published = _sample_page('<meta property="article:published_time" content="2026-09-01T10:00:00+03:00">')
    result = build_result([(info_url, published)])
    assert result["state"] == "CLEAR", result
    assert result["authorized_timestamp_count"] == 1, result
    assert result["entries"][0]["timestamp"] == "2026-09-01T10:00:00+03:00"
    assert result["entries"][0]["basis"] == "FIRST_PARTY_EXPLICIT_PUBLISHED_AT"

    zulu = _sample_page('<meta itemprop="datePublished" content="2026-09-01T07:00:00Z">')
    zulu_result = build_result([(ipj_url, zulu)])
    assert zulu_result["entries"][0]["timestamp"] == "2026-09-01T07:00:00+00:00"

    visible_only = b"<html><body>Data: 27 Februarie 2026 Ora: 14:15</body></html>"
    visible_result = build_result([(info_url, visible_only)])
    assert visible_result["authorized_timestamp_count"] == 0
    assert visible_result["diagnostics"][0]["visible_unzoned_datetime"]["timestamp_authorized"] is False

    naive = _sample_page('<meta property="article:published_time" content="2026-09-01T10:00:00">')
    naive_result = build_result([(info_url, naive)])
    assert naive_result["authorized_timestamp_count"] == 0
    assert naive_result["diagnostics"][0]["rejected_unzoned_or_invalid_candidate_count"] == 1

    conflict = _sample_page(
        '<meta property="article:published_time" content="2026-09-01T10:00:00+03:00">',
        '<script type="application/ld+json">{"datePublished":"2026-09-01T11:00:00+03:00"}</script>',
    )
    conflict_result = build_result([(info_url, conflict)])
    assert conflict_result["authorized_timestamp_count"] == 0
    assert conflict_result["conflict_count"] == 1

    same_instant = _sample_page(
        '<meta property="article:published_time" content="2026-09-01T10:00:00+03:00">',
        '<script type="application/ld+json">{"datePublished":"2026-09-01T07:00:00Z"}</script>',
        '<time itemprop="datePublished" datetime="2026-09-01T09:00:00+02:00">posted</time>',
    )
    same_result = build_result([(info_url, same_instant)])
    assert same_result["authorized_timestamp_count"] == 1, same_result
    assert same_result["entries"][0]["extraction_source"] == "meta:article:published_time"

    for flag in (
        "current_state_authorized",
        "active_incident_authorized",
        "same_incident_authorized",
        "breaking_news_authorized",
        "publication_authorized",
    ):
        assert same_result[flag] is False
    assert "local_timezone_inference" in same_result["disabled_capabilities"]
    print("self-test: ok")


def _load_reference_payload(path: str) -> list[str]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("state") != "CLEAR":
        raise TemporalInputError("reference payload is not CLEAR")
    refs = data.get("references")
    if not isinstance(refs, list) or len(refs) > MAX_REFERENCES:
        raise TemporalInputError("reference payload references are invalid")
    urls: list[str] = []
    for item in refs:
        if not isinstance(item, dict) or not isinstance(item.get("url"), str):
            raise TemporalInputError("reference payload item has no URL")
        urls.append(str(item["url"]))
    return urls


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--reference-url", action="append", default=[])
    parser.add_argument("--references-file", action="append", default=[])
    args = parser.parse_args(argv)
    if args.self_test:
        run_self_test()
        return 0

    try:
        urls = list(args.reference_url)
        for path in args.references_file:
            urls.extend(_load_reference_payload(path))
        if not urls or len(urls) > MAX_REFERENCES:
            raise TemporalInputError("provide between 1 and 24 bounded traffic references")
        pages: list[tuple[str, bytes]] = []
        for url in urls:
            body, canonical = fetch_article(url)
            pages.append((canonical, body))
        result = build_result(pages)
    except (TemporalInputError, OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
        result = {
            "state": "HOLD",
            "reason": "traffic_explicit_temporal_evidence_fetch_or_validation_failed",
            "error": str(exc),
            "content_contract": CONTENT_CONTRACT,
            "entries": [],
            "current_state_authorized": False,
            "breaking_news_authorized": False,
            "publication_authorized": False,
            "disabled_capabilities": DISABLED_CAPABILITIES,
        }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if result.get("state") == "CLEAR" else 2


if __name__ == "__main__":
    raise SystemExit(main())
