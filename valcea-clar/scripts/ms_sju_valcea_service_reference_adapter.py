#!/usr/bin/env python3
"""Evidence-first Ministry of Health -> SJU Valcea service-reference adapter.

The Ministry of Health unit page exposes the hospital's explicitly described
locations and service structure. This adapter turns that static official
structure into source signals without claiming that a department is currently
open, staffed, accepting patients, or offering appointments.

It is deliberately source-only: no persistence, Fact Kernel promotion, Writer,
public projection, medical advice, or live operational-status authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from typing import Optional

SOURCE_ID = "signal-ms-sju-valcea-service-reference"
TAXONOMY_VERSION = "2026-08-29.1"
SOURCE_URL = "https://ms.gov.ro/ro/unitati-sanitare/spitalul-judetean-de-urgenta-valcea/"
ALLOWED_HOSTS = {"ms.gov.ro", "www.ms.gov.ro"}
ALLOWED_PATH = "/ro/unitati-sanitare/spitalul-judetean-de-urgenta-valcea/"
MAX_RESPONSE_BYTES = 2_500_000
USER_AGENT = "CIVORA-ValceaClar-SJUServiceReference/1.0 (+evidence-first; contact via repository)"

INSTITUTION_TERMS = (
    "spitalul judetean de urgenta valcea",
    "spitalul judetean urgenta valcea",
)


@dataclass(frozen=True)
class ServiceReferenceSignal:
    source_id: str
    taxonomy_version: str
    signal_class: str
    institution: str
    location_text: Optional[str]
    services: tuple[str, ...]
    source_url: str
    payload_sha256: str
    evidence_excerpt: str
    hold_reason: Optional[str]
    reference_scope: str = "HOSPITAL_LOCATION_SERVICES"
    publication_authority: str = "NONE"
    current_open_status_claim_allowed: bool = False
    appointment_availability_claim_allowed: bool = False
    emergency_capacity_claim_allowed: bool = False
    staffing_status_claim_allowed: bool = False
    medical_advice_allowed: bool = False
    person_extraction_allowed: bool = False
    persistence_allowed: bool = False
    fact_kernel_promotion_allowed: bool = False
    writer_allowed: bool = False
    public_projection_allowed: bool = False


class VisibleTextParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}
    BREAK_TAGS = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "section", "article"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if tag in self.SKIP:
            self._skip_depth += 1
        if not self._skip_depth and tag in self.BREAK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
            return
        if not self._skip_depth and tag in self.BREAK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        value = " ".join(self.parts)
        value = re.sub(r"[ \t\r\f\v]+", " ", value)
        value = re.sub(r"\s*\n\s*", "\n", value)
        return value.strip()


def clean_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip(" \t\r\n-;,")


def fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return clean_space("".join(ch for ch in normalized if not unicodedata.combining(ch)).lower())


def validate_source_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path if parsed.path.endswith("/") else parsed.path + "/"
    if parsed.scheme != "https" or host not in ALLOWED_HOSTS or path != ALLOWED_PATH:
        raise ValueError(f"off-surface source refused: {url}")
    return urllib.parse.urlunsplit(("https", host, ALLOWED_PATH, "", ""))


def fetch_html(url: str, timeout: float = 10.0) -> tuple[str, str, bytes]:
    requested = validate_source_url(url)
    request = urllib.request.Request(
        requested,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final_url = validate_source_url(response.geturl())
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds size cap")
        charset = response.headers.get_content_charset() or "utf-8"
    return final_url, body.decode(charset, errors="replace"), body


def visible_text(html: str) -> str:
    parser = VisibleTextParser()
    parser.feed(html)
    return parser.text()


def institution_present(text: str) -> bool:
    folded = fold(text)
    return any(term in folded for term in INSTITUTION_TERMS)


def normalize_location(value: str) -> str:
    value = clean_space(value)
    value = re.sub(r"^(?:str\.?|strada)\s+", "str. ", value, flags=re.IGNORECASE)
    return value


def normalize_service(value: str) -> Optional[str]:
    value = clean_space(value)
    value = re.sub(r"\s*\(\s*\+?\s*", " (", value)
    value = re.sub(r"\s*\)\s*", ")", value)
    if len(value) < 2 or len(value) > 140:
        return None
    folded = fold(value)
    if folded.startswith(("locatia din", "locatie din", "detalii spital", "telefon")):
        return None
    return value


def _candidate_structure_region(text: str) -> str:
    folded = fold(text)
    marker = "locatii ale"
    idx = folded.find(marker)
    if idx >= 0:
        return text[idx:]
    return text


def extract_location_sections(text: str) -> list[tuple[str, tuple[str, ...], str]]:
    """Extract only explicit `locatia din ...: service, service` sections.

    The source page currently expresses the structural map in this form. We do
    not infer departments from unrelated prose elsewhere on the page.
    """
    region = _candidate_structure_region(text)
    pattern = re.compile(
        r"(?:^|[\n;]|\s-\s)\s*loca(?:t|ț)ia\s+din\s+([^:\n]{4,180})\s*:\s*(.*?)"
        r"(?=(?:[\n;]|\s-\s)\s*loca(?:t|ț)ia\s+din\s+|\n(?:Detalii|În municipiul|In municipiul)|$)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    rows: list[tuple[str, tuple[str, ...], str]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for match in pattern.finditer(region):
        location = normalize_location(match.group(1))
        service_blob = clean_space(match.group(2))
        raw_services = re.split(r"\s*[,;]\s*", service_blob)
        services: list[str] = []
        service_seen: set[str] = set()
        for raw in raw_services:
            service = normalize_service(raw)
            if not service:
                continue
            key = fold(service)
            if key not in service_seen:
                services.append(service)
                service_seen.add(key)
        if not location or not services:
            continue
        key = (fold(location), tuple(fold(item) for item in services))
        if key in seen:
            continue
        evidence = clean_space(match.group(0))[:900]
        rows.append((location, tuple(services), evidence))
        seen.add(key)
    return rows


def hold_signal(source_url: str, payload_sha256: str, excerpt: str, reason: str) -> ServiceReferenceSignal:
    return ServiceReferenceSignal(
        source_id=SOURCE_ID,
        taxonomy_version=TAXONOMY_VERSION,
        signal_class="HOLD",
        institution="Spitalul Județean de Urgență Vâlcea",
        location_text=None,
        services=(),
        source_url=source_url,
        payload_sha256=payload_sha256,
        evidence_excerpt=clean_space(excerpt)[:900],
        hold_reason=reason,
    )


def parse_html(html: str, source_url: str = SOURCE_URL) -> list[ServiceReferenceSignal]:
    canonical_url = validate_source_url(source_url)
    body = html.encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    text = visible_text(html)
    if not institution_present(text):
        return [hold_signal(canonical_url, digest, text, "SJU_VALCEA_IDENTITY_NOT_EXPLICIT")]
    rows = extract_location_sections(text)
    if not rows:
        return [hold_signal(canonical_url, digest, text, "NO_EXPLICIT_LOCATION_SERVICE_STRUCTURE")]
    return [
        ServiceReferenceSignal(
            source_id=SOURCE_ID,
            taxonomy_version=TAXONOMY_VERSION,
            signal_class="HEALTH_SERVICE_REFERENCE",
            institution="Spitalul Județean de Urgență Vâlcea",
            location_text=location,
            services=services,
            source_url=canonical_url,
            payload_sha256=digest,
            evidence_excerpt=evidence,
            hold_reason=None,
        )
        for location, services, evidence in rows
    ]


def self_test() -> None:
    sample = """
    <html><body>
      <h1>Spitalul Judetean de Urgenta Valcea</h1>
      <p>Spitalul are patru locatii de primire/tratare a pacientilor.</p>
      <p>Locatii ale Spitalului Judetean de Urgenta Valcea:</p>
      <p>- locatia din str. Calea lui Traian, nr. 201: Medicina interna, Cardiologie (+ USTACC), ambulatoriu de specialitate;</p>
      <p>- locatia din str. General Magheru, nr. 54: Boli infectioase, Oftalmologie, Endocrinologie;</p>
      <p>În municipiul Râmnicu Vâlcea funcționează cel mai mare spital din județ.</p>
    </body></html>
    """
    signals = parse_html(sample)
    assert len(signals) == 2, signals
    assert signals[0].signal_class == "HEALTH_SERVICE_REFERENCE"
    assert signals[0].location_text == "str. Calea lui Traian, nr. 201"
    assert "Cardiologie (USTACC)" in signals[0].services
    assert signals[0].current_open_status_claim_allowed is False
    assert signals[0].appointment_availability_claim_allowed is False
    assert signals[0].emergency_capacity_claim_allowed is False
    assert signals[0].medical_advice_allowed is False
    assert signals[0].fact_kernel_promotion_allowed is False
    assert signals[0].public_projection_allowed is False

    no_identity = parse_html("<html><body><p>locatia din str. Test, nr. 1: Cardiologie</p></body></html>")
    assert no_identity[0].signal_class == "HOLD"
    assert no_identity[0].hold_reason == "SJU_VALCEA_IDENTITY_NOT_EXPLICIT"

    no_structure = parse_html("<html><body><h1>Spitalul Judetean de Urgenta Valcea</h1><p>Informatii generale.</p></body></html>")
    assert no_structure[0].signal_class == "HOLD"
    assert no_structure[0].hold_reason == "NO_EXPLICIT_LOCATION_SERVICE_STRUCTURE"

    try:
        validate_source_url("https://example.com/ro/unitati-sanitare/spitalul-judetean-de-urgenta-valcea/")
    except ValueError:
        pass
    else:
        raise AssertionError("off-domain URL was not refused")

    print("SJU service-reference self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", help="Read an already captured UTF-8 HTML file instead of network fetch")
    parser.add_argument("--source-url", default=SOURCE_URL)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    try:
        if args.input:
            with open(args.input, "r", encoding="utf-8") as handle:
                html = handle.read(MAX_RESPONSE_BYTES + 1)
            if len(html.encode("utf-8")) > MAX_RESPONSE_BYTES:
                raise ValueError("input exceeds size cap")
            signals = parse_html(html, args.source_url)
        else:
            final_url, html, _ = fetch_html(args.source_url, timeout=args.timeout)
            signals = parse_html(html, final_url)
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc), "fail_closed": True}, ensure_ascii=False))
        return 2

    print(json.dumps([asdict(signal) for signal in signals], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
