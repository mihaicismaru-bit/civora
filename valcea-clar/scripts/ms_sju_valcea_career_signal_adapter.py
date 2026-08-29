#!/usr/bin/env python3
"""Evidence-first Ministry of Health -> SJU Valcea workforce signal adapter.

This adapter discovers public medical-career notices on the Romanian Ministry of
Health site that explicitly concern Spitalul Judetean de Urgenta Valcea. It is a
signal adapter only: it does not authorize publication, does not infer current
vacancy status, and never parses linked candidate/result documents.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date
from html.parser import HTMLParser
from typing import Iterable, Optional

SOURCE_ID = "signal-ms-sju-valcea-career"
TAXONOMY_VERSION = "2026-08-29.1"
BASE_URL = "https://ms.gov.ro/ro/minister/cariera-medici/"
ALLOWED_HOSTS = {"ms.gov.ro", "www.ms.gov.ro"}
MAX_RESPONSE_BYTES = 2_500_000
MAX_DETAIL_PAGES = 30
DEFAULT_LISTING_PAGES = 5
USER_AGENT = "CIVORA-ValceaClar-SJUWorkforceSignals/1.0 (+evidence-first; contact via repository)"

VACANCY_TERMS = (
    "concurs",
    "post vacant",
    "posturi vacante",
    "ocuparea unui post",
    "ocuparea a",
    "medic specialist",
    "medici specialisti",
    "medic primar",
    "medic rezident",
)
PRIVACY_OR_RESULT_TERMS = (
    "lista candidat",
    "lista candida",
    "rezultate candidat",
    "rezultat candidat",
    "punctaj",
    "admis",
    "respins",
    "contestatii rezultate",
    "rezultate finale",
)
INSTITUTION_TERMS = (
    "spitalul judetean de urgenta valcea",
    "spitalul judetean urgenta valcea",
    "sju valcea",
)
DOCUMENT_SUFFIXES = (".pdf", ".doc", ".docx", ".odt", ".xls", ".xlsx")

ROMANIAN_MONTHS = {
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


@dataclass(frozen=True)
class WorkforceSignal:
    source_id: str
    taxonomy_version: str
    signal_class: str
    title: str
    source_url: str
    publication_date: Optional[str]
    payload_sha256: str
    body_excerpt: str
    hold_reason: Optional[str]
    document_refs: tuple[str, ...]
    publication_authority: str = "NONE"
    current_status_claim_allowed: bool = False
    candidate_person_extraction_allowed: bool = False
    linked_document_body_parse_allowed: bool = False


class LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: Optional[str] = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "a":
            return
        attrs_dict = {k.lower(): v for k, v in attrs}
        href = attrs_dict.get("href")
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            text = clean_space(" ".join(self._text))
            self.links.append((self._href, text))
            self._href = None
            self._text = []


class VisibleTextParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.text_parts: list[str] = []
        self.links: list[str] = []
        self.headings: list[str] = []
        self._heading: Optional[str] = None
        self._heading_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if tag in self.SKIP:
            self._skip_depth += 1
        if tag in {"h1", "h2", "h3"}:
            self._heading = tag
            self._heading_parts = []
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        if self._heading == tag:
            heading = clean_space(" ".join(self._heading_parts))
            if heading:
                self.headings.append(heading)
            self._heading = None
            self._heading_parts = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = clean_space(data)
        if not text:
            return
        self.text_parts.append(text)
        if self._heading is not None:
            self._heading_parts.append(text)


def clean_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return clean_space("".join(ch for ch in normalized if not unicodedata.combining(ch)).lower())


def safe_join(base: str, href: str) -> Optional[str]:
    try:
        url = urllib.parse.urljoin(base, href)
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
        return None
    return urllib.parse.urlunsplit(("https", parsed.netloc.lower(), parsed.path, parsed.query, ""))


def fetch_html(url: str, timeout: float = 10.0) -> tuple[str, str, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final_url = response.geturl()
        parsed = urllib.parse.urlsplit(final_url)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
            raise ValueError(f"off-domain redirect refused: {final_url}")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds size cap")
        charset = response.headers.get_content_charset() or "utf-8"
    return final_url, body.decode(charset, errors="replace"), body


def listing_urls(pages: int) -> list[str]:
    pages = max(1, min(pages, 10))
    urls = [BASE_URL]
    urls.extend(f"{BASE_URL}?page={page}" for page in range(2, pages + 1))
    return urls


def is_sju_detail_url(url: str, anchor_text: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    if (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
        return False
    if "/ro/minister/cariera-medici/" not in parsed.path:
        return False
    if parsed.path.rstrip("/") == "/ro/minister/cariera-medici":
        return False
    folded = fold(anchor_text + " " + parsed.path.replace("-", " "))
    return "valcea" in folded and ("spital" in folded or "sju" in folded)


def discover_detail_urls(html: str, listing_url: str) -> list[str]:
    parser = LinkCollector()
    parser.feed(html)
    found: list[str] = []
    seen: set[str] = set()
    for href, text in parser.links:
        url = safe_join(listing_url, href)
        if not url or not is_sju_detail_url(url, text):
            continue
        if url not in seen:
            found.append(url)
            seen.add(url)
    return found


def extract_publication_date(text: str) -> Optional[str]:
    folded_text = fold(text)
    month_pattern = "|".join(ROMANIAN_MONTHS)
    match = re.search(rf"\b([0-3]?\d)\s+({month_pattern})\s+(20\d{{2}})\b", folded_text)
    if match:
        day, month_name, year = match.groups()
        try:
            parsed = date(int(year), ROMANIAN_MONTHS[month_name], int(day))
            return parsed.isoformat()
        except ValueError:
            return None
    match = re.search(r"\b([0-3]?\d)[./-]([01]?\d)[./-](20\d{2})\b", folded_text)
    if match:
        day, month, year = match.groups()
        try:
            return date(int(year), int(month), int(day)).isoformat()
        except ValueError:
            return None
    return None


def redact_excerpt(text: str, limit: int = 900) -> str:
    text = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[email-redacted]", text, flags=re.I)
    text = re.sub(r"(?<!\d)(?:\+40|0040|0)\s*\d(?:[\s./-]*\d){8}(?!\d)", "[phone-redacted]", text)
    return clean_space(text)[:limit]


def document_refs(links: Iterable[str], source_url: str) -> tuple[str, ...]:
    refs: list[str] = []
    seen: set[str] = set()
    for href in links:
        url = safe_join(source_url, href)
        if not url:
            continue
        path = urllib.parse.urlsplit(url).path.lower()
        if not (path.endswith(DOCUMENT_SUFFIXES) or "/media/documents/" in path):
            continue
        if url not in seen:
            refs.append(url)
            seen.add(url)
    return tuple(refs)


def classify_detail(html: str, source_url: str, raw_payload: bytes) -> Optional[WorkforceSignal]:
    parser = VisibleTextParser()
    parser.feed(html)
    visible = clean_space(" ".join(parser.text_parts))
    folded = fold(visible)
    title = next((h for h in parser.headings if "valcea" in fold(h)), parser.headings[0] if parser.headings else "")
    title = clean_space(title) or "SJU Valcea medical-career notice"

    if not any(term in folded for term in INSTITUTION_TERMS):
        return None

    publication_date = extract_publication_date(visible[:3000])
    hold_reason: Optional[str] = None
    signal_class = "HEALTH_WORKFORCE_RECRUITMENT"

    if any(term in folded for term in PRIVACY_OR_RESULT_TERMS):
        signal_class = "HOLD"
        hold_reason = "RESULT_OR_CANDIDATE_MATERIAL_REQUIRES_PRIVACY_REVIEW"
    elif not any(term in folded for term in VACANCY_TERMS):
        signal_class = "HOLD"
        hold_reason = "NO_EXPLICIT_RECRUITMENT_SIGNAL"
    elif publication_date is None:
        signal_class = "HOLD"
        hold_reason = "MISSING_OR_INVALID_PUBLICATION_DATE"

    return WorkforceSignal(
        source_id=SOURCE_ID,
        taxonomy_version=TAXONOMY_VERSION,
        signal_class=signal_class,
        title=title[:300],
        source_url=source_url,
        publication_date=publication_date,
        payload_sha256=hashlib.sha256(raw_payload).hexdigest(),
        body_excerpt=redact_excerpt(visible),
        hold_reason=hold_reason,
        document_refs=document_refs(parser.links, source_url),
    )


def collect(pages: int, timeout: float) -> list[WorkforceSignal]:
    detail_urls: list[str] = []
    seen: set[str] = set()
    for listing in listing_urls(pages):
        try:
            final_url, html, _ = fetch_html(listing, timeout=timeout)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            print(f"WARN listing fetch failed: {listing}: {exc}", file=sys.stderr)
            continue
        for detail in discover_detail_urls(html, final_url):
            if detail not in seen:
                seen.add(detail)
                detail_urls.append(detail)
        if len(detail_urls) >= MAX_DETAIL_PAGES:
            break

    signals: list[WorkforceSignal] = []
    for detail in detail_urls[:MAX_DETAIL_PAGES]:
        try:
            final_url, html, raw = fetch_html(detail, timeout=timeout)
            signal = classify_detail(html, final_url, raw)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            print(f"WARN detail fetch failed: {detail}: {exc}", file=sys.stderr)
            continue
        if signal is not None:
            signals.append(signal)
    signals.sort(key=lambda item: (item.publication_date or "", item.source_url), reverse=True)
    return signals


def self_test() -> None:
    valid = """
    <html><body><h1>Anunt concurs - Spitalul Judetean de Urgenta Valcea</h1>
    <p>20 August 2026</p><p>Concurs pentru ocuparea a 5 posturi vacante de medici specialisti medicina de urgenta la UPU-SMURD.</p>
    <p>Relatii: 0350405951, resurse@example.ro</p>
    <a href="/media/documents/anunt_sju_valcea.pdf">Anunt PDF</a></body></html>
    """
    signal = classify_detail(valid, "https://ms.gov.ro/ro/minister/cariera-medici/anunt-valcea/", valid.encode())
    assert signal is not None
    assert signal.signal_class == "HEALTH_WORKFORCE_RECRUITMENT"
    assert signal.publication_date == "2026-08-20"
    assert signal.publication_authority == "NONE"
    assert signal.current_status_claim_allowed is False
    assert signal.candidate_person_extraction_allowed is False
    assert signal.linked_document_body_parse_allowed is False
    assert signal.document_refs == ("https://ms.gov.ro/media/documents/anunt_sju_valcea.pdf",)
    assert "example.ro" not in signal.body_excerpt and "0350405951" not in signal.body_excerpt

    privacy = """
    <html><body><h1>Spitalul Judetean de Urgenta Valcea</h1><p>21 August 2026</p>
    <p>Rezultate finale - lista candidati admis/respins si punctaj.</p></body></html>
    """
    signal = classify_detail(privacy, "https://ms.gov.ro/ro/minister/cariera-medici/rezultate-valcea/", privacy.encode())
    assert signal is not None and signal.signal_class == "HOLD"
    assert signal.hold_reason == "RESULT_OR_CANDIDATE_MATERIAL_REQUIRES_PRIVACY_REVIEW"

    missing_date = """
    <html><body><h1>Spitalul Judetean de Urgenta Valcea</h1><p>Concurs pentru ocuparea unui post vacant de medic specialist.</p></body></html>
    """
    signal = classify_detail(missing_date, "https://ms.gov.ro/ro/minister/cariera-medici/anunt-fara-data/", missing_date.encode())
    assert signal is not None and signal.signal_class == "HOLD"
    assert signal.hold_reason == "MISSING_OR_INVALID_PUBLICATION_DATE"

    other = """
    <html><body><h1>Spitalul Judetean de Urgenta Alba</h1><p>20 August 2026</p><p>Concurs post vacant medic specialist.</p></body></html>
    """
    assert classify_detail(other, "https://ms.gov.ro/ro/minister/cariera-medici/anunt-alba/", other.encode()) is None

    listing = '<a href="/ro/minister/cariera-medici/anunt-concurs-spitalul-judetean-de-urgenta-valcea-25/">Anunt concurs - Spitalul Judetean de Urgenta Valcea</a>'
    urls = discover_detail_urls(listing, BASE_URL)
    assert urls == ["https://ms.gov.ro/ro/minister/cariera-medici/anunt-concurs-spitalul-judetean-de-urgenta-valcea-25/"]
    assert safe_join(BASE_URL, "https://evil.example/file.pdf") is None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=DEFAULT_LISTING_PAGES)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--input", help="Classify one local HTML file instead of fetching live pages")
    parser.add_argument("--source-url", default="https://ms.gov.ro/ro/minister/cariera-medici/local-fixture/")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        print("SJU workforce adapter self-test: OK")
        return 0

    if args.input:
        raw = open(args.input, "rb").read()
        signal = classify_detail(raw.decode("utf-8", errors="replace"), args.source_url, raw)
        payload = [] if signal is None else [asdict(signal)]
    else:
        payload = [asdict(signal) for signal in collect(args.pages, args.timeout)]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
