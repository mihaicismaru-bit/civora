#!/usr/bin/env python3
"""Evidence-first Filarmonica Vâlcea upcoming-event reference adapter.

The adapter starts from the official Filarmonica "Ion Dumitrescu" homepage,
discovers only first-party `/eveniment/<slug>/` URLs linked there, and may read
those bounded detail pages to confirm an explicit event date.

This is event-reference intelligence, not publication authority. A first-party
calendar entry does not prove that an event is still on, unchanged, on sale,
uncancelled, or happening "now". The adapter does not extract performers,
ticket prices, audience categories, venue claims, images, or external ticketing
data; does not persist state; does not promote to Fact Kernel; does not invoke
Writer; and does not publish.
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

SOURCE_ID = "signal-filarmonica-valcea-upcoming-event-references"
TAXONOMY_VERSION = "2026-08-31.1"
SOURCE_NAME = 'Filarmonica „Ion Dumitrescu” Râmnicu Vâlcea — evenimente viitoare'
SOURCE_TIER = "T1_OFFICIAL_CULTURE_FIRST_PARTY"
SOURCE_URL = "https://filarmonica-valcea.ro/"
CANONICAL_HOST = "filarmonica-valcea.ro"
ALLOWED_HOSTS = {"filarmonica-valcea.ro", "www.filarmonica-valcea.ro"}
HOME_PATH = "/"
EVENT_PATH_RE = re.compile(r"^/eveniment/[a-z0-9][a-z0-9._~!$&'()*+,;=:@%\-]*/$", re.I)
MAX_RESPONSE_BYTES = 2_500_000
MAX_EVENT_PAGES = 12
MAX_EVENT_HORIZON_DAYS = 400
TIMEOUT_SECONDS = 15
USER_AGENT = "CIVORA-ValceaClar-Filarmonica/1.0 (+evidence-first; contact via repository)"
ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")

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
class EventDiscovery:
    event_url: str
    homepage_title: str


@dataclass(frozen=True)
class EventReference:
    event_url: str
    homepage_title: str
    detail_title: Optional[str]
    event_date: Optional[str]
    event_payload_sha256: Optional[str]
    date_evidence: Optional[str]
    review_state: str
    hold_reason: Optional[str]


@dataclass(frozen=True)
class FilarmonicaEventState:
    source_id: str
    taxonomy_version: str
    source_name: str
    source_tier: str
    source_url: str
    homepage_payload_sha256: str
    state: str
    hold_reason: Optional[str]
    as_of_date: str
    references: tuple[EventReference, ...]
    reference_scope: str = "FIRST_PARTY_UPCOMING_EVENT_CALENDAR_REFERENCE_ONLY"
    detail_page_fetch_allowed: bool = True
    external_ticketing_fetch_allowed: bool = False
    event_body_claim_extraction_allowed: bool = False
    performer_identity_extraction_allowed: bool = False
    venue_claim_extraction_allowed: bool = False
    ticket_price_extraction_allowed: bool = False
    event_time_extraction_allowed: bool = False
    cancellation_or_currentness_inference_allowed: bool = False
    event_occurring_now_inference_allowed: bool = False
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
        raise ValueError(f"off-surface Filarmonica URL refused: {url}")
    return host, _path(parsed.path)


def validate_home_url(url: str) -> str:
    _, path = _base_url(url)
    if path != HOME_PATH:
        raise ValueError(f"non-home Filarmonica URL refused: {url}")
    return urlunsplit(("https", CANONICAL_HOST, HOME_PATH, "", ""))


def normalize_event_url(value: str, *, base_url: str = SOURCE_URL) -> str:
    joined = urljoin(base_url, clean(value))
    _, path = _base_url(joined)
    if not path.endswith("/"):
        path += "/"
    if not EVENT_PATH_RE.fullmatch(path):
        raise ValueError(f"non-event Filarmonica URL refused: {value}")
    return urlunsplit(("https", CANONICAL_HOST, path, "", ""))


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise ValueError(f"redirect refused: {newurl}")


def _fetch_html(canonical_url: str, validator: Callable[[str], str]) -> tuple[str, str, bytes]:
    opener = build_opener(NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(
        canonical_url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"},
    )
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


def fetch_home(url: str) -> tuple[str, str, bytes]:
    canonical = validate_home_url(url)
    return _fetch_html(canonical, validate_home_url)


def fetch_event(url: str) -> tuple[str, str, bytes]:
    canonical = normalize_event_url(url)
    return _fetch_html(canonical, normalize_event_url)


class HomeParser(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.skip = 0
        self.page_parts: list[str] = []
        self.title_depth = 0
        self.title_parts: list[str] = []
        self.href: Optional[str] = None
        self.link_parts: list[str] = []
        self.event_titles: dict[str, set[str]] = {}

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
            values = {k.casefold(): v for k, v in attrs if k and v is not None}
            raw_href = clean(values.get("href"))
            try:
                self.href = normalize_event_url(raw_href, base_url=self.page_url)
            except ValueError:
                self.href = None
            self.link_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.SKIP and self.skip:
            self.skip -= 1
            return
        if self.skip:
            return
        if tag == "a":
            if self.href:
                text = clean(" ".join(self.link_parts))
                folded = fold(text)
                if text and folded not in {"find out more", "find out more »", "citeste mai mult", "citește mai mult"}:
                    self.event_titles.setdefault(self.href, set()).add(text)
            self.href = None
            self.link_parts = []
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
        if self.href:
            self.link_parts.append(value)

    def page_text(self) -> str:
        return clean(" ".join(self.page_parts))

    def page_title(self) -> str:
        return clean(" ".join(self.title_parts))

    def discoveries(self) -> list[EventDiscovery]:
        rows: list[EventDiscovery] = []
        for event_url, titles in sorted(self.event_titles.items()):
            normalized_titles = sorted({clean(t) for t in titles if clean(t)})
            if not normalized_titles:
                continue
            title = normalized_titles[0] if len(normalized_titles) == 1 else " || ".join(normalized_titles)
            rows.append(EventDiscovery(event_url=event_url, homepage_title=title))
        return rows


class EventParser(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.page_parts: list[str] = []
        self.title_depth = 0
        self.title_parts: list[str] = []
        self.h1_depth = 0
        self.h1_parts: list[str] = []
        self.date_candidates: set[str] = set()

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        values = {k.casefold(): clean(v) for k, v in attrs if k and v is not None}
        if tag == "title":
            self.title_depth += 1
        if tag == "h1":
            self.h1_depth += 1
        cls = values.get("class", "").casefold()
        for key in ("datetime", "title"):
            raw = values.get(key, "")
            match = ISO_DATE_RE.search(raw)
            if not match:
                continue
            if key == "datetime" or "tribe-events" in cls or "start-date" in cls or tag == "time":
                self.date_candidates.add(match.group(0))

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
        for match in ISO_DATE_RE.finditer(value):
            self.date_candidates.add(match.group(0))

    def page_text(self) -> str:
        return clean(" ".join(self.page_parts))

    def page_title(self) -> str:
        return clean(" ".join(self.title_parts))

    def event_title(self) -> str:
        return clean(" ".join(self.h1_parts))


def placeholder_present(text: str) -> bool:
    value = fold(text[:5000])
    return any(term in value for term in PLACEHOLDER_TERMS)


def home_identity_present(text: str, page_title: str) -> bool:
    value = fold(f"{page_title} {text[:10000]}")
    return "filarmonica" in value and "ion dumitrescu" in value and "ramnicu valcea" in value


def event_identity_present(text: str, page_title: str) -> bool:
    value = fold(f"{page_title} {text[:10000]}")
    return "filarmonica" in value and ("ion dumitrescu" in value or "filarmonica valcea" in value)


def _valid_iso_date(value: str) -> Optional[date]:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def hold_reference(discovery: EventDiscovery, reason: str) -> EventReference:
    return EventReference(
        event_url=discovery.event_url,
        homepage_title=discovery.homepage_title,
        detail_title=None,
        event_date=None,
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
        return hold_reference(discovery, "event fetch URL does not match homepage discovery")

    parser = EventParser()
    parser.feed(event_html)
    text = parser.page_text()
    page_title = parser.page_title()
    detail_title = parser.event_title()

    if placeholder_present(text):
        return hold_reference(discovery, "event page challenge/placeholder detected")
    if not event_identity_present(text, page_title):
        return hold_reference(discovery, "Filarmonica event-page identity not present")
    if " || " in discovery.homepage_title:
        return hold_reference(discovery, "same event URL has conflicting homepage titles")
    if not detail_title:
        return hold_reference(discovery, "event page lacks explicit H1 title")
    if fold(detail_title) != fold(discovery.homepage_title):
        return hold_reference(discovery, "homepage/detail event title mismatch")

    valid_dates = sorted(
        {candidate for candidate in parser.date_candidates if _valid_iso_date(candidate) is not None}
    )
    if len(valid_dates) != 1:
        reason = "event page lacks a unique explicit ISO event date"
        if len(valid_dates) > 1:
            reason = "event page contains multiple explicit ISO dates"
        return hold_reference(discovery, reason)

    event_day = date.fromisoformat(valid_dates[0])
    if event_day < as_of:
        return hold_reference(discovery, "homepage-discovered event date is before as-of date")
    if event_day > as_of + timedelta(days=MAX_EVENT_HORIZON_DAYS):
        return hold_reference(discovery, "event date exceeds bounded future horizon")

    return EventReference(
        event_url=canonical,
        homepage_title=discovery.homepage_title,
        detail_title=detail_title,
        event_date=event_day.isoformat(),
        event_payload_sha256=hashlib.sha256(event_payload).hexdigest(),
        date_evidence="UNIQUE_EXPLICIT_ISO_DATE_ON_FIRST_PARTY_EVENT_PAGE",
        review_state="SCHEDULE_REFERENCE_ONLY",
        hold_reason=None,
    )


EventLoader = Callable[[str], tuple[str, str, bytes]]


def extract_state(
    source_url: str,
    home_html: str,
    home_payload: bytes,
    as_of: date,
    *,
    event_loader: EventLoader = fetch_event,
) -> FilarmonicaEventState:
    canonical_home = validate_home_url(source_url)
    parser = HomeParser(canonical_home)
    parser.feed(home_html)
    text = parser.page_text()
    title = parser.page_title()

    if placeholder_present(text):
        raise ValueError("homepage challenge/placeholder refused")
    if not home_identity_present(text, title):
        raise ValueError("Filarmonica Vâlcea homepage identity not present")

    discoveries = parser.discoveries()
    if not discoveries:
        return FilarmonicaEventState(
            source_id=SOURCE_ID,
            taxonomy_version=TAXONOMY_VERSION,
            source_name=SOURCE_NAME,
            source_tier=SOURCE_TIER,
            source_url=canonical_home,
            homepage_payload_sha256=hashlib.sha256(home_payload).hexdigest(),
            state="HOLD",
            hold_reason="no first-party event references discovered on homepage",
            as_of_date=as_of.isoformat(),
            references=(),
        )
    if len(discoveries) > MAX_EVENT_PAGES:
        raise ValueError("homepage event discovery exceeds bounded page cap")

    references: list[EventReference] = []
    for discovery in discoveries:
        try:
            event_url, event_html, event_payload = event_loader(discovery.event_url)
            reference = parse_event_reference(
                discovery,
                event_url,
                event_html,
                event_payload,
                as_of,
            )
        except Exception as exc:
            reference = hold_reference(discovery, f"event fetch/parse failed: {type(exc).__name__}")
        references.append(reference)

    references.sort(key=lambda item: (item.event_date or "9999-99-99", item.event_url))
    passed = any(item.review_state == "SCHEDULE_REFERENCE_ONLY" for item in references)
    state = "PASS" if passed else "HOLD"
    hold_reason = None if passed else "all discovered Filarmonica event references are held"

    return FilarmonicaEventState(
        source_id=SOURCE_ID,
        taxonomy_version=TAXONOMY_VERSION,
        source_name=SOURCE_NAME,
        source_tier=SOURCE_TIER,
        source_url=canonical_home,
        homepage_payload_sha256=hashlib.sha256(home_payload).hexdigest(),
        state=state,
        hold_reason=hold_reason,
        as_of_date=as_of.isoformat(),
        references=tuple(references),
    )


def validate_boundaries(state: FilarmonicaEventState) -> None:
    if not state.detail_page_fetch_allowed:
        raise AssertionError("detail-page fetch boundary unexpectedly disabled")
    forbidden_true = (
        "external_ticketing_fetch_allowed",
        "event_body_claim_extraction_allowed",
        "performer_identity_extraction_allowed",
        "venue_claim_extraction_allowed",
        "ticket_price_extraction_allowed",
        "event_time_extraction_allowed",
        "cancellation_or_currentness_inference_allowed",
        "event_occurring_now_inference_allowed",
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
            if any((ref.detail_title, ref.event_date, ref.event_payload_sha256, ref.date_evidence)):
                raise AssertionError("held event reference leaks promoted detail metadata")
        elif ref.review_state != "SCHEDULE_REFERENCE_ONLY":
            raise AssertionError("unexpected event review state")


def run_self_test() -> None:
    home = """
    <html>
      <head><title>Filarmonica Valcea – Filarmonica “Ion Dumitrescu” Râmnicu Vâlcea</title></head>
      <body>
        <h1>Filarmonica „Ion Dumitrescu” Râmnicu Vâlcea</h1>
        <h2>Evenimente viitoare</h2>
        <a href="/eveniment/jazz-in-the-evening/">JAZZ IN THE EVENING</a>
        <a href="/eveniment/jazz-in-the-evening/">Find out more »</a>
        <a href="https://filarmonica-valcea.ro/eveniment/latino-simfonic/">LATINO SIMFONIC</a>
        <a href="https://www.bilete.ro/eveniment/ignored/">Bilete externe</a>
      </body>
    </html>
    """
    pages = {
        "https://filarmonica-valcea.ro/eveniment/jazz-in-the-evening/": """
          <html><head><title>JAZZ IN THE EVENING – Filarmonica Valcea</title></head><body>
          <h1>JAZZ IN THE EVENING</h1>
          <div class="tribe-events-schedule"><abbr class="tribe-events-abbr tribe-events-start-date"
            title="2026-09-14">septembrie 14</abbr></div>
          <p>Filarmonica „Ion Dumitrescu”</p></body></html>
        """,
        "https://filarmonica-valcea.ro/eveniment/latino-simfonic/": """
          <html><head><title>LATINO SIMFONIC – Filarmonica Valcea</title></head><body>
          <h1>LATINO SIMFONIC</h1>
          <div>Details Date: septembrie 21 (2026-09-21)</div>
          <p>Filarmonica „Ion Dumitrescu”</p></body></html>
        """,
    }

    def loader(url: str) -> tuple[str, str, bytes]:
        text = pages[url]
        return url, text, text.encode()

    state = extract_state(SOURCE_URL, home, home.encode(), date(2026, 8, 31), event_loader=loader)
    validate_boundaries(state)
    assert state.state == "PASS"
    assert len(state.references) == 2
    refs = {ref.homepage_title: ref for ref in state.references}
    assert refs["JAZZ IN THE EVENING"].event_date == "2026-09-14"
    assert refs["LATINO SIMFONIC"].event_date == "2026-09-21"
    assert refs["JAZZ IN THE EVENING"].review_state == "SCHEDULE_REFERENCE_ONLY"

    mismatch_pages = dict(pages)
    mismatch_pages["https://filarmonica-valcea.ro/eveniment/latino-simfonic/"] = pages[
        "https://filarmonica-valcea.ro/eveniment/latino-simfonic/"
    ].replace("<h1>LATINO SIMFONIC</h1>", "<h1>ALT EVENIMENT</h1>")

    def mismatch_loader(url: str) -> tuple[str, str, bytes]:
        text = mismatch_pages[url]
        return url, text, text.encode()

    mismatch = extract_state(SOURCE_URL, home, home.encode(), date(2026, 8, 31), event_loader=mismatch_loader)
    held = next(ref for ref in mismatch.references if ref.homepage_title == "LATINO SIMFONIC")
    assert held.review_state == "HOLD"
    assert held.event_date is None
    validate_boundaries(mismatch)

    multiple_pages = dict(pages)
    multiple_pages["https://filarmonica-valcea.ro/eveniment/jazz-in-the-evening/"] = pages[
        "https://filarmonica-valcea.ro/eveniment/jazz-in-the-evening/"
    ].replace("</body>", "<time datetime='2026-09-15'></time></body>")

    def multiple_loader(url: str) -> tuple[str, str, bytes]:
        text = multiple_pages[url]
        return url, text, text.encode()

    multiple = extract_state(SOURCE_URL, home, home.encode(), date(2026, 8, 31), event_loader=multiple_loader)
    jazz = next(ref for ref in multiple.references if ref.homepage_title == "JAZZ IN THE EVENING")
    assert jazz.review_state == "HOLD"
    assert "multiple" in (jazz.hold_reason or "")

    past_pages = dict(pages)
    past_pages["https://filarmonica-valcea.ro/eveniment/jazz-in-the-evening/"] = pages[
        "https://filarmonica-valcea.ro/eveniment/jazz-in-the-evening/"
    ].replace("2026-09-14", "2026-08-14")

    def past_loader(url: str) -> tuple[str, str, bytes]:
        text = past_pages[url]
        return url, text, text.encode()

    past = extract_state(SOURCE_URL, home, home.encode(), date(2026, 8, 31), event_loader=past_loader)
    past_ref = next(ref for ref in past.references if ref.homepage_title == "JAZZ IN THE EVENING")
    assert past_ref.review_state == "HOLD"
    assert "before as-of" in (past_ref.hold_reason or "")

    no_identity = home.replace("Filarmonica „Ion Dumitrescu” Râmnicu Vâlcea", "Portal cultural generic")
    no_identity = no_identity.replace("Filarmonica Valcea – Filarmonica “Ion Dumitrescu” Râmnicu Vâlcea", "Portal")
    try:
        extract_state(SOURCE_URL, no_identity, no_identity.encode(), date(2026, 8, 31), event_loader=loader)
    except ValueError as exc:
        assert "identity" in str(exc)
    else:
        raise AssertionError("homepage identity drift must fail closed")

    for bad in (
        "http://filarmonica-valcea.ro/",
        "https://evil.example/",
        "https://filarmonica-valcea.ro/?x=1",
        "https://filarmonica-valcea.ro/#x",
        "https://filarmonica-valcea.ro/eveniment/",
    ):
        try:
            validate_home_url(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"off-surface homepage URL should fail: {bad}")

    for bad in (
        "http://filarmonica-valcea.ro/eveniment/x/",
        "https://evil.example/eveniment/x/",
        "https://filarmonica-valcea.ro/eveniment/x/?x=1",
        "https://filarmonica-valcea.ro/evenimente/x/",
    ):
        try:
            normalize_event_url(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"off-surface event URL should fail: {bad}")

    print("Filarmonica Vâlcea upcoming-event reference adapter self-test: PASS")


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
    source_url, home_html, home_payload = fetch_home(args.source_url)
    state = extract_state(source_url, home_html, home_payload, as_of)
    validate_boundaries(state)
    rendered = json.dumps(asdict(state), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered)
    else:
        print(rendered, end="")
    return 0 if state.state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
