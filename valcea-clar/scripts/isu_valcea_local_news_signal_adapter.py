#!/usr/bin/env python3
"""Evidence-first ISU Vâlcea local-news signal adapter.

Reads only the official ``/stiri-locale`` index and emits metadata-level
public-safety signals. Article bodies are never fetched. Publication dates are
not incident-state timestamps, and the adapter grants no persistence, Fact
Kernel, Writer, media-reuse, or publication authority.
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
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, HTTPSHandler

SOURCE_ID = "signal-isu-valcea-stiri-locale"
SOURCE_NAME = "ISU Vâlcea — Știri locale"
SOURCE_URL = "https://isuvl.igsu.ro/stiri-locale"
SOURCE_TIER = "T1"
SOURCE_KIND = "PUBLIC_SAFETY_OFFICIAL_LOCAL_NEWS"
ALLOWED_HOST = "isuvl.igsu.ro"
INDEX_PATH = "/stiri-locale"
ARTICLE_PREFIX = "/stiri-locale/"
USER_AGENT = "Mozilla/5.0 VÂLCEA-CLAR-ISU-Local-News/1.0 (+https://valceaclar.ro/)"
MAX_BODY_BYTES = 3_000_000
TIMEOUT_SECONDS = 20

PLACEHOLDER_TERMS = (
    "enable javascript", "access denied", "captcha", "robot",
    "temporarily unavailable", "service unavailable", "cloudflare",
)
MONTHS = {
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4,
    "mai": 5, "iunie": 6, "iulie": 7, "august": 8,
    "septembrie": 9, "octombrie": 10, "noiembrie": 11, "decembrie": 12,
}
MONTH_PATTERN = "|".join(MONTHS)
ROMANIAN_DATE_RE = re.compile(
    rf"\b([0-3]?\d)\s+({MONTH_PATTERN})\s+((?:20)\d{{2}})\b",
    re.IGNORECASE,
)
NUMERIC_DATE_RE = re.compile(r"\b([0-3]?\d)[./-]([01]?\d)[./-]((?:20)\d{2})\b")

EXERCISE_HINTS = ("exercitiu", "simulare", "alarmare publica")
ADVISORY_HINTS = (
    "recomandari", "masuri de prevenire", "prevenirea incendiilor",
    "avertizare", "atentionare", "risc de incendiu",
)
SUMMARY_HINTS = (
    "misiunile pompierilor", "interventiile pompierilor", "bilantul misiunilor",
    "bilantul interventiilor",
)
INCIDENT_HINTS = (
    "incendiu", "accident rutier", "explozie", "salvare", "evacuare",
    "descarcerare", "copac cazut", "inundatie", "inec", "autoturism",
    "autocar", "autotren", "gospodarie", "locuinta",
)


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", clean_text(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def official_index_url(url: str) -> bool:
    parsed = urlsplit(clean_text(url))
    if parsed.scheme.casefold() != "https" or parsed.hostname is None:
        return False
    if parsed.hostname.casefold() != ALLOWED_HOST or parsed.username or parsed.password:
        return False
    path = re.sub(r"/+", "/", unquote(parsed.path or "/"))
    return path.rstrip("/") == INDEX_PATH and not parsed.query and not parsed.fragment


def normalize_article_url(value: str, *, base_url: str = SOURCE_URL) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    parsed = urlsplit(urljoin(base_url, text))
    if (
        parsed.scheme.casefold() != "https"
        or parsed.hostname is None
        or parsed.hostname.casefold() != ALLOWED_HOST
        or parsed.username
        or parsed.password
    ):
        return None
    path = re.sub(r"/+", "/", unquote(parsed.path or "/"))
    if not path.startswith(ARTICLE_PREFIX) or path.rstrip("/") == INDEX_PATH:
        return None
    return urlunsplit(("https", ALLOWED_HOST, path, parsed.query, ""))


class IndexParser(html.parser.HTMLParser):
    """Collect visible tokens and anchors constrained to local-news articles."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.tokens: list[str] = []
        self.current_href: str | None = None
        self.current_parts: list[str] = []
        self.current_start = 0
        self.links: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "a":
            normalized = normalize_article_url(dict(attrs).get("href") or "")
            if normalized:
                self.current_href = normalized
                self.current_parts = []
                self.current_start = len(self.tokens)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag == "a" and self.current_href is not None:
            self.links.append({
                "url": self.current_href,
                "title": clean_text(" ".join(self.current_parts)),
                "start": self.current_start,
                "end": len(self.tokens),
            })
            self.current_href = None
            self.current_parts = []

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = clean_text(data)
        if not text:
            return
        self.tokens.append(text)
        if self.current_href is not None:
            self.current_parts.append(text)


def placeholder_response(html_text: str) -> bool:
    visible = fold(re.sub(r"<[^>]+>", " ", html_text))[:5000]
    return any(fold(term) in visible for term in PLACEHOLDER_TERMS)


def _valid_date(day: int, month: int, year: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def publication_dates(text: str) -> tuple[list[str], str]:
    values: list[str] = []
    anomalous = False
    for match in ROMANIAN_DATE_RE.finditer(fold(text)):
        value = _valid_date(int(match.group(1)), MONTHS[match.group(2).casefold()], int(match.group(3)))
        if value is None:
            anomalous = True
        elif value not in values:
            values.append(value)
    for match in NUMERIC_DATE_RE.finditer(text):
        value = _valid_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if value is None:
            anomalous = True
        elif value not in values:
            values.append(value)
    if anomalous:
        return values[:3], "PARTIAL_ANOMALY" if values else "ANOMALOUS"
    if len(values) == 1:
        return values, "EXPLICIT_INDEX_METADATA"
    if len(values) > 1:
        return values[:3], "AMBIGUOUS_MULTIPLE_DATES"
    return [], "MISSING"


def classify(title: str, *, date_status: str) -> str:
    if date_status != "EXPLICIT_INDEX_METADATA":
        return "HOLD"
    value = fold(title)
    if any(hint in value for hint in EXERCISE_HINTS):
        return "EMERGENCY_EXERCISE"
    if any(hint in value for hint in ADVISORY_HINTS):
        return "PUBLIC_SAFETY_ADVISORY"
    if any(hint in value for hint in SUMMARY_HINTS):
        return "PUBLIC_SAFETY_ACTIVITY_SUMMARY"
    if any(hint in value for hint in INCIDENT_HINTS):
        return "PUBLIC_SAFETY_INCIDENT_REPORT"
    return "HOLD"


def signal_id(*, url: str, title: str) -> str:
    basis = "\0".join([SOURCE_ID, url, fold(title)])
    return "isu-local-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:20]


def extract_signals(html_text: str, *, final_url: str = SOURCE_URL) -> list[dict[str, Any]]:
    if not official_index_url(final_url):
        raise ValueError(f"ISU local-news adapter refused unexpected source URL: {final_url}")
    if placeholder_response(html_text):
        raise ValueError("ISU local-news source returned a placeholder/challenge response")

    parser = IndexParser()
    parser.feed(html_text)
    parser.close()

    rows: dict[str, dict[str, Any]] = {}
    for index, link in enumerate(parser.links):
        title = clean_text(link["title"])
        if len(title) < 5:
            continue
        next_start = int(parser.links[index + 1]["start"]) if index + 1 < len(parser.links) else len(parser.tokens)
        context = clean_text(" ".join(parser.tokens[int(link["start"]):next_start]))
        dates, date_status = publication_dates(context)
        signal_class = classify(title, date_status=date_status)
        sid = signal_id(url=link["url"], title=title)
        rows[sid] = {
            "signal_id": sid,
            "source_id": SOURCE_ID,
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "source_surface": "stiri-locale",
            "final_url": final_url,
            "source_tier": SOURCE_TIER,
            "source_kind": SOURCE_KIND,
            "article_url": link["url"],
            "title": title,
            "signal_class": signal_class,
            "publication_dates": dates,
            "publication_date_status": date_status,
            "summary_excerpt": context[:700],
            "article_body_ingest_allowed": False,
            "current_incident_claim_allowed": False,
            "publication_date_is_not_incident_time": True,
            "publication_date_is_not_live_status": True,
            "casualty_count_inference_allowed": False,
            "medical_inference_allowed": False,
            "person_level_data_extraction_allowed": False,
            "media_candidates": [],
            "media_public_reuse_allowed": False,
            "publication_authority": "NONE",
            "public_projection": False,
            "auto_publication": False,
            "persistence_allowed": False,
            "fact_kernel_authority": False,
            "lifecycle": (
                "SIGNAL_ONLY_SOURCE_RECHECK_REQUIRED"
                if signal_class != "HOLD"
                else "HOLD_AMBIGUOUS_CLASS_OR_PUBLICATION_DATE"
            ),
            "provenance": {
                "authority": "ISU_VALCEA_OFFICIAL_LOCAL_NEWS_INDEX",
                "retrieval_surface": SOURCE_URL,
                "metadata_basis": "VISIBLE_OFFICIAL_INDEX_HTML",
                "article_body_basis": "OFFICIAL_ARTICLE_LINK_DISCOVERED_BODY_NOT_FETCHED",
            },
        }

    return sorted(
        rows.values(),
        key=lambda row: (
            row["signal_class"] == "HOLD",
            -(int(row["publication_dates"][0].replace("-", "")) if row["publication_dates"] else 0),
            row["title"].casefold(),
        ),
    )


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise ValueError(f"ISU local-news adapter refused redirect: {newurl}")


def html_response_ok(content_type: str, body: bytes) -> bool:
    return "html" in content_type.casefold() or b"<html" in body[:2000].lower()


def fetch_html(url: str = SOURCE_URL) -> tuple[str, str, str]:
    if not official_index_url(url):
        raise ValueError("ISU local-news fetch is restricted to the canonical index")
    opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        final_url = str(response.geturl())
        if not official_index_url(final_url):
            raise ValueError(f"ISU local-news adapter refused unexpected final URL: {final_url}")
        body = response.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            raise ValueError("ISU local-news response exceeds bounded body limit")
        content_type = str(response.headers.get("Content-Type") or "")
        if not html_response_ok(content_type, body):
            raise ValueError(f"ISU local-news source did not return HTML: {content_type or 'unknown'}")
        charset = response.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace"), final_url, hashlib.sha256(body).hexdigest()


def build_document(html_text: str, *, final_url: str, content_sha256: str) -> dict[str, Any]:
    signals = extract_signals(html_text, final_url=final_url)
    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR ISU local-news signals",
        "source_id": SOURCE_ID,
        "source_url": SOURCE_URL,
        "final_url": final_url,
        "source_content_sha256": content_sha256,
        "signal_count": len(signals),
        "signals": signals,
        "policy": {
            "publication_authority": "NONE",
            "signal_only": True,
            "public_projection": False,
            "auto_publication": False,
            "persistence_allowed": False,
            "fact_kernel_authority": False,
            "current_incident_claim_allowed": False,
            "publication_date_is_not_incident_time": True,
            "publication_date_is_not_live_status": True,
            "article_body_ingest_allowed": False,
            "casualty_count_inference_allowed": False,
            "medical_inference_allowed": False,
            "person_level_data_extraction_allowed": False,
            "media_public_reuse_allowed": False,
            "source_recheck_required": True,
        },
    }


def self_test() -> int:
    sample = """
    <html><body>
      <div><a href="/stiri-locale/accident-rutier-urmat-de-incendiu-763">Accident rutier urmat de incendiu în localitatea Băile Olănești</a><span>22 august 2026</span></div>
      <div><a href="/stiri-locale/incendiu-autocar-762">Incendiu autocar în municipiul Râmnicu Vâlcea</a><span>22 august 2026</span></div>
      <div><a href="/stiri-locale/exercitiu-dn7-695">Exercițiu desfășurat pentru optimizarea intervenției pe DN7</a><span>25 iunie 2026</span></div>
      <div><a href="/stiri-locale/material-neclar-700">Material fără clasă sigură</a><span>24 iunie 2026</span></div>
      <div><a href="/stiri-locale/data-invalida-701">Incendiu cu dată invalidă</a><span>31 februarie 2026</span></div>
      <div><a href="/stiri-locale/date-multiple-702">Accident rutier cu metadate conflictuale</a><span>20 iunie 2026</span><span>21 iunie 2026</span></div>
      <div><a href="/stiri-locale/fara-data-703">Incendiu fără dată</a></div>
      <a href="https://evil.example/stiri-locale/incendiu">Incendiu extern</a>
    </body></html>
    """
    signals = extract_signals(sample)
    by_title = {row["title"]: row for row in signals}

    incident = by_title["Accident rutier urmat de incendiu în localitatea Băile Olănești"]
    assert incident["signal_class"] == "PUBLIC_SAFETY_INCIDENT_REPORT"
    assert incident["publication_dates"] == ["2026-08-22"]
    assert incident["current_incident_claim_allowed"] is False
    assert incident["publication_date_is_not_incident_time"] is True
    assert incident["article_body_ingest_allowed"] is False

    second = by_title["Incendiu autocar în municipiul Râmnicu Vâlcea"]
    assert second["publication_dates"] == ["2026-08-22"]
    assert "25 iunie 2026" not in second["summary_excerpt"]

    exercise = by_title["Exercițiu desfășurat pentru optimizarea intervenției pe DN7"]
    assert exercise["signal_class"] == "EMERGENCY_EXERCISE"

    assert by_title["Material fără clasă sigură"]["signal_class"] == "HOLD"
    assert by_title["Incendiu cu dată invalidă"]["signal_class"] == "HOLD"
    assert by_title["Accident rutier cu metadate conflictuale"]["publication_date_status"] == "AMBIGUOUS_MULTIPLE_DATES"
    assert by_title["Accident rutier cu metadate conflictuale"]["signal_class"] == "HOLD"
    assert by_title["Incendiu fără dată"]["publication_date_status"] == "MISSING"
    assert by_title["Incendiu fără dată"]["signal_class"] == "HOLD"

    assert normalize_article_url("https://evil.example/stiri-locale/incendiu") is None
    assert normalize_article_url("https://isuvl.igsu.ro/comunicate-de-presa/test") is None
    assert normalize_article_url("https://isuvl.igsu.ro/stiri-locale") is None
    assert official_index_url(SOURCE_URL)
    assert not official_index_url("https://isuvl.igsu.ro/comunicate-de-presa")
    assert not official_index_url("http://isuvl.igsu.ro/stiri-locale")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.live:
        parser.error("choose --self-test or --live")
    html_text, final_url, digest = fetch_html()
    print(json.dumps(build_document(html_text, final_url=final_url, content_sha256=digest), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
