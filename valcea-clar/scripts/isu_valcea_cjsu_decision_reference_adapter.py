#!/usr/bin/env python3
"""Fail-closed ISU Vâlcea CJSU decision-reference adapter.

Reads the official ``/hotarari-csu`` index, follows only bounded first-party
CJSU year-collection pages discovered there, and emits metadata references for
decision documents. It never fetches decision PDFs, interprets their legal
effect, infers current measures, or grants publication/media authority.
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

SOURCE_ID = "reference-isu-valcea-cjsu-decisions"
TAXONOMY_VERSION = "2026-08-31.1"
SOURCE_NAME = "ISU Vâlcea — Hotărâri CJSU"
SOURCE_TIER = "T1_OFFICIAL_EMERGENCY_SERVICE"
SOURCE_URL = "https://isuvl.igsu.ro/hotarari-csu"
HOST = "isuvl.igsu.ro"
INDEX_PATH = "/hotarari-csu"
COLLECTION_PREFIX = "/hotarari-csu/"
RESOURCE_PREFIX = "/hotarari-csu/resources/"
MAX_BODY_BYTES = 2_000_000
MAX_COLLECTIONS = 6
TIMEOUT_SECONDS = 15
USER_AGENT = "CIVORA-ValceaClar-ISUVL-CJSU/1.0 (+evidence-first; contact via repository)"

MONTHS = {
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4,
    "mai": 5, "iunie": 6, "iulie": 7, "august": 8,
    "septembrie": 9, "octombrie": 10, "noiembrie": 11, "decembrie": 12,
}
MONTH_RE = "|".join(MONTHS)
ROMANIAN_DATE_RE = re.compile(rf"\b([0-3]?\d)\s+({MONTH_RE})\s+(20\d{{2}})\b", re.I)
YEAR_TITLE_RE = re.compile(r"\bhotarari\s+c\.?j\.?s\.?u\.?\s+(20\d{2})\b", re.I)
DECISION_RE = re.compile(
    r"\bhotararea\s+c\.?j\.?s\.?u\.?\s+valcea\s+nr\.?\s*(\d{1,4})"
    r"\s+din\s+([0-3]?\d)[.\-/]([01]?\d)[.\-/](20\d{2})\b",
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
class CollectionReference:
    collection_url: str
    collection_year: int
    collection_page_date: str


@dataclass(frozen=True)
class CjsuDecisionReference:
    signal_id: str
    source_id: str
    taxonomy_version: str
    reference_class: str
    review_status: str
    source_name: str
    source_tier: str
    index_url: str
    collection_url: Optional[str]
    collection_year: Optional[int]
    collection_page_date: Optional[str]
    decision_reference_url: Optional[str]
    decision_number: Optional[int]
    decision_date: Optional[str]
    as_of_date: str
    age_days: Optional[int]
    age_band: str
    index_payload_sha256: str
    collection_payload_sha256: Optional[str]
    evidence_excerpt: str
    supersession_state: str
    hold_reason: Optional[str]
    publication_authority: str = "NONE"
    decision_document_fetch_allowed: bool = False
    decision_body_ingest_allowed: bool = False
    current_measure_claim_allowed: bool = False
    legal_effect_claim_allowed: bool = False
    current_validity_claim_allowed: bool = False
    supersession_inference_allowed: bool = False
    person_or_entity_extraction_allowed: bool = False
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
        raise ValueError(f"off-surface CJSU index refused: {url}")
    return SOURCE_URL


def normalize_collection_url(value: str) -> Optional[str]:
    parsed = urlsplit(urljoin(SOURCE_URL, clean(value)))
    path = re.sub(r"/+", "/", unquote(parsed.path or "/"))
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != HOST
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not path.startswith(COLLECTION_PREFIX)
        or path.startswith(RESOURCE_PREFIX)
        or path.rstrip("/") == INDEX_PATH
        or parsed.query
        or parsed.fragment
    ):
        return None
    return urlunsplit(("https", HOST, path, "", ""))


def normalize_resource_url(value: str, collection_url: str) -> Optional[str]:
    parsed = urlsplit(urljoin(collection_url, clean(value)))
    path = re.sub(r"/+", "/", unquote(parsed.path or "/"))
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != HOST
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not path.startswith(RESOURCE_PREFIX)
        or not path.casefold().endswith(".pdf")
        or parsed.query
        or parsed.fragment
    ):
        return None
    return urlunsplit(("https", HOST, path, "", ""))


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise ValueError(f"redirect refused: {newurl}")


class LinkParser(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.tokens: list[str] = []
        self.links: list[dict[str, Any]] = []
        self.current_href: Optional[str] = None
        self.current_parts: list[str] = []
        self.current_start = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "a":
            self.current_href = clean(dict(attrs).get("href") or "")
            self.current_parts = []
            self.current_start = len(self.tokens)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.SKIP and self.skip:
            self.skip -= 1
            return
        if self.skip:
            return
        if tag == "a" and self.current_href is not None:
            self.links.append({
                "href": self.current_href,
                "title": clean(" ".join(self.current_parts)),
                "start": self.current_start,
                "end": len(self.tokens),
            })
            self.current_href = None
            self.current_parts = []

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        value = clean(data)
        if not value:
            return
        self.tokens.append(value)
        if self.current_href is not None:
            self.current_parts.append(value)


def page_identity_ok(tokens: list[str]) -> bool:
    value = fold(" ".join(tokens[:120]))
    return all(term in value for term in IDENTITY_TERMS) or "isu valcea" in value


def is_placeholder(tokens: list[str]) -> bool:
    value = fold(" ".join(tokens[:50]))
    return any(term in value for term in PLACEHOLDER_TERMS)


def parse_romanian_date(text: str) -> Optional[str]:
    values: set[str] = set()
    for day, month_name, year in ROMANIAN_DATE_RE.findall(fold(text)):
        try:
            values.add(date(int(year), MONTHS[month_name], int(day)).isoformat())
        except ValueError:
            continue
    return next(iter(values)) if len(values) == 1 else None


def parse_collection_year(title: str) -> Optional[int]:
    match = YEAR_TITLE_RE.search(fold(title))
    return int(match.group(1)) if match else None


def parse_decision_title(title: str) -> Optional[tuple[int, str]]:
    match = DECISION_RE.search(fold(title))
    if not match:
        return None
    number, day, month, year = match.groups()
    try:
        decision_date = date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None
    return int(number), decision_date


def age_band(days: int) -> str:
    if days <= 30:
        return "REFERENCE_0_30_DAYS"
    if days <= 180:
        return "REFERENCE_31_180_DAYS"
    if days <= 730:
        return "REFERENCE_181_730_DAYS"
    return "REFERENCE_OVER_730_DAYS"


def held(
    *, index_hash: str, as_of: date, reason: str, identity_basis: str,
    collection_hash: Optional[str] = None,
) -> CjsuDecisionReference:
    sid = hashlib.sha256(f"{SOURCE_ID}\0{identity_basis}\0{reason}".encode()).hexdigest()[:20]
    return CjsuDecisionReference(
        signal_id=f"isuvl-cjsu-{sid}", source_id=SOURCE_ID, taxonomy_version=TAXONOMY_VERSION,
        reference_class="HOLD_CJSU_DECISION_REFERENCE", review_status="HOLD",
        source_name=SOURCE_NAME, source_tier=SOURCE_TIER, index_url=SOURCE_URL,
        collection_url=None, collection_year=None, collection_page_date=None,
        decision_reference_url=None, decision_number=None, decision_date=None,
        as_of_date=as_of.isoformat(), age_days=None, age_band="UNKNOWN",
        index_payload_sha256=index_hash, collection_payload_sha256=collection_hash,
        evidence_excerpt="HELD_CJSU_DECISION_METADATA_SUPPRESSED",
        supersession_state="UNKNOWN_NOT_INFERRED", hold_reason=reason,
    )


def extract_collections(
    html_text: str, *, final_url: str, payload: bytes, as_of: date
) -> tuple[list[CollectionReference], str]:
    normalize_index_url(final_url)
    parser = LinkParser()
    parser.feed(html_text)
    parser.close()
    payload_hash = hashlib.sha256(payload).hexdigest()
    if is_placeholder(parser.tokens):
        raise ValueError("PLACEHOLDER_OR_CHALLENGE_PAGE")
    if not page_identity_ok(parser.tokens):
        raise ValueError("ISU_VALCEA_IDENTITY_NOT_PRESENT")

    collections: list[CollectionReference] = []
    seen_years: set[int] = set()
    for index, link in enumerate(parser.links):
        url = normalize_collection_url(link["href"])
        if not url:
            continue
        year = parse_collection_year(link["title"])
        if year is None:
            continue
        if year in seen_years:
            raise ValueError("DUPLICATE_CJSU_COLLECTION_YEAR")
        next_start = int(parser.links[index + 1]["start"]) if index + 1 < len(parser.links) else len(parser.tokens)
        context = clean(" ".join(parser.tokens[int(link["start"]):next_start]))
        page_date = parse_romanian_date(context)
        if page_date is None:
            raise ValueError("COLLECTION_PAGE_DATE_MISSING_OR_AMBIGUOUS")
        if date.fromisoformat(page_date) > as_of:
            raise ValueError("FUTURE_COLLECTION_PAGE_DATE")
        collections.append(CollectionReference(url, year, page_date))
        seen_years.add(year)

    if not collections:
        raise ValueError("NO_CJSU_YEAR_COLLECTIONS_FOUND")
    if len(collections) > MAX_COLLECTIONS:
        raise ValueError("CJSU_COLLECTION_BOUND_EXCEEDED")
    return collections, payload_hash


def extract_decisions(
    html_text: str, *, final_url: str, payload: bytes,
    collection: CollectionReference, index_hash: str, as_of: date,
) -> list[CjsuDecisionReference]:
    normalized_final = normalize_collection_url(final_url)
    collection_hash = hashlib.sha256(payload).hexdigest()
    if normalized_final != collection.collection_url:
        return [held(index_hash=index_hash, as_of=as_of, reason="COLLECTION_FINAL_URL_DRIFT",
                     identity_basis=final_url, collection_hash=collection_hash)]

    parser = LinkParser()
    parser.feed(html_text)
    parser.close()
    if is_placeholder(parser.tokens):
        return [held(index_hash=index_hash, as_of=as_of, reason="PLACEHOLDER_OR_CHALLENGE_COLLECTION_PAGE",
                     identity_basis=collection.collection_url, collection_hash=collection_hash)]
    if not page_identity_ok(parser.tokens):
        return [held(index_hash=index_hash, as_of=as_of, reason="ISU_VALCEA_IDENTITY_NOT_PRESENT_ON_COLLECTION",
                     identity_basis=collection.collection_url, collection_hash=collection_hash)]

    page_folded = fold(" ".join(parser.tokens[:80]))
    expected_a = f"hotarari c.j.s.u. {collection.collection_year}"
    expected_b = f"hotarari cjsu {collection.collection_year}"
    if expected_a not in page_folded and expected_b not in page_folded:
        return [held(index_hash=index_hash, as_of=as_of, reason="COLLECTION_YEAR_IDENTITY_DRIFT",
                     identity_basis=collection.collection_url, collection_hash=collection_hash)]

    output: list[CjsuDecisionReference] = []
    seen_numbers: set[int] = set()
    for link in parser.links:
        resource_url = normalize_resource_url(link["href"], collection.collection_url)
        if not resource_url:
            continue
        parsed = parse_decision_title(link["title"])
        if parsed is None:
            output.append(held(index_hash=index_hash, as_of=as_of, reason="DECISION_TITLE_UNPARSEABLE",
                               identity_basis=f"{collection.collection_url}\0{link['title']}",
                               collection_hash=collection_hash))
            continue
        number, decision_date = parsed
        decision_day = date.fromisoformat(decision_date)
        if decision_day.year != collection.collection_year:
            output.append(held(index_hash=index_hash, as_of=as_of, reason="DECISION_YEAR_COLLECTION_MISMATCH",
                               identity_basis=f"{resource_url}\0{decision_date}", collection_hash=collection_hash))
            continue
        if decision_day > as_of:
            output.append(held(index_hash=index_hash, as_of=as_of, reason="FUTURE_DECISION_DATE",
                               identity_basis=f"{resource_url}\0{decision_date}", collection_hash=collection_hash))
            continue
        if number in seen_numbers:
            output.append(held(index_hash=index_hash, as_of=as_of, reason="DUPLICATE_DECISION_NUMBER_IN_COLLECTION",
                               identity_basis=f"{collection.collection_year}\0{number}", collection_hash=collection_hash))
            continue
        seen_numbers.add(number)
        days = (as_of - decision_day).days
        sid = hashlib.sha256(
            f"{SOURCE_ID}\0{collection.collection_year}\0{number}\0{decision_date}\0{resource_url}".encode()
        ).hexdigest()[:20]
        output.append(CjsuDecisionReference(
            signal_id=f"isuvl-cjsu-{sid}", source_id=SOURCE_ID, taxonomy_version=TAXONOMY_VERSION,
            reference_class="CJSU_DECISION_DOCUMENT_REFERENCE", review_status="REVIEW_REQUIRED",
            source_name=SOURCE_NAME, source_tier=SOURCE_TIER, index_url=SOURCE_URL,
            collection_url=collection.collection_url, collection_year=collection.collection_year,
            collection_page_date=collection.collection_page_date, decision_reference_url=resource_url,
            decision_number=number, decision_date=decision_date, as_of_date=as_of.isoformat(),
            age_days=days, age_band=age_band(days), index_payload_sha256=index_hash,
            collection_payload_sha256=collection_hash,
            evidence_excerpt=(f"Hotărârea CJSU Vâlcea nr. {number} din {decision_date}; "
                              f"official year collection {collection.collection_year}"),
            supersession_state="UNKNOWN_NOT_INFERRED", hold_reason=None,
        ))

    if not output:
        return [held(index_hash=index_hash, as_of=as_of, reason="NO_DECISION_DOCUMENT_REFERENCES_FOUND",
                     identity_basis=collection.collection_url, collection_hash=collection_hash)]
    return output


def validate_boundaries(item: CjsuDecisionReference) -> None:
    flags = (
        "decision_document_fetch_allowed", "decision_body_ingest_allowed",
        "current_measure_claim_allowed", "legal_effect_claim_allowed", "current_validity_claim_allowed",
        "supersession_inference_allowed", "person_or_entity_extraction_allowed",
        "breaking_news_promotion_allowed", "inferred_photo_rights_allowed", "persistence_allowed",
        "fact_kernel_promotion_allowed", "writer_allowed", "public_projection_allowed",
    )
    if any(getattr(item, name) for name in flags):
        raise AssertionError("CJSU decision authority boundary drift")
    if item.publication_authority != "NONE":
        raise AssertionError("publication authority drift")
    if item.supersession_state != "UNKNOWN_NOT_INFERRED":
        raise AssertionError("supersession must not be inferred from decision numbering/date")
    if item.review_status == "HOLD":
        leaked = (item.collection_url, item.collection_year, item.collection_page_date,
                  item.decision_reference_url, item.decision_number, item.decision_date)
        if any(value is not None for value in leaked):
            raise AssertionError("held CJSU signal leaks metadata")
        if item.evidence_excerpt != "HELD_CJSU_DECISION_METADATA_SUPPRESSED":
            raise AssertionError("held CJSU signal leaks evidence")


def fetch_html(url: str, *, kind: str) -> tuple[str, str, bytes]:
    if kind == "index":
        canonical = normalize_index_url(url)
    elif kind == "collection":
        canonical = normalize_collection_url(url)
        if canonical is None:
            raise ValueError(f"unsafe collection URL: {url}")
    else:
        raise ValueError(f"unknown fetch kind: {kind}")
    opener = build_opener(NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(canonical, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
    with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        final = response.geturl()
        if kind == "index":
            final = normalize_index_url(final)
        else:
            final = normalize_collection_url(final)
            if final is None:
                raise ValueError("collection response escaped source boundary")
        body = response.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            raise ValueError("response exceeds bounded body limit")
        content_type = clean(response.headers.get("Content-Type")).casefold()
        if content_type and "html" not in content_type:
            raise ValueError(f"unexpected content type: {content_type}")
        charset = response.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace"), final, body


def self_test() -> None:
    index_sample = """
    <html><body>
      <div>INSPECTORATUL PENTRU SITUAȚII DE URGENȚĂ ”GENERAL MAGHERU” AL JUDEȚULUI VÂLCEA</div>
      <h1>Hotărâri CSU</h1>
      <a href="/hotarari-csu/hotarari-c.j.s.u.-2026-526">Hotarari C.J.S.U. 2026</a>
      <span>30 ianuarie 2026</span>
      <a href="/hotarari-csu/hotarari-c.j.s.u.-2025-400">Hotarari C.J.S.U. 2025</a>
      <span>31 decembrie 2025</span>
    </body></html>
    """
    collections, index_hash = extract_collections(
        index_sample, final_url=SOURCE_URL, payload=index_sample.encode(), as_of=date(2026, 8, 31)
    )
    assert [(c.collection_year, c.collection_page_date) for c in collections] == [
        (2026, "2026-01-30"), (2025, "2025-12-31")
    ]

    collection_sample = """
    <html><body>
      <div>INSPECTORATUL PENTRU SITUAȚII DE URGENȚĂ ”GENERAL MAGHERU” AL JUDEȚULUI VÂLCEA</div>
      <h1>Hotarari C.J.S.U. 2026</h1>
      <div>30 ianuarie 2026</div>
      <h4>Documente</h4>
      <a href="/hotarari-csu/resources/a.pdf">Hotărârea C.J.S.U. Vâlcea nr. 1 din 26.01.2026</a>
      <a href="/hotarari-csu/resources/b.pdf">Hotărărea CJSU Vâlcea nr. 9 din 05.06.2026</a>
      <a href="/hotarari-csu/resources/c.pdf">Hotărârea CJSU Vâlcea nr. 16 din 05.08.2026</a>
    </body></html>
    """
    result = extract_decisions(
        collection_sample, final_url=collections[0].collection_url, payload=collection_sample.encode(),
        collection=collections[0], index_hash=index_hash, as_of=date(2026, 8, 31),
    )
    assert [item.decision_number for item in result] == [1, 9, 16]
    assert result[-1].decision_date == "2026-08-05"
    assert result[-1].supersession_state == "UNKNOWN_NOT_INFERRED"
    assert result[-1].current_measure_claim_allowed is False
    for item in result:
        validate_boundaries(item)

    future = collection_sample.replace("05.08.2026", "05.09.2026")
    future_result = extract_decisions(
        future, final_url=collections[0].collection_url, payload=future.encode(), collection=collections[0],
        index_hash=index_hash, as_of=date(2026, 8, 31),
    )[-1]
    assert future_result.review_status == "HOLD"
    assert future_result.hold_reason == "FUTURE_DECISION_DATE"
    validate_boundaries(future_result)

    duplicate = collection_sample.replace(
        '<a href="/hotarari-csu/resources/b.pdf">Hotărărea CJSU Vâlcea nr. 9 din 05.06.2026</a>',
        '<a href="/hotarari-csu/resources/b.pdf">Hotărârea CJSU Vâlcea nr. 1 din 05.06.2026</a>',
    )
    duplicate_result = extract_decisions(
        duplicate, final_url=collections[0].collection_url, payload=duplicate.encode(), collection=collections[0],
        index_hash=index_hash, as_of=date(2026, 8, 31),
    )[1]
    assert duplicate_result.hold_reason == "DUPLICATE_DECISION_NUMBER_IN_COLLECTION"

    for unsafe in (
        "http://isuvl.igsu.ro/hotarari-csu",
        "https://isuvl.igsu.ro/hotarari-csu?x=1",
        "https://example.com/hotarari-csu",
    ):
        try:
            normalize_index_url(unsafe)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe index URL accepted: {unsafe}")
    assert normalize_collection_url("https://example.com/hotarari-csu/x") is None
    assert normalize_resource_url("https://example.com/x.pdf", collections[0].collection_url) is None
    assert normalize_resource_url("/hotarari-csu/resources/a.pdf?x=1", collections[0].collection_url) is None
    print("ISU Vâlcea CJSU decision-reference self-test: PASS")


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

    try:
        index_html, index_final, index_payload = fetch_html(SOURCE_URL, kind="index")
        collections, index_hash = extract_collections(
            index_html, final_url=index_final, payload=index_payload, as_of=as_of
        )
    except Exception:
        index_hash = hashlib.sha256(SOURCE_URL.encode()).hexdigest()
        result = [held(index_hash=index_hash, as_of=as_of, reason="INDEX_FETCH_OR_PARSE_FAILED",
                       identity_basis=SOURCE_URL)]
    else:
        result: list[CjsuDecisionReference] = []
        for collection in collections:
            try:
                html_text, final_url, payload = fetch_html(collection.collection_url, kind="collection")
                result.extend(extract_decisions(
                    html_text, final_url=final_url, payload=payload, collection=collection,
                    index_hash=index_hash, as_of=as_of,
                ))
            except Exception:
                result.append(held(index_hash=index_hash, as_of=as_of,
                                   reason="COLLECTION_FETCH_OR_PARSE_FAILED",
                                   identity_basis=collection.collection_url))

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
