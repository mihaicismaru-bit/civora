#!/usr/bin/env python3
"""Extract current Vâlcea road-traffic signals from the official INFOTRAFIC surface.

This adapter is intentionally fail-closed. It discovers only current listing links whose
visible title starts with ``JUDEȚUL VÂLCEA:``, then validates the direct official article
and preserves its source date/time/category/status as evidence. Output remains signal-only
and cannot authorize publication or a live-traffic claim without editorial verification.
"""
from __future__ import annotations

import argparse
import hashlib
import html.parser
import json
import re
import ssl
import unicodedata
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

SOURCE_ID = "signal-infotrafic-valcea"
SOURCE_NAME = "Centrul INFOTRAFIC — alerte Vâlcea"
SOURCE_ROOT = "https://politiaromana.ro/ro/info-trafic"
SOURCE_TIER = "T1"
SOURCE_KIND = "ROAD_TRAFFIC_ALERTS"
OFFICIAL_HOST = "politiaromana.ro"
ARTICLE_PREFIX = "/ro/info-trafic/"
TITLE_PREFIX = "judetul valcea:"
USER_AGENT = "Mozilla/5.0 VÂLCEA-CLAR-INFOTRAFIC-Signal/1.0 (+https://valceaclar.ro/)"
MAX_BODY_BYTES = 2_000_000
MAX_EXCERPT = 1600
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


def validate_url(value: str, *, article_required: bool) -> str:
    parsed = urlsplit(clean_text(value))
    if parsed.scheme.casefold() != "https":
        raise ValueError("INFOTRAFIC adapter requires HTTPS URLs")
    if parsed.username or parsed.password:
        raise ValueError("INFOTRAFIC adapter refuses credential-bearing URLs")
    if parsed.hostname is None or parsed.hostname.casefold() != OFFICIAL_HOST:
        raise ValueError(
            f"INFOTRAFIC adapter refused non-official host: {parsed.hostname or '<empty>'}"
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("INFOTRAFIC adapter refused malformed port") from exc
    if port not in (None, 443):
        raise ValueError("INFOTRAFIC adapter refuses non-standard ports")

    path = parsed.path.rstrip("/") or "/"
    if article_required:
        if not path.startswith(ARTICLE_PREFIX.rstrip("/") + "/"):
            raise ValueError("INFOTRAFIC adapter requires a direct info-trafic article path")
        if path == ARTICLE_PREFIX.rstrip("/"):
            raise ValueError("INFOTRAFIC adapter requires a direct article, not the listing")
    elif path != "/ro/info-trafic":
        raise ValueError("INFOTRAFIC discovery is limited to the canonical listing root")

    return urlunsplit(("https", OFFICIAL_HOST, path, parsed.query if article_required else "", ""))


class PageParser(html.parser.HTMLParser):
    """Collect visible text, H3 candidates, and anchor text/hrefs."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.h3_depth = 0
        self.h3_parts: list[str] = []
        self.h3_candidates: list[str] = []
        self.anchor_depth = 0
        self.anchor_href: str | None = None
        self.anchor_parts: list[str] = []
        self.anchors: list[tuple[str, str]] = []
        self.visible_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "template"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "h3":
            self.h3_depth += 1
            self.h3_parts = []
        if tag == "a":
            self.anchor_depth += 1
            self.anchor_parts = []
            self.anchor_href = None
            for key, value in attrs:
                if str(key).casefold() == "href" and value:
                    self.anchor_href = str(value)
                    break

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "template"} and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag == "h3" and self.h3_depth:
            self.h3_depth -= 1
            text = clean_text(" ".join(self.h3_parts))
            if text:
                self.h3_candidates.append(text)
            self.h3_parts = []
        if tag == "a" and self.anchor_depth:
            self.anchor_depth -= 1
            text = clean_text(" ".join(self.anchor_parts))
            if self.anchor_href and text:
                self.anchors.append((self.anchor_href, text))
            self.anchor_href = None
            self.anchor_parts = []

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = clean_text(data)
        if not text:
            return
        self.visible_parts.append(text)
        if self.h3_depth:
            self.h3_parts.append(text)
        if self.anchor_depth:
            self.anchor_parts.append(text)


def is_valcea_title(title: str) -> bool:
    return fold(title).startswith(TITLE_PREFIX)


def discover_valcea_article_urls(html_text: str) -> list[str]:
    parser = PageParser()
    parser.feed(html_text)
    parser.close()
    found: list[str] = []
    seen: set[str] = set()
    for href, label in parser.anchors:
        if not is_valcea_title(label):
            continue
        candidate = urljoin(SOURCE_ROOT + "/", href)
        try:
            normalized = validate_url(candidate, article_required=True)
        except ValueError:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        found.append(normalized)
    return found


def choose_valcea_title(candidates: list[str]) -> str:
    for title in candidates:
        if is_valcea_title(title):
            return clean_text(title)
    raise ValueError("INFOTRAFIC page is not a Vâlcea traffic article")


def parse_source_metadata(visible: str, title: str) -> dict[str, Any]:
    folded = fold(visible)
    if "sursa: infotrafic" not in folded and "sursa:infotrafic" not in folded:
        raise ValueError("INFOTRAFIC page lacks explicit INFOTRAFIC source attribution")

    title_pos = visible.find(title)
    if title_pos < 0:
        raise ValueError("INFOTRAFIC adapter could not anchor metadata to the article title")
    before_title = visible[:title_pos]
    after_title = visible[title_pos + len(title):]

    category_match = re.search(
        r"Categorie\s*:\s*([^:]{2,80}?)(?=\s+Status\s*:|$)", before_title, re.IGNORECASE
    )
    category = clean_text(category_match.group(1)) if category_match else None
    if not category:
        raise ValueError("INFOTRAFIC page lacks a source category")

    status_match = re.search(r"Status\s*:\s*([A-Za-zĂÂÎȘŞȚŢăâîșşțţ]+)", before_title, re.IGNORECASE)
    source_status = clean_text(status_match.group(1)) if status_match else None

    month_alt = "|".join(RO_MONTHS)
    date_match = re.search(
        rf"\bData\s*:\s*([0-3]?\d)\s+({month_alt})\s+((?:20)\d{{2}})\b",
        fold(after_title),
    )
    if not date_match:
        raise ValueError("INFOTRAFIC page lacks an exact source date")
    time_match = re.search(r"\bOra\s*:\s*([0-2]?\d):([0-5]\d)\b", fold(after_title))
    if not time_match:
        raise ValueError("INFOTRAFIC page lacks an exact source time")

    try:
        source_dt = datetime(
            int(date_match.group(3)),
            RO_MONTHS[date_match.group(2)],
            int(date_match.group(1)),
            int(time_match.group(1)),
            int(time_match.group(2)),
            tzinfo=ZoneInfo("Europe/Bucharest"),
        )
    except ValueError as exc:
        raise ValueError("INFOTRAFIC page has invalid source date/time metadata") from exc

    time_literal = time_match.group(0)
    folded_after = fold(after_title)
    folded_time_pos = folded_after.find(time_literal)
    excerpt = ""
    if folded_time_pos >= 0:
        # The folded and original strings differ only by diacritics/spacing normalization in normal pages;
        # use the original marker instead when available and otherwise fall back to metadata-stripped text.
        original_time = re.search(r"\bOra\s*:\s*[0-2]?\d:[0-5]\d\b", after_title, re.IGNORECASE)
        body = after_title[original_time.end():] if original_time else after_title
        for stop in (
            "Recomandări utile pentru un trafic în siguranță",
            "Informații, prognoze și avertizări meteo",
            "Situația drumurilor naționale",
        ):
            idx = body.find(stop)
            if idx >= 0:
                body = body[:idx]
        excerpt = clean_text(body)[:MAX_EXCERPT]

    if not excerpt:
        raise ValueError("INFOTRAFIC page lacks a bounded article body excerpt")

    return {
        "source_category": category,
        "source_status": source_status,
        "source_timestamp": source_dt.isoformat(),
        "source_date": source_dt.date().isoformat(),
        "source_time": source_dt.strftime("%H:%M"),
        "excerpt": excerpt,
    }


def signal_id(final_url: str, title: str, source_timestamp: str) -> str:
    raw = "\0".join([SOURCE_ID, final_url, clean_text(title), source_timestamp])
    return "infotrafic-valcea-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def extract_signal(
    html_text: str,
    *,
    requested_url: str,
    final_url: str,
    content_sha256: str,
) -> dict[str, Any]:
    requested = validate_url(requested_url, article_required=True)
    final = validate_url(final_url, article_required=True)
    parser = PageParser()
    parser.feed(html_text)
    parser.close()
    title = choose_valcea_title(parser.h3_candidates)
    visible = clean_text(" ".join(parser.visible_parts))
    metadata = parse_source_metadata(visible, title)
    sid = signal_id(final, title, metadata["source_timestamp"])
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
        **metadata,
        "status_semantics": "SOURCE_PAGE_LABEL_ONLY_RECHECK_BEFORE_CURRENT_STATUS_USE",
        "timestamp_semantics": "EXPLICIT_INFOTRAFIC_SOURCE_DATE_TIME_EUROPE_BUCHAREST",
        "lifecycle": "SIGNAL_ONLY_NEEDS_EDITORIAL_VERIFICATION",
        "publication_authority": "NONE",
        "public_projection": False,
        "auto_publication": False,
        "provenance": {
            "authority": "POLITIA_ROMANA_INFOTRAFIC",
            "official_host": OFFICIAL_HOST,
            "retrieval_surface": final,
            "discovery_surface": SOURCE_ROOT,
            "local_filter": "VISIBLE_TITLE_PREFIX_JUDETUL_VALCEA",
        },
    }


def html_response_ok(content_type: str, body: bytes) -> bool:
    return "html" in content_type.casefold() or b"<html" in body[:2000].lower()


def fetch_html(url: str, *, article_required: bool) -> tuple[str, str, str]:
    requested = validate_url(url, article_required=article_required)
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
        final_url = validate_url(str(response.geturl()), article_required=article_required)
        body = response.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            raise ValueError("INFOTRAFIC response exceeds bounded body limit")
        content_type = str(response.headers.get("Content-Type") or "")
        if not html_response_ok(content_type, body):
            raise ValueError(f"INFOTRAFIC source did not return HTML: {content_type or 'unknown'}")
        charset = response.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace"), final_url, hashlib.sha256(body).hexdigest()


def build_document(*, direct_urls: list[str], discover_current: bool) -> dict[str, Any]:
    urls: list[str] = []
    seen_urls: set[str] = set()

    if discover_current:
        listing_html, final_listing, _ = fetch_html(SOURCE_ROOT, article_required=False)
        if final_listing != SOURCE_ROOT:
            raise ValueError("INFOTRAFIC listing redirected away from the canonical root")
        for url in discover_valcea_article_urls(listing_html):
            if url not in seen_urls:
                seen_urls.add(url)
                urls.append(url)

    for value in direct_urls:
        normalized = validate_url(value, article_required=True)
        if normalized not in seen_urls:
            seen_urls.add(normalized)
            urls.append(normalized)

    signals: list[dict[str, Any]] = []
    seen_signals: set[str] = set()
    for url in urls:
        html_text, final_url, body_sha = fetch_html(url, article_required=True)
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
        "product": "VÂLCEA CLAR INFOTRAFIC Vâlcea signals",
        "source_id": SOURCE_ID,
        "source_root": SOURCE_ROOT,
        "discovery_enabled": discover_current,
        "article_count": len(urls),
        "signal_count": len(signals),
        "signals": signals,
        "policy": {
            "publication_authority": "NONE",
            "signal_only": True,
            "public_projection": False,
            "auto_publication": False,
            "current_listing_only": True,
            "visible_valcea_title_filter_required": True,
            "direct_official_article_validation_required": True,
            "source_status_is_candidate_only": True,
            "persistence_enabled": False,
            "fact_kernel_enabled": False,
        },
    }


def self_test() -> int:
    listing = """
    <html><body>
      <h3><a href="/ro/info-trafic/judetul-valcea-trafic-ingreunat-pe-dn-7">JUDEȚUL VÂLCEA: TRAFIC ÎNGREUNAT PE DN 7</a></h3>
      <h3><a href="/ro/info-trafic/judetul-brasov-trafic-ingreunat-pe-dn-1">JUDEȚUL BRAȘOV: TRAFIC ÎNGREUNAT PE DN 1</a></h3>
      <a href="https://evil.example/ro/info-trafic/judetul-valcea-fals">JUDEȚUL VÂLCEA: FALS</a>
    </body></html>
    """
    discovered = discover_valcea_article_urls(listing)
    assert discovered == [
        "https://politiaromana.ro/ro/info-trafic/judetul-valcea-trafic-ingreunat-pe-dn-7"
    ]

    active = """
    <HTML><body>
      <div>Sursa: INFOTRAFIC Categorie: Alerta trafic Status: Activ</div>
      <h3>JUDEȚUL VÂLCEA: TRAFIC OPRIT PE DN 7</h3>
      <div>Data: 28 August 2026</div><div>Ora: 16:35</div>
      <p>Centrul INFOTRAFIC informează că traficul este oprit temporar.</p>
      <div>Recomandări utile pentru un trafic în siguranță</div>
    </body></HTML>
    """
    url = "https://politiaromana.ro/ro/info-trafic/judetul-valcea-trafic-oprit-pe-dn-7"
    signal = extract_signal(
        active,
        requested_url=url,
        final_url=url,
        content_sha256="abc",
    )
    assert signal["source_date"] == "2026-08-28"
    assert signal["source_time"] == "16:35"
    assert signal["source_status"] == "Activ"
    assert signal["publication_authority"] == "NONE"
    assert signal["auto_publication"] is False
    assert signal["lifecycle"] == "SIGNAL_ONLY_NEEDS_EDITORIAL_VERIFICATION"

    inactive = active.replace("Status: Activ", "Status: Inactiv")
    signal2 = extract_signal(
        inactive,
        requested_url=url,
        final_url=url,
        content_sha256="def",
    )
    assert signal2["source_status"] == "Inactiv"

    wrong_county = active.replace("JUDEȚUL VÂLCEA", "JUDEȚUL SIBIU")
    try:
        extract_signal(wrong_county, requested_url=url, final_url=url, content_sha256="x")
        raise AssertionError("wrong-county page unexpectedly passed")
    except ValueError:
        pass

    no_source = active.replace("Sursa: INFOTRAFIC", "Sursa: ALTCEVA")
    try:
        extract_signal(no_source, requested_url=url, final_url=url, content_sha256="x")
        raise AssertionError("missing INFOTRAFIC attribution unexpectedly passed")
    except ValueError:
        pass

    no_time = active.replace("Ora: 16:35", "")
    try:
        extract_signal(no_time, requested_url=url, final_url=url, content_sha256="x")
        raise AssertionError("missing source time unexpectedly passed")
    except ValueError:
        pass

    try:
        validate_url("https://example.com/ro/info-trafic/judetul-valcea", article_required=True)
        raise AssertionError("off-domain URL unexpectedly passed")
    except ValueError:
        pass

    assert html_response_ok("application/octet-stream", b"<HTML><body>x</body></HTML>")
    assert not html_response_ok("application/json", b'{"ok":true}')
    print("PASS: INFOTRAFIC Vâlcea signal adapter self-test")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="*", help="Direct official INFOTRAFIC Vâlcea article URLs")
    parser.add_argument(
        "--discover-current",
        action="store_true",
        help="Discover Vâlcea-titled articles from the canonical current INFOTRAFIC listing",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if not args.urls and not args.discover_current:
        parser.error("provide direct article URLs and/or --discover-current")

    document = build_document(direct_urls=args.urls, discover_current=args.discover_current)
    print(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
