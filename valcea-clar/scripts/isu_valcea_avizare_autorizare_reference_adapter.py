#!/usr/bin/env python3
"""Fail-closed ISU Vâlcea avizare/autorizare index adapter.

Reads only the official ``/avizare-autorizare`` index and emits bounded
reference metadata for fire-safety authorization/service documents. It does
not follow article/document links, determine current legal validity, parse
entities from registries, provide legal advice, or grant publication/media
authority.
"""
from __future__ import annotations

import argparse
import hashlib
import html.parser
import json
import re
import ssl
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

SOURCE_ID = "reference-isu-valcea-avizare-autorizare"
TAXONOMY_VERSION = "2026-08-31.1"
SOURCE_NAME = "ISU Vâlcea — Avizare-autorizare"
SOURCE_TIER = "T1_OFFICIAL_EMERGENCY_SERVICE"
SOURCE_URL = "https://isuvl.igsu.ro/avizare-autorizare"
HOST = "isuvl.igsu.ro"
INDEX_PATH = "/avizare-autorizare"
ARTICLE_PREFIX = "/avizare-autorizare/"
MAX_BODY_BYTES = 2_000_000
TIMEOUT_SECONDS = 15
USER_AGENT = "CIVORA-ValceaClar-ISUVL-Avizare/1.0 (+evidence-first; contact via repository)"

MONTHS = {
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4,
    "mai": 5, "iunie": 6, "iulie": 7, "august": 8,
    "septembrie": 9, "octombrie": 10, "noiembrie": 11, "decembrie": 12,
}
MONTH_RE = "|".join(MONTHS)
DATE_RE = re.compile(rf"\b([0-3]?\d)\s+({MONTH_RE})\s+(20\d{{2}})\b", re.I)
REGISTRY_AS_OF_RE = re.compile(
    r"(?:actualizat[aă]?\s+la\s+data\s+de|actualizat[aă]?\s+la|la\s+data\s+de)\s*"
    r"([0-3]?\d)[.\-/]([01]?\d)[.\-/](20\d{2})",
    re.I,
)
IDENTITY_TERMS = (
    "inspectoratul pentru situatii de urgenta",
    "general magheru",
    "judetului valcea",
)
PLACEHOLDER_TERMS = (
    "access denied", "captcha", "temporarily unavailable", "service unavailable",
    "verify you are human", "cloudflare",
)


@dataclass(frozen=True)
class AvizareReference:
    signal_id: str
    source_id: str
    taxonomy_version: str
    reference_class: str
    review_status: str
    source_name: str
    source_tier: str
    index_url: str
    reference_url: Optional[str]
    title: Optional[str]
    publication_date: Optional[str]
    stated_registry_as_of_date: Optional[str]
    as_of_date: str
    age_days: Optional[int]
    age_band: str
    payload_sha256: str
    evidence_excerpt: str
    hold_reason: Optional[str]
    publication_authority: str = "NONE"
    article_or_document_fetch_allowed: bool = False
    document_body_ingest_allowed: bool = False
    authorization_validity_claim_allowed: bool = False
    legal_status_claim_allowed: bool = False
    current_compliance_claim_allowed: bool = False
    current_procedure_validity_claim_allowed: bool = False
    entity_or_address_extraction_allowed: bool = False
    person_level_extraction_allowed: bool = False
    legal_advice_allowed: bool = False
    breaking_news_promotion_allowed: bool = False
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


def normalize_index_url(url: str) -> str:
    parsed = urlsplit(clean(url))
    path = re.sub(r"/+", "/", unquote(parsed.path or "/"))
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != HOST
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or path.rstrip("/") != INDEX_PATH
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"off-surface avizare index refused: {url}")
    return SOURCE_URL


def normalize_reference_url(value: str) -> Optional[str]:
    parsed = urlsplit(urljoin(SOURCE_URL, clean(value)))
    path = re.sub(r"/+", "/", unquote(parsed.path or "/"))
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != HOST
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not path.startswith(ARTICLE_PREFIX)
        or path.rstrip("/") == INDEX_PATH
        or parsed.query
        or parsed.fragment
    ):
        return None
    return urlunsplit(("https", HOST, path, "", ""))


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise ValueError(f"redirect refused: {newurl}")


class IndexParser(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.tokens: list[str] = []
        self.current_url: Optional[str] = None
        self.current_parts: list[str] = []
        self.current_start = 0
        self.links: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "a":
            href = dict(attrs).get("href") or ""
            normalized = normalize_reference_url(href)
            if normalized:
                self.current_url = normalized
                self.current_parts = []
                self.current_start = len(self.tokens)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.SKIP and self.skip:
            self.skip -= 1
            return
        if self.skip:
            return
        if tag == "a" and self.current_url:
            self.links.append({
                "url": self.current_url,
                "title": clean(" ".join(self.current_parts)),
                "start": self.current_start,
                "end": len(self.tokens),
            })
            self.current_url = None
            self.current_parts = []

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        value = clean(data)
        if not value:
            return
        self.tokens.append(value)
        if self.current_url:
            self.current_parts.append(value)


def page_identity_ok(tokens: list[str]) -> bool:
    value = fold(" ".join(tokens[:120]))
    return all(term in value for term in IDENTITY_TERMS) or "isu valcea" in value


def is_placeholder(tokens: list[str]) -> bool:
    value = fold(" ".join(tokens[:50]))
    return any(term in value for term in PLACEHOLDER_TERMS)


def parse_publication_date(text: str) -> Optional[str]:
    values: set[str] = set()
    for day, month_name, year in DATE_RE.findall(fold(text)):
        try:
            values.add(date(int(year), MONTHS[month_name], int(day)).isoformat())
        except ValueError:
            continue
    return next(iter(values)) if len(values) == 1 else None


def parse_registry_as_of_date(text: str) -> Optional[str]:
    values: set[str] = set()
    for day, month, year in REGISTRY_AS_OF_RE.findall(fold(text)):
        try:
            values.add(date(int(year), int(month), int(day)).isoformat())
        except ValueError:
            continue
    return next(iter(values)) if len(values) == 1 else None


def classify(title: str) -> Optional[str]:
    value = fold(title)
    if (
        ("evidenta" in value or "registr" in value)
        and "autoriz" in value
        and "securitate la incendiu" in value
    ):
        return "FIRE_SAFETY_AUTHORIZATION_REGISTRY_REFERENCE"
    if "depunere online" in value and ("avizare" in value or "autorizare" in value):
        return "ELECTRONIC_SUBMISSION_PROCEDURE_REFERENCE"
    if "modele document" in value:
        return "DOCUMENT_TEMPLATE_REFERENCE"
    if value == "cereri" or value.startswith("cereri "):
        return "APPLICATION_FORMS_REFERENCE"
    if "firme" in value and "experti" in value and "atestat" in value:
        return "ACCREDITED_FIRMS_EXPERTS_REFERENCE"
    return None


def age_band(days: int) -> str:
    if days <= 30:
        return "REFERENCE_0_30_DAYS"
    if days <= 180:
        return "REFERENCE_31_180_DAYS"
    if days <= 730:
        return "REFERENCE_181_730_DAYS"
    return "REFERENCE_OVER_730_DAYS"


def held(payload_hash: str, as_of: date, reason: str, identity_basis: str) -> AvizareReference:
    sid = hashlib.sha256(f"{SOURCE_ID}\0{identity_basis}\0{reason}".encode()).hexdigest()[:20]
    return AvizareReference(
        signal_id=f"isuvl-avizare-{sid}", source_id=SOURCE_ID,
        taxonomy_version=TAXONOMY_VERSION, reference_class="HOLD_AVIZARE_REFERENCE",
        review_status="HOLD", source_name=SOURCE_NAME, source_tier=SOURCE_TIER,
        index_url=SOURCE_URL, reference_url=None, title=None, publication_date=None,
        stated_registry_as_of_date=None, as_of_date=as_of.isoformat(), age_days=None,
        age_band="UNKNOWN", payload_sha256=payload_hash,
        evidence_excerpt="HELD_ISU_AVIZARE_REFERENCE_METADATA_SUPPRESSED",
        hold_reason=reason,
    )


def extract(html_text: str, *, final_url: str, payload: bytes, as_of: date) -> list[AvizareReference]:
    normalize_index_url(final_url)
    parser = IndexParser()
    parser.feed(html_text)
    parser.close()
    payload_hash = hashlib.sha256(payload).hexdigest()

    if is_placeholder(parser.tokens):
        return [held(payload_hash, as_of, "PLACEHOLDER_OR_CHALLENGE_PAGE", final_url)]
    if not page_identity_ok(parser.tokens):
        return [held(payload_hash, as_of, "ISU_VALCEA_IDENTITY_NOT_PRESENT", final_url)]

    output: list[AvizareReference] = []
    for index, link in enumerate(parser.links):
        title = clean(link["title"])
        if not title:
            continue
        next_start = int(parser.links[index + 1]["start"]) if index + 1 < len(parser.links) else len(parser.tokens)
        context = clean(" ".join(parser.tokens[int(link["start"]):next_start]))
        cls = classify(title)
        basis = f"{link['url']}\0{title}"
        if cls is None:
            output.append(held(payload_hash, as_of, "UNCLASSIFIED_AVIZARE_REFERENCE", basis))
            continue

        pub = parse_publication_date(context)
        if pub is None:
            output.append(held(payload_hash, as_of, "PUBLICATION_DATE_MISSING_OR_AMBIGUOUS", basis))
            continue
        pub_date = date.fromisoformat(pub)
        if pub_date > as_of:
            output.append(held(payload_hash, as_of, "FUTURE_PUBLICATION_DATE", basis))
            continue

        registry_as_of: Optional[str] = None
        if cls == "FIRE_SAFETY_AUTHORIZATION_REGISTRY_REFERENCE":
            registry_as_of = parse_registry_as_of_date(context)
            has_registry_update_marker = "actualizat" in fold(context) and "data" in fold(context)
            if has_registry_update_marker and registry_as_of is None:
                output.append(held(payload_hash, as_of, "REGISTRY_AS_OF_DATE_AMBIGUOUS", basis))
                continue
            if registry_as_of is not None:
                registry_date = date.fromisoformat(registry_as_of)
                if registry_date > as_of:
                    output.append(held(payload_hash, as_of, "FUTURE_REGISTRY_AS_OF_DATE", basis))
                    continue

        days = (as_of - pub_date).days
        sid = hashlib.sha256(
            f"{SOURCE_ID}\0{link['url']}\0{title}\0{pub}\0{registry_as_of or ''}".encode()
        ).hexdigest()[:20]
        evidence = f"{title} | official ISU Vâlcea index date {pub}"
        if registry_as_of:
            evidence += f" | registry explicitly states updated through {registry_as_of}"
        output.append(AvizareReference(
            signal_id=f"isuvl-avizare-{sid}", source_id=SOURCE_ID,
            taxonomy_version=TAXONOMY_VERSION, reference_class=cls,
            review_status="REVIEW_REQUIRED", source_name=SOURCE_NAME, source_tier=SOURCE_TIER,
            index_url=SOURCE_URL, reference_url=link["url"], title=title,
            publication_date=pub, stated_registry_as_of_date=registry_as_of,
            as_of_date=as_of.isoformat(), age_days=days, age_band=age_band(days),
            payload_sha256=payload_hash, evidence_excerpt=evidence, hold_reason=None,
        ))
    return output


def validate_boundaries(item: AvizareReference) -> None:
    flags = (
        "article_or_document_fetch_allowed", "document_body_ingest_allowed",
        "authorization_validity_claim_allowed", "legal_status_claim_allowed",
        "current_compliance_claim_allowed", "current_procedure_validity_claim_allowed",
        "entity_or_address_extraction_allowed", "person_level_extraction_allowed",
        "legal_advice_allowed", "breaking_news_promotion_allowed",
        "inferred_photo_rights_allowed", "persistence_allowed",
        "fact_kernel_promotion_allowed", "writer_allowed", "public_projection_allowed",
    )
    if any(getattr(item, name) for name in flags):
        raise AssertionError("ISU avizare authority boundary drift")
    if item.publication_authority != "NONE":
        raise AssertionError("publication authority drift")
    if item.review_status == "HOLD":
        if item.reference_url or item.title or item.publication_date or item.stated_registry_as_of_date:
            raise AssertionError("held ISU avizare signal leaks metadata")
        if item.evidence_excerpt != "HELD_ISU_AVIZARE_REFERENCE_METADATA_SUPPRESSED":
            raise AssertionError("held ISU avizare signal leaks evidence")


def fetch_html(url: str = SOURCE_URL) -> tuple[str, str, bytes]:
    canonical = normalize_index_url(url)
    opener = build_opener(NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(canonical, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
    with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        final_url = normalize_index_url(response.geturl())
        body = response.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            raise ValueError("response exceeds bounded body limit")
        content_type = clean(response.headers.get("Content-Type")).casefold()
        if content_type and "html" not in content_type:
            raise ValueError(f"unexpected content type: {content_type}")
        charset = response.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace"), final_url, body


def self_test() -> None:
    sample = """
    <html><body>
      <div>INSPECTORATUL PENTRU SITUAȚII DE URGENȚĂ ”GENERAL MAGHERU” AL JUDEȚULUI VÂLCEA</div>
      <h1>Avizare-autorizare</h1>
      <a href="/avizare-autorizare/evidenta-constructiilor-care-detin-autorizatie-1">EVIDENȚA CONSTRUCȚIILOR, AMENAJĂRILOR ȘI INSTALAȚIILOR CARE DEȚIN AUTORIZAȚIE DE SECURITATE LA INCENDIU</a>
      <span>09 septembrie 2025</span><p>Evidența din 2011 ACTUALIZATĂ LA DATA DE 31.07.2025</p>
      <a href="/avizare-autorizare/depunere-online-documentatii-2">Depunere online a documentațiilor electronice pentru avizare și autorizare</a>
      <span>23 martie 2026</span>
      <a href="/avizare-autorizare/modele-documente-3">MODELE DOCUMENTE</a>
      <span>17 decembrie 2024</span>
      <a href="/avizare-autorizare/cereri-4">CERERI</a>
      <span>17 decembrie 2024</span>
      <a href="/avizare-autorizare/firme-si-experti-atestati-5">FIRME ȘI EXPERȚI ATESTAȚI</a>
      <span>17 decembrie 2024</span>
    </body></html>
    """
    result = extract(sample, final_url=SOURCE_URL, payload=sample.encode(), as_of=date(2026, 8, 31))
    assert [r.reference_class for r in result] == [
        "FIRE_SAFETY_AUTHORIZATION_REGISTRY_REFERENCE",
        "ELECTRONIC_SUBMISSION_PROCEDURE_REFERENCE",
        "DOCUMENT_TEMPLATE_REFERENCE",
        "APPLICATION_FORMS_REFERENCE",
        "ACCREDITED_FIRMS_EXPERTS_REFERENCE",
    ]
    assert result[0].publication_date == "2025-09-09"
    assert result[0].stated_registry_as_of_date == "2025-07-31"
    assert result[1].publication_date == "2026-03-23"
    assert result[0].authorization_validity_claim_allowed is False
    assert result[1].current_procedure_validity_claim_allowed is False
    for item in result:
        validate_boundaries(item)

    unknown = sample.replace("MODELE DOCUMENTE", "ALT MATERIAL NECUNOSCUT")
    unknown_result = extract(unknown, final_url=SOURCE_URL, payload=unknown.encode(), as_of=date(2026, 8, 31))[2]
    assert unknown_result.review_status == "HOLD"
    assert unknown_result.hold_reason == "UNCLASSIFIED_AVIZARE_REFERENCE"
    validate_boundaries(unknown_result)

    future_pub = sample.replace("23 martie 2026", "01 septembrie 2026", 1)
    future_result = extract(future_pub, final_url=SOURCE_URL, payload=future_pub.encode(), as_of=date(2026, 8, 31))[1]
    assert future_result.hold_reason == "FUTURE_PUBLICATION_DATE"

    future_registry = sample.replace("31.07.2025", "01.09.2026", 1)
    future_registry_result = extract(
        future_registry, final_url=SOURCE_URL, payload=future_registry.encode(), as_of=date(2026, 8, 31)
    )[0]
    assert future_registry_result.hold_reason == "FUTURE_REGISTRY_AS_OF_DATE"

    ambiguous_registry = sample.replace(
        "ACTUALIZATĂ LA DATA DE 31.07.2025",
        "ACTUALIZATĂ LA DATA DE 31.07.2025 și ACTUALIZATĂ LA DATA DE 01.08.2025",
        1,
    )
    ambiguous_registry_result = extract(
        ambiguous_registry, final_url=SOURCE_URL, payload=ambiguous_registry.encode(), as_of=date(2026, 8, 31)
    )[0]
    assert ambiguous_registry_result.hold_reason == "REGISTRY_AS_OF_DATE_AMBIGUOUS"

    no_registry_as_of = sample.replace("<p>Evidența din 2011 ACTUALIZATĂ LA DATA DE 31.07.2025</p>", "", 1)
    no_registry_result = extract(
        no_registry_as_of, final_url=SOURCE_URL, payload=no_registry_as_of.encode(), as_of=date(2026, 8, 31)
    )[0]
    assert no_registry_result.review_status == "REVIEW_REQUIRED"
    assert no_registry_result.stated_registry_as_of_date is None

    for url in (
        "http://isuvl.igsu.ro/avizare-autorizare",
        "https://isuvl.igsu.ro/avizare-autorizare?x=1",
        "https://isuvl.igsu.ro/informare-preventiva",
        "https://example.com/avizare-autorizare",
    ):
        try:
            normalize_index_url(url)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe index URL accepted: {url}")
    assert normalize_reference_url("/avizare-autorizare/item-1?x=1") is None
    assert normalize_reference_url("https://example.com/avizare-autorizare/item-1") is None
    print("ISU Vâlcea avizare-autorizare reference self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.as_of:
        parser.error("--as-of is required unless --self-test is used")
    try:
        as_of = date.fromisoformat(args.as_of)
    except ValueError as exc:
        raise SystemExit("--as-of must be YYYY-MM-DD") from exc
    html_text, final_url, payload = fetch_html()
    result = extract(html_text, final_url=final_url, payload=payload, as_of=as_of)
    for item in result:
        validate_boundaries(item)
    rendered = json.dumps([asdict(item) for item in result], ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
