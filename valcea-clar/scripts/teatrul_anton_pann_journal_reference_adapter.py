#!/usr/bin/env python3
"""Evidence-first Teatrul Anton Pann journal reference adapter.

The adapter reads only the official first-party Jurnal archive page and extracts
bounded article-reference metadata from isolated post blocks. It does not read
article bodies. A journal publication date is not an event date and does not
prove that an activity is upcoming, ongoing, unchanged, ticketed, or suitable
for breaking-news publication.

This lane is reference intelligence only: no people extraction, no child/minor
data, no external ticketing, no image ingest or inferred photo rights, no
persistence, no Fact Kernel promotion, no Writer invocation, and no public
projection.
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
from datetime import date, datetime, timezone
from typing import Any, Optional
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

SOURCE_ID = "signal-teatrul-anton-pann-journal-references"
TAXONOMY_VERSION = "2026-08-31.1"
SOURCE_NAME = "Teatrul Anton Pann Râmnicu Vâlcea — Jurnal"
SOURCE_TIER = "T1_OFFICIAL_CULTURE_FIRST_PARTY"
SOURCE_URL = "https://teatrulantonpann.ro/anunturi/jurnal/"
CANONICAL_HOST = "teatrulantonpann.ro"
ALLOWED_HOSTS = {"teatrulantonpann.ro", "www.teatrulantonpann.ro"}
JOURNAL_PATH = "/anunturi/jurnal/"
MAX_RESPONSE_BYTES = 2_500_000
MAX_REFERENCES = 40
TIMEOUT_SECONDS = 15
USER_AGENT = "CIVORA-ValceaClar-AntonPann/1.0 (+evidence-first; contact via repository)"

READ_MORE_TERMS = {
    "citeste articolul",
    "citește articolul",
    "read more",
    "mai multe",
}
RESERVED_ROOT_PATHS = {
    "/",
    "/program/",
    "/contact/",
    "/bilete/",
    "/cine-suntem/",
    "/ce-facem/",
    "/proiecte/",
    "/cariere/",
}
DATE_PATH_RE = re.compile(r"^/20\d{2}/(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])/?$")
ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
EN_DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+([0-3]?\d),\s*(20\d{2})\b",
    re.I,
)
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
PLACEHOLDER_TERMS = (
    "enable javascript",
    "access denied",
    "captcha",
    "service unavailable",
    "temporarily unavailable",
    "verify you are human",
    "checking your browser",
)


@dataclass(frozen=True)
class JournalReference:
    article_url: str
    title: Optional[str]
    published_date: Optional[str]
    reference_kind: Optional[str]
    provenance_sha256: Optional[str]
    review_state: str
    hold_reason: Optional[str]


@dataclass(frozen=True)
class AntonPannJournalState:
    source_id: str
    taxonomy_version: str
    source_name: str
    source_tier: str
    source_url: str
    source_payload_sha256: str
    state: str
    hold_reason: Optional[str]
    as_of_date: str
    references: tuple[JournalReference, ...]
    reference_scope: str = "FIRST_PARTY_JOURNAL_INDEX_REFERENCE_ONLY"
    article_body_fetch_allowed: bool = False
    external_ticketing_fetch_allowed: bool = False
    person_identity_extraction_allowed: bool = False
    minor_or_child_data_extraction_allowed: bool = False
    event_date_inference_from_publication_date_allowed: bool = False
    current_event_status_inference_allowed: bool = False
    cancellation_or_ticket_status_inference_allowed: bool = False
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
        raise ValueError(f"off-surface Anton Pann URL refused: {url}")
    return host, _path(parsed.path)


def validate_source_url(url: str) -> str:
    _, path = _base_url(url)
    if path != JOURNAL_PATH:
        raise ValueError(f"non-journal Anton Pann URL refused: {url}")
    return urlunsplit(("https", CANONICAL_HOST, JOURNAL_PATH, "", ""))


def normalize_article_url(value: str, *, base_url: str = SOURCE_URL) -> str:
    joined = urljoin(base_url, clean(value))
    _, path = _base_url(joined)
    if not path.endswith("/"):
        path += "/"
    if path == JOURNAL_PATH or path in RESERVED_ROOT_PATHS:
        raise ValueError(f"non-article Anton Pann URL refused: {value}")
    if path.startswith("/anunturi/") or DATE_PATH_RE.fullmatch(path):
        raise ValueError(f"non-article Anton Pann URL refused: {value}")
    parts = [part for part in path.split("/") if part]
    if len(parts) != 1 or not re.fullmatch(r"[a-z0-9][a-z0-9._~!$&'()*+,;=:@%\-]*", parts[0], re.I):
        raise ValueError(f"non-root article URL refused: {value}")
    return urlunsplit(("https", CANONICAL_HOST, path, "", ""))


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise ValueError(f"redirect refused: {newurl}")


def fetch_source(url: str) -> tuple[str, str, bytes]:
    canonical = validate_source_url(url)
    opener = build_opener(NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(canonical, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
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


@dataclass
class _Block:
    depth: int
    text_parts: list[str]
    href_texts: dict[str, set[str]]
    dates: set[str]


class JournalParser(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.skip = 0
        self.depth = 0
        self.title_depth = 0
        self.title_parts: list[str] = []
        self.page_parts: list[str] = []
        self.blocks: list[_Block] = []
        self.active: Optional[_Block] = None
        self.anchor_url: Optional[str] = None
        self.anchor_parts: list[str] = []

    def _maybe_start_block(self, tag: str, values: dict[str, str]) -> None:
        if self.active is not None:
            return
        cls = fold(values.get("class", ""))
        ident = fold(values.get("id", ""))
        if tag == "article" or "elementor-post" in cls or re.search(r"\bpost[-_]\d+\b", cls + " " + ident):
            self.active = _Block(depth=self.depth, text_parts=[], href_texts={}, dates=set())

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        self.depth += 1
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        values = {k.casefold(): clean(v) for k, v in attrs if k and v is not None}
        self._maybe_start_block(tag, values)
        if tag == "title":
            self.title_depth += 1
        if tag == "a":
            raw_href = values.get("href", "")
            try:
                self.anchor_url = normalize_article_url(raw_href, base_url=self.page_url)
            except ValueError:
                self.anchor_url = None
            self.anchor_parts = []
        for key in ("datetime", "title"):
            self._capture_dates(values.get(key, ""))

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.SKIP and self.skip:
            self.skip -= 1
            self.depth -= 1
            return
        if self.skip:
            self.depth -= 1
            return
        if tag == "a":
            if self.active is not None and self.anchor_url:
                text = clean(" ".join(self.anchor_parts))
                if text and fold(text) not in READ_MORE_TERMS:
                    self.active.href_texts.setdefault(self.anchor_url, set()).add(text)
            self.anchor_url = None
            self.anchor_parts = []
        if tag == "title" and self.title_depth:
            self.title_depth -= 1
        if self.active is not None and self.active.depth == self.depth:
            self.blocks.append(self.active)
            self.active = None
        self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        value = clean(data)
        if not value:
            return
        self.page_parts.append(value)
        if self.title_depth:
            self.title_parts.append(value)
        if self.active is not None:
            self.active.text_parts.append(value)
            self._capture_dates(value)
        if self.anchor_url:
            self.anchor_parts.append(value)

    def _capture_dates(self, value: str) -> None:
        if self.active is None:
            return
        for match in ISO_DATE_RE.finditer(value):
            try:
                parsed = date.fromisoformat(match.group(0))
            except ValueError:
                continue
            self.active.dates.add(parsed.isoformat())
        for match in EN_DATE_RE.finditer(value):
            try:
                parsed = date(int(match.group(3)), MONTHS[match.group(1).casefold()], int(match.group(2)))
            except (ValueError, KeyError):
                continue
            self.active.dates.add(parsed.isoformat())

    def page_text(self) -> str:
        return clean(" ".join(self.page_parts))

    def page_title(self) -> str:
        return clean(" ".join(self.title_parts))


def placeholder_present(text: str) -> bool:
    value = fold(text[:5000])
    return any(term in value for term in PLACEHOLDER_TERMS)


def source_identity_present(text: str, page_title: str) -> bool:
    value = fold(f"{page_title} {text[:12000]}")
    return "teatrul anton pann" in value and "jurnal" in value


def classify_title(title: str) -> str:
    value = fold(title)
    if "festival" in value or "fits" in value or "undercloud" in value:
        return "FESTIVAL_PARTICIPATION_REFERENCE"
    if any(term in value for term in ("in vizita", "gradinita", "scoala", "muzeul", "mall", "babeni", "dragasani")):
        return "COMMUNITY_OUTREACH_REFERENCE"
    return "JOURNAL_ACTIVITY_REFERENCE"


def hold_reference(article_url: str, reason: str) -> JournalReference:
    return JournalReference(
        article_url=article_url,
        title=None,
        published_date=None,
        reference_kind=None,
        provenance_sha256=None,
        review_state="HOLD",
        hold_reason=reason,
    )


def block_to_reference(block: _Block, as_of: date) -> Optional[JournalReference]:
    if not block.href_texts:
        return None
    if len(block.href_texts) != 1:
        first = sorted(block.href_texts)[0]
        return hold_reference(first, "post block contains multiple first-party article URLs")

    article_url, titles = next(iter(block.href_texts.items()))
    clean_titles = sorted({clean(item) for item in titles if clean(item)})
    if len(clean_titles) != 1:
        return hold_reference(article_url, "article URL lacks a unique non-generic title in its post block")
    if len(block.dates) != 1:
        return hold_reference(article_url, "article post block lacks a unique explicit publication date")

    published = date.fromisoformat(next(iter(block.dates)))
    if published > as_of:
        return hold_reference(article_url, "journal publication date is in the future relative to as-of date")

    title = clean_titles[0]
    evidence = clean(" | ".join((article_url, title, published.isoformat())))
    return JournalReference(
        article_url=article_url,
        title=title,
        published_date=published.isoformat(),
        reference_kind=classify_title(title),
        provenance_sha256=hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
        review_state="ACTIVITY_REFERENCE_ONLY",
        hold_reason=None,
    )


def extract_state(
    source_url: str,
    source_html: str,
    source_payload: bytes,
    as_of: date,
) -> AntonPannJournalState:
    canonical = validate_source_url(source_url)
    parser = JournalParser(canonical)
    parser.feed(source_html)
    text = parser.page_text()
    title = parser.page_title()

    if placeholder_present(text):
        raise ValueError("journal page challenge/placeholder refused")
    if not source_identity_present(text, title):
        raise ValueError("Teatrul Anton Pann journal identity not present")
    if not parser.blocks:
        return AntonPannJournalState(
            source_id=SOURCE_ID,
            taxonomy_version=TAXONOMY_VERSION,
            source_name=SOURCE_NAME,
            source_tier=SOURCE_TIER,
            source_url=canonical,
            source_payload_sha256=hashlib.sha256(source_payload).hexdigest(),
            state="HOLD",
            hold_reason="no bounded journal post blocks discovered",
            as_of_date=as_of.isoformat(),
            references=(),
        )
    if len(parser.blocks) > MAX_REFERENCES:
        raise ValueError("journal post discovery exceeds bounded reference cap")

    references = [ref for block in parser.blocks if (ref := block_to_reference(block, as_of)) is not None]
    if not references:
        state, reason = "HOLD", "no first-party journal article references discovered"
    elif any(ref.review_state == "ACTIVITY_REFERENCE_ONLY" for ref in references):
        state, reason = "PASS", None
    else:
        state, reason = "HOLD", "all discovered journal references are held"

    references.sort(key=lambda item: (item.published_date or "0000-00-00", item.article_url), reverse=True)
    return AntonPannJournalState(
        source_id=SOURCE_ID,
        taxonomy_version=TAXONOMY_VERSION,
        source_name=SOURCE_NAME,
        source_tier=SOURCE_TIER,
        source_url=canonical,
        source_payload_sha256=hashlib.sha256(source_payload).hexdigest(),
        state=state,
        hold_reason=reason,
        as_of_date=as_of.isoformat(),
        references=tuple(references),
    )


def validate_boundaries(state: AntonPannJournalState) -> None:
    forbidden_true = (
        "article_body_fetch_allowed",
        "external_ticketing_fetch_allowed",
        "person_identity_extraction_allowed",
        "minor_or_child_data_extraction_allowed",
        "event_date_inference_from_publication_date_allowed",
        "current_event_status_inference_allowed",
        "cancellation_or_ticket_status_inference_allowed",
        "image_ingest_allowed",
        "inferred_photo_rights_allowed",
        "breaking_news_promotion_allowed",
        "persistence_allowed",
        "fact_kernel_promotion_allowed",
        "writer_allowed",
        "public_projection_allowed",
    )
    for field in forbidden_true:
        if getattr(state, field):
            raise AssertionError(f"boundary drift: {field}=true")
    if state.publication_authority != "NONE":
        raise AssertionError("publication authority drift")
    for ref in state.references:
        if ref.review_state == "HOLD":
            if any((ref.title, ref.published_date, ref.reference_kind, ref.provenance_sha256)):
                raise AssertionError("held journal reference leaks promoted metadata")
        elif ref.review_state != "ACTIVITY_REFERENCE_ONLY":
            raise AssertionError("unexpected journal reference state")


def run_self_test() -> None:
    source = """
    <html><head><title>Jurnal – Teatrul Anton Pann</title></head><body>
    <header>Teatrul Anton Pann</header><h1>Jurnal</h1>
    <article class="elementor-post post-101">
      <h3><a href="/in-vizita-la-gradinita-busy-bee/">In vizita la Gradinita Busy Bee</a></h3>
      <a href="/anunturi/jurnal/">Jurnal</a><a href="/2026/07/08/">July 8, 2026</a>
      <a href="/in-vizita-la-gradinita-busy-bee/">Citeste articolul</a>
    </article>
    <article class="elementor-post post-102">
      <h3><a href="https://teatrulantonpann.ro/festivalului-atelier-baia-mare/">Festivalului ATELIER – Baia Mare</a></h3>
      <time datetime="2026-06-16">June 16, 2026</time>
    </article>
    <a href="https://theatrum.ro/eveniment/x">Bilete externe</a>
    </body></html>
    """
    state = extract_state(SOURCE_URL, source, source.encode(), date(2026, 8, 31))
    validate_boundaries(state)
    assert state.state == "PASS"
    assert len(state.references) == 2
    refs = {ref.title: ref for ref in state.references}
    assert refs["In vizita la Gradinita Busy Bee"].published_date == "2026-07-08"
    assert refs["In vizita la Gradinita Busy Bee"].reference_kind == "COMMUNITY_OUTREACH_REFERENCE"
    assert refs["Festivalului ATELIER – Baia Mare"].reference_kind == "FESTIVAL_PARTICIPATION_REFERENCE"

    ambiguous = source.replace(
        '<time datetime="2026-06-16">June 16, 2026</time>',
        '<time datetime="2026-06-16">June 16, 2026</time><time datetime="2026-06-17">June 17, 2026</time>',
    )
    held_state = extract_state(SOURCE_URL, ambiguous, ambiguous.encode(), date(2026, 8, 31))
    held = next(ref for ref in held_state.references if ref.article_url.endswith("/festivalului-atelier-baia-mare/"))
    assert held.review_state == "HOLD"
    assert held.published_date is None
    validate_boundaries(held_state)

    future = source.replace("July 8, 2026", "September 8, 2026").replace("/2026/07/08/", "/2026/09/08/")
    future_state = extract_state(SOURCE_URL, future, future.encode(), date(2026, 8, 31))
    held_future = next(ref for ref in future_state.references if ref.article_url.endswith("/in-vizita-la-gradinita-busy-bee/"))
    assert held_future.review_state == "HOLD"

    conflict = source.replace(
        '<a href="/in-vizita-la-gradinita-busy-bee/">Citeste articolul</a>',
        '<a href="/alt-articol/">Alt articol</a>',
    )
    conflict_state = extract_state(SOURCE_URL, conflict, conflict.encode(), date(2026, 8, 31))
    assert any(ref.review_state == "HOLD" for ref in conflict_state.references)

    no_identity = source.replace("Teatrul Anton Pann", "Portal Cultural")
    try:
        extract_state(SOURCE_URL, no_identity, no_identity.encode(), date(2026, 8, 31))
    except ValueError as exc:
        assert "identity" in str(exc)
    else:
        raise AssertionError("source identity drift must fail closed")

    for bad in (
        "http://teatrulantonpann.ro/anunturi/jurnal/",
        "https://evil.example/anunturi/jurnal/",
        "https://teatrulantonpann.ro/anunturi/jurnal/?x=1",
        "https://teatrulantonpann.ro/program/",
    ):
        try:
            validate_source_url(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"off-surface source URL should fail: {bad}")

    for bad in (
        "https://evil.example/articol/",
        "http://teatrulantonpann.ro/articol/",
        "https://teatrulantonpann.ro/anunturi/jurnal/",
        "https://teatrulantonpann.ro/2026/07/08/",
        "https://teatrulantonpann.ro/a/b/",
    ):
        try:
            normalize_article_url(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"off-surface article URL should fail: {bad}")

    print("Teatrul Anton Pann journal reference adapter self-test: PASS")


def parse_as_of(value: str) -> date:
    return date.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-url", default=SOURCE_URL)
    parser.add_argument("--as-of", type=parse_as_of, default=None)
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        return 0

    as_of = args.as_of or datetime.now(timezone.utc).date()
    source_url, source_html, source_payload = fetch_source(args.source_url)
    state = extract_state(source_url, source_html, source_payload, as_of)
    validate_boundaries(state)
    encoded = json.dumps(asdict(state), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(encoded)
    else:
        print(encoded, end="")
    return 0 if state.state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
