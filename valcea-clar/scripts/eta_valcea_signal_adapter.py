#!/usr/bin/env python3
"""Evidence-first ETA Râmnicu Vâlcea operational signal adapter.

Boundaries:
- official eta-bus.ro HTTPS pages only;
- `/comunicate` is the discovery surface; direct `/comunicate/<slug>` pages are evidence;
- static stop timetables (`/s/<id>`) are never interpreted as live service status;
- CMS publication time is kept separate from explicitly stated effective dates;
- images are provenance-only and carry no public-reuse permission;
- output is signal-only: no Fact Kernel, persistence, Writer or publication authority.
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

SOURCE_ID = "signal-eta-valcea"
SOURCE_NAME = "ETA S.A. Râmnicu Vâlcea"
SOURCE_URL = "https://eta-bus.ro/comunicate"
SOURCE_TIER = "T1"
SOURCE_KIND = "PUBLIC_TRANSPORT"
OFFICIAL_HOSTS = {"eta-bus.ro", "www.eta-bus.ro"}
USER_AGENT = "Mozilla/5.0 VÂLCEA-CLAR-ETA-Signal/1.0 (+https://valceaclar.ro/)"
MAX_BODY_BYTES = 2_000_000
DEFAULT_LIMIT = 20

RO_MONTHS = {
    "ian": 1, "ianuarie": 1,
    "feb": 2, "februarie": 2,
    "mar": 3, "martie": 3,
    "apr": 4, "aprilie": 4,
    "mai": 5,
    "iun": 6, "iunie": 6,
    "iul": 7, "iulie": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "septembrie": 9,
    "oct": 10, "octombrie": 10,
    "nov": 11, "noiembrie": 11,
    "dec": 12, "decembrie": 12,
}

NUMERIC_DATE_RE = re.compile(r"\b([0-3]?\d)[./-]([01]?\d)[./-]((?:20)\d{2})\b")
NUMERIC_RANGE_RE = re.compile(
    r"\b([0-3]?\d)[./]([01]?\d)[./]((?:20)\d{2})\s*(?:-|–|—)\s*"
    r"([0-3]?\d)[./]([01]?\d)[./]((?:20)\d{2})\b"
)
CMS_DATE_RE = re.compile(
    r"\bPublicat\s+la\s*:\s*([0-3]?\d)\s+([A-Za-zĂÂÎȘŞȚŢăâîșşțţ]+)\s+((?:20)\d{2})\b",
    re.IGNORECASE,
)
TIME_RE = re.compile(r"\b(?:ora|orele)\s+([0-2]?\d[:.][0-5]\d)\b", re.IGNORECASE)
MONTH_YEAR_RE = re.compile(
    r"\b(?:incepand|începând)\s+cu\s+luna\s+([A-Za-zĂÂÎȘŞȚŢăâîșşțţ]+)\s+((?:20)\d{2})\b",
    re.IGNORECASE,
)

IRRELEVANT_HINTS = (
    "vanzare", "vânzare", "licitatie", "licitație", "achizitie", "achiziție",
    "servicii de paza", "servicii de pază",
)
FARE_ACCESS_HINTS = (
    "tarif", "bilet", "abonament", "gratuit", "gratuitate", "facilitat",
    "pensionar", "elev", "donator", "titlu de calatorie", "titlu de călătorie",
)
SCHEDULE_HINTS = (
    "orar", "program de circulatie", "program de circulație", "traseu", "statie",
    "stație", "plecare", "sosire", "circula", "circulă",
)
CHANGE_HINTS = (
    "incepand", "începând", "modific", "temporar", "suspend", "devia",
    "restriction", "restricț", "nu circul", "relua", "prelung", "schimb",
)
SERVICE_HINTS = (
    "anomalii", "upgrade", "indisponibil", "intrerup", "întrerup", "afisarea informatiilor",
    "afișarea informațiilor", "panouri", "serviciu", "functionare", "funcționare",
)


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", clean_text(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _official_https(url: str) -> bool:
    p = urlsplit(url)
    return (
        p.scheme.casefold() == "https"
        and p.hostname is not None
        and p.hostname.casefold() in OFFICIAL_HOSTS
        and not p.username
        and not p.password
    )


def normalize_archive_url(value: str) -> str:
    text = clean_text(value)
    if not _official_https(text):
        raise ValueError("ETA adapter requires official HTTPS host")
    p = urlsplit(text)
    path = re.sub(r"/+", "/", p.path or "/").rstrip("/")
    if path != "/comunicate":
        raise ValueError("ETA discovery is restricted to /comunicate")
    return "https://eta-bus.ro/comunicate"


def normalize_notice_url(value: str, *, base_url: str = SOURCE_URL) -> str:
    joined = urljoin(base_url.rstrip("/") + "/", clean_text(value))
    if not _official_https(joined):
        raise ValueError("ETA notice requires official HTTPS host")
    p = urlsplit(joined)
    path = re.sub(r"/+", "/", p.path or "/").rstrip("/")
    if path == "/comunicate" or not re.fullmatch(r"/comunicate/[^/]+", path):
        raise ValueError("ETA notice requires direct /comunicate/<slug> URL")
    return urlunsplit(("https", "eta-bus.ro", path, "", ""))


def normalize_media_url(value: str, *, base_url: str) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    joined = urljoin(base_url, text)
    if not _official_https(joined):
        return None
    p = urlsplit(joined)
    path = re.sub(r"/+", "/", p.path or "/")
    if not re.search(r"\.(?:jpe?g|png|webp)(?:$|\?)", path, re.IGNORECASE):
        return None
    return urlunsplit(("https", "eta-bus.ro", path, "", ""))


def _iso_date(day: str, month: str, year: str) -> str | None:
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def _word_date(day: str, month_word: str, year: str) -> str | None:
    key = fold(month_word).rstrip(".")
    month = RO_MONTHS.get(key)
    if not month:
        return None
    return _iso_date(day, str(month), year)


class VisibleParser(html.parser.HTMLParser):
    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.skip_depth = 0
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.in_h1 = 0
        self.links: list[tuple[str, str]] = []
        self.capture_href: str | None = None
        self.capture_parts: list[str] = []
        self.image_url: str | None = None
        self.meta_published_at: str | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        ad = {str(k).casefold(): str(v or "") for k, v in attrs}
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "h1":
            self.in_h1 += 1
        elif tag == "a":
            self.capture_href = ad.get("href", "")
            self.capture_parts = []
        elif tag == "meta":
            prop = ad.get("property", "").casefold()
            name = ad.get("name", "").casefold()
            if prop in {"og:image", "twitter:image"} or name in {"og:image", "twitter:image"}:
                self.image_url = self.image_url or normalize_media_url(ad.get("content", ""), base_url=self.page_url)
            if prop == "article:published_time" or name == "article:published_time":
                self.meta_published_at = clean_text(ad.get("content"))
        elif tag == "img" and not self.image_url:
            for key in ("data-src", "data-lazy-src", "src"):
                media = normalize_media_url(ad.get(key, ""), base_url=self.page_url)
                if media:
                    self.image_url = media
                    break

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag == "h1" and self.in_h1:
            self.in_h1 -= 1
        elif tag == "a" and self.capture_href is not None:
            self.links.append((self.capture_href, clean_text(" ".join(self.capture_parts))))
            self.capture_href = None
            self.capture_parts = []

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = clean_text(data)
        if not text:
            return
        self.parts.append(text)
        if self.in_h1:
            self.title_parts.append(text)
        if self.capture_href is not None:
            self.capture_parts.append(text)

    @property
    def visible_text(self) -> str:
        return clean_text(" ".join(self.parts))

    @property
    def title(self) -> str:
        return clean_text(" ".join(self.title_parts))


def parse_archive(html_text: str) -> list[dict[str, str]]:
    parser = VisibleParser(SOURCE_URL)
    parser.feed(html_text)
    parser.close()
    seen: set[str] = set()
    rows: list[dict[str, str]] = []
    for href, anchor in parser.links:
        try:
            url = normalize_notice_url(href, base_url=SOURCE_URL)
        except ValueError:
            continue
        if url in seen:
            continue
        title = clean_text(anchor)
        if not title or fold(title) in {"citeste mai mult", "read more"}:
            continue
        seen.add(url)
        rows.append({"article_url": url, "title": title})
    return rows


def parse_publication_date(text: str, meta_value: str | None = None) -> tuple[str | None, str | None]:
    match = CMS_DATE_RE.search(text)
    if match:
        value = _word_date(match.group(1), match.group(2), match.group(3))
        if value:
            return value, "EXPLICIT_VISIBLE_CMS_DATE"
    meta = clean_text(meta_value)
    if meta and re.match(r"^20\d{2}-[01]\d-[0-3]\d(?:T|$)", meta):
        return meta, "ARTICLE_PUBLISHED_TIME_SOURCE_METADATA"
    return None, None


def extract_effective_window(text: str) -> dict[str, Any]:
    raw = clean_text(text)
    f = fold(raw)
    range_match = NUMERIC_RANGE_RE.search(raw)
    if range_match:
        start = _iso_date(range_match.group(1), range_match.group(2), range_match.group(3))
        end = _iso_date(range_match.group(4), range_match.group(5), range_match.group(6))
        if start and end and start <= end:
            time_match = TIME_RE.search(raw)
            return {
                "effective_start": start,
                "effective_end": end,
                "effective_time": time_match.group(1).replace(".", ":") if time_match else None,
                "effective_semantics": "EXPLICIT_VISIBLE_DATE_RANGE",
            }

    month_match = MONTH_YEAR_RE.search(raw)
    if month_match:
        month = RO_MONTHS.get(fold(month_match.group(1)).rstrip("."))
        year = int(month_match.group(2))
        if month:
            return {
                "effective_start": f"{year:04d}-{month:02d}-01",
                "effective_end": None,
                "effective_time": None,
                "effective_semantics": "EXPLICIT_VISIBLE_EFFECTIVE_MONTH_START",
            }

    date_matches = list(NUMERIC_DATE_RE.finditer(raw))
    if date_matches and any(token in f for token in ("incepand", "data de", "valabil", "perioada", "actualizarea")):
        m = date_matches[0]
        value = _iso_date(m.group(1), m.group(2), m.group(3))
        if value:
            time_match = TIME_RE.search(raw)
            return {
                "effective_start": value,
                "effective_end": None,
                "effective_time": time_match.group(1).replace(".", ":") if time_match else None,
                "effective_semantics": "EXPLICIT_VISIBLE_EFFECTIVE_DATE",
            }

    return {
        "effective_start": None,
        "effective_end": None,
        "effective_time": None,
        "effective_semantics": None,
    }


def _has_hint(combined: str, hint: str) -> bool:
    """Match a folded term/phrase only at a token boundary; suffix inflection is allowed."""
    needle = fold(hint)
    return bool(needle and re.search(r"(?<!\w)" + re.escape(needle), combined))


def classify_notice(title: str, text: str) -> tuple[str, list[str]]:
    combined = fold(f"{title} {text}")
    if any(_has_hint(combined, hint) for hint in IRRELEVANT_HINTS):
        return "HOLD", ["NON_PASSENGER_OPERATIONAL_NOTICE"]

    reasons: list[str] = []
    if any(_has_hint(combined, hint) for hint in FARE_ACCESS_HINTS):
        reasons.append("FARE_OR_PASSENGER_ACCESS_TERMS")
        return "FARE_OR_ACCESS_CHANGE", reasons

    has_schedule = any(_has_hint(combined, hint) for hint in SCHEDULE_HINTS)
    has_change = any(_has_hint(combined, hint) for hint in CHANGE_HINTS)
    if has_schedule and has_change:
        return "SCHEDULE_CHANGE", ["SCHEDULE_TERMS", "CHANGE_TERMS"]

    if has_change or any(_has_hint(combined, hint) for hint in SERVICE_HINTS):
        return "SERVICE_ALERT", ["OPERATIONAL_SERVICE_CHANGE_OR_DEGRADATION"]

    return "HOLD", ["NO_SUPPORTED_PASSENGER_IMPACT_CLASS"]


def build_signal(*, article_url: str, html_text: str, discovered_title: str | None = None) -> dict[str, Any]:
    url = normalize_notice_url(article_url)
    parser = VisibleParser(url)
    parser.feed(html_text)
    parser.close()

    title = parser.title or clean_text(discovered_title)
    visible = parser.visible_text
    if not title or not visible:
        raise ValueError("ETA notice requires visible title and evidence text")

    classification, reasons = classify_notice(title, visible)
    published_at, published_semantics = parse_publication_date(visible, parser.meta_published_at)
    effective = extract_effective_window(visible)
    evidence_sha = hashlib.sha256(html_text.encode("utf-8")).hexdigest()
    signal_basis = json.dumps(
        {
            "source_id": SOURCE_ID,
            "url": url,
            "title": title,
            "classification": classification,
            "effective": effective,
            "evidence_sha256": evidence_sha,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    signal_id = "eta-" + hashlib.sha256(signal_basis).hexdigest()[:24]

    image = None
    if parser.image_url:
        image = {
            "source_url": parser.image_url,
            "provenance_url": url,
            "rights_status": "UNKNOWN_REUSE_REQUIRES_EDITORIAL_CLEARANCE",
            "public_reuse_allowed": False,
        }

    return {
        "schema_version": "1.0",
        "signal_id": signal_id,
        "source": {
            "id": SOURCE_ID,
            "name": SOURCE_NAME,
            "tier": SOURCE_TIER,
            "kind": SOURCE_KIND,
            "canonical_url": SOURCE_URL,
        },
        "article_url": url,
        "title": title,
        "classification": classification,
        "classification_reasons": reasons,
        "cms_published_at": published_at,
        "cms_timestamp_semantics": published_semantics,
        **effective,
        "evidence": {
            "content_sha256": evidence_sha,
            "source_url": url,
            "source_host": "eta-bus.ro",
        },
        "visual_candidate": image,
        "boundaries": {
            "lifecycle": "SIGNAL_ONLY",
            "publication_authority": "NONE",
            "public_projection": False,
            "auto_publication": False,
            "persistence_authority": "NONE",
            "fact_kernel_authority": "NONE",
            "writer_authority": "NONE",
            "live_status_claim_allowed": False,
            "static_timetable_is_live_status": False,
        },
    }


def fetch_html(url: str) -> tuple[str, str]:
    if not _official_https(url):
        raise ValueError("ETA fetch requires official HTTPS host")
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    context = ssl.create_default_context()
    with urlopen(request, timeout=20, context=context) as response:
        final_url = response.geturl()
        if not _official_https(final_url):
            raise ValueError("ETA redirect left official host")
        body = response.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            raise ValueError("ETA response exceeds bounded body size")
        content_type = response.headers.get_content_type()
        if content_type not in {"text/html", "application/xhtml+xml"}:
            raise ValueError("ETA adapter requires HTML response")
        charset = response.headers.get_content_charset() or "utf-8"
        return final_url, body.decode(charset, errors="replace")


def discover_and_enrich(*, limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    final_url, archive_html = fetch_html(SOURCE_URL)
    normalize_archive_url(final_url)
    discovered = parse_archive(archive_html)[: max(0, limit)]
    out: list[dict[str, Any]] = []
    for row in discovered:
        article_url = row["article_url"]
        try:
            final_article_url, article_html = fetch_html(article_url)
            normalized_final = normalize_notice_url(final_article_url)
            if normalized_final != article_url:
                raise ValueError("ETA notice canonical URL changed after redirect")
            out.append(build_signal(article_url=article_url, html_text=article_html, discovered_title=row["title"]))
        except Exception as exc:
            out.append({
                "schema_version": "1.0",
                "source": {"id": SOURCE_ID, "name": SOURCE_NAME, "tier": SOURCE_TIER, "kind": SOURCE_KIND},
                "article_url": article_url,
                "title": row["title"],
                "classification": "HOLD",
                "hold_reason": f"ENRICHMENT_FAILED:{type(exc).__name__}",
                "boundaries": {
                    "lifecycle": "SIGNAL_ONLY",
                    "publication_authority": "NONE",
                    "public_projection": False,
                    "auto_publication": False,
                    "persistence_authority": "NONE",
                    "fact_kernel_authority": "NONE",
                    "writer_authority": "NONE",
                    "live_status_claim_allowed": False,
                    "static_timetable_is_live_status": False,
                },
            })
    return out


def self_test() -> None:
    archive = """
    <html><body>
      <a href="/comunicate/comunicat-aplicatie-skayo-avl/">Comunicat aplicație Skayo AVL</a>
      <a href="/comunicate/tarife-01-02-2026">Tarife de transport valabile începând cu data de 01/02/2026</a>
      <a href="/s/114">Str. Republicii Liceul Sanitar</a>
    </body></html>
    """
    rows = parse_archive(archive)
    assert [r["article_url"] for r in rows] == [
        "https://eta-bus.ro/comunicate/comunicat-aplicatie-skayo-avl",
        "https://eta-bus.ro/comunicate/tarife-01-02-2026",
    ]

    service_html = """
    <html><head><meta property="og:image" content="/images/skayo.jpg"></head><body>
    <h1>Comunicat aplicație Skayo AVL</h1>
    <div>Publicat la: 16 Iul 2026</div>
    <p>În perioada 17.07.2026 – 20.07.2026 va fi realizat un upgrade major al aplicației.</p>
    <p>Actualizarea propriu-zisă va avea loc în data de 17.07.2026, începând cu ora 20:00.
    Pe durata implementării este posibil să apară mici anomalii temporare în afișarea informațiilor pe panouri.</p>
    </body></html>
    """
    service = build_signal(
        article_url="https://www.eta-bus.ro/comunicate/comunicat-aplicatie-skayo-avl/",
        html_text=service_html,
    )
    assert service["classification"] == "SERVICE_ALERT"
    assert service["effective_start"] == "2026-07-17"
    assert service["effective_end"] == "2026-07-20"
    assert service["effective_time"] == "20:00"
    assert service["cms_published_at"] == "2026-07-16"
    assert service["visual_candidate"]["public_reuse_allowed"] is False
    assert service["boundaries"]["live_status_claim_allowed"] is False

    fare_html = """
    <html><body><h1>Tarife de transport valabile începând cu data de 01/02/2026</h1>
    <div>Publicat la: 30 Ian 2026</div>
    <p>Bilet 1 călătorie 4.00 lei. Abonament lunar 130 lei.</p></body></html>
    """
    fare = build_signal(
        article_url="https://eta-bus.ro/comunicate/tarife-01-02-2026",
        html_text=fare_html,
    )
    assert fare["classification"] == "FARE_OR_ACCESS_CHANGE"
    assert fare["effective_start"] == "2026-02-01"
    assert fare["cms_published_at"] == "2026-01-30"

    schedule_html = """
    <html><body><h1>Modificare temporară program traseu 5</h1>
    <p>Publicat la: 12 Aug 2026</p>
    <p>Începând cu data de 13.08.2026 se modifică programul de circulație pe traseul 5.</p>
    </body></html>
    """
    schedule = build_signal(
        article_url="https://eta-bus.ro/comunicate/modificare-program-traseu-5",
        html_text=schedule_html,
    )
    assert schedule["classification"] == "SCHEDULE_CHANGE"
    assert schedule["effective_start"] == "2026-08-13"

    irrelevant_html = """
    <html><body><h1>Anunț vânzare autovehicul</h1>
    <p>Publicat la: 20 Aug 2026</p><p>Licitație pentru vânzare autovehicul.</p></body></html>
    """
    irrelevant = build_signal(
        article_url="https://eta-bus.ro/comunicate/anunt-vanzare-autovehicul",
        html_text=irrelevant_html,
    )
    assert irrelevant["classification"] == "HOLD"

    month_html = """
    <html><body><h1>Călătorii gratuite locuitori municipiu</h1>
    <p>Începând cu luna DECEMBRIE 2025, locuitorii cu vârsta peste 62 de ani beneficiază
    de 20 de călătorii gratuite pe lună.</p></body></html>
    """
    month_signal = build_signal(
        article_url="https://eta-bus.ro/comunicate/calatorii-gratuite-locuitori",
        html_text=month_html,
    )
    assert month_signal["classification"] == "FARE_OR_ACCESS_CHANGE"
    assert month_signal["effective_start"] == "2025-12-01"
    assert month_signal["effective_semantics"] == "EXPLICIT_VISIBLE_EFFECTIVE_MONTH_START"

    try:
        normalize_notice_url("https://evil.example/comunicate/alerta")
        raise AssertionError("non-official host must fail")
    except ValueError:
        pass
    try:
        normalize_notice_url("https://eta-bus.ro/s/114")
        raise AssertionError("static timetable must not be accepted as notice")
    except ValueError:
        pass
    try:
        normalize_notice_url("http://eta-bus.ro/comunicate/alerta")
        raise AssertionError("HTTP must fail")
    except ValueError:
        pass

    assert classify_notice("Stație", "Program de circulație traseu 1") == ("HOLD", ["NO_SUPPORTED_PASSENGER_IMPACT_CLASS"])

    cms_only = build_signal(
        article_url="https://eta-bus.ro/comunicate/informare-generala",
        html_text="<html><body><h1>Informare generală</h1><p>Publicat la: 29 Aug 2026</p></body></html>",
    )
    assert cms_only["cms_published_at"] == "2026-08-29"
    assert cms_only["effective_start"] is None

    print("ETA evidence-first self-test: OK")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return 0
    print(json.dumps(discover_and_enrich(limit=args.limit), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
