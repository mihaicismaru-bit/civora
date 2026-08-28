#!/usr/bin/env python3
"""Discover and enrich BJAI Vâlcea event signals without publication or image-reuse authority.

The adapter is evidence-first and deliberately bounded:
- archive pages may discover official event URLs, explicit CMS publication metadata and media;
- direct event pages may add event date/time only when visible source text states it explicitly;
- anti-bot/interstitial responses fail closed for enrichment;
- official-site images remain provenance-only Visual Desk candidates with unknown reuse rights;
- no output is reader-facing, persistent, Fact Kernel-authoritative or publishable.
"""
from __future__ import annotations

import argparse
import hashlib
import html.parser
import json
import re
import ssl
import unicodedata
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

SOURCE_ID = "signal-bjai-valcea-events"
SOURCE_NAME = "Biblioteca Județeană „Antim Ivireanul” Vâlcea — Evenimente"
SOURCE_URL = "https://www.bjai.ro/evenimente/"
SOURCE_TIER = "T1B"
SOURCE_KIND = "CULTURE_LIBRARY_EVENTS"
OFFICIAL_HOSTS = {"bjai.ro", "www.bjai.ro"}
USER_AGENT = "Mozilla/5.0 VÂLCEA-CLAR-BJAI-Signal/1.0 (+https://valceaclar.ro/)"
MAX_BODY_BYTES = 2_000_000
MAX_PAGES = 10
GENERIC_MEDIA_FILENAMES = {"logo-biblioteca-judeteana-valcea.png"}
CHALLENGE_MARKERS = (
    "please wait while your request is being verified",
    "checking your browser before accessing",
    "verify you are human",
)
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
MONTH_ALT = "|".join(RO_MONTHS)
CMS_DATE_RE = re.compile(
    rf"\bpostare\s+din\s*:\s*([0-3]?\d)\s+({MONTH_ALT})\s+((?:20)\d{{2}})\b",
    re.IGNORECASE,
)
SINGLE_EVENT_RE = re.compile(
    rf"\b([0-3]?\d)\s+({MONTH_ALT})\s+((?:20)\d{{2}})"
    r"(?:\s*,?\s*(?:ora|orele)\s+([0-2]?\d[:.][0-5]\d)"
    r"(?:\s*(?:-|–|—)\s*([0-2]?\d[:.][0-5]\d))?)?",
    re.IGNORECASE,
)
SAME_MONTH_RANGE_RE = re.compile(
    rf"\b(?:intre|între)?\s*([0-3]?\d)\s*(?:-|–|—)\s*([0-3]?\d)\s+"
    rf"({MONTH_ALT})\s+((?:20)\d{{2}})\b",
    re.IGNORECASE,
)
NUMERIC_RANGE_RE = re.compile(
    r"\b([0-3]?\d)[.\/]([01]?\d)\s*(?:-|–|—)\s*"
    r"([0-3]?\d)[.\/]([01]?\d)[.\/]((?:20)\d{2})\b"
)


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", clean_text(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _official_https(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme.casefold() == "https"
        and parsed.hostname is not None
        and parsed.hostname.casefold() in OFFICIAL_HOSTS
        and not parsed.username
        and not parsed.password
    )


def normalize_archive_url(value: str) -> str:
    text = clean_text(value)
    if not _official_https(text):
        raise ValueError("BJAI archive adapter requires official HTTPS host")
    parsed = urlsplit(text)
    path = re.sub(r"/+", "/", parsed.path or "/")
    if path == "/evenimente":
        path = "/evenimente/"
    if path != "/evenimente/" and not re.fullmatch(r"/evenimente/page/[1-9]\d*/", path):
        raise ValueError("BJAI archive adapter refuses non-archive URL")
    return urlunsplit(("https", "www.bjai.ro", path, "", ""))


def normalize_event_url(value: str, *, base_url: str = SOURCE_URL) -> str:
    text = clean_text(value)
    joined = urljoin(base_url, text)
    if not _official_https(joined):
        raise ValueError("BJAI event adapter requires official HTTPS host")
    parsed = urlsplit(joined)
    path = re.sub(r"/+", "/", parsed.path or "/")
    if not path.endswith("/"):
        path += "/"
    if not re.fullmatch(r"/evenimente/[^/]+/", path):
        raise ValueError("BJAI event adapter requires direct /evenimente/<slug>/ URL")
    if "/page/" in path:
        raise ValueError("BJAI event adapter refuses pagination as event")
    return urlunsplit(("https", "www.bjai.ro", path, "", ""))


def normalize_media_url(value: str, *, base_url: str = SOURCE_URL) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    joined = urljoin(base_url, text)
    if not _official_https(joined):
        return None
    parsed = urlsplit(joined)
    path = re.sub(r"/+", "/", parsed.path or "/")
    filename = path.rsplit("/", 1)[-1].casefold()
    if not path.startswith("/wp-content/uploads/") or filename in GENERIC_MEDIA_FILENAMES:
        return None
    return urlunsplit(("https", "www.bjai.ro", path, "", ""))


def _parse_source_date(day: str, month_name: str, year: str) -> str | None:
    try:
        month = RO_MONTHS[fold(month_name)]
        parsed = date(int(year), month, int(day))
    except (KeyError, ValueError):
        return None
    return parsed.isoformat()


class ArchiveParser(html.parser.HTMLParser):
    """Collect event links and optional evidence from article cards, with a safe link fallback."""

    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.article_depth = 0
        self.current: dict[str, Any] | None = None
        self.capture_href: str | None = None
        self.capture_parts: list[str] = []
        self.fallback: dict[str, str] = {}
        self.items: list[dict[str, Any]] = []
        self.next_page_url: str | None = None
        self.skip_depth = 0

    def _start_article(self) -> None:
        self.current = {
            "article_url": None,
            "title": "",
            "cms_published_at": None,
            "cms_timestamp_semantics": None,
            "image_url": None,
            "visible_parts": [],
        }

    def _flush_article(self) -> None:
        if not self.current:
            return
        article_url = self.current.get("article_url")
        title = clean_text(self.current.get("title"))
        if article_url and title:
            visible = clean_text(" ".join(self.current.get("visible_parts") or []))
            if not self.current.get("cms_published_at"):
                match = CMS_DATE_RE.search(fold(visible))
                if match:
                    explicit_date = _parse_source_date(match.group(1), match.group(2), match.group(3))
                    if explicit_date:
                        self.current["cms_published_at"] = explicit_date
                        self.current["cms_timestamp_semantics"] = "EXPLICIT_VISIBLE_POST_DATE_DATE_ONLY"
            self.current["title"] = title
            self.current.pop("visible_parts", None)
            self.items.append(self.current)
        self.current = None

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        attrs_dict = {str(k).casefold(): str(v or "") for k, v in attrs}
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "article":
            if self.article_depth == 0:
                self._start_article()
            self.article_depth += 1
            return
        if tag == "a":
            href = attrs_dict.get("href", "")
            rel = {part.casefold() for part in attrs_dict.get("rel", "").split()}
            cls = attrs_dict.get("class", "").casefold()
            try:
                archive_candidate = normalize_archive_url(urljoin(self.page_url, href))
            except ValueError:
                archive_candidate = None
            if archive_candidate and archive_candidate != normalize_archive_url(self.page_url):
                if "next" in rel or "next" in cls or "page-numbers" in cls:
                    self.next_page_url = archive_candidate
            try:
                event_url = normalize_event_url(href, base_url=self.page_url)
            except ValueError:
                event_url = None
            if event_url:
                self.capture_href = event_url
                self.capture_parts = []
                if self.current and not self.current.get("article_url"):
                    self.current["article_url"] = event_url
            return
        if tag == "img" and self.current:
            for key in ("data-src", "data-lazy-src", "src"):
                candidate = normalize_media_url(attrs_dict.get(key, ""), base_url=self.page_url)
                if candidate:
                    self.current["image_url"] = self.current.get("image_url") or candidate
                    break
            return
        if tag == "time" and self.current:
            raw = clean_text(attrs_dict.get("datetime"))
            if raw:
                self.current["cms_published_at"] = raw
                self.current["cms_timestamp_semantics"] = "HTML_TIME_DATETIME_SOURCE_METADATA"
            return
        if tag == "meta" and self.current:
            prop = attrs_dict.get("property", "").casefold()
            name = attrs_dict.get("name", "").casefold()
            if prop == "article:published_time" or name == "article:published_time":
                raw = clean_text(attrs_dict.get("content"))
                if raw:
                    self.current["cms_published_at"] = raw
                    self.current["cms_timestamp_semantics"] = "ARTICLE_PUBLISHED_TIME_SOURCE_METADATA"

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag == "a" and self.capture_href:
            text = clean_text(" ".join(self.capture_parts))
            if text and fold(text) not in {"citeste mai mult", "citește mai mult", "read more"}:
                previous = self.fallback.get(self.capture_href, "")
                if len(text) > len(previous):
                    self.fallback[self.capture_href] = text
                if self.current and self.current.get("article_url") == self.capture_href:
                    current_title = clean_text(self.current.get("title"))
                    if len(text) > len(current_title):
                        self.current["title"] = text
            self.capture_href = None
            self.capture_parts = []
            return
        if tag == "article" and self.article_depth:
            self.article_depth -= 1
            if self.article_depth == 0:
                self._flush_article()

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = clean_text(data)
        if not text:
            return
        if self.capture_href:
            self.capture_parts.append(text)
        if self.current:
            self.current["visible_parts"].append(text)

    def close(self) -> None:
        super().close()
        if self.article_depth and self.current:
            self._flush_article()
            self.article_depth = 0
        known = {str(row.get("article_url")) for row in self.items}
        for article_url, title in self.fallback.items():
            if article_url not in known and title:
                self.items.append({
                    "article_url": article_url,
                    "title": title,
                    "cms_published_at": None,
                    "cms_timestamp_semantics": None,
                    "image_url": None,
                })


class VisibleTextParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.parts: list[str] = []
        self.meta_published: str | None = None
        self.meta_modified: str | None = None
        self.og_image: str | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        attrs_dict = {str(k).casefold(): str(v or "") for k, v in attrs}
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "meta":
            prop = attrs_dict.get("property", "").casefold()
            name = attrs_dict.get("name", "").casefold()
            content = clean_text(attrs_dict.get("content"))
            key = prop or name
            if key == "article:published_time" and content:
                self.meta_published = content
            elif key == "article:modified_time" and content:
                self.meta_modified = content
            elif key == "og:image" and content:
                self.og_image = content

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = clean_text(data)
        if text:
            self.parts.append(text)


def _challenge_detected(text: str) -> bool:
    hay = fold(text)
    return any(fold(marker) in hay for marker in CHALLENGE_MARKERS)


def extract_event_period(visible_text: str) -> dict[str, Any] | None:
    value = clean_text(visible_text)
    folded = fold(value)

    numeric = NUMERIC_RANGE_RE.search(folded)
    if numeric:
        try:
            start = date(int(numeric.group(5)), int(numeric.group(2)), int(numeric.group(1)))
            end = date(int(numeric.group(5)), int(numeric.group(4)), int(numeric.group(3)))
        except ValueError:
            return None
        if end < start:
            return None
        return {
            "event_start_date": start.isoformat(),
            "event_end_date": end.isoformat(),
            "event_start_time": None,
            "event_end_time": None,
            "event_temporal_precision": "EXPLICIT_DATE_RANGE",
            "event_temporal_evidence": numeric.group(0),
        }

    ranged = SAME_MONTH_RANGE_RE.search(folded)
    if ranged:
        start_iso = _parse_source_date(ranged.group(1), ranged.group(3), ranged.group(4))
        end_iso = _parse_source_date(ranged.group(2), ranged.group(3), ranged.group(4))
        if start_iso and end_iso and end_iso >= start_iso:
            return {
                "event_start_date": start_iso,
                "event_end_date": end_iso,
                "event_start_time": None,
                "event_end_time": None,
                "event_temporal_precision": "EXPLICIT_DATE_RANGE",
                "event_temporal_evidence": ranged.group(0),
            }

    single = SINGLE_EVENT_RE.search(folded)
    if single:
        event_date = _parse_source_date(single.group(1), single.group(2), single.group(3))
        if not event_date:
            return None
        start_time = single.group(4).replace(".", ":") if single.group(4) else None
        end_time = single.group(5).replace(".", ":") if single.group(5) else None
        return {
            "event_start_date": event_date,
            "event_end_date": event_date,
            "event_start_time": start_time,
            "event_end_time": end_time,
            "event_temporal_precision": "EXPLICIT_DATE_TIME" if start_time else "EXPLICIT_DATE",
            "event_temporal_evidence": single.group(0),
        }
    return None


def signal_id(article_url: str) -> str:
    raw = "\0".join([SOURCE_ID, article_url])
    return "bjai-event-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _visual_record(image_url: str | None, article_url: str) -> dict[str, Any]:
    return {
        "source_image_url": image_url,
        "source_page_url": article_url,
        "visual_desk_candidate": bool(image_url),
        "rights_state": (
            "UNKNOWN_REUSE_REQUIRES_EDITORIAL_CLEARANCE"
            if image_url else "NO_EVENT_SPECIFIC_IMAGE_DISCOVERED"
        ),
        "public_reuse_allowed": False,
        "generic_fallback_images_rejected": True,
        "image_semantics": "SOURCE_MEDIA_PROVENANCE_ONLY_NOT_A_REPUBLICATION_LICENSE",
    }


def discover_archive(html_text: str, *, final_url: str) -> dict[str, Any]:
    page_url = normalize_archive_url(final_url)
    if _challenge_detected(html_text):
        raise ValueError("BJAI archive response looks like an anti-bot/interstitial page")
    parser = ArchiveParser(page_url)
    parser.feed(html_text)
    parser.close()
    signals: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in parser.items:
        article_url = normalize_event_url(str(row["article_url"]), base_url=page_url)
        if article_url in seen:
            continue
        seen.add(article_url)
        title = clean_text(row.get("title"))
        if not title:
            continue
        cms_published_at = clean_text(row.get("cms_published_at")) or None
        signals.append({
            "signal_id": signal_id(article_url),
            "source_id": SOURCE_ID,
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "source_tier": SOURCE_TIER,
            "source_kind": SOURCE_KIND,
            "title": title,
            "article_url": article_url,
            "archive_page_url": page_url,
            "cms_published_at": cms_published_at,
            "cms_timestamp_semantics": row.get("cms_timestamp_semantics"),
            "cms_timestamp_is_event_time": False,
            "event_period": None,
            "event_enrichment_state": "NOT_FETCHED",
            "visual": _visual_record(row.get("image_url"), article_url),
            "lifecycle": "SIGNAL_ONLY_NEEDS_EDITORIAL_VERIFICATION",
            "publication_authority": "NONE",
            "fact_kernel_authority": "NONE",
            "writer_authority": "NONE",
            "public_projection": False,
            "auto_publication": False,
            "persistence_authority": "NONE",
            "provenance": {
                "authority": "BJAI_VALCEA_OFFICIAL",
                "discovery_surface": page_url,
                "event_url_basis": "OFFICIAL_ARCHIVE_LINK",
                "cms_time_basis": (
                    row.get("cms_timestamp_semantics") or "NOT_DISCOVERED"
                ),
            },
        })
    return {
        "archive_page_url": page_url,
        "signal_count": len(signals),
        "signals": signals,
        "next_page_url": parser.next_page_url,
    }


def enrich_signal(signal: dict[str, Any], html_text: str, *, final_url: str, content_sha256: str) -> dict[str, Any]:
    expected_url = normalize_event_url(str(signal.get("article_url") or ""))
    actual_url = normalize_event_url(final_url)
    if expected_url != actual_url:
        raise ValueError("BJAI enrichment refused redirect to a different event URL")
    if _challenge_detected(html_text):
        enriched = deepcopy(signal)
        enriched["event_enrichment_state"] = "HELD_ANTIBOT_OR_INTERSTITIAL"
        enriched["event_period"] = None
        enriched["provenance"]["event_fetch_content_sha256"] = content_sha256
        enriched["provenance"]["event_fetch_state"] = "HELD_ANTIBOT_OR_INTERSTITIAL"
        return enriched

    parser = VisibleTextParser()
    parser.feed(html_text)
    parser.close()
    visible = clean_text(" ".join(parser.parts))
    period = extract_event_period(visible)
    enriched = deepcopy(signal)
    enriched["event_period"] = period
    enriched["event_enrichment_state"] = (
        "EXPLICIT_EVENT_TIME_EXTRACTED" if period else "NO_EXPLICIT_EVENT_TIME_EXTRACTED"
    )
    enriched["event_date_semantics"] = "EXPLICIT_VISIBLE_SOURCE_TEXT_ONLY_NOT_CMS_TIMESTAMP"
    if not enriched.get("cms_published_at") and parser.meta_published:
        enriched["cms_published_at"] = parser.meta_published
        enriched["cms_timestamp_semantics"] = "ARTICLE_PUBLISHED_TIME_SOURCE_METADATA"
    if not enriched["visual"].get("source_image_url"):
        image = normalize_media_url(parser.og_image or "", base_url=actual_url)
        if image:
            enriched["visual"] = _visual_record(image, expected_url)
    enriched["provenance"]["event_fetch_content_sha256"] = content_sha256
    enriched["provenance"]["event_fetch_state"] = "PASS"
    enriched["provenance"]["event_time_basis"] = (
        "EXPLICIT_VISIBLE_SOURCE_TEXT" if period else "NONE"
    )
    if parser.meta_modified:
        enriched["provenance"]["cms_modified_at"] = parser.meta_modified
    return enriched


def html_response_ok(content_type: str, body: bytes) -> bool:
    return "html" in content_type.casefold() or b"<html" in body[:2000].lower()


def fetch_html(url: str) -> tuple[str, str, str]:
    request = Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    with urlopen(request, timeout=18, context=ssl.create_default_context()) as response:
        final_url = str(response.geturl())
        if not _official_https(final_url):
            raise ValueError("BJAI adapter refused redirect outside official HTTPS host")
        body = response.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            raise ValueError("BJAI source response exceeds bounded body limit")
        content_type = str(response.headers.get("Content-Type") or "")
        if not html_response_ok(content_type, body):
            raise ValueError(f"BJAI source did not return HTML: {content_type or 'unknown'}")
        charset = response.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace"), final_url, hashlib.sha256(body).hexdigest()


def build_live_document(*, max_pages: int = 1, enrich_limit: int = 8) -> dict[str, Any]:
    if isinstance(max_pages, bool) or not 1 <= max_pages <= MAX_PAGES:
        raise ValueError(f"max_pages must be between 1 and {MAX_PAGES}")
    if isinstance(enrich_limit, bool) or not 0 <= enrich_limit <= 50:
        raise ValueError("enrich_limit must be between 0 and 50")

    page_url: str | None = SOURCE_URL
    pages: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for _ in range(max_pages):
        if not page_url:
            break
        html_text, final_url, page_sha = fetch_html(page_url)
        page = discover_archive(html_text, final_url=final_url)
        page["source_content_sha256"] = page_sha
        pages.append({
            "archive_page_url": page["archive_page_url"],
            "source_content_sha256": page_sha,
            "signal_count": page["signal_count"],
            "next_page_url": page["next_page_url"],
        })
        for signal in page["signals"]:
            article_url = signal["article_url"]
            if article_url not in seen_urls:
                seen_urls.add(article_url)
                signals.append(signal)
        next_url = page["next_page_url"]
        page_url = normalize_archive_url(next_url) if next_url else None

    for index, signal in enumerate(list(signals)):
        if index >= enrich_limit:
            break
        try:
            html_text, final_url, sha = fetch_html(signal["article_url"])
            signals[index] = enrich_signal(
                signal, html_text, final_url=final_url, content_sha256=sha
            )
        except Exception as exc:
            held = deepcopy(signal)
            held["event_enrichment_state"] = "HELD_FETCH_OR_STRUCTURE_ERROR"
            held["event_period"] = None
            held["provenance"]["event_fetch_state"] = "HELD_FETCH_OR_STRUCTURE_ERROR"
            held["provenance"]["event_fetch_error_class"] = type(exc).__name__
            signals[index] = held

    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR BJAI Vâlcea event signals",
        "source_id": SOURCE_ID,
        "source_url": SOURCE_URL,
        "page_count": len(pages),
        "signal_count": len(signals),
        "pages": pages,
        "signals": signals,
        "policy": {
            "signal_only": True,
            "reader_facing_eligible": False,
            "publication_authority": "NONE",
            "fact_kernel_authority": "NONE",
            "writer_authority": "NONE",
            "public_projection": False,
            "auto_publication": False,
            "persistence_authority": "NONE",
            "event_datetime_requires_explicit_visible_source_text": True,
            "cms_timestamp_never_substitutes_for_event_datetime": True,
            "source_media_does_not_imply_republication_rights": True,
            "generic_fallback_images_rejected": True,
            "anti_bot_or_fetch_failure_holds_enrichment": True,
        },
    }


def self_test() -> int:
    archive = """
    <html><body>
      <article>
        <h2><a href="/evenimente/ziua-limbii-romane-test/">ZIUA LIMBII ROMÂNE</a></h2>
        <time datetime="2026-08-26T12:11:45+03:00"></time>
        <img src="https://www.bjai.ro/wp-content/uploads/2026/08/ziua-limbii-romane.jpg">
        <a href="/evenimente/ziua-limbii-romane-test/">Citește mai mult</a>
      </article>
      <article>
        <h2><a href="https://www.bjai.ro/evenimente/fara-foto/">Eveniment fără fotografie</a></h2>
        <p>Postare din: 20 august 2026</p>
        <img src="https://www.bjai.ro/wp-content/uploads/2017/06/logo-biblioteca-judeteana-valcea.png">
      </article>
      <a class="next page-numbers" href="/evenimente/page/2/">Următoarea</a>
    </body></html>
    """
    page = discover_archive(archive, final_url=SOURCE_URL)
    assert page["signal_count"] == 2
    assert page["next_page_url"] == "https://www.bjai.ro/evenimente/page/2/"
    first = page["signals"][0]
    assert first["cms_published_at"] == "2026-08-26T12:11:45+03:00"
    assert first["visual"]["visual_desk_candidate"] is True
    assert first["visual"]["public_reuse_allowed"] is False
    second = page["signals"][1]
    assert second["visual"]["source_image_url"] is None
    assert second["cms_published_at"] == "2026-08-20"
    assert second["publication_authority"] == "NONE"

    event_html = """
    <html><head>
      <meta property="article:published_time" content="2026-08-26T12:11:45+03:00">
      <meta property="og:image" content="https://www.bjai.ro/wp-content/uploads/2026/08/poster.jpg">
    </head><body>
      <h1>ZIUA LIMBII ROMÂNE</h1>
      <p>Luni, 31 August 2026, ora 11:00, Biblioteca Județeană găzduiește evenimentul.</p>
    </body></html>
    """
    enriched = enrich_signal(
        deepcopy(first),
        event_html,
        final_url=first["article_url"],
        content_sha256="a" * 64,
    )
    assert enriched["event_period"]["event_start_date"] == "2026-08-31"
    assert enriched["event_period"]["event_start_time"] == "11:00"
    assert enriched["event_enrichment_state"] == "EXPLICIT_EVENT_TIME_EXTRACTED"
    assert enriched["cms_published_at"] != enriched["event_period"]["event_start_date"]
    assert enriched["fact_kernel_authority"] == "NONE"

    range_period = extract_event_period("Între 25 – 26 Septembrie 2025 are loc evenimentul")
    assert range_period and range_period["event_start_date"] == "2025-09-25"
    assert range_period["event_end_date"] == "2025-09-26"
    numeric_period = extract_event_period("Tabăra are loc 21.07 – 01.08.2026.")
    assert numeric_period and numeric_period["event_start_date"] == "2026-07-21"
    assert numeric_period["event_end_date"] == "2026-08-01"

    challenged = enrich_signal(
        deepcopy(first),
        "<html><body>Please wait while your request is being verified...</body></html>",
        final_url=first["article_url"],
        content_sha256="b" * 64,
    )
    assert challenged["event_enrichment_state"] == "HELD_ANTIBOT_OR_INTERSTITIAL"
    assert challenged["event_period"] is None

    assert normalize_media_url(
        "https://www.bjai.ro/wp-content/uploads/2017/06/logo-biblioteca-judeteana-valcea.png"
    ) is None
    try:
        discover_archive(archive, final_url="https://example.com/evenimente/")
    except ValueError:
        pass
    else:
        raise AssertionError("off-domain archive URL must fail closed")
    try:
        enrich_signal(
            first,
            event_html,
            final_url="https://www.bjai.ro/evenimente/other-event/",
            content_sha256="c" * 64,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("redirect to another event must fail closed")

    doc_policy = build_document_from_samples([page["signals"]])
    assert doc_policy["policy"]["source_media_does_not_imply_republication_rights"] is True
    print("VÂLCEA CLAR BJAI event signal adapter self-test: PASS")
    return 0


def build_document_from_samples(signal_pages: list[list[dict[str, Any]]]) -> dict[str, Any]:
    """Small deterministic document helper used by regression/self-test, with no network I/O."""
    signals: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rows in signal_pages:
        for row in rows:
            url = normalize_event_url(str(row.get("article_url") or ""))
            if url not in seen:
                seen.add(url)
                signals.append(deepcopy(row))
    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR BJAI Vâlcea event signals",
        "source_id": SOURCE_ID,
        "source_url": SOURCE_URL,
        "signal_count": len(signals),
        "signals": signals,
        "policy": {
            "signal_only": True,
            "reader_facing_eligible": False,
            "publication_authority": "NONE",
            "fact_kernel_authority": "NONE",
            "writer_authority": "NONE",
            "public_projection": False,
            "auto_publication": False,
            "persistence_authority": "NONE",
            "event_datetime_requires_explicit_visible_source_text": True,
            "cms_timestamp_never_substitutes_for_event_datetime": True,
            "source_media_does_not_imply_republication_rights": True,
            "generic_fallback_images_rejected": True,
            "anti_bot_or_fetch_failure_holds_enrichment": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--enrich-limit", type=int, default=8)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    document = build_live_document(
        max_pages=args.max_pages,
        enrich_limit=args.enrich_limit,
    )
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "source_id": SOURCE_ID,
        "page_count": document["page_count"],
        "signal_count": document["signal_count"],
        "publication_authority": "NONE",
        "fact_kernel_authority": "NONE",
        "output": str(args.output) if args.output else None,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
