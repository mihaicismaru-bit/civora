#!/usr/bin/env python3
"""Evidence-first CJ Vâlcea county-road works/restrictions signal adapter."""
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
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

SOURCE_ID = "signal-cj-valcea-drumuri"
SOURCE_NAME = "Consiliul Județean Vâlcea — drumuri județene"
SOURCE_URL = "https://cjvalcea.ro/categorie/consiliul-judetean-la-zi/"
SOURCE_TIER = "T1"
SOURCE_KIND = "LOCAL_GOVERNMENT_OFFICIAL_ROAD_INFRASTRUCTURE_NEWS"
ALLOWED_HOST = "cjvalcea.ro"
INDEX_PATH = "/categorie/consiliul-judetean-la-zi/"
USER_AGENT = "Mozilla/5.0 VÂLCEA-CLAR-CJ-Roadworks/1.0 (+https://valceaclar.ro/)"
MAX_INDEX_BYTES, MAX_ARTICLE_BYTES, TIMEOUT_SECONDS, DEFAULT_ARTICLE_LIMIT = 3_000_000, 2_000_000, 20, 16

ARTICLE_RE = re.compile(r"^/(20\d{2})/(0[1-9]|1[0-2])/([0-2]\d|3[01])/[^/?#]+/$")
ROUTE_RE = re.compile(r"\bDJ\s*([0-9]{3}\s*[A-Z]?)\b", re.I)
NUMERIC_DATE_RE = re.compile(r"\b([0-3]?\d)[./-]([01]?\d)[./-]((?:20)\d{2})\b")
MONTHS = {"ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4, "mai": 5, "iunie": 6,
          "iulie": 7, "august": 8, "septembrie": 9, "octombrie": 10, "noiembrie": 11, "decembrie": 12}
ROMANIAN_DATE_RE = re.compile(rf"\b([0-3]?\d)\s+({'|'.join(MONTHS)})\s+((?:20)\d{{2}})\b", re.I)
PLACEHOLDER_TERMS = ("enable javascript", "access denied", "captcha", "robot",
                     "temporarily unavailable", "service unavailable", "cloudflare")
SESSION_TITLE_HINTS = ("sedinta ordinara", "sedinta extraordinara", "sedinta de consiliu",
                       "ordine de zi", "proces-verbal", "proces verbal", "minuta")
CLOSURE_HINTS = ("inchidem temporar circulatia", "inchidere temporara", "inchiderea circulatiei",
                 "circulatia va fi inchisa", "circulatia este inchisa", "inchis circulatiei", "inchisa circulatiei")
RESTRICTION_HINTS = ("restrictii de circulatie", "restrictie de circulatie", "restrictionarea circulatiei",
                     "circulatia va fi restrictionata", "circulatia este restrictionata", "trafic restrictionat")
WORKS_HINTS = ("asfaltam", "asfaltare", "asfaltic", "modernizam", "modernizare", "reabilitam", "reabilitare",
               "lucrari", "se lucreaza", "interventii", "refacere", "reparatii", "drumuri si poduri")
INFRA_HINTS = ("drum judetean", "drumurile judetene", "pod", "poduri", "carosabil", "infrastructura rutiera")


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", clean(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _path(path: str) -> str:
    value = re.sub(r"/+", "/", unquote(path or "/"))
    return value if value.startswith("/") else "/" + value


def official_index_url(url: str) -> bool:
    p = urlsplit(clean(url))
    return bool(p.scheme.casefold() == "https" and p.hostname and p.hostname.casefold() == ALLOWED_HOST
                and not p.username and not p.password and _path(p.path).rstrip("/") == INDEX_PATH.rstrip("/")
                and not p.query and not p.fragment)


def normalize_article_url(value: str, *, base_url: str = SOURCE_URL) -> str | None:
    p = urlsplit(urljoin(base_url, clean(value)))
    if not (p.scheme.casefold() == "https" and p.hostname and p.hostname.casefold() == ALLOWED_HOST
            and not p.username and not p.password and not p.query and not p.fragment):
        return None
    path = _path(p.path)
    if not path.endswith("/"):
        path += "/"
    if not ARTICLE_RE.fullmatch(path):
        return None
    return urlunsplit(("https", ALLOWED_HOST, path, "", ""))


def article_url_date(url: str) -> str | None:
    normalized = normalize_article_url(url)
    match = ARTICLE_RE.fullmatch(urlsplit(normalized).path) if normalized else None
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
    except ValueError:
        return None


def placeholder(html_text: str) -> bool:
    visible = fold(re.sub(r"<[^>]+>", " ", html_text))[:5000]
    return any(fold(term) in visible for term in PLACEHOLDER_TERMS)


class IndexParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.url: str | None = None
        self.parts: list[str] = []
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip += 1
        elif not self.skip and tag == "a" and self.url is None:
            url = normalize_article_url(dict(attrs).get("href") or "")
            if url:
                self.url, self.parts = url, []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"} and self.skip:
            self.skip -= 1
        elif not self.skip and tag == "a" and self.url:
            title = clean(" ".join(self.parts))
            if title:
                self.links.append({"url": self.url, "title": title})
            self.url, self.parts = None, []

    def handle_data(self, data: str) -> None:
        if not self.skip and self.url:
            value = clean(data)
            if value:
                self.parts.append(value)


class ArticleParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = self.article_depth = self.h1_depth = 0
        self.article_seen = False
        self.tokens: list[str] = []
        self.times: list[str] = []
        self.h1: list[str] = []
        self.title = ""

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip += 1
        elif not self.skip and tag == "article":
            self.article_depth += 1
            self.article_seen = True
        elif not self.skip and self.article_depth and tag == "h1":
            self.h1_depth += 1
        elif not self.skip and self.article_depth and tag == "time":
            value = clean(dict(attrs).get("datetime") or "")
            if value:
                self.times.append(value)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"} and self.skip:
            self.skip -= 1
        elif not self.skip and tag == "h1" and self.article_depth and self.h1_depth:
            self.h1_depth -= 1
            if self.h1 and not self.title:
                self.title = clean(" ".join(self.h1))
        elif not self.skip and tag == "article" and self.article_depth:
            self.article_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.skip or not self.article_depth:
            return
        value = clean(data)
        if value:
            self.tokens.append(value)
            if self.h1_depth:
                self.h1.append(value)


def dates_in_text(text: str) -> list[str]:
    values: list[str] = []
    for match in ROMANIAN_DATE_RE.finditer(fold(text)):
        try:
            value = date(int(match.group(3)), MONTHS[match.group(2).casefold()], int(match.group(1))).isoformat()
        except ValueError:
            continue
        if value not in values:
            values.append(value)
    for match in NUMERIC_DATE_RE.finditer(text):
        try:
            value = date(int(match.group(3)), int(match.group(2)), int(match.group(1))).isoformat()
        except ValueError:
            continue
        if value not in values:
            values.append(value)
    return values


def publication_date_status(parser: ArticleParser, url_date: str) -> str:
    for value in parser.times:
        match = re.match(r"^(20\d{2})-(\d{2})-(\d{2})", value)
        if not match:
            continue
        try:
            if date(*map(int, match.groups())).isoformat() == url_date:
                return "URL_PATH_AND_ARTICLE_TIME_MATCH"
        except ValueError:
            pass
    if url_date in dates_in_text(" ".join(parser.tokens[:30])):
        return "URL_PATH_AND_VISIBLE_ARTICLE_DATE_MATCH"
    return "HOLD_PUBLICATION_DATE_NOT_CONFIRMED_IN_ARTICLE"


def route_refs(text: str) -> list[str]:
    values: list[str] = []
    for match in ROUTE_RE.finditer(text):
        value = "DJ " + re.sub(r"\s+", "", match.group(1)).upper()
        if value not in values:
            values.append(value)
    return values


def classify(title: str, text: str, routes: list[str], date_status: str) -> str:
    if not routes or not date_status.startswith("URL_PATH_AND_") or any(h in fold(title) for h in SESSION_TITLE_HINTS):
        return "HOLD"
    value = fold(text)
    for signal_class, hints in (
        ("ROAD_CLOSURE_NOTICE", CLOSURE_HINTS),
        ("ROAD_RESTRICTION_NOTICE", RESTRICTION_HINTS),
        ("ROADWORKS_NOTICE", WORKS_HINTS),
        ("ROAD_INFRASTRUCTURE_UPDATE", INFRA_HINTS),
    ):
        if any(hint in value for hint in hints):
            return signal_class
    return "HOLD"


def signal_id(url: str, title: str) -> str:
    return "cj-road-" + hashlib.sha256("\0".join([SOURCE_ID, url, fold(title)]).encode()).hexdigest()[:20]


def extract_article_signal(html_text: str, *, article_url: str, discovered_title: str = "") -> dict[str, Any]:
    url = normalize_article_url(article_url)
    if not url:
        raise ValueError(f"CJ roadworks adapter refused unexpected article URL: {article_url}")
    if placeholder(html_text):
        raise ValueError("CJ roadworks article returned a placeholder/challenge response")
    url_date = article_url_date(url)
    if not url_date:
        raise ValueError("CJ roadworks article URL has no valid publication date")
    parser = ArticleParser()
    parser.feed(html_text)
    parser.close()
    if not parser.article_seen:
        return {"signal_id": signal_id(url, discovered_title or url), "source_id": SOURCE_ID, "article_url": url,
                "signal_class": "HOLD", "lifecycle": "HOLD_ARTICLE_SCOPE_NOT_FOUND", "publication_date": url_date,
                "publication_date_status": "HOLD_ARTICLE_SCOPE_NOT_FOUND", "route_refs": [],
                "publication_authority": "NONE", "public_projection": False, "current_status_claim_allowed": False}
    title = parser.title or clean(discovered_title)
    text = clean(" ".join(parser.tokens))
    date_status = publication_date_status(parser, url_date)
    routes = route_refs(text)
    signal_class = classify(title, text, routes, date_status)
    return {
        "signal_id": signal_id(url, title), "source_id": SOURCE_ID, "source_name": SOURCE_NAME,
        "source_url": SOURCE_URL, "source_surface": "categorie/consiliul-judetean-la-zi",
        "source_tier": SOURCE_TIER, "source_kind": SOURCE_KIND, "article_url": url,
        "article_locator_sha256": hashlib.sha256(url.encode()).hexdigest(), "title": title,
        "title_sha256": hashlib.sha256(title.encode()).hexdigest(), "summary_excerpt": text[:900] or None,
        "signal_class": signal_class, "route_refs": routes, "publication_date": url_date,
        "publication_date_status": date_status, "publication_date_is_not_operational_status": True,
        "current_status_claim_allowed": False, "current_closure_claim_allowed": False,
        "current_restriction_claim_allowed": False, "operational_status_inference_allowed": False,
        "operational_end_inference_allowed": False, "article_body_ingest_scope": "OFFICIAL_ARTICLE_TEXT_ONLY",
        "document_attachment_parse_allowed": False, "media_candidates": [], "media_public_reuse_allowed": False,
        "photo_rights_inferred": False, "publication_authority": "NONE", "public_projection": False,
        "auto_publication": False, "persistence_allowed": False, "fact_kernel_authority": False,
        "source_recheck_required": True,
        "lifecycle": "SIGNAL_ONLY_SOURCE_RECHECK_REQUIRED" if signal_class != "HOLD"
                     else "HOLD_INSUFFICIENT_OR_AMBIGUOUS_ROAD_SIGNAL",
        "provenance": {"authority": "CJ_VALCEA_OFFICIAL_WEBSITE", "retrieval_surface": SOURCE_URL,
                       "article_scope_basis": "HTML_ARTICLE_ELEMENT_ONLY", "publication_date_basis": date_status,
                       "route_basis": "EXPLICIT_OFFICIAL_ARTICLE_TEXT_ONLY",
                       "classification_basis": "EXPLICIT_OFFICIAL_ARTICLE_TEXT_ONLY"},
    }


def discover_articles(html_text: str, *, final_url: str = SOURCE_URL) -> list[dict[str, str]]:
    if not official_index_url(final_url):
        raise ValueError(f"CJ roadworks adapter refused unexpected index URL: {final_url}")
    if placeholder(html_text):
        raise ValueError("CJ roadworks index returned a placeholder/challenge response")
    parser = IndexParser()
    parser.feed(html_text)
    parser.close()
    rows, seen = [], set()
    for row in parser.links:
        if row["url"] not in seen:
            seen.add(row["url"])
            rows.append(row)
    return rows


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise ValueError(f"CJ roadworks adapter refused redirect: {newurl}")


def fetch_html(url: str, *, max_bytes: int) -> tuple[str, str, str]:
    if not (official_index_url(url) or normalize_article_url(url) == url):
        raise ValueError(f"CJ roadworks fetch refused URL outside canonical surfaces: {url}")
    opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        final_url = str(response.geturl())
        valid = official_index_url(final_url) if url == SOURCE_URL else normalize_article_url(final_url) == url
        if not valid:
            raise ValueError(f"CJ roadworks adapter refused unexpected final URL: {final_url}")
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ValueError("CJ roadworks response exceeds bounded body limit")
        ctype = str(response.headers.get("Content-Type") or "")
        if "html" not in ctype.casefold() and b"<html" not in body[:2000].lower():
            raise ValueError(f"CJ roadworks source did not return HTML: {ctype or 'unknown'}")
        charset = response.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace"), final_url, hashlib.sha256(body).hexdigest()


def build_live_document(*, article_limit: int = DEFAULT_ARTICLE_LIMIT) -> dict[str, Any]:
    index_html, final_url, index_sha = fetch_html(SOURCE_URL, max_bytes=MAX_INDEX_BYTES)
    discovered = discover_articles(index_html, final_url=final_url)[:max(1, article_limit)]
    signals, holds = [], []
    for row in discovered:
        try:
            article_html, article_final, _ = fetch_html(row["url"], max_bytes=MAX_ARTICLE_BYTES)
            signals.append(extract_article_signal(article_html, article_url=article_final, discovered_title=row["title"]))
        except Exception as exc:
            holds.append({"article_locator_sha256": hashlib.sha256(row["url"].encode()).hexdigest(),
                          "lifecycle": "HOLD_ARTICLE_FETCH_FAILED", "reason": clean(exc)})
    return {"schema_version": "1.0", "product": "VÂLCEA CLAR CJ Vâlcea county-road signals",
            "source_id": SOURCE_ID, "source_url": SOURCE_URL, "source_content_sha256": index_sha,
            "discovered_article_count": len(discovered), "signal_count": len(signals),
            "fetch_holds": holds, "signals": signals,
            "policy": {"publication_authority": "NONE", "signal_only": True, "public_projection": False,
                       "auto_publication": False, "persistence_allowed": False, "fact_kernel_authority": False,
                       "current_status_claim_allowed": False, "current_closure_claim_allowed": False,
                       "current_restriction_claim_allowed": False, "operational_status_inference_allowed": False,
                       "document_attachment_parse_allowed": False, "media_public_reuse_allowed": False}}


def fixture(title: str, pub_date: str, body: str, *, dt: str | None = None) -> str:
    attr = f' datetime="{dt}"' if dt else ""
    return f"<html><body><article><h1>{title}</h1><time{attr}>{pub_date}</time><div>{body}</div></article></body></html>"


def self_test() -> None:
    index = """<a href="/2026/07/31/continuam-sa-modernizam-drumurile-judetene-kilometru-cu-kilometru/">Modernizăm</a>
    <a href="https://evil.example/2026/07/31/fake/">Fake</a><a href="/storage/road.pdf">PDF</a>
    <a href="/2026/07/31/continuam-sa-modernizam-drumurile-judetene-kilometru-cu-kilometru/">Dup</a>"""
    rows = discover_articles(index)
    assert len(rows) == 1
    works = extract_article_signal(
        fixture("Continuăm să modernizăm drumurile județene", "31.07.2026",
                "Se toarnă un nou covor asfaltic pe DJ 676D. Se lucrează pe raza comunei Alunu.",
                dt="2026-07-31T09:00:00+03:00"), article_url=rows[0]["url"])
    assert works["signal_class"] == "ROADWORKS_NOTICE" and works["route_refs"] == ["DJ 676D"]
    assert works["current_status_claim_allowed"] is False and works["publication_authority"] == "NONE"
    closure = extract_article_signal(
        fixture("Închidem temporar circulația pe DJ 658", "10.07.2025",
                "Circulația va fi închisă temporar pe DJ 658 pentru executarea unor lucrări."),
        article_url="https://cjvalcea.ro/2025/07/10/inchidem-temporar-circulatia-pe-dj-658/")
    assert closure["signal_class"] == "ROAD_CLOSURE_NOTICE" and closure["current_closure_claim_allowed"] is False
    restriction = extract_article_signal(
        fixture("Restricții de circulație pe DJ 677A", "28.06.2026",
                "Circulația este restricționată pe DJ 677A pentru lucrări."),
        article_url="https://cjvalcea.ro/2026/06/28/restrictii-de-circulatie-pe-dj-677a/")
    assert restriction["signal_class"] == "ROAD_RESTRICTION_NOTICE"
    session = extract_article_signal(
        fixture("Sedinta extraordinara – 11.08.2026", "11.08.2026",
                "Proiect privind modernizare DJ 677A și programul lucrărilor."),
        article_url="https://cjvalcea.ro/2026/08/11/sedinta-extraordinara-11-08-2026/")
    assert session["signal_class"] == "HOLD"
    mismatch = extract_article_signal(
        fixture("Asfaltăm DJ 676 B", "29.06.2026", "Lucrări de asfaltare pe DJ 676 B."),
        article_url="https://cjvalcea.ro/2026/06/28/asfaltam-dj-676-b/")
    assert mismatch["signal_class"] == "HOLD" and mismatch["publication_date_status"].startswith("HOLD_")
    no_scope = extract_article_signal("<h1>Asfaltăm DJ 676 B</h1><p>28.06.2026</p>",
                                      article_url="https://cjvalcea.ro/2026/06/28/asfaltam-dj-676-b/")
    assert no_scope["lifecycle"] == "HOLD_ARTICLE_SCOPE_NOT_FOUND"
    assert normalize_article_url("https://evil.example/2026/06/28/x/") is None
    assert normalize_article_url("http://cjvalcea.ro/2026/06/28/x/") is None
    assert normalize_article_url("https://cjvalcea.ro/storage/road.pdf") is None
    assert not official_index_url("https://cjvalcea.ro/categorie/anunturi/")
    assert route_refs("DJ676D, DJ 677 A și DN7") == ["DJ 676D", "DJ 677A"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--article-limit", type=int, default=DEFAULT_ARTICLE_LIMIT)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("CJ Vâlcea roadworks signal adapter self-test: OK")
    elif args.live:
        print(json.dumps(build_live_document(article_limit=args.article_limit), ensure_ascii=False, indent=2))
    else:
        parser.error("choose --self-test or --live")


if __name__ == "__main__":
    main()
