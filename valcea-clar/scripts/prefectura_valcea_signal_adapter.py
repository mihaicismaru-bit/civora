#!/usr/bin/env python3
"""Extract dated Prefectura Vâlcea press signals without publication authority.

This adapter is intentionally narrow and fail-closed. It accepts only direct HTTPS
article URLs on the official Vâlcea prefecture host, requires a press-material title
and explicit `Publicat în ...` metadata immediately after that title, and emits
signal-only evidence for editorial verification. It does not crawl the homepage,
persist newsroom state, build facts, or authorize publication.
"""
from __future__ import annotations

import argparse
import hashlib
import html.parser
import json
import re
import ssl
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

SOURCE_ID = "signal-prefectura-valcea-press"
SOURCE_NAME = "Instituția Prefectului — Județul Vâlcea"
SOURCE_ROOT = "https://vl.prefectura.mai.gov.ro/"
SOURCE_TIER = "T1"
SOURCE_KIND = "PUBLIC_ADMINISTRATION_PREFECTURE_PRESS"
OFFICIAL_HOST = "vl.prefectura.mai.gov.ro"
USER_AGENT = "Mozilla/5.0 VÂLCEA-CLAR-Prefectura-Signal/1.0 (+https://valceaclar.ro/)"
MAX_BODY_BYTES = 2_000_000
MAX_METADATA_DISTANCE = 700
MAX_EXCERPT = 1400
PRESS_PREFIXES = ("comunicat de presa", "informare de presa")
RO_MONTHS = {
    "ianuarie": 1,
    "februarie": 2,
    "martie": 3,
    "aprilie": 4,
    "mai": 5,
    "iunie": 6,
    "iulie": 7,
    "august": 8,
    "septembrie": 9,
    "octombrie": 10,
    "noiembrie": 11,
    "decembrie": 12,
}


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", clean_text(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def validate_article_url(value: str) -> str:
    parsed = urlsplit(clean_text(value))
    if parsed.scheme.casefold() != "https":
        raise ValueError("Prefectura adapter requires HTTPS article URLs")
    if parsed.username or parsed.password:
        raise ValueError("Prefectura adapter refuses credential-bearing URLs")
    if parsed.hostname is None or parsed.hostname.casefold() != OFFICIAL_HOST:
        raise ValueError(
            f"Prefectura adapter refused non-official host: {parsed.hostname or '<empty>'}"
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Prefectura adapter refused malformed port") from exc
    if port not in (None, 443):
        raise ValueError("Prefectura adapter refuses non-standard ports")
    if parsed.path in ("", "/"):
        raise ValueError("Prefectura adapter requires a direct article path")
    return urlunsplit(("https", OFFICIAL_HOST, parsed.path, parsed.query, ""))


class PageParser(html.parser.HTMLParser):
    """Collect visible text and H1 candidates while excluding active/non-visible payloads."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.h1_depth = 0
        self.h1_parts: list[str] = []
        self.h1_candidates: list[str] = []
        self.visible_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "template"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "h1":
            self.h1_depth += 1
            self.h1_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "template"} and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag == "h1" and self.h1_depth:
            self.h1_depth -= 1
            title = clean_text(" ".join(self.h1_parts))
            if title:
                self.h1_candidates.append(title)
            self.h1_parts = []

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = clean_text(data)
        if not text:
            return
        self.visible_parts.append(text)
        if self.h1_depth:
            self.h1_parts.append(text)


def press_title(title: str) -> bool:
    normalized = fold(title)
    return any(normalized.startswith(prefix) for prefix in PRESS_PREFIXES)


def choose_press_title(candidates: list[str]) -> str:
    for title in candidates:
        if press_title(title):
            return clean_text(title)
    raise ValueError("Prefectura page is not an allowed press material")


def parse_publication_metadata(text_after_title: str) -> dict[str, str]:
    """Require explicit source publication metadata, not dates inferred from the title/body."""
    value = fold(text_after_title[:MAX_METADATA_DISTANCE])
    numeric = re.search(
        r"\bpublicat\s+in\s+([0-3]?\d)[./-]([01]?\d)[./-]((?:20)\d{2})\b",
        value,
    )
    if numeric:
        evidence = numeric.group(0)
        try:
            published = date(int(numeric.group(3)), int(numeric.group(2)), int(numeric.group(1)))
        except ValueError as exc:
            raise ValueError("Prefectura page has invalid publication metadata date") from exc
        return {
            "publication_date": published.isoformat(),
            "publication_precision": "EXACT_DATE",
            "publication_evidence": evidence,
        }

    month_alt = "|".join(RO_MONTHS)
    named = re.search(
        rf"\bpublicat\s+in\s+([0-3]?\d)\s+({month_alt})\s+((?:20)\d{{2}})\b",
        value,
    )
    if named:
        evidence = named.group(0)
        try:
            published = date(
                int(named.group(3)),
                RO_MONTHS[named.group(2)],
                int(named.group(1)),
            )
        except ValueError as exc:
            raise ValueError("Prefectura page has invalid publication metadata date") from exc
        return {
            "publication_date": published.isoformat(),
            "publication_precision": "EXACT_DATE",
            "publication_evidence": evidence,
        }

    raise ValueError(
        "Prefectura page lacks explicit `Publicat în <exact date>` metadata near the title"
    )


def extract_page_evidence(html_text: str) -> tuple[str, str, dict[str, str]]:
    parser = PageParser()
    parser.feed(html_text)
    parser.close()
    title = choose_press_title(parser.h1_candidates)
    visible = clean_text(" ".join(parser.visible_parts))
    index = visible.find(title)
    if index < 0:
        raise ValueError("Prefectura adapter could not anchor visible metadata to the press title")
    after_title = visible[index + len(title):]
    publication = parse_publication_metadata(after_title)
    return title, after_title, publication


def signal_id(final_url: str, title: str, publication_date: str) -> str:
    raw = "\0".join([SOURCE_ID, final_url, clean_text(title), publication_date])
    return "prefectura-press-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def extract_signal(
    html_text: str,
    *,
    requested_url: str,
    final_url: str,
    content_sha256: str,
) -> dict[str, Any]:
    requested = validate_article_url(requested_url)
    final = validate_article_url(final_url)
    title, after_title, publication = extract_page_evidence(html_text)
    sid = signal_id(final, title, publication["publication_date"])
    excerpt = clean_text(after_title)
    return {
        "signal_id": sid,
        "source_id": SOURCE_ID,
        "source_name": SOURCE_NAME,
        "source_root": SOURCE_ROOT,
        "source_tier": SOURCE_TIER,
        "source_kind": SOURCE_KIND,
        "requested_url": requested,
        "article_url": final,
        "source_content_sha256": content_sha256,
        "title": title,
        **publication,
        "publication_date_semantics": "SOURCE_PAGE_PUBLICATION_METADATA",
        "excerpt": excerpt[:MAX_EXCERPT],
        "lifecycle": "SIGNAL_ONLY_NEEDS_EDITORIAL_VERIFICATION",
        "publication_authority": "NONE",
        "public_projection": False,
        "auto_publication": False,
        "provenance": {
            "authority": "PREFECTURA_VALCEA_OFFICIAL",
            "official_host": OFFICIAL_HOST,
            "retrieval_surface": final,
            "temporal_basis": "EXPLICIT_VISIBLE_PUBLICAT_IN_METADATA_NEAR_TITLE",
        },
    }


def html_response_ok(content_type: str, body: bytes) -> bool:
    return "html" in content_type.casefold() or b"<html" in body[:2000].lower()


def fetch_html(url: str) -> tuple[str, str, str]:
    requested = validate_article_url(url)
    request = Request(
        requested,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
    )
    with urlopen(request, timeout=18, context=ssl.create_default_context()) as response:
        final_url = validate_article_url(str(response.geturl()))
        body = response.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            raise ValueError("Prefectura source response exceeds bounded body limit")
        content_type = str(response.headers.get("Content-Type") or "")
        if not html_response_ok(content_type, body):
            raise ValueError(
                f"Prefectura source did not return HTML: {content_type or 'unknown'}"
            )
        charset = response.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace"), final_url, hashlib.sha256(body).hexdigest()


def build_document(urls: list[str]) -> dict[str, Any]:
    normalized_urls: list[str] = []
    seen_urls: set[str] = set()
    for value in urls:
        normalized = validate_article_url(value)
        if normalized in seen_urls:
            continue
        seen_urls.add(normalized)
        normalized_urls.append(normalized)

    signals: list[dict[str, Any]] = []
    seen_signals: set[str] = set()
    for url in normalized_urls:
        html_text, final_url, body_sha = fetch_html(url)
        signal = extract_signal(
            html_text,
            requested_url=url,
            final_url=final_url,
            content_sha256=body_sha,
        )
        if signal["signal_id"] in seen_signals:
            continue
        seen_signals.add(signal["signal_id"])
        signals.append(signal)

    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR Prefectura Vâlcea press signals",
        "source_id": SOURCE_ID,
        "source_root": SOURCE_ROOT,
        "input_url_count": len(normalized_urls),
        "signal_count": len(signals),
        "signals": signals,
        "policy": {
            "publication_authority": "NONE",
            "signal_only": True,
            "public_projection": False,
            "auto_publication": False,
            "direct_official_article_url_required": True,
            "press_material_title_required": True,
            "explicit_publication_metadata_required": True,
            "homepage_crawl_enabled": False,
            "persistence_enabled": False,
        },
    }


def self_test() -> int:
    sample_named = """
    <HTML><body>
      <h1>COMUNICAT DE PRESĂ – măsuri de siguranță</h1>
      <div>Publicat în 14 aprilie 2026</div>
      <p>Instituția Prefectului informează publicul asupra măsurilor dispuse.</p>
    </body></HTML>
    """
    sample_numeric = """
    <html><body>
      <h1>Comunicat de presă – 10.02.2026</h1>
      <p>Publicat în 13/02/2026 de vlceaprefectura</p>
      <p>Material oficial.</p>
    </body></html>
    """
    sample_info = """
    <html><body>
      <h1>INFORMARE DE PRESĂ privind Colegiul Prefectural</h1>
      <span>Publicat în 30 aprilie 2025</span>
      <p>Informare oficială.</p>
    </body></html>
    """
    official = "https://vl.prefectura.mai.gov.ro/comunicat-de-presa-test/"
    signal = extract_signal(
        sample_named,
        requested_url=official,
        final_url=official,
        content_sha256="abc",
    )
    assert signal["publication_date"] == "2026-04-14"
    assert signal["publication_authority"] == "NONE"
    assert signal["auto_publication"] is False
    assert signal["lifecycle"] == "SIGNAL_ONLY_NEEDS_EDITORIAL_VERIFICATION"

    numeric = extract_signal(
        sample_numeric,
        requested_url=official,
        final_url=official,
        content_sha256="def",
    )
    assert numeric["publication_date"] == "2026-02-13"

    info = extract_signal(
        sample_info,
        requested_url=official,
        final_url=official,
        content_sha256="ghi",
    )
    assert info["publication_date"] == "2025-04-30"

    title_date_only = """
    <html><body>
      <h1>COMUNICAT DE PRESĂ – 10.02.2026</h1>
      <p>Material oficial fără metadată de publicare.</p>
    </body></html>
    """
    try:
        extract_signal(
            title_date_only,
            requested_url=official,
            final_url=official,
            content_sha256="x",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("date in title must not substitute for publication metadata")

    generic_page = """
    <html><body>
      <h1>Ședința Colegiului Prefectural</h1>
      <p>Publicat în 14 aprilie 2026</p>
    </body></html>
    """
    try:
        extract_signal(
            generic_page,
            requested_url=official,
            final_url=official,
            content_sha256="y",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("non-press title must fail closed")

    try:
        validate_article_url("https://example.com/comunicat/")
    except ValueError:
        pass
    else:
        raise AssertionError("off-domain URL must fail closed")

    try:
        extract_signal(
            sample_named,
            requested_url=official,
            final_url="https://example.com/redirected/",
            content_sha256="z",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("off-domain final redirect must fail closed")

    assert html_response_ok("text/html; charset=utf-8", b"plain") is True
    assert html_response_ok("text/plain", b"<HTML><body>ok</body></HTML>") is True
    assert html_response_ok("application/octet-stream", b"not html") is False

    metadata_too_far = (
        "<html><body><h1>Comunicat de presă test</h1><p>"
        + ("x" * (MAX_METADATA_DISTANCE + 30))
        + "</p><p>Publicat în 14 aprilie 2026</p></body></html>"
    )
    try:
        extract_signal(
            metadata_too_far,
            requested_url=official,
            final_url=official,
            content_sha256="q",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("distant page metadata must not be accepted as article metadata")

    print("VÂLCEA CLAR Prefectura press signal adapter self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--url", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.url:
        parser.error("at least one direct official --url is required")

    document = build_document(args.url)
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "source_id": SOURCE_ID,
        "signal_count": document["signal_count"],
        "publication_authority": "NONE",
        "output": str(args.output) if args.output else None,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
