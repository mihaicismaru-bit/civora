#!/usr/bin/env python3
"""Evidence-first CAS Valcea health-service access signal adapter.

The adapter reads only public CAS Valcea index/directory HTML on the current
cas.cnas.ro/casvl surface (while allowing first-party CNAS legacy links) and emits
service-directory references. It never downloads linked PDF/XLS/DOC bodies and
never asserts that a provider is currently available, open, contracted, or
accepting patients.

This is a signal-only boundary: no persistence, Fact Kernel authority, Writer,
public projection, appointment availability, or medical-status claims.
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
from pathlib import Path
from typing import Optional

SOURCE_ID = "signal-cas-valcea-service-access"
TAXONOMY_VERSION = "2026-08-30.1"
START_URLS = (
    "https://cas.cnas.ro/casvl/informatii-furnizori/furnizori-de-servicii-medicale",
)
ALLOWED_HOSTS = {"cas.cnas.ro", "cnas.ro", "www.cnas.ro"}
ALLOWED_PATH_PREFIX = "/casvl/"
MAX_RESPONSE_BYTES = 2_500_000
USER_AGENT = "CIVORA-ValceaClar-CASServiceSignals/1.0 (+evidence-first; contact via repository)"
DOCUMENT_SUFFIXES = (".pdf", ".doc", ".docx", ".odt", ".xls", ".xlsx", ".csv")

CATEGORY_RULES = (
    ("PRIMARY_CARE", ("medicina primara", "asistenta medicala primara", "medici de familie")),
    ("OUTPATIENT_SPECIALTY", ("ambulatoriu", "specialitati clinice", "specialitate clinica")),
    ("PARACLINICAL", ("paraclinic", "laborator", "imagistica")),
    ("HOSPITAL", ("spitalic", "spitalicesc")),
    ("PHARMACY", ("farmac", "medicamente")),
    ("MEDICAL_DEVICES", ("dispozitive medicale",)),
    ("HOME_CARE", ("ingrijiri la domiciliu", "paliative la domiciliu")),
    ("DENTAL", ("stomatolog", "medicina dentara", "dentar")),
    ("REHABILITATION", ("recuperare", "reabilitare")),
)

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
class ServiceAccessSignal:
    signal_id: str
    source_id: str
    taxonomy_version: str
    signal_class: str
    directory_scope: str
    title: str
    source_url: str
    index_url: str
    index_date: Optional[str]
    payload_sha256: str
    reference_kind: str
    hold_reason: Optional[str]
    publication_authority: str = "NONE"
    current_provider_status_claim_allowed: bool = False
    appointment_availability_claim_allowed: bool = False
    linked_document_body_parse_allowed: bool = False
    provider_person_extraction_allowed: bool = False


class IndexParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._href: Optional[str] = None
        self._anchor_parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if tag in self.SKIP:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._href = href
                self._anchor_parts = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = clean_space(data)
        if not text:
            return
        self.text_parts.append(text)
        if self._href is not None:
            self._anchor_parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if tag == "a" and self._href is not None:
            text = clean_space(" ".join(self._anchor_parts))
            self.links.append((self._href, text))
            self._href = None
            self._anchor_parts = []


def clean_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return clean_space("".join(ch for ch in normalized if not unicodedata.combining(ch)).lower())


def canonical_allowed_url(base: str, href: str) -> Optional[str]:
    try:
        url = urllib.parse.urljoin(base, href)
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in ALLOWED_HOSTS:
        return None
    if not parsed.path.startswith(ALLOWED_PATH_PREFIX):
        return None
    return urllib.parse.urlunsplit(("https", parsed.netloc.lower(), parsed.path, parsed.query, ""))


def fetch_html(url: str, timeout: float = 10.0) -> tuple[str, str, bytes]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final_url = response.geturl()
        parsed = urllib.parse.urlsplit(final_url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or host not in ALLOWED_HOSTS or not parsed.path.startswith(ALLOWED_PATH_PREFIX):
            raise ValueError(f"off-surface redirect refused: {final_url}")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds size cap")
        charset = response.headers.get_content_charset() or "utf-8"
    return final_url, body.decode(charset, errors="replace"), body


def extract_index_date(text: str) -> Optional[str]:
    folded = fold(text)
    month_pattern = "|".join(ROMANIAN_MONTHS)
    match = re.search(rf"\b([0-3]?\d)\s+({month_pattern})\s+(20\d{{2}})\b", folded)
    if match:
        day, month_name, year = match.groups()
        try:
            return date(int(year), ROMANIAN_MONTHS[month_name], int(day)).isoformat()
        except ValueError:
            return None
    match = re.search(r"\b([0-3]?\d)[./-]([01]?\d)[./-](20\d{2})\b", folded)
    if match:
        day, month, year = match.groups()
        try:
            return date(int(year), int(month), int(day)).isoformat()
        except ValueError:
            return None
    return None


def directory_scope(anchor_text: str, url: str) -> Optional[str]:
    haystack = fold(anchor_text + " " + urllib.parse.urlsplit(url).path.replace("-", " "))
    for scope, terms in CATEGORY_RULES:
        if any(term in haystack for term in terms):
            return scope
    return None


def reference_kind(url: str) -> str:
    path = urllib.parse.urlsplit(url).path.lower()
    return "DOCUMENT_REFERENCE" if path.endswith(DOCUMENT_SUFFIXES) else "HTML_REFERENCE"


def deterministic_signal_id(scope: str, source_url: str) -> str:
    digest = hashlib.sha256(f"{scope}\0{source_url}".encode("utf-8")).hexdigest()[:20]
    return f"casvl-{scope.lower().replace('_', '-')}-{digest}"


def analyze_index(html: str, index_url: str, raw_payload: bytes) -> list[ServiceAccessSignal]:
    parsed_index = urllib.parse.urlsplit(index_url)
    if (
        parsed_index.scheme != "https"
        or (parsed_index.hostname or "").lower() not in ALLOWED_HOSTS
        or not parsed_index.path.startswith(ALLOWED_PATH_PREFIX)
    ):
        raise ValueError(f"untrusted index URL: {index_url}")

    parser = IndexParser()
    parser.feed(html)
    visible = clean_space(" ".join(parser.text_parts))
    index_date = extract_index_date(visible[:5000])
    payload_sha256 = hashlib.sha256(raw_payload).hexdigest()

    signals: list[ServiceAccessSignal] = []
    seen: set[tuple[str, str]] = set()
    for href, text in parser.links:
        source_url = canonical_allowed_url(index_url, href)
        if not source_url:
            continue
        scope = directory_scope(text, source_url)
        if not scope:
            continue
        key = (scope, source_url)
        if key in seen:
            continue
        seen.add(key)
        signals.append(
            ServiceAccessSignal(
                signal_id=deterministic_signal_id(scope, source_url),
                source_id=SOURCE_ID,
                taxonomy_version=TAXONOMY_VERSION,
                signal_class="HEALTH_PROVIDER_DIRECTORY",
                directory_scope=scope,
                title=clean_space(text)[:300] or f"CAS Valcea provider directory — {scope}",
                source_url=source_url,
                index_url=index_url,
                index_date=index_date,
                payload_sha256=payload_sha256,
                reference_kind=reference_kind(source_url),
                hold_reason=None,
            )
        )

    if not signals:
        signals.append(
            ServiceAccessSignal(
                signal_id=deterministic_signal_id("HOLD", index_url),
                source_id=SOURCE_ID,
                taxonomy_version=TAXONOMY_VERSION,
                signal_class="HOLD",
                directory_scope="UNKNOWN",
                title="CAS Valcea provider directory index",
                source_url=index_url,
                index_url=index_url,
                index_date=index_date,
                payload_sha256=payload_sha256,
                reference_kind="HTML_REFERENCE",
                hold_reason="NO_EXPLICIT_SERVICE_CATEGORY_REFERENCE",
            )
        )
    signals.sort(key=lambda item: (item.directory_scope, item.source_url))
    return signals


def collect(timeout: float) -> list[ServiceAccessSignal]:
    collected: list[ServiceAccessSignal] = []
    seen_ids: set[str] = set()
    for url in START_URLS:
        try:
            final_url, html, raw = fetch_html(url, timeout=timeout)
            signals = analyze_index(html, final_url, raw)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            print(f"WARN CAS Valcea index fetch failed: {url}: {exc}", file=sys.stderr)
            continue
        for signal in signals:
            if signal.signal_id in seen_ids:
                continue
            seen_ids.add(signal.signal_id)
            collected.append(signal)
    collected.sort(key=lambda item: (item.signal_class, item.directory_scope, item.source_url))
    return collected


def self_test() -> None:
    sample = """
    <html><body>
      <h1>Lista furnizorilor CAS Vâlcea</h1>
      <p>3 noiembrie 2025</p>
      <a href="/casvl/wp-content/uploads/2026/08/furnizori-medicina-primara.xlsx">
        Asistență medicală primară
      </a>
      <a href="/casvl/informatii-furnizori/furnizori-de-servicii-medicale/asistenta-medicala-spitaliceasca/">
        Asistență medicală spitalicească
      </a>
      <a href="/casvl/informatii-furnizori/furnizori-de-servicii-medicale/farmacii/">Farmacii și medicamente</a>
      <a href="https://example.invalid/providers.pdf">Asistență medicală primară</a>
    </body></html>
    """
    signals = analyze_index(
        sample,
        "https://cas.cnas.ro/casvl/informatii-furnizori/furnizori-de-servicii-medicale",
        sample.encode("utf-8"),
    )
    assert [s.directory_scope for s in signals] == ["HOSPITAL", "PHARMACY", "PRIMARY_CARE"]
    primary = next(s for s in signals if s.directory_scope == "PRIMARY_CARE")
    assert primary.reference_kind == "DOCUMENT_REFERENCE"
    assert primary.source_url.startswith("https://cas.cnas.ro/casvl/")
    assert primary.signal_class == "HEALTH_PROVIDER_DIRECTORY"
    assert primary.index_date == "2025-11-03"
    assert primary.publication_authority == "NONE"
    assert primary.current_provider_status_claim_allowed is False
    assert primary.appointment_availability_claim_allowed is False
    assert primary.linked_document_body_parse_allowed is False
    assert primary.provider_person_extraction_allowed is False
    assert all("example.invalid" not in s.source_url for s in signals)

    empty = "<html><body><h1>CAS Vâlcea</h1><p>Informații generale.</p></body></html>"
    held = analyze_index(
        empty,
        "https://cas.cnas.ro/casvl/informatii-furnizori/furnizori-de-servicii-medicale",
        empty.encode(),
    )
    assert len(held) == 1
    assert held[0].signal_class == "HOLD"
    assert held[0].hold_reason == "NO_EXPLICIT_SERVICE_CATEGORY_REFERENCE"

    assert canonical_allowed_url(
        "https://cas.cnas.ro/casvl/informatii-furnizori/furnizori-de-servicii-medicale",
        "https://cas.cnas.ro/casvl/wp-content/uploads/2026/08/furnizori-medicina-primara.xlsx",
    )
    assert canonical_allowed_url(
        "https://cas.cnas.ro/casvl/informatii-furnizori/furnizori-de-servicii-medicale",
        "https://cnas.ro/casvl/lista-furnizorilor-cas-valcea/",
    )
    assert canonical_allowed_url(
        "https://cas.cnas.ro/casvl/informatii-furnizori/furnizori-de-servicii-medicale",
        "https://cas.cnas.ro/casag/file.pdf",
    ) is None
    assert canonical_allowed_url(
        "https://cas.cnas.ro/casvl/informatii-furnizori/furnizori-de-servicii-medicale",
        "https://evil.example/casvl/file.pdf",
    ) is None

    print("CAS Valcea service-access adapter self-test: OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", help="Parse a local HTML fixture instead of fetching CAS Valcea.")
    parser.add_argument(
        "--source-url",
        default=START_URLS[0],
        help="Official CAS Valcea URL represented by --input.",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    if args.input:
        raw = Path(args.input).read_bytes()
        html = raw.decode("utf-8", errors="replace")
        signals = analyze_index(html, args.source_url, raw)
    else:
        signals = collect(timeout=max(1.0, min(args.timeout, 30.0)))

    json.dump([asdict(signal) for signal in signals], sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
