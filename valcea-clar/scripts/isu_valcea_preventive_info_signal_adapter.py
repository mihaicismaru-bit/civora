#!/usr/bin/env python3
"""Fail-closed ISU Vâlcea preventive-information index adapter.

Reads only the official ``/informare-preventiva`` index and emits bounded
reference metadata for preventive campaigns/material collections. It does not
follow article/document links, ingest guidance bodies, infer current hazards,
or grant publication/media authority.
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

SOURCE_ID = "signal-isu-valcea-informare-preventiva"
TAXONOMY_VERSION = "2026-08-30.1"
SOURCE_NAME = "ISU Vâlcea — Informare preventivă"
SOURCE_TIER = "T1_OFFICIAL_EMERGENCY_SERVICE"
SOURCE_URL = "https://isuvl.igsu.ro/informare-preventiva"
HOST = "isuvl.igsu.ro"
INDEX_PATH = "/informare-preventiva"
ARTICLE_PREFIX = "/informare-preventiva/"
MAX_BODY_BYTES = 2_000_000
TIMEOUT_SECONDS = 15
USER_AGENT = "CIVORA-ValceaClar-ISUVL-Prevention/1.0 (+evidence-first; contact via repository)"

MONTHS = {
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4,
    "mai": 5, "iunie": 6, "iulie": 7, "august": 8,
    "septembrie": 9, "octombrie": 10, "noiembrie": 11, "decembrie": 12,
}
MONTH_RE = "|".join(MONTHS)
DATE_RE = re.compile(rf"\b([0-3]?\d)\s+({MONTH_RE})\s+(20\d{{2}})\b", re.I)
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
class PreventiveReference:
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
    as_of_date: str
    age_days: Optional[int]
    age_band: str
    payload_sha256: str
    evidence_excerpt: str
    hold_reason: Optional[str]
    publication_authority: str = "NONE"
    article_or_document_fetch_allowed: bool = False
    guidance_body_ingest_allowed: bool = False
    guidance_content_projection_allowed: bool = False
    current_hazard_claim_allowed: bool = False
    current_warning_validity_claim_allowed: bool = False
    breaking_news_promotion_allowed: bool = False
    medical_advice_allowed: bool = False
    person_level_extraction_allowed: bool = False
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
        raise ValueError(f"off-surface prevention index refused: {url}")
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
    value = fold(" ".join(tokens[:100]))
    return all(term in value for term in IDENTITY_TERMS) or "isu valcea" in value


def is_placeholder(tokens: list[str]) -> bool:
    value = fold(" ".join(tokens[:50]))
    return any(term in value for term in PLACEHOLDER_TERMS)


def parse_date(text: str) -> Optional[str]:
    values: set[str] = set()
    for day, month_name, year in DATE_RE.findall(fold(text)):
        try:
            values.add(date(int(year), MONTHS[month_name], int(day)).isoformat())
        except ValueError:
            continue
    return next(iter(values)) if len(values) == 1 else None


def classify(title: str) -> Optional[str]:
    value = fold(title)
    if "festival" in value or "petrece responsabil" in value:
        return "PREVENTIVE_CAMPAIGN_REFERENCE"
    if "materiale informare preventiva" in value and "i.g.s.u" in value:
        return "NATIONAL_PREVENTIVE_MATERIALS_REFERENCE"
    if "materiale informare preventiva" in value and "isu valcea" in value:
        return "LOCAL_PREVENTIVE_MATERIALS_REFERENCE"
    return None


def age_band(days: int) -> str:
    if days <= 30:
        return "REFERENCE_0_30_DAYS"
    if days <= 180:
        return "REFERENCE_31_180_DAYS"
    if days <= 730:
        return "REFERENCE_181_730_DAYS"
    return "REFERENCE_OVER_730_DAYS"


def held(payload_hash: str, as_of: date, reason: str, identity_basis: str) -> PreventiveReference:
    sid = hashlib.sha256(f"{SOURCE_ID}\0{identity_basis}\0{reason}".encode()).hexdigest()[:20]
    return PreventiveReference(
        signal_id=f"isuvl-prevention-{sid}", source_id=SOURCE_ID,
        taxonomy_version=TAXONOMY_VERSION, reference_class="HOLD_PREVENTIVE_REFERENCE",
        review_status="HOLD", source_name=SOURCE_NAME, source_tier=SOURCE_TIER,
        index_url=SOURCE_URL, reference_url=None, title=None, publication_date=None,
        as_of_date=as_of.isoformat(), age_days=None, age_band="UNKNOWN",
        payload_sha256=payload_hash, evidence_excerpt="HELD_PREVENTIVE_REFERENCE_METADATA_SUPPRESSED",
        hold_reason=reason,
    )


def extract(html_text: str, *, final_url: str, payload: bytes, as_of: date) -> list[PreventiveReference]:
    normalize_index_url(final_url)
    parser = IndexParser()
    parser.feed(html_text)
    parser.close()
    payload_hash = hashlib.sha256(payload).hexdigest()
    if is_placeholder(parser.tokens):
        return [held(payload_hash, as_of, "PLACEHOLDER_OR_CHALLENGE_PAGE", final_url)]
    if not page_identity_ok(parser.tokens):
        return [held(payload_hash, as_of, "ISU_VALCEA_IDENTITY_NOT_PRESENT", final_url)]

    output: list[PreventiveReference] = []
    for index, link in enumerate(parser.links):
        title = clean(link["title"])
        if not title:
            continue
        next_start = int(parser.links[index + 1]["start"]) if index + 1 < len(parser.links) else len(parser.tokens)
        context = clean(" ".join(parser.tokens[int(link["start"]):next_start]))
        pub = parse_date(context)
        cls = classify(title)
        basis = f"{link['url']}\0{title}"
        if cls is None:
            output.append(held(payload_hash, as_of, "UNCLASSIFIED_PREVENTIVE_REFERENCE", basis))
            continue
        if pub is None:
            output.append(held(payload_hash, as_of, "PUBLICATION_DATE_MISSING_OR_AMBIGUOUS", basis))
            continue
        pub_date = date.fromisoformat(pub)
        if pub_date > as_of:
            output.append(held(payload_hash, as_of, "FUTURE_PUBLICATION_DATE", basis))
            continue
        days = (as_of - pub_date).days
        sid = hashlib.sha256(f"{SOURCE_ID}\0{link['url']}\0{title}\0{pub}".encode()).hexdigest()[:20]
        output.append(PreventiveReference(
            signal_id=f"isuvl-prevention-{sid}", source_id=SOURCE_ID,
            taxonomy_version=TAXONOMY_VERSION, reference_class=cls,
            review_status="REVIEW_REQUIRED", source_name=SOURCE_NAME, source_tier=SOURCE_TIER,
            index_url=SOURCE_URL, reference_url=link["url"], title=title,
            publication_date=pub, as_of_date=as_of.isoformat(), age_days=days,
            age_band=age_band(days), payload_sha256=payload_hash,
            evidence_excerpt=f"{title} | official ISU Vâlcea index date {pub}", hold_reason=None,
        ))
    return output


def validate_boundaries(item: PreventiveReference) -> None:
    flags = (
        "article_or_document_fetch_allowed", "guidance_body_ingest_allowed",
        "guidance_content_projection_allowed", "current_hazard_claim_allowed",
        "current_warning_validity_claim_allowed", "breaking_news_promotion_allowed",
        "medical_advice_allowed", "person_level_extraction_allowed",
        "inferred_photo_rights_allowed", "persistence_allowed",
        "fact_kernel_promotion_allowed", "writer_allowed", "public_projection_allowed",
    )
    if any(getattr(item, name) for name in flags):
        raise AssertionError("preventive-information authority boundary drift")
    if item.publication_authority != "NONE":
        raise AssertionError("publication authority drift")
    if item.review_status == "HOLD":
        if item.reference_url or item.title or item.publication_date:
            raise AssertionError("held preventive signal leaks metadata")
        if item.evidence_excerpt != "HELD_PREVENTIVE_REFERENCE_METADATA_SUPPRESSED":
            raise AssertionError("held preventive signal leaks evidence")


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
      <h1>Informare preventivă</h1>
      <a href="/informare-preventiva/participi-la-un-festival-petrece-responsabil-123">Participi la un festival? Petrece Responsabil!</a>
      <span>22 mai 2026</span>
      <a href="/informare-preventiva/materiale-informare-preventiva-i.g.s.u.-71">MATERIALE INFORMARE PREVENTIVĂ I.G.S.U.</a>
      <span>18 decembrie 2024</span>
      <a href="/informare-preventiva/materiale-informare-preventiva-isu-valcea-72">MATERIALE INFORMARE PREVENTIVĂ ISU VÂLCEA</a>
      <span>18 decembrie 2024</span>
    </body></html>
    """
    result = extract(sample, final_url=SOURCE_URL, payload=sample.encode(), as_of=date(2026, 8, 30))
    assert [r.reference_class for r in result] == [
        "PREVENTIVE_CAMPAIGN_REFERENCE",
        "NATIONAL_PREVENTIVE_MATERIALS_REFERENCE",
        "LOCAL_PREVENTIVE_MATERIALS_REFERENCE",
    ]
    assert result[0].publication_date == "2026-05-22"
    assert result[0].guidance_content_projection_allowed is False
    assert result[0].current_hazard_claim_allowed is False
    for item in result:
        validate_boundaries(item)

    unknown = sample.replace("Participi la un festival? Petrece Responsabil!", "Alt material necunoscut")
    held_result = extract(unknown, final_url=SOURCE_URL, payload=unknown.encode(), as_of=date(2026, 8, 30))[0]
    assert held_result.review_status == "HOLD"
    assert held_result.hold_reason == "UNCLASSIFIED_PREVENTIVE_REFERENCE"
    validate_boundaries(held_result)

    future = sample.replace("22 mai 2026", "31 august 2026", 1)
    future_result = extract(future, final_url=SOURCE_URL, payload=future.encode(), as_of=date(2026, 8, 30))[0]
    assert future_result.hold_reason == "FUTURE_PUBLICATION_DATE"

    for url in (
        "http://isuvl.igsu.ro/informare-preventiva",
        "https://isuvl.igsu.ro/informare-preventiva?x=1",
        "https://isuvl.igsu.ro/comunicate-de-presa",
        "https://example.com/informare-preventiva",
    ):
        try:
            normalize_index_url(url)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe index URL accepted: {url}")
    assert normalize_reference_url("/informare-preventiva/item-1?x=1") is None
    assert normalize_reference_url("https://example.com/informare-preventiva/item-1") is None
    print("ISU Vâlcea preventive-information self-test: PASS")


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
