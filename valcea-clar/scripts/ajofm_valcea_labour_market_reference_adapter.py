#!/usr/bin/env python3
"""Evidence-first AJOFM Vâlcea labour-market press reference adapter.

Reads only the official AJOFM Vâlcea press-release index and exposes dated,
first-party article references for newsroom review. It does not fetch article
bodies or downloadable documents and does not infer unemployment levels,
vacancy counts, employer facts, eligibility, benefit rights, current job
availability, or event status from a title/reference alone.
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
from datetime import date, timedelta
from typing import Any, Optional
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

SOURCE_ID = "signal-ajofm-valcea-labour-market-references"
TAXONOMY_VERSION = "2026-08-31.1"
SOURCE_NAME = "AJOFM Vâlcea — comunicate de presă"
SOURCE_TIER = "T1_OFFICIAL_EMPLOYMENT_AGENCY_FIRST_PARTY"
SOURCE_URL = "https://www.anofm.ro/valcea/categorie/comunicate-de-presa/"
CANONICAL_HOST = "www.anofm.ro"
ALLOWED_HOSTS = {"anofm.ro", "www.anofm.ro"}
ROOT_PATH = "/valcea/categorie/comunicate-de-presa"
ARTICLE_PREFIX = "/valcea/"
MAX_RESPONSE_BYTES = 2_500_000
MAX_REFERENCES = 24
TIMEOUT_SECONDS = 15
USER_AGENT = "CIVORA-ValceaClar-AJOFMValcea/1.0 (+evidence-first; contact via repository)"

IDENTITY_MARKERS = (
    "ajofm valcea",
    "agentia judeteana pentru ocuparea fortei de munca valcea",
)
PLACEHOLDER_TERMS = (
    "access denied",
    "captcha",
    "checking your browser",
    "enable javascript",
    "service unavailable",
    "temporarily unavailable",
    "verify you are human",
)
EXCLUDED_SLUGS = {
    "calendar",
    "categorie",
    "contact",
    "despre-noi",
    "executia-bugetara",
    "formulare",
    "informatii-de-interes-public",
}
DATE_RE = re.compile(r"(?<!\d)(0?[1-9]|[12]\d|3[01])\s*[./-]\s*(0?[1-9]|1[0-2])\s*[./-]\s*(20\d{2})(?!\d)")


@dataclass(frozen=True)
class PressReference:
    kind: str
    canonical_url: str
    title: str
    published_date: str
    evidence_sha256: str


@dataclass(frozen=True)
class AJOFMValceaReferenceState:
    source_id: str
    taxonomy_version: str
    source_name: str
    source_tier: str
    source_url: str
    source_payload_sha256: str
    state: str
    hold_reason: Optional[str]
    references: tuple[PressReference, ...]
    reference_scope: str = "FIRST_PARTY_DATED_PRESS_REFERENCE_ONLY"
    article_body_fetch_allowed: bool = False
    document_body_fetch_allowed: bool = False
    employer_or_person_extraction_allowed: bool = False
    unemployment_value_extraction_allowed: bool = False
    vacancy_count_extraction_allowed: bool = False
    benefit_or_eligibility_inference_allowed: bool = False
    current_job_availability_inference_allowed: bool = False
    event_currentness_inference_allowed: bool = False
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


def normalized_path(value: str) -> str:
    path = re.sub(r"/+", "/", unquote(value or "/"))
    if not path.startswith("/"):
        path = "/" + path
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return path


def validate_first_party_url(url: str) -> tuple[str, str]:
    parsed = urlsplit(clean(url))
    host = (parsed.hostname or "").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or host not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.port not in (None, 443)
    ):
        raise ValueError(f"off-surface AJOFM Vâlcea URL refused: {url}")
    return host, normalized_path(parsed.path)


def validate_source_url(url: str) -> str:
    _, path = validate_first_party_url(url)
    if path != ROOT_PATH:
        raise ValueError(f"non-index AJOFM Vâlcea URL refused: {url}")
    return urlunsplit(("https", CANONICAL_HOST, ROOT_PATH + "/", "", ""))


def normalize_article_url(value: str, *, base_url: str = SOURCE_URL) -> str:
    joined = urljoin(base_url, clean(value))
    _, path = validate_first_party_url(joined)
    if not path.startswith(ARTICLE_PREFIX):
        raise ValueError(f"non-AJOFM Vâlcea article refused: {value}")
    tail = path[len(ARTICLE_PREFIX):]
    segments = [segment for segment in tail.split("/") if segment]
    if len(segments) != 1 or segments[0].casefold() in EXCLUDED_SLUGS:
        raise ValueError(f"non-article AJOFM Vâlcea path refused: {value}")
    return urlunsplit(("https", CANONICAL_HOST, path + "/", "", ""))


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise ValueError(f"redirect refused: {newurl}")


def fetch_source(url: str = SOURCE_URL) -> tuple[str, str, bytes]:
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


class ArticleIndexParser(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.skip = 0
        self.article_depth = 0
        self.article_parts: list[str] = []
        self.article_links: list[tuple[str, str]] = []
        self.href: Optional[str] = None
        self.link_parts: list[str] = []
        self.page_parts: list[str] = []
        self.articles: list[tuple[str, tuple[tuple[str, str], ...]]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "article":
            if self.article_depth == 0:
                self.article_parts = []
                self.article_links = []
            self.article_depth += 1
            return
        if tag == "a" and self.article_depth:
            values = {k.casefold(): v for k, v in attrs if k and v is not None}
            raw_href = clean(values.get("href"))
            try:
                self.href = normalize_article_url(raw_href, base_url=self.page_url)
            except (TypeError, ValueError):
                self.href = None
            self.link_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.SKIP:
            if self.skip:
                self.skip -= 1
            return
        if self.skip:
            return
        if tag == "a" and self.article_depth:
            if self.href:
                self.article_links.append((self.href, clean(" ".join(self.link_parts))))
            self.href = None
            self.link_parts = []
            return
        if tag == "article" and self.article_depth:
            self.article_depth -= 1
            if self.article_depth == 0:
                self.articles.append((clean(" ".join(self.article_parts)), tuple(self.article_links)))

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        text = clean(data)
        if not text:
            return
        self.page_parts.append(text)
        if self.article_depth:
            self.article_parts.append(text)
            if self.href:
                self.link_parts.append(text)


def parse_date_from_text(value: str) -> Optional[date]:
    matches = DATE_RE.findall(value)
    parsed: set[date] = set()
    for day, month, year in matches:
        try:
            parsed.add(date(int(year), int(month), int(day)))
        except ValueError:
            continue
    if len(parsed) != 1:
        return None
    return next(iter(parsed))


def classify_title(title: str) -> str:
    text = fold(title)
    if "locuri de munca vacante" in text or "eures" in text:
        return "VACANCY_MARKET_REFERENCE"
    if "rata somajului" in text:
        return "UNEMPLOYMENT_RATE_REFERENCE"
    if "bursa" in text and "locurilor de munca" in text:
        return "JOB_FAIR_REFERENCE"
    if "incadrate" in text or "incadrari" in text:
        return "PLACEMENT_OUTCOME_REFERENCE"
    if "economie sociala" in text:
        return "SOCIAL_ECONOMY_REFERENCE"
    if "formare profesionala" in text or "curs" in text:
        return "TRAINING_REFERENCE"
    return "AJOFM_PRESS_REFERENCE"


def build_state(
    html_text: str,
    *,
    source_url: str = SOURCE_URL,
    raw_bytes: Optional[bytes] = None,
    as_of: Optional[date] = None,
) -> AJOFMValceaReferenceState:
    canonical_source = validate_source_url(source_url)
    payload = raw_bytes if raw_bytes is not None else html_text.encode("utf-8")
    payload_sha = hashlib.sha256(payload).hexdigest()
    parser = ArticleIndexParser(canonical_source)
    parser.feed(html_text)
    page_text = fold(" ".join(parser.page_parts))

    def hold(reason: str) -> AJOFMValceaReferenceState:
        return AJOFMValceaReferenceState(
            SOURCE_ID, TAXONOMY_VERSION, SOURCE_NAME, SOURCE_TIER, canonical_source,
            payload_sha, "HOLD", reason, (),
        )

    if any(term in page_text for term in PLACEHOLDER_TERMS):
        return hold("PLACEHOLDER_OR_ACCESS_CHALLENGE")
    if not any(marker in page_text for marker in IDENTITY_MARKERS):
        return hold("SOURCE_IDENTITY_NOT_CONFIRMED")

    today = as_of or date.today()
    by_url: dict[str, PressReference] = {}
    for article_text, links in parser.articles:
        published = parse_date_from_text(article_text)
        if published is None:
            continue
        if published > today + timedelta(days=1):
            return hold("FUTURE_PUBLICATION_DATE")
        candidates = [(url, clean(title)) for url, title in links if clean(title)]
        if not candidates:
            continue
        url, title = max(candidates, key=lambda item: len(item[1]))
        if len(title) < 8:
            continue
        kind = classify_title(title)
        evidence = f"{kind}|{url}|{title}|{published.isoformat()}".encode("utf-8")
        reference = PressReference(kind, url, title, published.isoformat(), hashlib.sha256(evidence).hexdigest())
        prior = by_url.get(url)
        if prior and prior != reference:
            return hold("CONFLICTING_REFERENCE_FOR_SAME_URL")
        by_url[url] = reference

    references = tuple(sorted(by_url.values(), key=lambda item: (item.published_date, item.canonical_url), reverse=True)[:MAX_REFERENCES])
    if not references:
        return hold("NO_DATED_PRESS_REFERENCES")
    return AJOFMValceaReferenceState(
        SOURCE_ID, TAXONOMY_VERSION, SOURCE_NAME, SOURCE_TIER, canonical_source,
        payload_sha, "REFERENCE_READY", None, references,
    )


def run_self_test() -> None:
    fixture = """
    <html><body>
      <header>AJOFM Vâlcea</header>
      <article><h2><a href="https://www.anofm.ro/valcea/locuri-de-munca-vacante-la-nivel-judetean-si-in-reteaua-eures-31-iulie-2026/">Locuri de muncă vacante la nivel județean și în rețeaua EURES – 31 iulie 2026</a></h2><div>31/07/2026 Comunicate de presă</div></article>
      <article><h2><a href="/valcea/rata-somajului-iunie-2026/">Rata șomajului iunie 2026</a></h2><div>20/07/2026 Comunicate de presă</div></article>
      <article><a href="https://example.com/offsite">offsite</a><div>19/07/2026</div></article>
    </body></html>
    """
    state = build_state(fixture, as_of=date(2026, 8, 31))
    assert state.state == "REFERENCE_READY"
    assert len(state.references) == 2
    assert state.references[0].kind == "VACANCY_MARKET_REFERENCE"
    assert {ref.kind for ref in state.references} == {"VACANCY_MARKET_REFERENCE", "UNEMPLOYMENT_RATE_REFERENCE"}
    assert all(ref.canonical_url.startswith("https://www.anofm.ro/valcea/") for ref in state.references)
    assert not state.article_body_fetch_allowed
    assert not state.document_body_fetch_allowed
    assert not state.current_job_availability_inference_allowed
    assert not state.public_projection_allowed
    assert state.publication_authority == "NONE"

    placeholder = build_state("<html><body>AJOFM Vâlcea captcha verify you are human</body></html>", as_of=date(2026, 8, 31))
    assert placeholder.state == "HOLD" and placeholder.hold_reason == "PLACEHOLDER_OR_ACCESS_CHALLENGE"

    wrong_identity = build_state("<html><body><article><a href='/valcea/test/'>Test articol valid</a> 20/07/2026</article></body></html>", as_of=date(2026, 8, 31))
    assert wrong_identity.state == "HOLD" and wrong_identity.hold_reason == "SOURCE_IDENTITY_NOT_CONFIRMED"

    future = build_state("<html><body>AJOFM Vâlcea<article><a href='/valcea/test-future/'>Comunicat test viitor</a> 03/09/2026</article></body></html>", as_of=date(2026, 8, 31))
    assert future.state == "HOLD" and future.hold_reason == "FUTURE_PUBLICATION_DATE"

    assert validate_source_url("https://anofm.ro/valcea/categorie/comunicate-de-presa/") == SOURCE_URL
    try:
        normalize_article_url("https://www.anofm.ro/valcea/categorie/comunicate-de-presa/")
        raise AssertionError("category path must fail closed")
    except ValueError:
        pass
    try:
        normalize_article_url("https://example.com/valcea/test/")
        raise AssertionError("external host must fail closed")
    except ValueError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-url", default=SOURCE_URL)
    parser.add_argument("--as-of", help="YYYY-MM-DD; defaults to local date")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        print("AJOFM Vâlcea labour-market reference adapter self-test: OK")
        return 0

    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    try:
        final_url, html_text, raw = fetch_source(args.source_url)
        state = build_state(html_text, source_url=final_url, raw_bytes=raw, as_of=as_of)
    except Exception as exc:
        state = AJOFMValceaReferenceState(
            SOURCE_ID, TAXONOMY_VERSION, SOURCE_NAME, SOURCE_TIER, validate_source_url(args.source_url),
            "", "HOLD", f"FETCH_OR_PARSE_ERROR:{type(exc).__name__}", (),
        )
    print(json.dumps(asdict(state), ensure_ascii=False, indent=2))
    return 0 if state.state == "REFERENCE_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
