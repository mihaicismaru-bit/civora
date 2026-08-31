#!/usr/bin/env python3
"""Evidence-first BJAI Vâlcea event-reference adapter.

The adapter starts from the official Biblioteca Județeană „Antim Ivireanul”
Vâlcea events archive, discovers only first-party `/evenimente/<slug>/` links,
and may read a bounded number of those detail pages to confirm one explicit
Romanian weekday/date phrase.

This is event-reference intelligence only. It does not infer currentness,
cancellation, availability, ticketing, venue, people, audience, photo rights,
or publication authority. It does not persist state, promote to Fact Kernel,
invoke Writer, or project reader-facing output.
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
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

SOURCE_ID = "signal-bjai-valcea-event-references"
TAXONOMY_VERSION = "2026-08-31.1"
SOURCE_NAME = 'Biblioteca Județeană „Antim Ivireanul” Vâlcea — Evenimente'
SOURCE_TIER = "T1_OFFICIAL_CULTURE_FIRST_PARTY"
SOURCE_URL = "https://www.bjai.ro/evenimente/"
CANONICAL_HOST = "www.bjai.ro"
ALLOWED_HOSTS = {"bjai.ro", "www.bjai.ro"}
ARCHIVE_PATH = "/evenimente/"
EVENT_PATH_RE = re.compile(r"^/evenimente/[a-z0-9][a-z0-9._~!$&'()*+,;=:@%\-]*/$", re.I)
MAX_RESPONSE_BYTES = 2_500_000
MAX_EVENT_PAGES = 12
MAX_REFERENCE_AGE_DAYS = 550
TIMEOUT_SECONDS = 15
USER_AGENT = "CIVORA-ValceaClar-BJAI/1.0 (+evidence-first; contact via repository)"

READ_MORE_TERMS = {"citeste mai mult", "citește mai mult", "read more", "mai multe"}
PLACEHOLDER_TERMS = (
    "enable javascript",
    "access denied",
    "captcha",
    "service unavailable",
    "temporarily unavailable",
    "verify you are human",
    "checking your browser",
)
MONTHS = {
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
WEEKDAY_DATE_RE = re.compile(
    r"\b(?:luni|mar[țt]i|miercuri|joi|vineri|s[aâ]mb[aă]t[aă]|duminic[aă])\s*,?\s*"
    r"([0-3]?\d)\s+"
    r"(ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)\s+"
    r"(20\d{2})\b",
    re.I,
)


@dataclass(frozen=True)
class EventDiscovery:
    event_url: str
    archive_title: str


@dataclass(frozen=True)
class EventReference:
    event_url: str
    archive_title: str
    detail_title: Optional[str]
    event_date: Optional[str]
    reference_kind: Optional[str]
    event_payload_sha256: Optional[str]
    date_evidence: Optional[str]
    review_state: str
    hold_reason: Optional[str]


@dataclass(frozen=True)
class BjaiEventState:
    source_id: str
    taxonomy_version: str
    source_name: str
    source_tier: str
    source_url: str
    source_payload_sha256: str
    state: str
    hold_reason: Optional[str]
    as_of_date: str
    references: tuple[EventReference, ...]
    reference_scope: str = "FIRST_PARTY_EVENT_ARCHIVE_REFERENCE_ONLY"
    detail_page_fetch_allowed: bool = True
    external_site_fetch_allowed: bool = False
    person_identity_extraction_allowed: bool = False
    minor_or_child_data_extraction_allowed: bool = False
    venue_claim_extraction_allowed: bool = False
    event_time_extraction_allowed: bool = False
    ticket_or_admission_extraction_allowed: bool = False
    current_event_status_inference_allowed: bool = False
    cancellation_inference_allowed: bool = False
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


def title_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", fold(value))


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
        raise ValueError(f"off-surface BJAI URL refused: {url}")
    return host, _path(parsed.path)


def validate_source_url(url: str) -> str:
    _, path = _base_url(url)
    if path.rstrip("/") != ARCHIVE_PATH.rstrip("/"):
        raise ValueError(f"non-events-archive BJAI URL refused: {url}")
    return urlunsplit(("https", CANONICAL_HOST, ARCHIVE_PATH, "", ""))


def normalize_event_url(value: str, *, base_url: str = SOURCE_URL) -> str:
    joined = urljoin(base_url, clean(value))
    _, path = _base_url(joined)
    if not path.endswith("/"):
        path += "/"
    if not EVENT_PATH_RE.fullmatch(path):
        raise ValueError(f"non-event BJAI URL refused: {value}")
    return urlunsplit(("https", CANONICAL_HOST, path, "", ""))


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise ValueError(f"redirect refused: {newurl}")


def _fetch_html(canonical_url: str, validator: Callable[[str], str]) -> tuple[str, str, bytes]:
    opener = build_opener(NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(canonical_url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
    with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        final_url = validator(response.geturl())
        if final_url != canonical_url:
            raise ValueError("canonical URL drift after fetch")
        content_type = clean(response.headers.get("Content-Type", "")).casefold()
        if "text/html" not in content_type:
            raise ValueError(f"non-HTML source refused: {content_type or 'unknown'}")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds size cap")
        charset = response.headers.get_content_charset() or "utf-8"
    return final_url, body.decode(charset, errors="replace"), body


def fetch_source(url: str) -> tuple[str, str, bytes]:
    canonical = validate_source_url(url)
    return _fetch_html(canonical, validate_source_url)


def fetch_event(url: str) -> tuple[str, str, bytes]:
    canonical = normalize_event_url(url)
    return _fetch_html(canonical, normalize_event_url)


class ArchiveParser(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.skip = 0
        self.title_depth = 0
        self.title_parts: list[str] = []
        self.page_parts: list[str] = []
        self.anchor_url: Optional[str] = None
        self.anchor_parts: list[str] = []
        self.titles: dict[str, set[str]] = {}

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
            try:
                self.anchor_url = normalize_event_url(values.get("href", ""), base_url=self.page_url)
            except ValueError:
                self.anchor_url = None
            self.anchor_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.SKIP and self.skip:
            self.skip -= 1
            return
        if self.skip:
            return
        if tag == "a":
            if self.anchor_url:
                text = clean(" ".join(self.anchor_parts))
                if text and fold(text) not in READ_MORE_TERMS:
                    self.titles.setdefault(self.anchor_url, set()).add(text)
            self.anchor_url = None
            self.anchor_parts = []
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
        if self.anchor_url:
            self.anchor_parts.append(value)

    def page_text(self) -> str:
        return clean(" ".join(self.page_parts))

    def page_title(self) -> str:
        return clean(" ".join(self.title_parts))

    def discoveries(self) -> list[EventDiscovery]:
        rows: list[EventDiscovery] = []
        for event_url, titles in sorted(self.titles.items()):
            clean_titles = sorted({clean(item) for item in titles if clean(item)})
            if len(clean_titles) == 1:
                title = clean_titles[0]
            elif clean_titles:
                title = " || ".join(clean_titles)
            else:
                continue
            rows.append(EventDiscovery(event_url=event_url, archive_title=title))
        return rows


class DetailParser(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.title_depth = 0
        self.title_parts: list[str] = []
        self.h1_depth = 0
        self.h1_parts: list[str] = []
        self.page_parts: list[str] = []
        self.date_candidates: set[str] = set()

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "title":
            self.title_depth += 1
        if tag == "h1":
            self.h1_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.SKIP and self.skip:
            self.skip -= 1
            return
        if self.skip:
            return
        if tag == "title" and self.title_depth:
            self.title_depth -= 1
        if tag == "h1" and self.h1_depth:
            self.h1_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        value = clean(data)
        if not value:
            return
        self.page_parts.append(value)
        if self.title_depth:
            self.title_parts.append(value)
        if self.h1_depth:
            self.h1_parts.append(value)
        for match in WEEKDAY_DATE_RE.finditer(value):
            day = int(match.group(1))
            month = MONTHS[fold(match.group(2))]
            year = int(match.group(3))
            try:
                parsed = date(year, month, day)
            except ValueError:
                continue
            self.date_candidates.add(parsed.isoformat())

    def page_text(self) -> str:
        return clean(" ".join(self.page_parts))

    def page_title(self) -> str:
        return clean(" ".join(self.title_parts))

    def event_title(self) -> str:
        return clean(" ".join(self.h1_parts))


def placeholder_present(text: str) -> bool:
    value = fold(text[:5000])
    return any(term in value for term in PLACEHOLDER_TERMS)


def source_identity_present(text: str, page_title: str) -> bool:
    value = fold(f"{page_title} {text[:12000]}")
    return "biblioteca" in value and "antim ivireanul" in value and "valcea" in value and "evenimente" in value


def detail_identity_present(text: str, page_title: str) -> bool:
    value = fold(f"{page_title} {text[:12000]}")
    return "biblioteca" in value and "antim ivireanul" in value and "valcea" in value


def classify_title(title: str) -> str:
    value = fold(title)
    if "lansar" in value or "volum" in value or "carte" in value:
        return "BOOK_LAUNCH_REFERENCE"
    if "festival" in value:
        return "FESTIVAL_REFERENCE"
    if "colocvi" in value or "confer" in value or "simpoz" in value:
        return "COLLOQUIUM_REFERENCE"
    if "atelier" in value or "tabara" in value:
        return "WORKSHOP_OR_CAMP_REFERENCE"
    if "expoz" in value:
        return "EXHIBITION_REFERENCE"
    if "recital" in value or "concert" in value or "muzical" in value:
        return "RECITAL_OR_CONCERT_REFERENCE"
    return "CULTURAL_EVENT_REFERENCE"


def hold_reference(discovery: EventDiscovery, reason: str) -> EventReference:
    return EventReference(
        event_url=discovery.event_url,
        archive_title=discovery.archive_title,
        detail_title=None,
        event_date=None,
        reference_kind=None,
        event_payload_sha256=None,
        date_evidence=None,
        review_state="HOLD",
        hold_reason=reason,
    )


def parse_event_reference(
    discovery: EventDiscovery,
    event_url: str,
    event_html: str,
    event_payload: bytes,
    as_of: date,
) -> EventReference:
    canonical = normalize_event_url(event_url)
    if canonical != discovery.event_url:
        return hold_reference(discovery, "event fetch URL does not match archive discovery")
    if " || " in discovery.archive_title:
        return hold_reference(discovery, "same event URL has conflicting archive titles")

    parser = DetailParser()
    parser.feed(event_html)
    text = parser.page_text()
    page_title = parser.page_title()
    detail_title = parser.event_title()

    if placeholder_present(text):
        return hold_reference(discovery, "event page challenge/placeholder detected")
    if not detail_identity_present(text, page_title):
        return hold_reference(discovery, "BJAI event-page identity not present")
    if not detail_title:
        return hold_reference(discovery, "event page lacks explicit H1 title")
    if title_key(detail_title) != title_key(discovery.archive_title):
        return hold_reference(discovery, "archive/detail event title mismatch")

    valid_dates = sorted(parser.date_candidates)
    if len(valid_dates) != 1:
        reason = "event page lacks a unique explicit Romanian weekday/date"
        if len(valid_dates) > 1:
            reason = "event page contains multiple explicit Romanian weekday/dates"
        return hold_reference(discovery, reason)

    event_day = date.fromisoformat(valid_dates[0])
    if event_day > as_of + timedelta(days=400):
        return hold_reference(discovery, "event date exceeds bounded future horizon")
    if event_day < as_of - timedelta(days=MAX_REFERENCE_AGE_DAYS):
        return hold_reference(discovery, "event date exceeds bounded historical horizon")

    return EventReference(
        event_url=canonical,
        archive_title=discovery.archive_title,
        detail_title=detail_title,
        event_date=event_day.isoformat(),
        reference_kind=classify_title(detail_title),
        event_payload_sha256=hashlib.sha256(event_payload).hexdigest(),
        date_evidence="UNIQUE_EXPLICIT_ROMANIAN_WEEKDAY_DATE_ON_FIRST_PARTY_EVENT_PAGE",
        review_state="EVENT_REFERENCE_ONLY",
        hold_reason=None,
    )


EventLoader = Callable[[str], tuple[str, str, bytes]]


def extract_state(
    source_url: str,
    source_html: str,
    source_payload: bytes,
    as_of: date,
    *,
    event_loader: EventLoader = fetch_event,
) -> BjaiEventState:
    canonical = validate_source_url(source_url)
    parser = ArchiveParser(canonical)
    parser.feed(source_html)
    text = parser.page_text()
    title = parser.page_title()

    if placeholder_present(text):
        raise ValueError("events archive challenge/placeholder refused")
    if not source_identity_present(text, title):
        raise ValueError("BJAI Vâlcea events archive identity not present")

    discoveries = parser.discoveries()
    if not discoveries:
        return BjaiEventState(
            source_id=SOURCE_ID,
            taxonomy_version=TAXONOMY_VERSION,
            source_name=SOURCE_NAME,
            source_tier=SOURCE_TIER,
            source_url=canonical,
            source_payload_sha256=hashlib.sha256(source_payload).hexdigest(),
            state="HOLD",
            hold_reason="no first-party BJAI event references discovered",
            as_of_date=as_of.isoformat(),
            references=(),
        )
    if len(discoveries) > MAX_EVENT_PAGES:
        raise ValueError("events archive discovery exceeds bounded page cap")

    refs: list[EventReference] = []
    for discovery in discoveries:
        try:
            event_url, event_html, event_payload = event_loader(discovery.event_url)
            ref = parse_event_reference(discovery, event_url, event_html, event_payload, as_of)
        except Exception as exc:
            ref = hold_reference(discovery, f"event fetch/parse failed: {type(exc).__name__}")
        refs.append(ref)

    refs.sort(key=lambda item: (item.event_date or "0000-00-00", item.event_url), reverse=True)
    passed = any(ref.review_state == "EVENT_REFERENCE_ONLY" for ref in refs)
    return BjaiEventState(
        source_id=SOURCE_ID,
        taxonomy_version=TAXONOMY_VERSION,
        source_name=SOURCE_NAME,
        source_tier=SOURCE_TIER,
        source_url=canonical,
        source_payload_sha256=hashlib.sha256(source_payload).hexdigest(),
        state="PASS" if passed else "HOLD",
        hold_reason=None if passed else "all discovered BJAI event references are held",
        as_of_date=as_of.isoformat(),
        references=tuple(refs),
    )


def validate_boundaries(state: BjaiEventState) -> None:
    if not state.detail_page_fetch_allowed:
        raise AssertionError("detail-page fetch boundary unexpectedly disabled")
    forbidden_true = (
        "external_site_fetch_allowed",
        "person_identity_extraction_allowed",
        "minor_or_child_data_extraction_allowed",
        "venue_claim_extraction_allowed",
        "event_time_extraction_allowed",
        "ticket_or_admission_extraction_allowed",
        "current_event_status_inference_allowed",
        "cancellation_inference_allowed",
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
            if any((ref.detail_title, ref.event_date, ref.reference_kind, ref.event_payload_sha256, ref.date_evidence)):
                raise AssertionError("held BJAI event reference leaks promoted detail metadata")
        elif ref.review_state != "EVENT_REFERENCE_ONLY":
            raise AssertionError("unexpected BJAI event reference state")


def run_self_test() -> None:
    source = """
    <html><head><title>Evenimente la Biblioteca Judeteana Antim Ivireanul Valcea</title></head><body>
      <h1>Evenimente la Biblioteca Judeteana „Antim Ivireanul” Valcea</h1>
      <h2><a href="/evenimente/ziua-limbii-romane/">ZIUA LIMBII ROMÂNE</a></h2>
      <a href="/evenimente/ziua-limbii-romane/">Citește mai mult</a>
      <h2><a href="https://www.bjai.ro/evenimente/colocviul-regele-mihai/">Colocviul Regele Mihai I</a></h2>
      <a href="https://external.example/eveniment/x">Extern</a>
    </body></html>
    """
    pages = {
        "https://www.bjai.ro/evenimente/ziua-limbii-romane/": """
          <html><head><title>ZIUA LIMBII ROMÂNE | Biblioteca Judeteana Antim Ivireanul</title></head><body>
          <h1>ZIUA LIMBII ROMÂNE</h1>
          <p>Luni, 31 August 2026, ora 11:00, Biblioteca Județeană „Antim Ivireanul” Vâlcea găzduiește evenimentul.</p>
          </body></html>
        """,
        "https://www.bjai.ro/evenimente/colocviul-regele-mihai/": """
          <html><head><title>Colocviul Regele Mihai I | Biblioteca Judeteana Antim Ivireanul</title></head><body>
          <h1>Colocviul Regele Mihai I</h1>
          <p>Duminică, 23 August 2026, ora 12:00, Biblioteca Județeană „Antim Ivireanul” Vâlcea organizează evenimentul.</p>
          </body></html>
        """,
    }

    def loader(url: str) -> tuple[str, str, bytes]:
        text = pages[url]
        return url, text, text.encode()

    state = extract_state(SOURCE_URL, source, source.encode(), date(2026, 8, 31), event_loader=loader)
    validate_boundaries(state)
    assert state.state == "PASS"
    assert len(state.references) == 2
    refs = {ref.archive_title: ref for ref in state.references}
    assert refs["ZIUA LIMBII ROMÂNE"].event_date == "2026-08-31"
    assert refs["Colocviul Regele Mihai I"].reference_kind == "COLLOQUIUM_REFERENCE"

    ambiguous_pages = dict(pages)
    ambiguous_pages["https://www.bjai.ro/evenimente/ziua-limbii-romane/"] = pages[
        "https://www.bjai.ro/evenimente/ziua-limbii-romane/"
    ].replace("</body>", "<p>Marți, 1 Septembrie 2026</p></body>")

    def ambiguous_loader(url: str) -> tuple[str, str, bytes]:
        text = ambiguous_pages[url]
        return url, text, text.encode()

    ambiguous = extract_state(SOURCE_URL, source, source.encode(), date(2026, 8, 31), event_loader=ambiguous_loader)
    held = next(ref for ref in ambiguous.references if ref.archive_title == "ZIUA LIMBII ROMÂNE")
    assert held.review_state == "HOLD"
    assert held.event_date is None
    validate_boundaries(ambiguous)

    mismatch_pages = dict(pages)
    mismatch_pages["https://www.bjai.ro/evenimente/colocviul-regele-mihai/"] = pages[
        "https://www.bjai.ro/evenimente/colocviul-regele-mihai/"
    ].replace("<h1>Colocviul Regele Mihai I</h1>", "<h1>Alt eveniment</h1>")

    def mismatch_loader(url: str) -> tuple[str, str, bytes]:
        text = mismatch_pages[url]
        return url, text, text.encode()

    mismatch = extract_state(SOURCE_URL, source, source.encode(), date(2026, 8, 31), event_loader=mismatch_loader)
    bad = next(ref for ref in mismatch.references if ref.archive_title == "Colocviul Regele Mihai I")
    assert bad.review_state == "HOLD"

    conflict_source = source.replace(
        '<a href="/evenimente/ziua-limbii-romane/">Citește mai mult</a>',
        '<a href="/evenimente/ziua-limbii-romane/">Alt titlu incompatibil</a>',
    )
    conflict = extract_state(SOURCE_URL, conflict_source, conflict_source.encode(), date(2026, 8, 31), event_loader=loader)
    conflict_ref = next(ref for ref in conflict.references if ref.event_url.endswith("/ziua-limbii-romane/"))
    assert conflict_ref.review_state == "HOLD"

    no_identity = source.replace("Antim Ivireanul", "Portal Cultural")
    try:
        extract_state(SOURCE_URL, no_identity, no_identity.encode(), date(2026, 8, 31), event_loader=loader)
    except ValueError as exc:
        assert "identity" in str(exc)
    else:
        raise AssertionError("source identity drift must fail closed")

    for bad_url in (
        "http://www.bjai.ro/evenimente/",
        "https://evil.example/evenimente/",
        "https://www.bjai.ro/evenimente/?page=2",
        "https://www.bjai.ro/calendar-evenimente/",
    ):
        try:
            validate_source_url(bad_url)
        except ValueError:
            pass
        else:
            raise AssertionError(f"off-surface source URL should fail: {bad_url}")

    for bad_url in (
        "https://evil.example/evenimente/x/",
        "http://www.bjai.ro/evenimente/x/",
        "https://www.bjai.ro/evenimente/",
        "https://www.bjai.ro/evenimente/a/b/",
        "https://www.bjai.ro/evenimente/x/?utm_source=y",
    ):
        try:
            normalize_event_url(bad_url)
        except ValueError:
            pass
        else:
            raise AssertionError(f"off-surface event URL should fail: {bad_url}")

    print("BJAI Vâlcea event reference adapter self-test: PASS")


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
