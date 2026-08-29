#!/usr/bin/env python3
"""Evidence-first APAVIL Vâlcea scheduled-outage signal adapter.

The official APAVIL "Opriri programate" page is treated as a metadata index.
Linked PDF bodies are deliberately not downloaded or parsed by this adapter.
Every emitted row remains signal-only and cannot assert live/current service
status, persistence, Fact Kernel authority, Writer authority or publication.
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
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

SOURCE_ID = "signal-apavil-valcea-scheduled-outages"
SOURCE_NAME = "APAVIL S.A. Vâlcea — Opriri programate"
SOURCE_URL = "https://apavil.ro/?page_id=962"
SOURCE_TIER = "T1"
SOURCE_KIND = "PUBLIC_WATER_UTILITY_SCHEDULED_OUTAGES"
ALLOWED_HOSTS = {"apavil.ro", "www.apavil.ro"}
USER_AGENT = "Mozilla/5.0 VÂLCEA-CLAR-APAVIL-Signal/1.0 (+https://valceaclar.ro/)"
MAX_BODY_BYTES = 3_000_000

DATE_RE = re.compile(r"\b([0-3]?\d)[./-]([01]?\d)[./-]((?:20)\d{2})\b")
TIME_RANGE_RE = re.compile(
    r"\b(?:interval(?:ul)?(?:\s+orar)?|intre\s+orele|între\s+orele|orele?)?\s*"
    r"([0-2]?\d)(?:[:.^\s]?([0-5]\d))?\s*(?:-|–|—)\s*"
    r"([0-2]?\d)(?:[:.^\s]?([0-5]\d))?\b",
    re.IGNORECASE,
)
PLACE_RE = re.compile(
    r"\b(?:municipiul|orasul|orașul|comuna|localitatea|uat|satul|sat|strada|str\.)\s+"
    r"([A-ZĂÂÎȘŞȚŢ][A-Za-zĂÂÎȘŞȚŢăâîșşțţ0-9 .,'’/-]{1,90})",
    re.IGNORECASE,
)
OUTAGE_TERMS = (
    "intrerupere furnizare", "întrerupere furnizare", "intrerupe furnizare",
    "întrerupe furnizare", "oprire furnizare", "fara apa", "fără apă",
)
PLACEHOLDER_TERMS = (
    "enable javascript", "access denied", "captcha", "robot",
    "temporarily unavailable", "service unavailable",
)


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", clean_text(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def official_index_url(url: str) -> bool:
    parsed = urlsplit(clean_text(url))
    if parsed.scheme.casefold() != "https" or parsed.hostname is None:
        return False
    if parsed.hostname.casefold() not in ALLOWED_HOSTS or parsed.username or parsed.password:
        return False
    if (parsed.path or "/").rstrip("/") not in {"", "/"}:
        return False
    params = parse_qs(parsed.query, keep_blank_values=False)
    return params == {"page_id": ["962"]}


def normalize_attachment_url(value: str, *, base_url: str = SOURCE_URL) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    joined = urljoin(base_url, text)
    parsed = urlsplit(joined)
    if (
        parsed.scheme.casefold() != "https"
        or parsed.hostname is None
        or parsed.hostname.casefold() not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
    ):
        return None
    path = re.sub(r"/+", "/", unquote(parsed.path or "/"))
    if not path.casefold().startswith("/materiale/anunturi/"):
        return None
    if not path.casefold().endswith(".pdf"):
        return None
    return urlunsplit(("https", "apavil.ro", path, "", ""))


class ListingParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.href: str | None = None
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "a":
            self.href = dict(attrs).get("href") or ""
            self.parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag == "a" and self.href is not None:
            text = clean_text(" ".join(self.parts))
            if text:
                self.links.append((self.href, text))
            self.href = None
            self.parts = []

    def handle_data(self, data: str) -> None:
        if self.skip_depth or self.href is None:
            return
        text = clean_text(data)
        if text:
            self.parts.append(text)


def placeholder_response(html_text: str) -> bool:
    visible = fold(re.sub(r"<[^>]+>", " ", html_text))[:5000]
    return any(fold(term) in visible for term in PLACEHOLDER_TERMS)


def iso_date(day: str, month: str, year: str) -> str | None:
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def extract_dates(text: str) -> tuple[list[str], str]:
    dates: list[str] = []
    anomalous = False
    for match in DATE_RE.finditer(text):
        value = iso_date(match.group(1), match.group(2), match.group(3))
        if value is None:
            anomalous = True
            continue
        if value not in dates:
            dates.append(value)
    if anomalous:
        return dates[:4], "PARTIAL_ANOMALY" if dates else "ANOMALOUS"
    return dates[:4], "EXPLICIT_VISIBLE_TEXT" if dates else "MISSING"


def normalize_clock(hour: str, minute: str | None) -> str | None:
    try:
        h = int(hour)
        m = int(minute or "00")
    except ValueError:
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return f"{h:02d}:{m:02d}"


def extract_time_range(text: str) -> dict[str, str] | None:
    for match in TIME_RANGE_RE.finditer(text):
        start = normalize_clock(match.group(1), match.group(2))
        end = normalize_clock(match.group(3), match.group(4))
        if start and end:
            return {"start": start, "end": end, "basis": "EXPLICIT_VISIBLE_TEXT"}
    return None


def extract_geography(text: str) -> list[str]:
    out: list[str] = []
    for match in PLACE_RE.finditer(text):
        value = clean_text(match.group(0))
        value = re.split(
            r"\b(?:in data|în data|in interval|în interval|respectiv|astfel|si|și|iar)\b",
            value,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].rstrip(" ,.;:-")
        if 4 <= len(value) <= 110 and value not in out:
            out.append(value)
    return out[:16]


def classify(text: str, *, date_status: str) -> str:
    value = fold(text)
    if date_status in {"ANOMALOUS", "PARTIAL_ANOMALY"}:
        return "HOLD"
    if any(fold(term) in value for term in OUTAGE_TERMS):
        return "SCHEDULED_WATER_OUTAGE"
    return "HOLD"


def evidence_id(*, text: str, attachment_url: str | None) -> str:
    basis = "\0".join([SOURCE_ID, fold(text), attachment_url or "NO_ATTACHMENT"])
    return "apavil-outage-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:20]


def extract_signals(html_text: str, *, final_url: str = SOURCE_URL) -> list[dict[str, Any]]:
    if not official_index_url(final_url):
        raise ValueError(f"APAVIL adapter refused unexpected index URL: {final_url}")
    if placeholder_response(html_text):
        raise ValueError("APAVIL source returned a placeholder/challenge response")

    parser = ListingParser()
    parser.feed(html_text)
    parser.close()

    by_id: dict[str, dict[str, Any]] = {}
    for href, raw_text in parser.links:
        text = clean_text(raw_text)
        if len(text) < 20:
            continue
        if not any(fold(term) in fold(text) for term in OUTAGE_TERMS):
            continue
        attachment_url = normalize_attachment_url(href)
        dates, date_status = extract_dates(text)
        signal_class = classify(text, date_status=date_status)
        sid = evidence_id(text=text, attachment_url=attachment_url)
        row = {
            "signal_id": sid,
            "source_id": SOURCE_ID,
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "final_url": final_url,
            "source_tier": SOURCE_TIER,
            "source_kind": SOURCE_KIND,
            "title": text,
            "signal_class": signal_class,
            "effective_dates": dates,
            "effective_date_status": date_status,
            "effective_date_semantics": "SCHEDULED_SERVICE_WINDOW_FROM_VISIBLE_OFFICIAL_INDEX_TEXT",
            "time_range": extract_time_range(text),
            "explicit_geography": extract_geography(text),
            "attachment_url": attachment_url,
            "attachment_type": "PDF" if attachment_url else None,
            "attachment_fetch_allowed": False,
            "attachment_body_ingest_allowed": False,
            "current_status_claim_allowed": False,
            "publication_authority": "NONE",
            "public_projection": False,
            "auto_publication": False,
            "persistence_allowed": False,
            "fact_kernel_authority": False,
            "media_public_reuse_allowed": False,
            "lifecycle": (
                "SIGNAL_ONLY_NEEDS_FRESHNESS_RECHECK"
                if signal_class == "SCHEDULED_WATER_OUTAGE"
                else "HOLD_DATE_OR_CLASSIFICATION_ANOMALY"
            ),
            "provenance": {
                "authority": "APAVIL_OFFICIAL_SCHEDULED_OUTAGES_INDEX",
                "retrieval_surface": SOURCE_URL,
                "metadata_basis": "EXPLICIT_VISIBLE_OFFICIAL_INDEX_TEXT",
                "attachment_basis": (
                    "OFFICIAL_APAVIL_PDF_LINK_DISCOVERED_NOT_FETCHED"
                    if attachment_url else "NO_SUPPORTED_ATTACHMENT_CAPTURED"
                ),
            },
        }
        by_id[sid] = row

    return sorted(
        by_id.values(),
        key=lambda row: ((row["effective_dates"][-1] if row["effective_dates"] else "0000-00-00"), row["title"]),
        reverse=True,
    )


def html_response_ok(content_type: str, body: bytes) -> bool:
    return "html" in content_type.casefold() or b"<html" in body[:2000].lower()


def fetch_html(url: str = SOURCE_URL) -> tuple[str, str, str]:
    if not official_index_url(url):
        raise ValueError("APAVIL fetch is restricted to the canonical scheduled-outages index")
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with urlopen(request, timeout=20, context=ssl.create_default_context()) as response:
        final_url = str(response.geturl())
        if not official_index_url(final_url):
            raise ValueError(f"APAVIL adapter refused redirect outside canonical index: {final_url}")
        body = response.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            raise ValueError("APAVIL source response exceeds bounded body limit")
        content_type = str(response.headers.get("Content-Type") or "")
        if not html_response_ok(content_type, body):
            raise ValueError(f"APAVIL source did not return HTML: {content_type or 'unknown'}")
        charset = response.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace"), final_url, hashlib.sha256(body).hexdigest()


def build_document(html_text: str, *, final_url: str, content_sha256: str) -> dict[str, Any]:
    signals = extract_signals(html_text, final_url=final_url)
    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR APAVIL scheduled-outage signals",
        "source_id": SOURCE_ID,
        "source_url": SOURCE_URL,
        "final_url": final_url,
        "source_content_sha256": content_sha256,
        "signal_count": len(signals),
        "signals": signals,
        "policy": {
            "publication_authority": "NONE",
            "signal_only": True,
            "public_projection": False,
            "auto_publication": False,
            "persistence_allowed": False,
            "fact_kernel_authority": False,
            "current_status_claim_allowed": False,
            "attachment_fetch_allowed": False,
            "attachment_body_ingest_allowed": False,
            "effective_window_must_be_explicit": True,
            "media_public_reuse_allowed": False,
        },
    }


def self_test() -> int:
    sample = """
    <html><body>
      <h1>Opriri programate</h1>
      <a href="/materiale/anunturi/2026/oprire_cazanesti1008.pdf">
      Anunț întrerupere furnizare alimentare cu apa potabila a consumatorilor existenți din
      municipiul Râmnicu Vâlcea, străzile: Căzănești, Gura Văii, Mărului, în data de
      10.08.2026, în intervalul 09:00 – 15:00</a>
      <a href="https://apavil.ro/materiale/anunturi/2026/horezu.pdf">
      Anunt intrerupere furnizare apa potabila in localitatea Horezu, în intervalul
      24.04.2026 ora 09:00 – 25.04.2026, ora 19:00</a>
      <a href="https://evil.example/outage.pdf">
      Anunț întrerupere furnizare apă potabilă în comuna Test, în data de 30.07.2026,
      în intervalul 08:00 – 17:00</a>
      <a href="/materiale/anunturi/2026/bad.pdf">
      Anunț întrerupere furnizare apă potabilă în comuna Test, în data de 31.02.2026,
      în intervalul 08:00 – 17:00</a>
      <a href="/?p=8582">APEL CĂTRE UAT-uri pentru folosirea rațională a apei</a>
    </body></html>
    """
    signals = extract_signals(sample)
    assert len(signals) == 4, signals

    caz = next(row for row in signals if "Căzănești" in row["title"])
    assert caz["signal_class"] == "SCHEDULED_WATER_OUTAGE"
    assert caz["effective_dates"] == ["2026-08-10"]
    assert caz["time_range"]["start"] == "09:00"
    assert caz["time_range"]["end"] == "15:00"
    assert caz["attachment_url"] == "https://apavil.ro/materiale/anunturi/2026/oprire_cazanesti1008.pdf"
    assert caz["attachment_fetch_allowed"] is False
    assert caz["current_status_claim_allowed"] is False
    assert caz["persistence_allowed"] is False
    assert caz["fact_kernel_authority"] is False
    assert caz["media_public_reuse_allowed"] is False

    horezu = next(row for row in signals if "Horezu" in row["title"])
    assert horezu["effective_dates"] == ["2026-04-24", "2026-04-25"]
    assert horezu["attachment_body_ingest_allowed"] is False

    offsite = next(row for row in signals if "comuna Test" in row["title"] and row["effective_date_status"] == "EXPLICIT_VISIBLE_TEXT")
    assert offsite["attachment_url"] is None

    anomalous = next(row for row in signals if row["effective_date_status"] == "ANOMALOUS")
    assert anomalous["signal_class"] == "HOLD"
    assert anomalous["current_status_claim_allowed"] is False

    assert official_index_url("https://apavil.ro/?page_id=962")
    assert not official_index_url("http://apavil.ro/?page_id=962")
    assert not official_index_url("https://apavil.ro/?page_id=967")
    assert normalize_attachment_url("https://example.com/a.pdf") is None

    doc = build_document(sample, final_url=SOURCE_URL, content_sha256="a" * 64)
    assert doc["policy"]["signal_only"] is True
    assert doc["policy"]["current_status_claim_allowed"] is False
    assert doc["policy"]["attachment_body_ingest_allowed"] is False

    print("APAVIL scheduled-outage signal adapter self-test: ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    html_text, final_url, sha = fetch_html()
    print(json.dumps(build_document(html_text, final_url=final_url, content_sha256=sha), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
