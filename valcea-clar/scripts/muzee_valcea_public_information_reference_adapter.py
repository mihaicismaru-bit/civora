#!/usr/bin/env python3
"""Evidence-first Muzeul Județean Vâlcea public-information reference adapter.

The adapter reads only the official Muzeul Județean „Aurelian Sacerdoțeanu”
Vâlcea announcements/public-information surface and discovers one bounded
current-year tariff-document reference.

This is reference intelligence only. It does not download or parse the tariff
PDF, infer opening hours, ticket availability, current admission prices,
accessibility, photo rights, publication authority, or any reader-facing fact.
It does not persist state, promote to Fact Kernel, invoke Writer, or publish.
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
from typing import Any, Callable, Optional
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

SOURCE_ID = "signal-muzee-valcea-public-information-references"
TAXONOMY_VERSION = "2026-08-31.1"
SOURCE_NAME = "Muzeul Județean „Aurelian Sacerdoțeanu” Vâlcea — Informații publice"
SOURCE_TIER = "T1_OFFICIAL_CULTURE_FIRST_PARTY"
SOURCE_URL = "https://www.muzee-valcea.ro/inc_anunturi.php"
CANONICAL_HOST = "www.muzee-valcea.ro"
ALLOWED_HOSTS = {"www.muzee-valcea.ro", "muzee-valcea.ro"}
SOURCE_PATH = "/inc_anunturi.php"
DOCUMENT_PATH_RE = re.compile(r"^/documente/(20\d{2})/[^?#]+\.pdf$", re.I)
MAX_RESPONSE_BYTES = 1_500_000
TIMEOUT_SECONDS = 15
USER_AGENT = "CIVORA-ValceaClar-MuzeeValcea/1.0 (+evidence-first; contact via repository)"
PLACEHOLDER_TERMS = (
    "enable javascript",
    "access denied",
    "captcha",
    "service unavailable",
    "temporarily unavailable",
    "verify you are human",
    "checking your browser",
)
TARIFF_LABEL_RE = re.compile(
    r"\blista\s+cu\s+taxe\s+(?:si|și)\s+tarife\s+(20\d{2})\b", re.I
)


@dataclass(frozen=True)
class TariffCandidate:
    document_url: str
    year: int
    label: str
    anchor_text: str
    evidence_sha256: str


@dataclass(frozen=True)
class MuzeeValceaPublicInfoState:
    source_id: str
    taxonomy_version: str
    source_name: str
    source_tier: str
    source_url: str
    source_payload_sha256: str
    state: str
    hold_reason: Optional[str]
    as_of_date: str
    references: tuple[TariffCandidate, ...]
    reference_scope: str = "FIRST_PARTY_PUBLIC_INFORMATION_REFERENCE_ONLY"
    document_fetch_allowed: bool = False
    document_body_parse_allowed: bool = False
    opening_hours_inference_allowed: bool = False
    open_now_inference_allowed: bool = False
    current_price_claim_allowed: bool = False
    ticket_availability_inference_allowed: bool = False
    accessibility_claim_extraction_allowed: bool = False
    person_identity_extraction_allowed: bool = False
    image_ingest_allowed: bool = False
    inferred_photo_rights_allowed: bool = False
    breaking_news_promotion_allowed: bool = False
    persistence_allowed: bool = False
    fact_kernel_promotion_allowed: bool = False
    writer_allowed: bool = False
    public_projection_allowed: bool = False
    publication_authority: str = "NONE"


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", clean(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _path(value: str) -> str:
    path = re.sub(r"/+", "/", unquote(value or "/"))
    if not path.startswith("/"):
        path = "/" + path
    return path


def _base_url(url: str) -> tuple[str, str]:
    parsed = urlsplit(clean(url))
    host = (parsed.hostname or "").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or host not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"off-surface Muzee Vâlcea URL refused: {url}")
    return host, _path(parsed.path)


def validate_source_url(url: str) -> str:
    _, path = _base_url(url)
    if path != SOURCE_PATH:
        raise ValueError(f"non-public-information source URL refused: {url}")
    return urlunsplit(("https", CANONICAL_HOST, SOURCE_PATH, "", ""))


def normalize_document_url(value: str, *, base_url: str = SOURCE_URL) -> tuple[str, int]:
    joined = urljoin(base_url, clean(value))
    _, path = _base_url(joined)
    match = DOCUMENT_PATH_RE.fullmatch(path)
    if not match:
        raise ValueError(f"non-tariff-document URL refused: {value}")
    year = int(match.group(1))
    return urlunsplit(("https", CANONICAL_HOST, path, "", "")), year


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise ValueError(f"redirect refused: {newurl}")


def fetch_source(url: str) -> tuple[str, str, bytes]:
    canonical = validate_source_url(url)
    opener = build_opener(NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(
        canonical,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"},
    )
    with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        final_url = validate_source_url(response.geturl())
        if final_url != canonical:
            raise ValueError("canonical URL drift after fetch")
        content_type = clean(response.headers.get("Content-Type", "")).casefold()
        if "text/html" not in content_type:
            raise ValueError(f"non-HTML source refused: {content_type or 'unknown'}")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds size cap")
        charset = response.headers.get_content_charset() or "utf-8"
    return final_url, body.decode(charset, errors="replace"), body


class PublicInfoParser(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.skip = 0
        self.title_depth = 0
        self.title_parts: list[str] = []
        self.page_parts: list[str] = []
        self.current_href: Optional[str] = None
        self.current_anchor_parts: list[str] = []
        self.anchors: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "title":
            self.title_depth += 1
        if tag == "a":
            values = {k.casefold(): clean(v) for k, v in attrs if k and v is not None}
            self.current_href = values.get("href")
            self.current_anchor_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.SKIP and self.skip:
            self.skip -= 1
            return
        if self.skip:
            return
        if tag == "a":
            if self.current_href:
                self.anchors.append(
                    (self.current_href, clean(" ".join(self.current_anchor_parts)))
                )
            self.current_href = None
            self.current_anchor_parts = []
        if tag == "title" and self.title_depth:
            self.title_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        value = clean(data)
        if not value:
            return
        self.page_parts.append(value)
        if self.title_depth:
            self.title_parts.append(value)
        if self.current_href is not None:
            self.current_anchor_parts.append(value)

    def page_text(self) -> str:
        return clean(" ".join(self.page_parts))

    def page_title(self) -> str:
        return clean(" ".join(self.title_parts))


def placeholder_present(text: str) -> bool:
    value = fold(text[:5000])
    return any(term in value for term in PLACEHOLDER_TERMS)


def source_identity_present(text: str, page_title: str) -> bool:
    value = fold(f"{page_title} {text[:16000]}")
    return (
        "muzeul judetean" in value
        and "aurelian sacerdoteanu" in value
        and "valcea" in value
    )


def _context_for_href(html_text: str, href: str) -> str:
    # Bound context around the literal href. This deliberately avoids trying to
    # reinterpret remote document content or unrelated page-wide years.
    index = html_text.find(href)
    if index < 0:
        return ""
    start = max(0, index - 900)
    end = min(len(html_text), index + len(href) + 900)
    snippet = re.sub(r"<[^>]+>", " ", html_text[start:end])
    return clean(snippet)


def parse_current_tariff_reference(
    source_url: str,
    source_html: str,
    source_payload: bytes,
    *,
    as_of: date,
) -> MuzeeValceaPublicInfoState:
    canonical_source = validate_source_url(source_url)
    source_hash = hashlib.sha256(source_payload).hexdigest()
    parser = PublicInfoParser(canonical_source)
    parser.feed(source_html)
    text = parser.page_text()
    page_title = parser.page_title()

    def hold(reason: str) -> MuzeeValceaPublicInfoState:
        return MuzeeValceaPublicInfoState(
            source_id=SOURCE_ID,
            taxonomy_version=TAXONOMY_VERSION,
            source_name=SOURCE_NAME,
            source_tier=SOURCE_TIER,
            source_url=canonical_source,
            source_payload_sha256=source_hash,
            state="HOLD",
            hold_reason=reason,
            as_of_date=as_of.isoformat(),
            references=(),
        )

    if placeholder_present(text):
        return hold("placeholder/challenge page detected")
    if not source_identity_present(text, page_title):
        return hold("official museum identity not present")
    if not parser.anchors:
        return hold("no anchors discovered")

    current_year = as_of.year
    candidates: dict[str, TariffCandidate] = {}
    errors: list[str] = []
    for href, anchor_text in parser.anchors:
        context = _context_for_href(source_html, href)
        label_match = TARIFF_LABEL_RE.search(context)
        if not label_match or int(label_match.group(1)) != current_year:
            continue
        try:
            document_url, path_year = normalize_document_url(href, base_url=canonical_source)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if path_year != current_year:
            errors.append("tariff label year and document path year disagree")
            continue
        evidence = clean(f"{context} | {anchor_text} | {document_url}")
        candidate = TariffCandidate(
            document_url=document_url,
            year=current_year,
            label=clean(label_match.group(0)),
            anchor_text=anchor_text,
            evidence_sha256=hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
        )
        previous = candidates.get(document_url)
        if previous and previous != candidate:
            errors.append("same tariff URL has conflicting evidence")
            continue
        candidates[document_url] = candidate

    if errors:
        return hold("; ".join(sorted(set(errors))))
    rows = tuple(sorted(candidates.values(), key=lambda item: item.document_url))
    if not rows:
        return hold(f"no explicit {current_year} first-party tariff reference")
    if len(rows) != 1:
        return hold(f"multiple distinct {current_year} tariff references discovered")

    return MuzeeValceaPublicInfoState(
        source_id=SOURCE_ID,
        taxonomy_version=TAXONOMY_VERSION,
        source_name=SOURCE_NAME,
        source_tier=SOURCE_TIER,
        source_url=canonical_source,
        source_payload_sha256=source_hash,
        state="PASS",
        hold_reason=None,
        as_of_date=as_of.isoformat(),
        references=rows,
    )


def build_state(
    *,
    as_of: date,
    source_url: str = SOURCE_URL,
    fetcher: Callable[[str], tuple[str, str, bytes]] = fetch_source,
) -> MuzeeValceaPublicInfoState:
    try:
        final_url, source_html, source_payload = fetcher(source_url)
        return parse_current_tariff_reference(
            final_url, source_html, source_payload, as_of=as_of
        )
    except Exception as exc:  # fail closed at the network/parser boundary
        canonical = validate_source_url(source_url)
        return MuzeeValceaPublicInfoState(
            source_id=SOURCE_ID,
            taxonomy_version=TAXONOMY_VERSION,
            source_name=SOURCE_NAME,
            source_tier=SOURCE_TIER,
            source_url=canonical,
            source_payload_sha256="",
            state="HOLD",
            hold_reason=f"source fetch/parse failure: {exc}",
            as_of_date=as_of.isoformat(),
            references=(),
        )


def _fixture(href: str, label: str = "LISTA CU TAXE SI TARIFE 2026") -> str:
    return f"""<!doctype html><html><head>
    <title>Muzeul Judetean Aurelian Sacerdoteanu Valcea</title></head><body>
    <header>Muzeul Judetean Aurelian Sacerdoteanu Valcea</header>
    <section><h2>{label}</h2><a href="{href}">Vizualizare taxa</a></section>
    </body></html>"""


def self_test() -> None:
    as_of = date(2026, 8, 31)
    good_href = "/documente/2026/Lista%20taxe%202026.pdf"
    good_html = _fixture(good_href)
    good = parse_current_tariff_reference(
        SOURCE_URL, good_html, good_html.encode(), as_of=as_of
    )
    assert good.state == "PASS"
    assert len(good.references) == 1
    assert good.references[0].year == 2026
    assert good.document_fetch_allowed is False
    assert good.current_price_claim_allowed is False
    assert good.public_projection_allowed is False

    duplicate_html = good_html.replace(
        "</section>",
        f'<a href="{good_href}">Vizualizare taxa</a></section>',
    )
    duplicate = parse_current_tariff_reference(
        SOURCE_URL, duplicate_html, duplicate_html.encode(), as_of=as_of
    )
    assert duplicate.state == "PASS"
    assert len(duplicate.references) == 1

    external = _fixture("https://example.com/documente/2026/taxe.pdf")
    external_state = parse_current_tariff_reference(
        SOURCE_URL, external, external.encode(), as_of=as_of
    )
    assert external_state.state == "HOLD"

    missing = _fixture("/documente/2025/taxe.pdf", "LISTA CU TAXE SI TARIFE 2025")
    missing_state = parse_current_tariff_reference(
        SOURCE_URL, missing, missing.encode(), as_of=as_of
    )
    assert missing_state.state == "HOLD"

    conflict = good_html.replace(
        "</section>",
        '<a href="/documente/2026/alta-lista.pdf">Vizualizare taxa</a></section>',
    )
    conflict_state = parse_current_tariff_reference(
        SOURCE_URL, conflict, conflict.encode(), as_of=as_of
    )
    assert conflict_state.state == "HOLD"

    no_identity = good_html.replace(
        "Muzeul Judetean Aurelian Sacerdoteanu Valcea", "Site cultural"
    )
    no_identity_state = parse_current_tariff_reference(
        SOURCE_URL, no_identity, no_identity.encode(), as_of=as_of
    )
    assert no_identity_state.state == "HOLD"

    drift = _fixture("/documente/2025/taxe.pdf", "LISTA CU TAXE SI TARIFE 2026")
    drift_state = parse_current_tariff_reference(
        SOURCE_URL, drift, drift.encode(), as_of=as_of
    )
    assert drift_state.state == "HOLD"

    print("muzee_valcea_public_information_reference_adapter: self-test PASS")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--source-url", default=SOURCE_URL)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return

    as_of = date.fromisoformat(args.as_of)
    state = build_state(as_of=as_of, source_url=args.source_url)
    print(json.dumps(asdict(state), ensure_ascii=False, sort_keys=True, indent=2))
    if state.state != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
