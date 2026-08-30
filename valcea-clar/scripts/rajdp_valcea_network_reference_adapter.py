#!/usr/bin/env python3
"""Evidence-first RAJDP Vâlcea road-network reference adapter.

The official RAJDP site exposes useful, mostly structural information about the
county-road operator, its maintenance sections and a road-viability document
index. This adapter intentionally keeps those surfaces as reference signals.
It never turns a static page or linked document into a claim that a road is
currently open, closed, restricted, passable or under active works.

Source-only by design: no persistence, Fact Kernel promotion, Writer/public
projection, deployment changes, inferred photo rights or live-status authority.
"""
from __future__ import annotations

import argparse
import hashlib
import html.parser
import json
import re
import ssl
import sys
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Optional
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

SOURCE_ID = "signal-rajdp-valcea-network-reference"
TAXONOMY_VERSION = "2026-08-30.1"
SOURCE_NAME = "Regia Autonomă Județeană de Drumuri și Poduri Vâlcea"
SOURCE_TIER = "T1"
ALLOWED_HOSTS = {"rajdp.ro", "www.rajdp.ro"}
CANONICAL_HOST = "rajdp.ro"
SURFACES = {
    "/": "ROAD_NETWORK_OPERATOR",
    "/contact/": "MAINTENANCE_SECTIONS",
    "/stare-viabilitate-drumuri-judetene/": "VIABILITY_DOCUMENT_INDEX",
}
MAX_RESPONSE_BYTES = 2_500_000
TIMEOUT_SECONDS = 15
USER_AGENT = "CIVORA-ValceaClar-RAJDPReference/1.0 (+evidence-first; contact via repository)"

IDENTITY_TERMS = (
    "regia autonoma judeteana de drumuri si poduri valcea",
    "r.a.j.d.p valcea",
    "r.a.j.d.p. valcea",
)
ROUTE_RE = re.compile(r"\bDJ\s*([0-9]{3}\s*[A-Z]?)\b", re.IGNORECASE)
NETWORK_KM_RE = re.compile(
    r"reteaua\s+rutiera\s+de\s+drumuri\s+judetene[^0-9]{0,120}"
    r"([0-9]{2,4}(?:[.,][0-9]{1,3})?)\s*km\b",
    re.IGNORECASE,
)
SECTION_LINE_RE = re.compile(r"^(SECTI(?:A|E)(?:\s+MECANICA)?\s+R?\.?A?\.?J?\.?D?\.?P?\.?\s*VALCEA\s*[-–—:]?\s*|SECTI(?:A|E)\s+)(.+)$", re.IGNORECASE)
PLACEHOLDER_TERMS = (
    "enable javascript",
    "access denied",
    "captcha",
    "service unavailable",
    "temporarily unavailable",
    "cloudflare",
)


@dataclass(frozen=True)
class RoadReferenceSignal:
    source_id: str
    taxonomy_version: str
    signal_class: str
    source_tier: str
    operator: str
    source_url: str
    payload_sha256: str
    evidence_excerpt: str
    hold_reason: Optional[str]
    road_network_km: Optional[float] = None
    maintenance_section: Optional[str] = None
    location_text: Optional[str] = None
    route_refs: tuple[str, ...] = ()
    document_url: Optional[str] = None
    document_label: Optional[str] = None
    snapshot_date: Optional[str] = None
    reference_scope: str = "COUNTY_ROAD_REFERENCE"
    publication_authority: str = "NONE"
    current_status_claim_allowed: bool = False
    current_viability_claim_allowed: bool = False
    current_closure_claim_allowed: bool = False
    current_restriction_claim_allowed: bool = False
    current_roadworks_claim_allowed: bool = False
    document_parse_allowed: bool = False
    inferred_photo_rights_allowed: bool = False
    persistence_allowed: bool = False
    fact_kernel_promotion_allowed: bool = False
    writer_allowed: bool = False
    public_projection_allowed: bool = False


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", clean(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _path(value: str) -> str:
    path = re.sub(r"/+", "/", unquote(value or "/"))
    if not path.startswith("/"):
        path = "/" + path
    if path != "/" and not path.endswith("/"):
        path += "/"
    return path


def validate_source_url(url: str) -> tuple[str, str]:
    parsed = urlsplit(clean(url))
    host = (parsed.hostname or "").casefold()
    path = _path(parsed.path)
    if (
        parsed.scheme.casefold() != "https"
        or host not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or path not in SURFACES
    ):
        raise ValueError(f"off-surface source refused: {url}")
    return urlunsplit(("https", CANONICAL_HOST, path, "", "")), SURFACES[path]


def normalize_document_url(value: str, base_url: str) -> Optional[str]:
    parsed = urlsplit(urljoin(base_url, clean(value)))
    host = (parsed.hostname or "").casefold()
    path = re.sub(r"/+", "/", unquote(parsed.path or "/"))
    if (
        parsed.scheme.casefold() != "https"
        or host not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not path.casefold().endswith(".pdf")
        or not path.startswith("/wp-content/uploads/")
    ):
        return None
    return urlunsplit(("https", CANONICAL_HOST, path, "", ""))


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise ValueError(f"redirect refused: {newurl}")


def fetch_html(url: str, timeout: float = TIMEOUT_SECONDS) -> tuple[str, str, bytes]:
    canonical, _ = validate_source_url(url)
    context = ssl.create_default_context()
    opener = build_opener(NoRedirects(), HTTPSHandler(context=context))
    request = Request(canonical, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
    with opener.open(request, timeout=timeout) as response:
        final_url, _ = validate_source_url(response.geturl())
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds size cap")
        charset = response.headers.get_content_charset() or "utf-8"
    return final_url, body.decode(charset, errors="replace"), body


class VisibleParser(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}
    BREAKS = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "section", "article"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts: list[str] = []
        self.anchor_href: Optional[str] = None
        self.anchor_parts: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag in self.BREAKS:
            self.parts.append("\n")
        if tag == "a" and self.anchor_href is None:
            self.anchor_href = clean(dict(attrs).get("href") or "")
            self.anchor_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.SKIP and self.skip:
            self.skip -= 1
            return
        if self.skip:
            return
        if tag == "a" and self.anchor_href is not None:
            label = clean(" ".join(self.anchor_parts))
            self.links.append((self.anchor_href, label))
            self.anchor_href = None
            self.anchor_parts = []
        if tag in self.BREAKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        value = clean(data)
        if value:
            self.parts.append(value)
            if self.anchor_href is not None:
                self.anchor_parts.append(value)

    def text(self) -> str:
        value = " ".join(self.parts)
        value = re.sub(r"[ \t\r\f\v]+", " ", value)
        value = re.sub(r"\s*\n\s*", "\n", value)
        return value.strip()


def parse_document(html_text: str) -> tuple[str, list[tuple[str, str]]]:
    parser = VisibleParser()
    parser.feed(html_text)
    return parser.text(), parser.links


def identity_present(text: str) -> bool:
    value = fold(text)
    return any(term in value for term in IDENTITY_TERMS)


def placeholder(text: str) -> bool:
    value = fold(text)[:5000]
    return any(term in value for term in PLACEHOLDER_TERMS)


def route_refs(text: str) -> tuple[str, ...]:
    values: list[str] = []
    for match in ROUTE_RE.finditer(text):
        value = "DJ " + re.sub(r"\s+", "", match.group(1)).upper()
        if value not in values:
            values.append(value)
    return tuple(values)


def hold_signal(source_url: str, digest: str, excerpt: str, reason: str) -> RoadReferenceSignal:
    return RoadReferenceSignal(
        source_id=SOURCE_ID,
        taxonomy_version=TAXONOMY_VERSION,
        signal_class="HOLD",
        source_tier=SOURCE_TIER,
        operator=SOURCE_NAME,
        source_url=source_url,
        payload_sha256=digest,
        evidence_excerpt=clean(excerpt)[:900],
        hold_reason=reason,
    )


def parse_network_operator(text: str, source_url: str, digest: str) -> list[RoadReferenceSignal]:
    match = NETWORK_KM_RE.search(fold(text))
    if not match:
        return [hold_signal(source_url, digest, text, "ROAD_NETWORK_LENGTH_NOT_EXPLICIT")]
    try:
        km = float(match.group(1).replace(",", "."))
    except ValueError:
        return [hold_signal(source_url, digest, match.group(0), "ROAD_NETWORK_LENGTH_INVALID")]
    if not (100.0 <= km <= 5_000.0):
        return [hold_signal(source_url, digest, match.group(0), "ROAD_NETWORK_LENGTH_OUT_OF_BOUNDS")]
    return [
        RoadReferenceSignal(
            source_id=SOURCE_ID,
            taxonomy_version=TAXONOMY_VERSION,
            signal_class="ROAD_NETWORK_OPERATOR_REFERENCE",
            source_tier=SOURCE_TIER,
            operator=SOURCE_NAME,
            source_url=source_url,
            payload_sha256=digest,
            evidence_excerpt=clean(match.group(0))[:900],
            hold_reason=None,
            road_network_km=km,
            reference_scope="COUNTY_ROAD_OPERATOR_AND_NETWORK_EXTENT",
        )
    ]


def normalize_section_line(line: str) -> Optional[tuple[str, str]]:
    value = clean(line)
    folded = fold(value)
    if not folded.startswith(("sectia ", "sectie ")):
        return None
    if len(value) > 220:
        return None
    match = SECTION_LINE_RE.match(value)
    if match:
        details = clean(match.group(2))
    else:
        details = re.sub(r"^SECTI(?:A|E)\s+", "", value, flags=re.IGNORECASE)
    details = clean(details.strip("-–—: "))
    if not details:
        return None
    label = clean(re.split(r"[-–—:]", details, maxsplit=1)[0])
    if not label:
        label = details
    return label, details


def parse_maintenance_sections(text: str, source_url: str, digest: str) -> list[RoadReferenceSignal]:
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line in text.splitlines():
        row = normalize_section_line(line)
        if not row:
            continue
        key = fold(row[1])
        if key in seen:
            continue
        rows.append(row)
        seen.add(key)
    if not rows:
        return [hold_signal(source_url, digest, text, "NO_EXPLICIT_MAINTENANCE_SECTIONS")]
    return [
        RoadReferenceSignal(
            source_id=SOURCE_ID,
            taxonomy_version=TAXONOMY_VERSION,
            signal_class="ROAD_MAINTENANCE_SECTION_REFERENCE",
            source_tier=SOURCE_TIER,
            operator=SOURCE_NAME,
            source_url=source_url,
            payload_sha256=digest,
            evidence_excerpt=details[:900],
            hold_reason=None,
            maintenance_section=label,
            location_text=details,
            route_refs=route_refs(details),
            reference_scope="COUNTY_ROAD_MAINTENANCE_GEOGRAPHY",
        )
        for label, details in rows
    ]


def parse_viability_index(text: str, links: list[tuple[str, str]], source_url: str, digest: str) -> list[RoadReferenceSignal]:
    candidates: list[tuple[str, str]] = []
    for href, label in links:
        document_url = normalize_document_url(href, source_url)
        if not document_url:
            continue
        if "viabil" not in fold(label) and "starea_de_viabilitate" not in fold(document_url):
            continue
        candidates.append((document_url, clean(label) or "Document stare viabilitate drumuri județene"))
    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in candidates:
        if item[0] not in seen:
            unique.append(item)
            seen.add(item[0])
    if len(unique) != 1:
        reason = "NO_EXPLICIT_VIABILITY_DOCUMENT" if not unique else "MULTIPLE_VIABILITY_DOCUMENTS_REVIEW_REQUIRED"
        return [hold_signal(source_url, digest, text, reason)]
    document_url, label = unique[0]
    return [
        RoadReferenceSignal(
            source_id=SOURCE_ID,
            taxonomy_version=TAXONOMY_VERSION,
            signal_class="ROAD_VIABILITY_DOCUMENT_REFERENCE",
            source_tier=SOURCE_TIER,
            operator=SOURCE_NAME,
            source_url=source_url,
            payload_sha256=digest,
            evidence_excerpt=label[:900],
            hold_reason=None,
            document_url=document_url,
            document_label=label,
            snapshot_date=None,
            reference_scope="ROAD_VIABILITY_DOCUMENT_INDEX_ONLY",
        )
    ]


def parse_html(html_text: str, source_url: str) -> list[RoadReferenceSignal]:
    canonical_url, surface = validate_source_url(source_url)
    body = html_text.encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    text, links = parse_document(html_text)
    if placeholder(text):
        return [hold_signal(canonical_url, digest, text, "PLACEHOLDER_OR_ACCESS_BLOCK")]
    if not identity_present(text):
        return [hold_signal(canonical_url, digest, text, "RAJDP_VALCEA_IDENTITY_NOT_EXPLICIT")]
    if surface == "ROAD_NETWORK_OPERATOR":
        return parse_network_operator(text, canonical_url, digest)
    if surface == "MAINTENANCE_SECTIONS":
        return parse_maintenance_sections(text, canonical_url, digest)
    if surface == "VIABILITY_DOCUMENT_INDEX":
        return parse_viability_index(text, links, canonical_url, digest)
    return [hold_signal(canonical_url, digest, text, "UNSUPPORTED_SURFACE")]


def assert_fail_closed(signal: RoadReferenceSignal) -> None:
    assert signal.publication_authority == "NONE"
    assert signal.current_status_claim_allowed is False
    assert signal.current_viability_claim_allowed is False
    assert signal.current_closure_claim_allowed is False
    assert signal.current_restriction_claim_allowed is False
    assert signal.current_roadworks_claim_allowed is False
    assert signal.document_parse_allowed is False
    assert signal.inferred_photo_rights_allowed is False
    assert signal.persistence_allowed is False
    assert signal.fact_kernel_promotion_allowed is False
    assert signal.writer_allowed is False
    assert signal.public_projection_allowed is False


def self_test() -> None:
    homepage = """
    <html><body><h1>R.A.J.D.P VALCEA</h1>
    <p>Regia Autonomă Judeţeană de Drumuri şi Poduri Vâlcea, este unitatea de construcţii prin care
    Consiliul Judeţean Vâlcea administrează şi întreţine reţeaua rutieră de drumuri judeţene,
    însumând 957,043km.</p></body></html>
    """
    signals = parse_html(homepage, "https://rajdp.ro/")
    assert len(signals) == 1 and signals[0].signal_class == "ROAD_NETWORK_OPERATOR_REFERENCE"
    assert signals[0].road_network_km == 957.043
    assert_fail_closed(signals[0])

    contact = """
    <html><body><h1>R.A.J.D.P VALCEA</h1>
    <h3>SECTIA DRAGASANI – STRADA DEALUL VIILOR</h3>
    <h3>SECTIA TATARANI – DJ 678A BRATIA DIN VALE</h3>
    <h3>SECTIA CALIMANESTI – DJ 703L JIBLEA</h3>
    </body></html>
    """
    rows = parse_html(contact, "https://www.rajdp.ro/contact/")
    assert len(rows) == 3 and all(row.signal_class == "ROAD_MAINTENANCE_SECTION_REFERENCE" for row in rows)
    assert rows[1].route_refs == ("DJ 678A",)
    assert rows[2].route_refs == ("DJ 703L",)
    for row in rows:
        assert_fail_closed(row)

    viability = """
    <html><body><h1>R.A.J.D.P VALCEA</h1><h2>Stare viabilitate drumuri judetene</h2>
    <a href="/wp-content/uploads/2021/07/Starea_de_viabilitate_a_drumurilor_judetene-1.pdf">
    Starea_de_viabilitate_a_drumurilor_judetene-1</a></body></html>
    """
    docs = parse_html(viability, "https://rajdp.ro/stare-viabilitate-drumuri-judetene/")
    assert len(docs) == 1 and docs[0].signal_class == "ROAD_VIABILITY_DOCUMENT_REFERENCE"
    assert docs[0].snapshot_date is None and docs[0].document_parse_allowed is False
    assert docs[0].document_url and docs[0].document_url.endswith(".pdf")
    assert_fail_closed(docs[0])

    bad_doc = """
    <html><body><h1>R.A.J.D.P VALCEA</h1>
    <a href="https://evil.example/stare-viabilitate.pdf">Viabilitatea drumurilor</a></body></html>
    """
    held = parse_html(bad_doc, "https://rajdp.ro/stare-viabilitate-drumuri-judetene/")
    assert held[0].signal_class == "HOLD" and held[0].hold_reason == "NO_EXPLICIT_VIABILITY_DOCUMENT"
    assert_fail_closed(held[0])

    missing_identity = parse_html("<html><body><h1>Contact</h1><h3>SECTIA HOREZU</h3></body></html>", "https://rajdp.ro/contact/")
    assert missing_identity[0].signal_class == "HOLD"
    assert missing_identity[0].hold_reason == "RAJDP_VALCEA_IDENTITY_NOT_EXPLICIT"

    try:
        validate_source_url("https://example.com/contact/")
    except ValueError:
        pass
    else:
        raise AssertionError("off-domain source must be refused")

    try:
        validate_source_url("https://rajdp.ro/contact/?preview=1")
    except ValueError:
        pass
    else:
        raise AssertionError("query-bearing source must be refused")

    print("RAJDP Vâlcea network reference self-test: OK")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--url", default="https://rajdp.ro/")
    parser.add_argument("--timeout", type=float, default=TIMEOUT_SECONDS)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    try:
        final_url, html_text, _ = fetch_html(args.url, timeout=args.timeout)
        signals = parse_html(html_text, final_url)
    except Exception as exc:
        print(json.dumps({"status": "HOLD_FETCH_OR_PARSE", "error": clean(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps([asdict(signal) for signal in signals], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
