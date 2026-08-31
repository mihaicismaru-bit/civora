#!/usr/bin/env python3
"""Evidence-first AJOFM Vâlcea labor-market index adapter.

Consumes only the official AJOFM Vâlcea press-release index and emits bounded
article references for labor-market review. Metadata is accepted only when a
classified first-party link and one unambiguous publication date occur inside
the same HTML ``article`` element.

This is reference intelligence, not operational truth. It does not infer that
a vacancy remains open, an employer is currently hiring, unemployment is
rising/falling, a labor shortage exists, or a job fair is active now. It does
not follow article/document bodies, extract people, persist state, promote to
Fact Kernel, invoke Writer, publish, or infer photo rights.
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

SOURCE_ID = "signal-ajofm-valcea-labor-market-references"
TAXONOMY_VERSION = "2026-08-31.1"
SOURCE_NAME = "AJOFM Vâlcea — Comunicate de presă"
SOURCE_TIER = "T1_GOVERNMENT_FIRST_PARTY"
CANONICAL_HOST = "www.anofm.ro"
ALLOWED_HOSTS = {"anofm.ro", "www.anofm.ro"}
INDEX_PATH = "/valcea/categorie/comunicate-de-presa/"
ARTICLE_PATH_PREFIX = "/valcea/"
MAX_RESPONSE_BYTES = 2_500_000
TIMEOUT_SECONDS = 15
USER_AGENT = "CIVORA-ValceaClar-AJOFM/1.1 (+evidence-first; contact via repository)"

PLACEHOLDER_TERMS = (
    "enable javascript",
    "access denied",
    "captcha",
    "service unavailable",
    "temporarily unavailable",
    "verify you are human",
)
DATE_RE = re.compile(r"\b([0-3]?\d)[./-]([01]?\d)[./-](20\d{2})\b")
SIGNAL_PATTERNS = (
    ("VACANCY_RELEASE_REFERENCE", re.compile(r"\blocuri\s+de\s+munca\s+vacante\s+la\s+nivel\s+judetean\b", re.I)),
    ("UNEMPLOYMENT_RATE_RELEASE_REFERENCE", re.compile(r"\brata\s+(?:a\s+)?somajului\b", re.I)),
    ("JOB_FAIR_REFERENCE", re.compile(r"\bbursa\s+locurilor\s+de\s+munca\b", re.I)),
)


@dataclass(frozen=True)
class ArticleBlock:
    text: str
    links: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class LaborMarketReference:
    signal_class: str
    title: str
    publication_date: Optional[str]
    article_url: str
    review_state: str
    hold_reason: Optional[str]


@dataclass(frozen=True)
class AJOFMLaborMarketState:
    source_id: str
    taxonomy_version: str
    source_name: str
    source_tier: str
    source_url: str
    payload_sha256: str
    state: str
    hold_reason: Optional[str]
    as_of_date: str
    references: tuple[LaborMarketReference, ...]
    reference_scope: str = "AJOFM_VALCEA_INDEX_METADATA_ONLY"
    article_body_fetch_allowed: bool = False
    linked_document_fetch_allowed: bool = False
    vacancy_currentness_inference_allowed: bool = False
    employer_current_hiring_inference_allowed: bool = False
    unemployment_trend_inference_allowed: bool = False
    labor_shortage_inference_allowed: bool = False
    applicant_or_employee_identity_extraction_allowed: bool = False
    job_fair_currentness_inference_allowed: bool = False
    breaking_news_promotion_allowed: bool = False
    inferred_photo_rights_allowed: bool = False
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


def validate_index_url(url: str) -> str:
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
        or path.rstrip("/") + "/" != INDEX_PATH
    ):
        raise ValueError(f"off-surface AJOFM index refused: {url}")
    return urlunsplit(("https", CANONICAL_HOST, INDEX_PATH, "", ""))


def validate_article_url(url: str) -> str:
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
        or not path.startswith(ARTICLE_PATH_PREFIX)
        or path.rstrip("/") + "/" == INDEX_PATH
        or path == ARTICLE_PATH_PREFIX
    ):
        raise ValueError(f"off-surface AJOFM article refused: {url}")
    return urlunsplit(("https", CANONICAL_HOST, path, "", ""))


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise ValueError(f"redirect refused: {newurl}")


def fetch_html(url: str, timeout: float = TIMEOUT_SECONDS) -> tuple[str, str, bytes]:
    canonical = validate_index_url(url)
    opener = build_opener(NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(canonical, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
    with opener.open(request, timeout=timeout) as response:
        final_url = validate_index_url(response.geturl())
        content_type = clean(response.headers.get("Content-Type", "")).casefold()
        if "text/html" not in content_type:
            raise ValueError(f"non-HTML source refused: {content_type or 'unknown'}")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds size cap")
        charset = response.headers.get_content_charset() or "utf-8"
    return final_url, body.decode(charset, errors="replace"), body


class IndexParser(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.page_parts: list[str] = []
        self.title_parts: list[str] = []
        self.title_depth = 0
        self.article_depth = 0
        self.article_parts: list[str] = []
        self.article_links: list[tuple[str, str]] = []
        self.articles: list[ArticleBlock] = []
        self.href: Optional[str] = None
        self.link_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "title":
            self.title_depth += 1
        if tag == "article":
            if self.article_depth == 0:
                self.article_parts = []
                self.article_links = []
            self.article_depth += 1
        if tag == "a":
            values = {k.casefold(): v for k, v in attrs if k and v}
            self.href = values.get("href")
            self.link_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.SKIP and self.skip:
            self.skip -= 1
            return
        if self.skip:
            return
        if tag == "a" and self.href is not None:
            link_text = clean(" ".join(self.link_parts))
            if self.article_depth and link_text:
                self.article_links.append((self.href, link_text))
            self.href = None
            self.link_parts = []
        if tag == "title" and self.title_depth:
            self.title_depth -= 1
        if tag == "article" and self.article_depth:
            self.article_depth -= 1
            if self.article_depth == 0:
                self.articles.append(
                    ArticleBlock(clean(" ".join(self.article_parts)), tuple(self.article_links))
                )
                self.article_parts = []
                self.article_links = []

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        value = clean(data)
        if not value:
            return
        self.page_parts.append(value)
        if self.title_depth:
            self.title_parts.append(value)
        if self.article_depth:
            self.article_parts.append(value)
        if self.href is not None:
            self.link_parts.append(value)

    def page_text(self) -> str:
        return clean(" ".join(self.page_parts))

    def page_title(self) -> str:
        return clean(" ".join(self.title_parts))


def classify_title(title: str) -> Optional[str]:
    value = fold(title)
    for signal_class, pattern in SIGNAL_PATTERNS:
        if pattern.search(value):
            return signal_class
    return None


def source_identity_present(text: str, page_title: str) -> bool:
    value = fold(f"{page_title} {text[:8000]}")
    return "ajofm valcea" in value and "comunicate de presa" in value


def placeholder_present(text: str) -> bool:
    value = fold(text[:5000])
    return any(term in value for term in PLACEHOLDER_TERMS)


def explicit_block_date(text: str) -> tuple[Optional[str], Optional[str]]:
    values: set[str] = set()
    for day, month, year in DATE_RE.findall(text):
        try:
            parsed = date(int(year), int(month), int(day))
        except ValueError:
            continue
        if parsed.year >= 2020:
            values.add(parsed.isoformat())
    if len(values) == 1:
        return next(iter(values)), None
    if not values:
        return None, "classified AJOFM article block lacks an explicit publication date"
    return None, "classified AJOFM article block contains ambiguous multiple dates"


def make_reference(
    canonical: str,
    block: ArticleBlock,
    href: str,
    link_title: str,
    signal_class: str,
    as_of: date,
) -> LaborMarketReference:
    try:
        article_url = validate_article_url(urljoin(canonical, href))
    except ValueError:
        return LaborMarketReference(
            signal_class=signal_class,
            title=clean(link_title),
            publication_date=None,
            article_url="HELD_OFF_SURFACE_URL",
            review_state="HOLD",
            hold_reason="classified AJOFM reference points off the approved first-party surface",
        )

    publication_date, hold_reason = explicit_block_date(block.text)
    if publication_date and date.fromisoformat(publication_date) > as_of:
        publication_date = None
        hold_reason = "classified AJOFM reference has a future publication date"
    return LaborMarketReference(
        signal_class=signal_class,
        title=clean(link_title),
        publication_date=publication_date,
        article_url=article_url,
        review_state="REFERENCE_ONLY" if hold_reason is None else "HOLD",
        hold_reason=hold_reason,
    )


def extract_state(source_url: str, html_text: str, payload: bytes, as_of: date) -> AJOFMLaborMarketState:
    canonical = validate_index_url(source_url)
    parser = IndexParser()
    parser.feed(html_text)
    text = parser.page_text()
    title = parser.page_title()
    if placeholder_present(text):
        raise ValueError("placeholder/challenge page refused")
    if not source_identity_present(text, title):
        raise ValueError("AJOFM Vâlcea press-release identity not present")

    by_url: dict[str, LaborMarketReference] = {}
    off_surface: list[LaborMarketReference] = []
    for block in parser.articles:
        for href, link_title in block.links:
            signal_class = classify_title(link_title)
            if not signal_class:
                continue
            ref = make_reference(canonical, block, href, link_title, signal_class, as_of)
            if ref.article_url == "HELD_OFF_SURFACE_URL":
                if ref not in off_surface:
                    off_surface.append(ref)
                continue
            previous = by_url.get(ref.article_url)
            if previous is None:
                by_url[ref.article_url] = ref
            elif previous != ref:
                by_url[ref.article_url] = LaborMarketReference(
                    signal_class=ref.signal_class,
                    title=ref.title,
                    publication_date=None,
                    article_url=ref.article_url,
                    review_state="HOLD",
                    hold_reason="same AJOFM article URL has conflicting index metadata",
                )

    references = list(by_url.values()) + off_surface
    references.sort(key=lambda item: (item.publication_date or "", item.article_url), reverse=True)
    passed = any(item.review_state == "REFERENCE_ONLY" for item in references)
    if not references:
        state = "HOLD"
        hold_reason = "no bounded labor-market article references found inside AJOFM index article blocks"
    elif not passed:
        state = "HOLD"
        hold_reason = "all bounded AJOFM references are held"
    else:
        state = "PASS"
        hold_reason = None

    return AJOFMLaborMarketState(
        source_id=SOURCE_ID,
        taxonomy_version=TAXONOMY_VERSION,
        source_name=SOURCE_NAME,
        source_tier=SOURCE_TIER,
        source_url=canonical,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        state=state,
        hold_reason=hold_reason,
        as_of_date=as_of.isoformat(),
        references=tuple(references),
    )


def validate_boundaries(state: AJOFMLaborMarketState) -> None:
    forbidden_true = (
        "article_body_fetch_allowed",
        "linked_document_fetch_allowed",
        "vacancy_currentness_inference_allowed",
        "employer_current_hiring_inference_allowed",
        "unemployment_trend_inference_allowed",
        "labor_shortage_inference_allowed",
        "applicant_or_employee_identity_extraction_allowed",
        "job_fair_currentness_inference_allowed",
        "breaking_news_promotion_allowed",
        "inferred_photo_rights_allowed",
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
        if ref.review_state == "HOLD" and ref.publication_date is not None:
            raise AssertionError("held AJOFM reference leaks publication date")


def run_self_test() -> None:
    sample = """
    <html><head><title>Comunicate de presă – AJOFM Vâlcea</title></head><body>
      <h1>Comunicate de presă</h1>
      <article><h2><a href="https://www.anofm.ro/valcea/locuri-de-munca-vacante-la-nivel-judetean-si-in-reteaua-eures-31-iulie-2026/">Locuri de muncă vacante la nivel județean și în rețeaua EURES – 31 iulie 2026</a></h2><p>31/07/2026 Comunicate de presă</p></article>
      <article><h2><a href="/valcea/rata-somajului-iunie-2026/">Rata șomajului iunie 2026</a></h2><p>20/07/2026 Comunicate de presă</p></article>
      <article><h2><a href="/valcea/bursa-locurilor-de-munca-8-mai-2026/">Bursa locurilor de muncă – 8 mai 2026</a></h2><p>28/04/2026 Comunicate de presă</p></article>
      <article><h2><a href="/valcea/alt-comunicat/">Alt comunicat</a></h2><p>01/08/2026 Comunicate de presă</p></article>
    </body></html>
    """
    state = extract_state(f"https://{CANONICAL_HOST}{INDEX_PATH}", sample, sample.encode(), date(2026, 8, 31))
    validate_boundaries(state)
    assert state.state == "PASS"
    assert [(x.signal_class, x.publication_date) for x in state.references] == [
        ("VACANCY_RELEASE_REFERENCE", "2026-07-31"),
        ("UNEMPLOYMENT_RATE_RELEASE_REFERENCE", "2026-07-20"),
        ("JOB_FAIR_REFERENCE", "2026-04-28"),
    ]

    no_date = sample.replace("31/07/2026 Comunicate de presă", "Comunicate de presă", 1)
    state = extract_state(f"https://{CANONICAL_HOST}{INDEX_PATH}", no_date, no_date.encode(), date(2026, 8, 31))
    vacancy = next(x for x in state.references if x.signal_class == "VACANCY_RELEASE_REFERENCE")
    assert vacancy.review_state == "HOLD" and vacancy.publication_date is None

    ambiguous = sample.replace("31/07/2026 Comunicate de presă", "31/07/2026 actualizat 01/08/2026 Comunicate de presă", 1)
    state = extract_state(f"https://{CANONICAL_HOST}{INDEX_PATH}", ambiguous, ambiguous.encode(), date(2026, 8, 31))
    vacancy = next(x for x in state.references if x.signal_class == "VACANCY_RELEASE_REFERENCE")
    assert vacancy.review_state == "HOLD" and "ambiguous" in (vacancy.hold_reason or "")

    future = sample.replace("31/07/2026", "31/12/2026", 1)
    state = extract_state(f"https://{CANONICAL_HOST}{INDEX_PATH}", future, future.encode(), date(2026, 8, 31))
    vacancy = next(x for x in state.references if x.signal_class == "VACANCY_RELEASE_REFERENCE")
    assert vacancy.review_state == "HOLD" and vacancy.publication_date is None

    external = sample.replace(
        "https://www.anofm.ro/valcea/locuri-de-munca-vacante-la-nivel-judetean-si-in-reteaua-eures-31-iulie-2026/",
        "https://example.com/valcea/jobs/",
        1,
    )
    state = extract_state(f"https://{CANONICAL_HOST}{INDEX_PATH}", external, external.encode(), date(2026, 8, 31))
    vacancy = next(x for x in state.references if x.signal_class == "VACANCY_RELEASE_REFERENCE")
    assert vacancy.review_state == "HOLD" and vacancy.article_url == "HELD_OFF_SURFACE_URL"

    no_articles = sample.replace("<article>", "<div>").replace("</article>", "</div>")
    state = extract_state(f"https://{CANONICAL_HOST}{INDEX_PATH}", no_articles, no_articles.encode(), date(2026, 8, 31))
    assert state.state == "HOLD" and not state.references

    try:
        validate_index_url("https://www.anofm.ro/valcea/categorie/comunicate-de-presa/?page=2")
    except ValueError:
        pass
    else:
        raise AssertionError("query-bearing index URL must fail closed")

    try:
        extract_state(f"https://{CANONICAL_HOST}{INDEX_PATH}", "<html>captcha</html>", b"captcha", date(2026, 8, 31))
    except ValueError:
        pass
    else:
        raise AssertionError("placeholder page must fail closed")

    print("AJOFM Vâlcea labor-market index self-test: PASS")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=f"https://{CANONICAL_HOST}{INDEX_PATH}")
    parser.add_argument("--as-of", help="YYYY-MM-DD; defaults to current UTC date")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        run_self_test()
        return
    as_of = date.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc).date()
    final_url, html_text, payload = fetch_html(args.url)
    state = extract_state(final_url, html_text, payload, as_of)
    validate_boundaries(state)
    print(json.dumps(asdict(state), ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
