#!/usr/bin/env python3
"""Reference-only CFR Craiova speed-restriction bulletin adapter.

Reads only the official CFR speed-restriction bulletin index and emits bounded
metadata references for links explicitly labelled Craiova. The linked DOCX
bulletins are never fetched or parsed here. Because SRCF Craiova is a regional
surface, this adapter never infers that a listed bulletin affects Vâlcea, any
specific line/station, train operation, delay, or current operating condition.
"""
from __future__ import annotations

import argparse
import hashlib
import html.parser
import json
import re
import ssl
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

SOURCE_ID = "reference-cfr-srcf-craiova-speed-restriction-bulletins"
TAXONOMY_VERSION = "2026-08-31.1"
SOURCE_NAME = "CNCF CFR SA — Buletine Avizare Restricţii de Viteză / SRCF Craiova"
SOURCE_TIER = "T1_OFFICIAL_RAIL_INFRASTRUCTURE"
SOURCE_URL = "https://cfr.ro/ct-menu-item-116-2-2/"
HOST = "cfr.ro"
INDEX_PATH = "/ct-menu-item-116-2-2/"
DOCUMENT_PREFIX = "/wp-content/uploads/"
MAX_BODY_BYTES = 2_000_000
TIMEOUT_SECONDS = 15
USER_AGENT = "CIVORA-ValceaClar-CFR-Craiova/1.0 (+evidence-first; contact via repository)"

PERIOD_RE = re.compile(
    r"\b([0-3]?\d)\s*-\s*([0-3]?\d)\.([01]?\d)\.(20\d{2})\b"
)
IDENTITY_TERMS = (
    "compania nationala de cai ferate",
    "cfr",
    "buletine avizare restrictii de viteza",
)
PLACEHOLDER_TERMS = (
    "access denied",
    "captcha",
    "temporarily unavailable",
    "service unavailable",
    "verify you are human",
    "cloudflare",
)


@dataclass(frozen=True)
class BulletinReference:
    signal_id: str
    source_id: str
    taxonomy_version: str
    reference_class: str
    review_status: str
    source_name: str
    source_tier: str
    scope_state: str
    index_url: str
    period_label: Optional[str]
    period_start: Optional[str]
    period_end: Optional[str]
    document_url: Optional[str]
    document_format: Optional[str]
    index_payload_sha256: str
    evidence_excerpt: str
    hold_reason: Optional[str]
    publication_authority: str = "NONE"
    document_body_fetch_allowed: bool = False
    document_body_parse_allowed: bool = False
    valcea_impact_inferred: bool = False
    line_or_station_impact_inferred: bool = False
    current_operational_status_inferred: bool = False
    delay_or_timetable_impact_inferred: bool = False
    breaking_news_promotion_allowed: bool = False
    inferred_photo_rights_allowed: bool = False
    persistence_allowed: bool = False
    fact_kernel_promotion_allowed: bool = False
    writer_allowed: bool = False
    public_projection_allowed: bool = False


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: Any) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKD", clean(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_index_url(url: str) -> str:
    parsed = urlsplit(clean(url))
    path = re.sub(r"/+", "/", unquote(parsed.path or "/"))
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != HOST
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or path != INDEX_PATH
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"off-surface CFR index refused: {url}")
    return SOURCE_URL


def normalize_document_url(value: str) -> Optional[str]:
    parsed = urlsplit(urljoin(SOURCE_URL, clean(value)))
    path = re.sub(r"/+", "/", unquote(parsed.path or "/"))
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != HOST
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not path.startswith(DOCUMENT_PREFIX)
        or not path.casefold().endswith(".docx")
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
            self.links.append(
                {
                    "href": self.current_href,
                    "title": clean(" ".join(self.current_parts)),
                    "start": self.current_start,
                }
            )
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
    value = fold(" ".join(tokens[:220]))
    return all(term in value for term in IDENTITY_TERMS)


def is_placeholder(tokens: list[str]) -> bool:
    value = fold(" ".join(tokens[:80]))
    return any(term in value for term in PLACEHOLDER_TERMS)


def period_from_context(
    tokens: list[str], start: int
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    context = clean(" ".join(tokens[max(0, start - 40) : start]))
    matches = list(PERIOD_RE.finditer(context))
    if not matches:
        return None, None, None
    match = matches[-1]
    day1, day2, month, year = map(int, match.groups())
    try:
        start_date = date(year, month, day1)
        end_date = date(year, month, day2)
    except ValueError:
        return match.group(0), None, None
    if start_date > end_date:
        return match.group(0), None, None
    return match.group(0), start_date.isoformat(), end_date.isoformat()


def held(index_hash: str, reason: str, evidence: str) -> BulletinReference:
    sid = hashlib.sha256(
        f"{SOURCE_ID}\0{reason}\0{evidence}".encode()
    ).hexdigest()[:20]
    return BulletinReference(
        signal_id=f"cfr-craiova-{sid}",
        source_id=SOURCE_ID,
        taxonomy_version=TAXONOMY_VERSION,
        reference_class="HOLD_CFR_CRAIOVA_BULLETIN_REFERENCE",
        review_status="HOLD",
        source_name=SOURCE_NAME,
        source_tier=SOURCE_TIER,
        scope_state="REGIONAL_REFERENCE_ONLY",
        index_url=SOURCE_URL,
        period_label=None,
        period_start=None,
        period_end=None,
        document_url=None,
        document_format=None,
        index_payload_sha256=index_hash,
        evidence_excerpt=clean(evidence)[:500],
        hold_reason=reason,
    )


def parse_index_html(body: str) -> list[BulletinReference]:
    index_hash = sha256_text(body)
    parser = LinkParser()
    parser.feed(body)

    if is_placeholder(parser.tokens):
        return [
            held(
                index_hash,
                "PLACEHOLDER_OR_CHALLENGE_PAGE",
                " ".join(parser.tokens[:30]),
            )
        ]
    if not page_identity_ok(parser.tokens):
        return [
            held(
                index_hash,
                "SOURCE_IDENTITY_DRIFT",
                " ".join(parser.tokens[:80]),
            )
        ]

    craiova_links = [
        link for link in parser.links if fold(link["title"]) == "craiova"
    ]
    if not craiova_links:
        return [
            held(
                index_hash,
                "NO_CRAIOVA_BULLETIN_REFERENCES",
                " ".join(parser.tokens[-80:]),
            )
        ]

    results: list[BulletinReference] = []
    seen_periods: dict[tuple[str, str], str] = {}
    seen_documents: set[str] = set()

    for link in craiova_links:
        period_label, period_start, period_end = period_from_context(
            parser.tokens, int(link["start"])
        )
        evidence = clean(
            " ".join(
                parser.tokens[
                    max(0, int(link["start"]) - 8) : int(link["start"]) + 3
                ]
            )
        )
        document_url = normalize_document_url(str(link["href"]))

        if not period_start or not period_end:
            results.append(
                held(index_hash, "MISSING_OR_INVALID_PERIOD_CONTEXT", evidence)
            )
            continue
        if not document_url:
            results.append(
                held(index_hash, "UNSUPPORTED_OR_OFF_SURFACE_DOCUMENT", evidence)
            )
            continue

        period_key = (period_start, period_end)
        prior_document = seen_periods.get(period_key)
        if prior_document and prior_document != document_url:
            results.append(
                held(index_hash, "CONFLICTING_DOCUMENTS_FOR_SAME_PERIOD", evidence)
            )
            continue
        if document_url in seen_documents and prior_document != document_url:
            results.append(
                held(index_hash, "DOCUMENT_REUSED_ACROSS_PERIODS", evidence)
            )
            continue

        seen_periods[period_key] = document_url
        seen_documents.add(document_url)
        sid = hashlib.sha256(
            f"{SOURCE_ID}\0{period_start}\0{period_end}\0{document_url}".encode()
        ).hexdigest()[:20]
        results.append(
            BulletinReference(
                signal_id=f"cfr-craiova-{sid}",
                source_id=SOURCE_ID,
                taxonomy_version=TAXONOMY_VERSION,
                reference_class="CFR_CRAIOVA_SPEED_RESTRICTION_BULLETIN_REFERENCE",
                review_status="REFERENCE_ONLY",
                source_name=SOURCE_NAME,
                source_tier=SOURCE_TIER,
                scope_state="REGIONAL_REFERENCE_ONLY",
                index_url=SOURCE_URL,
                period_label=period_label,
                period_start=period_start,
                period_end=period_end,
                document_url=document_url,
                document_format="DOCX_REFERENCE_ONLY",
                index_payload_sha256=index_hash,
                evidence_excerpt=evidence[:500],
                hold_reason=None,
            )
        )
    return results


def fetch_index(url: str = SOURCE_URL) -> str:
    normalized = normalize_index_url(url)
    request = Request(
        normalized,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
    )
    opener = build_opener(
        NoRedirects(), HTTPSHandler(context=ssl.create_default_context())
    )
    with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        content_type = clean(response.headers.get("Content-Type", "")).casefold()
        if "text/html" not in content_type:
            raise ValueError(
                f"unexpected content type: {content_type or 'missing'}"
            )
        payload = response.read(MAX_BODY_BYTES + 1)
        if len(payload) > MAX_BODY_BYTES:
            raise ValueError("CFR index exceeds bounded response size")
        charset = response.headers.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="strict")


def envelope(references: list[BulletinReference]) -> dict[str, Any]:
    status = (
        "HOLD"
        if not references or any(item.review_status == "HOLD" for item in references)
        else "PASS"
    )
    return {
        "status": status,
        "source_id": SOURCE_ID,
        "taxonomy_version": TAXONOMY_VERSION,
        "source_name": SOURCE_NAME,
        "source_tier": SOURCE_TIER,
        "scope_state": "REGIONAL_REFERENCE_ONLY",
        "reference_count": sum(
            item.review_status != "HOLD" for item in references
        ),
        "hold_count": sum(item.review_status == "HOLD" for item in references),
        "references": [asdict(item) for item in references],
        "safety": {
            "document_body_fetch_allowed": False,
            "document_body_parse_allowed": False,
            "valcea_impact_inferred": False,
            "line_or_station_impact_inferred": False,
            "current_operational_status_inferred": False,
            "delay_or_timetable_impact_inferred": False,
            "breaking_news_promotion_allowed": False,
            "inferred_photo_rights_allowed": False,
            "persistence_allowed": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "public_projection_allowed": False,
        },
    }


def run_self_test() -> None:
    fixture = """
    <html><body>
      <h1>Compania Națională de Căi Ferate CFR SA</h1>
      <h2>Buletine Avizare Restricţii de Viteză</h2>
      <p>Buletine Avizare Restricţii de Viteză DECADA 01-10.09.2026</p>
      <a href="https://cfr.ro/wp-content/uploads/2026/08/craiova-2.docx">Craiova</a>
      <p>Buletine Avizare Restricţii de Viteză DECADA 21-31.08.2026</p>
      <a href="/wp-content/uploads/2026/08/craiova-1.docx">Craiova</a>
    </body></html>
    """
    refs = parse_index_html(fixture)
    assert len(refs) == 2
    assert all(item.review_status == "REFERENCE_ONLY" for item in refs)
    assert refs[0].period_start == "2026-09-01"
    assert refs[0].period_end == "2026-09-10"
    assert refs[1].period_start == "2026-08-21"
    assert refs[1].period_end == "2026-08-31"
    assert all(item.scope_state == "REGIONAL_REFERENCE_ONLY" for item in refs)
    assert all(not item.valcea_impact_inferred for item in refs)
    assert all(not item.current_operational_status_inferred for item in refs)

    off_host = fixture.replace(
        "https://cfr.ro/wp-content/uploads/2026/08/craiova-2.docx",
        "https://example.org/craiova.docx",
    )
    assert envelope(parse_index_html(off_host))["status"] == "HOLD"

    unsupported = fixture.replace("craiova-2.docx", "craiova-2.pdf")
    assert envelope(parse_index_html(unsupported))["status"] == "HOLD"

    missing_period = """
    <html><body><h1>Compania Națională de Căi Ferate CFR SA</h1>
    <h2>Buletine Avizare Restricţii de Viteză</h2>
    <a href="/wp-content/uploads/2026/08/craiova.docx">Craiova</a></body></html>
    """
    assert envelope(parse_index_html(missing_period))["status"] == "HOLD"

    conflict = fixture.replace(
        "</body>",
        '<p>DECADA 01-10.09.2026</p><a href="/wp-content/uploads/2026/08/craiova-other.docx">Craiova</a></body>',
    )
    assert envelope(parse_index_html(conflict))["status"] == "HOLD"

    identity_drift = fixture.replace(
        "Compania Națională de Căi Ferate CFR SA", "Alt operator"
    )
    assert envelope(parse_index_html(identity_drift))["status"] == "HOLD"

    safe = envelope(refs)["safety"]
    assert safe and not any(bool(value) for value in safe.values())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--input-html", type=Path)
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        print(
            json.dumps(
                {"status": "PASS", "self_test": True, "source_id": SOURCE_ID},
                ensure_ascii=False,
            )
        )
        return 0

    try:
        body = (
            args.input_html.read_text(encoding="utf-8")
            if args.input_html
            else fetch_index()
        )
        output = envelope(parse_index_html(body))
    except Exception as exc:
        output = envelope([held("", "FETCH_OR_PARSE_FAILURE", repr(exc))])

    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if output["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
