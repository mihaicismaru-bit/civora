#!/usr/bin/env python3
"""Evidence-first CCI Vâlcea signal adapter.

The Camera de Comerț și Industrie Vâlcea site mixes genuinely local items with
national and international business opportunities. This adapter therefore
never equates "published by CCI Vâlcea" with "local event".

Boundary:
- discovery is limited to the official Noutăți / Evenimente category surfaces;
- direct article URLs must remain on the official HTTPS host after redirects;
- CMS publication metadata is kept separate from event date/time evidence;
- locality is explicit and conservative: local, external, or hold;
- official-site images are provenance-only and carry no reuse permission;
- output is signal-only, non-persistent and has no publication authority.
"""
from __future__ import annotations

import argparse
import hashlib
import html.parser
import json
import re
import ssl
import unicodedata
from datetime import date
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

SOURCE_ID = "signal-cci-valcea"
SOURCE_NAME = "Camera de Comerț și Industrie Vâlcea"
SOURCE_TIER = "T1B"
SOURCE_KIND = "ECONOMY_CHAMBER"
OFFICIAL_HOSTS = {"ccivl.ro", "www.ccivl.ro"}
CATEGORY_PATHS = {"/category/noutati/", "/category/evenimente/"}
SOURCE_URLS = (
    "https://www.ccivl.ro/category/noutati/",
    "https://www.ccivl.ro/category/evenimente/",
)
USER_AGENT = "Mozilla/5.0 VÂLCEA-CLAR-CCI-Signal/1.0 (+https://valceaclar.ro/)"
MAX_BODY_BYTES = 2_000_000
MAX_PAGES = 8
GENERIC_MEDIA = {"logo.png", "logo-cci.png", "cropped-logo.png", "favicon.png"}
RESERVED_ROOTS = {
    "category", "tag", "author", "wp-admin", "wp-content", "wp-includes",
    "feed", "comments", "contact", "despre-noi", "servicii", "proiecte",
}

RO_MONTHS = {
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4,
    "mai": 5, "iunie": 6, "iulie": 7, "august": 8,
    "septembrie": 9, "octombrie": 10, "noiembrie": 11, "decembrie": 12,
}
MONTH_ALT = "|".join(RO_MONTHS)

# A bare "Vâlcea" is deliberately insufficient because it occurs in publisher chrome.
LOCAL_EVIDENCE = (
    "ramnicu valcea", "ramnicu-valcea", "judetul valcea", "jud. valcea",
    "municipiul ramnicu valcea", "in valcea, romania", "din judetul valcea",
)
EXTERNAL_VENUES = (
    "paris", "bruxelles", "brussels", "viena", "vienna", "istanbul", "ankara",
    "budapesta", "budapest", "berlin", "munchen", "münchen", "madrid",
    "barcelona", "lisabona", "londra", "london", "roma", "rome", "milano",
    "milan", "kenya", "nairobi", "elgeyo marakwet",
)
EXTERNAL_CONTEXT = (
    "international business summit", "international trade", "targ international",
    "târg internațional", "expozitional paris", "expozițional paris",
)

EVENT_CONTEXT_DATE_RE = re.compile(
    rf"(?:\b(?:in|în)\s+data\s+de|\bpe|\bva\s+avea\s+loc(?:\s+in|\s+în)?|\bse\s+desfasoara(?:\s+in|\s+în)?|\bse\s+desfășoară(?:\s+in|\s+în)?)"
    rf"\s+([0-3]?\d)\s+({MONTH_ALT})\s+((?:20)\d{{2}})"
    r"(?:\s*,?\s*(?:de\s+la\s+)?(?:ora|orele)\s+([0-2]?\d[:.][0-5]\d))?",
    re.IGNORECASE,
)
NUMERIC_CONTEXT_DATE_RE = re.compile(
    r"(?:\b(?:in|în)\s+data\s+de|\bpe)\s+([0-3]?\d)[./]([01]?\d)[./]((?:20)\d{2})"
    r"(?:\s*(?:de\s+la\s+)?(?:ora|orele)\s+([0-2]?\d[:.][0-5]\d))?",
    re.IGNORECASE,
)
EXPLICIT_RANGE_RE = re.compile(
    rf"\b([0-3]?\d)\s*(?:-|–|—)\s*([0-3]?\d)\s+({MONTH_ALT})\s+((?:20)\d{{2}})\b",
    re.IGNORECASE,
)


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", clean_text(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _official_https(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme.casefold() == "https"
        and parsed.hostname is not None
        and parsed.hostname.casefold() in OFFICIAL_HOSTS
        and not parsed.username
        and not parsed.password
    )


def normalize_category_url(value: str) -> str:
    text = clean_text(value)
    if not _official_https(text):
        raise ValueError("CCI category adapter requires official HTTPS host")
    parsed = urlsplit(text)
    path = re.sub(r"/+", "/", parsed.path or "/")
    if not path.endswith("/"):
        path += "/"
    base = None
    page = None
    for candidate in CATEGORY_PATHS:
        if path == candidate:
            base = candidate
            break
        prefix = candidate + "page/"
        if path.startswith(prefix):
            suffix = path[len(prefix):]
            if re.fullmatch(r"[1-9]\d*/", suffix):
                base = candidate
                page = suffix
                break
    if base is None:
        raise ValueError("CCI adapter refuses non-category discovery URL")
    normalized_path = base if page is None else base + "page/" + page
    return urlunsplit(("https", "www.ccivl.ro", normalized_path, "", ""))


def normalize_article_url(value: str, *, base_url: str = SOURCE_URLS[0]) -> str:
    joined = urljoin(base_url, clean_text(value))
    if not _official_https(joined):
        raise ValueError("CCI article adapter requires official HTTPS host")
    parsed = urlsplit(joined)
    path = re.sub(r"/+", "/", parsed.path or "/")
    if not path.endswith("/"):
        path += "/"
    segments = [part for part in path.split("/") if part]
    if len(segments) != 1:
        raise ValueError("CCI article adapter requires a single canonical root slug")
    slug = segments[0].casefold()
    if slug in RESERVED_ROOTS or slug.startswith("page"):
        raise ValueError("CCI adapter refuses reserved/root utility paths")
    return urlunsplit(("https", "www.ccivl.ro", "/" + segments[0] + "/", "", ""))


def normalize_media_url(value: str, *, base_url: str) -> str | None:
    joined = urljoin(base_url, clean_text(value))
    if not _official_https(joined):
        return None
    parsed = urlsplit(joined)
    path = re.sub(r"/+", "/", parsed.path or "/")
    filename = path.rsplit("/", 1)[-1].casefold()
    if not path.startswith("/wp-content/uploads/"):
        return None
    if filename in GENERIC_MEDIA or "logo" in filename:
        return None
    return urlunsplit(("https", "www.ccivl.ro", path, "", ""))


def _iso_date(day: str, month: str, year: str) -> str | None:
    try:
        return date(int(year), RO_MONTHS[fold(month)], int(day)).isoformat()
    except (KeyError, ValueError):
        return None


def _iso_numeric_date(day: str, month: str, year: str) -> str | None:
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def _normalize_time(value: str | None) -> str | None:
    return value.replace(".", ":") if value else None


def extract_event_window(text: str) -> dict[str, Any]:
    """Extract only explicit event dates; never fall back to CMS metadata."""
    visible = clean_text(text)
    for match in EVENT_CONTEXT_DATE_RE.finditer(visible):
        event_date = _iso_date(match.group(1), match.group(2), match.group(3))
        if event_date:
            return {
                "event_start_date": event_date,
                "event_end_date": event_date,
                "event_start_time": _normalize_time(match.group(4)),
                "temporal_evidence": clean_text(match.group(0)),
                "temporal_semantics": "EXPLICIT_EVENT_DATE_CONTEXT",
            }
    for match in NUMERIC_CONTEXT_DATE_RE.finditer(visible):
        event_date = _iso_numeric_date(match.group(1), match.group(2), match.group(3))
        if event_date:
            return {
                "event_start_date": event_date,
                "event_end_date": event_date,
                "event_start_time": _normalize_time(match.group(4)),
                "temporal_evidence": clean_text(match.group(0)),
                "temporal_semantics": "EXPLICIT_EVENT_DATE_CONTEXT",
            }
    for match in EXPLICIT_RANGE_RE.finditer(visible):
        start = _iso_date(match.group(1), match.group(3), match.group(4))
        end = _iso_date(match.group(2), match.group(3), match.group(4))
        if start and end and start <= end:
            return {
                "event_start_date": start,
                "event_end_date": end,
                "event_start_time": None,
                "temporal_evidence": clean_text(match.group(0)),
                "temporal_semantics": "EXPLICIT_EVENT_DATE_RANGE",
            }
    return {
        "event_start_date": None,
        "event_end_date": None,
        "event_start_time": None,
        "temporal_evidence": None,
        "temporal_semantics": "DATE_UNKNOWN_REQUIRES_EDITORIAL_VERIFICATION",
    }


def classify_locality(text: str) -> dict[str, Any]:
    value = fold(text)
    local_hits = sorted({needle for needle in LOCAL_EVIDENCE if needle in value})
    external_hits = sorted(
        {fold(needle) for needle in (*EXTERNAL_VENUES, *EXTERNAL_CONTEXT) if fold(needle) in value}
    )
    if local_hits and external_hits:
        classification = "HOLD_LOCALITY_CONFLICT"
    elif local_hits:
        classification = "LOCAL_VALCEA_EVENT"
    elif external_hits:
        classification = "EXTERNAL_BUSINESS_OPPORTUNITY"
    else:
        classification = "HOLD_LOCALITY_UNVERIFIED"
    return {
        "locality_classification": classification,
        "locality_local_evidence": local_hits,
        "locality_external_evidence": external_hits,
        "local_reader_claim_allowed": classification == "LOCAL_VALCEA_EVENT",
    }


class ArticleParser(html.parser.HTMLParser):
    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.article_depth = 0
        self.skip_depth = 0
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.capture_title = False
        self.cms_published_at: str | None = None
        self.images: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        attrs_dict = {str(k).casefold(): str(v or "") for k, v in attrs}
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "article":
            self.article_depth += 1
            return
        if not self.article_depth:
            return
        if tag in {"h1", "h2"} and not self.title_parts:
            self.capture_title = True
        if tag == "time" and not self.cms_published_at:
            raw = clean_text(attrs_dict.get("datetime"))
            if raw:
                self.cms_published_at = raw
        if tag == "img":
            for key in ("data-src", "data-lazy-src", "src"):
                candidate = normalize_media_url(attrs_dict.get(key, ""), base_url=self.page_url)
                if candidate:
                    if candidate not in self.images:
                        self.images.append(candidate)
                    break

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag in {"h1", "h2"}:
            self.capture_title = False
        if tag == "article" and self.article_depth:
            self.article_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.skip_depth or not self.article_depth:
            return
        text = clean_text(data)
        if not text:
            return
        self.parts.append(text)
        if self.capture_title:
            self.title_parts.append(text)


class ArchiveParser(html.parser.HTMLParser):
    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.article_depth = 0
        self.links: list[str] = []
        self.next_page_url: str | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        attrs_dict = {str(k).casefold(): str(v or "") for k, v in attrs}
        if tag == "article":
            self.article_depth += 1
            return
        if tag != "a":
            return
        href = attrs_dict.get("href", "")
        if self.article_depth:
            try:
                article = normalize_article_url(href, base_url=self.page_url)
            except ValueError:
                article = None
            if article and article not in self.links:
                self.links.append(article)
        rel = {part.casefold() for part in attrs_dict.get("rel", "").split()}
        cls = attrs_dict.get("class", "").casefold()
        if "next" in rel or "next" in cls:
            try:
                candidate = normalize_category_url(urljoin(self.page_url, href))
            except ValueError:
                candidate = None
            if candidate and candidate != normalize_category_url(self.page_url):
                self.next_page_url = candidate

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "article" and self.article_depth:
            self.article_depth -= 1


def parse_article_html(html_text: str, *, article_url: str, fetched_at: str | None = None) -> dict[str, Any]:
    canonical_url = normalize_article_url(article_url)
    parser = ArticleParser(canonical_url)
    parser.feed(html_text)
    visible = clean_text(" ".join(parser.parts))
    title = clean_text(" ".join(parser.title_parts))
    if not title or not visible:
        raise ValueError("CCI article lacks bounded visible article evidence")

    temporal = extract_event_window(visible)
    locality = classify_locality(visible)
    images = [
        {
            "url": url,
            "provenance": "OFFICIAL_CCI_ARTICLE_EMBED",
            "public_reuse_allowed": False,
            "rights_status": "UNKNOWN_REUSE_REQUIRES_EDITORIAL_CLEARANCE",
        }
        for url in parser.images
    ]
    return {
        "source_id": SOURCE_ID,
        "source_name": SOURCE_NAME,
        "source_tier": SOURCE_TIER,
        "source_kind": SOURCE_KIND,
        "article_url": canonical_url,
        "title": title,
        "cms_published_at": parser.cms_published_at,
        "cms_timestamp_semantics": (
            "SOURCE_CMS_METADATA_NOT_EVENT_TIME" if parser.cms_published_at else "CMS_TIMESTAMP_NOT_CAPTURED"
        ),
        **temporal,
        **locality,
        "media_candidates": images,
        "evidence": {
            "official_url": canonical_url,
            "fetched_at": fetched_at,
            "content_sha256": hashlib.sha256(html_text.encode("utf-8")).hexdigest(),
            "visible_article_text_sha256": hashlib.sha256(visible.encode("utf-8")).hexdigest(),
        },
        "lifecycle": "SIGNAL_ONLY_NEEDS_EDITORIAL_VERIFICATION",
        "editorial_verification_required": True,
        "publication_authority": "NONE",
        "public_projection": False,
        "auto_publication": False,
        "persistence_authority": "NONE",
        "fact_kernel_authority": "NONE",
    }


def parse_archive_html(html_text: str, *, archive_url: str) -> dict[str, Any]:
    canonical = normalize_category_url(archive_url)
    parser = ArchiveParser(canonical)
    parser.feed(html_text)
    return {
        "archive_url": canonical,
        "article_urls": parser.links,
        "next_page_url": parser.next_page_url,
        "lifecycle": "DISCOVERY_ONLY",
        "publication_authority": "NONE",
        "persistence_authority": "NONE",
    }


def _fetch_text(url: str, *, timeout: float = 20.0) -> tuple[str, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    context = ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:
        final_url = response.geturl()
        if not _official_https(final_url):
            raise ValueError("CCI adapter refuses redirect outside official HTTPS host")
        body = response.read(MAX_BODY_BYTES + 1)
    if len(body) > MAX_BODY_BYTES:
        raise ValueError("CCI response exceeds bounded body size")
    return body.decode("utf-8", errors="replace"), final_url


def fetch_article(url: str, *, fetched_at: str | None = None) -> dict[str, Any]:
    requested = normalize_article_url(url)
    html_text, final_url = _fetch_text(requested)
    canonical_final = normalize_article_url(final_url)
    if canonical_final != requested:
        raise ValueError("CCI article redirect changed canonical article identity")
    return parse_article_html(html_text, article_url=canonical_final, fetched_at=fetched_at)


def discover_archive(url: str, *, max_pages: int = MAX_PAGES) -> list[str]:
    if max_pages < 1 or max_pages > MAX_PAGES:
        raise ValueError("CCI archive discovery page bound invalid")
    current = normalize_category_url(url)
    seen_pages: set[str] = set()
    discovered: list[str] = []
    for _ in range(max_pages):
        if current in seen_pages:
            break
        seen_pages.add(current)
        html_text, final_url = _fetch_text(current)
        final_canonical = normalize_category_url(final_url)
        if final_canonical != current:
            raise ValueError("CCI archive redirect changed canonical discovery identity")
        parsed = parse_archive_html(html_text, archive_url=current)
        for article_url in parsed["article_urls"]:
            if article_url not in discovered:
                discovered.append(article_url)
        next_page = parsed["next_page_url"]
        if not next_page:
            break
        current = next_page
    return discovered


def _self_test() -> None:
    local_html = """
    <html><body><article>
      <h1>Workshop Informarea și Educarea Consumatorilor</h1>
      <time datetime="2026-03-17T09:00:00+02:00">17 mart. 2026</time>
      <p>Evenimentul va avea loc pe 23 martie 2026, ora 10:00 la FMMAE Râmnicu Vâlcea.</p>
      <img src="/wp-content/uploads/2026/03/workshop-consumatori.jpg">
    </article></body></html>
    """
    local = parse_article_html(
        local_html,
        article_url="https://www.ccivl.ro/workshop-informarea-si-educarea-consumatorilor/",
        fetched_at="2026-08-29T03:30:00Z",
    )
    assert local["locality_classification"] == "LOCAL_VALCEA_EVENT"
    assert local["local_reader_claim_allowed"] is True
    assert local["event_start_date"] == "2026-03-23"
    assert local["event_start_time"] == "10:00"
    assert local["cms_published_at"].startswith("2026-03-17")
    assert local["cms_published_at"] != local["event_start_date"]
    assert local["media_candidates"][0]["public_reuse_allowed"] is False

    external_html = """
    <html><body><article>
      <h1>SIAL Paris 2026</h1>
      <time datetime="2026-06-30">30 iun. 2026</time>
      <p>17 – 21 OCTOMBRIE 2026, Centrul Expozițional Paris Nord Villepinte.</p>
    </article></body></html>
    """
    external = parse_article_html(external_html, article_url="https://www.ccivl.ro/sial-paris-2026/")
    assert external["locality_classification"] == "EXTERNAL_BUSINESS_OPPORTUNITY"
    assert external["local_reader_claim_allowed"] is False
    assert external["event_start_date"] == "2026-10-17"
    assert external["event_end_date"] == "2026-10-21"

    ambiguous_html = """
    <html><body><article>
      <h1>Oportunități pentru IMM-uri</h1>
      <time datetime="2026-07-01">1 iul. 2026</time>
      <p>Camera invită firmele interesate la o sesiune de informare. Detaliile vor fi comunicate ulterior.</p>
    </article></body></html>
    """
    ambiguous = parse_article_html(ambiguous_html, article_url="https://www.ccivl.ro/oportunitati-pentru-imm-uri/")
    assert ambiguous["locality_classification"] == "HOLD_LOCALITY_UNVERIFIED"
    assert ambiguous["event_start_date"] is None

    conflict_html = """
    <html><body><article>
      <h1>Misiune economică</h1>
      <p>Companii din Râmnicu Vâlcea sunt invitate la o expoziție organizată la Paris.</p>
    </article></body></html>
    """
    conflict = parse_article_html(conflict_html, article_url="https://www.ccivl.ro/misiune-economica/")
    assert conflict["locality_classification"] == "HOLD_LOCALITY_CONFLICT"
    assert conflict["local_reader_claim_allowed"] is False

    archive_html = """
    <html><body>
      <article><h2><a href="/workshop-informarea-si-educarea-consumatorilor/">Workshop</a></h2></article>
      <article><h2><a href="https://www.ccivl.ro/sial-paris-2026/">SIAL</a></h2></article>
      <a class="next page-numbers" href="/category/evenimente/page/2/">Următoarea</a>
    </body></html>
    """
    archive = parse_archive_html(archive_html, archive_url=SOURCE_URLS[1])
    assert len(archive["article_urls"]) == 2
    assert archive["next_page_url"].endswith("/category/evenimente/page/2/")

    for bad in (
        "http://www.ccivl.ro/category/evenimente/",
        "https://evil.example/category/evenimente/",
        "https://www.ccivl.ro/wp-admin/",
    ):
        try:
            if "category" in bad:
                normalize_category_url(bad)
            else:
                normalize_article_url(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe URL accepted: {bad}")

    for result in (local, external, ambiguous, conflict):
        assert result["lifecycle"] == "SIGNAL_ONLY_NEEDS_EDITORIAL_VERIFICATION"
        assert result["publication_authority"] == "NONE"
        assert result["public_projection"] is False
        assert result["auto_publication"] is False
        assert result["persistence_authority"] == "NONE"
        assert result["fact_kernel_authority"] == "NONE"

    print("CCI Vâlcea evidence-first self-test: OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--article-url")
    parser.add_argument("--archive-url")
    parser.add_argument("--max-pages", type=int, default=1)
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        return 0
    if args.article_url:
        print(json.dumps(fetch_article(args.article_url), ensure_ascii=False, indent=2))
        return 0
    if args.archive_url:
        print(json.dumps(discover_archive(args.archive_url, max_pages=args.max_pages), ensure_ascii=False, indent=2))
        return 0
    parser.error("use --self-test, --article-url or --archive-url")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
