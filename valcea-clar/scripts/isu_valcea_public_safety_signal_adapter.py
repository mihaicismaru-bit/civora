#!/usr/bin/env python3
"""Evidence-first ISU Vâlcea public-safety signal adapter.

The adapter reads only the official ISU Vâlcea press-release index and emits
metadata-level public-safety signals. It deliberately does not fetch article
bodies, infer live incident state, extract person-level data, or grant
publication/media rights.
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
from urllib.request import Request, urlopen

SOURCE_ID = "signal-isu-valcea-comunicate"
SOURCE_NAME = "ISU Vâlcea — Comunicate de presă"
SOURCE_URL = "https://isuvl.igsu.ro/comunicate-de-presa"
SOURCE_TIER = "T1"
SOURCE_KIND = "PUBLIC_SAFETY_OFFICIAL_REPORTS"
ALLOWED_HOSTS = {"isuvl.igsu.ro"}
INDEX_PATH = "/comunicate-de-presa"
ALLOWED_ARTICLE_PREFIXES = ("/comunicate-de-presa/", "/stiri-locale/")
USER_AGENT = "Mozilla/5.0 VÂLCEA-CLAR-ISU-Safety-Signal/1.0 (+https://valceaclar.ro/)"
MAX_BODY_BYTES = 3_000_000

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

SUMMARY_HINTS = (
    "misiunile pompierilor", "interventiile pompierilor", "bilantul misiunilor",
    "bilantul interventiilor", "activitatea pompierilor",
)
EXERCISE_HINTS = (
    "exercitiu", "alarmare publica", "simulare",
)
CIVIL_PROTECTION_HINTS = (
    "fondului de adapostire", "fondul de adapostire", "adaposturi de protectie civila",
    "protectie civila",
)
ADVISORY_HINTS = (
    "prevenire", "recomandari", "avertizare", "atentie", "masuri de prevenire",
    "siguranta", "campanie", "risc de incendiu", "arderea vegetatiei",
)
INCIDENT_HINTS = (
    "incendiu", "accident", "explozie", "salvare", "degajare", "evacuare",
    "interventie", "autoturism", "gospodarie", "locuinta", "copac cazut",
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
    if parsed.hostname.casefold() not in ALLOWED_HOSTS or parsed.username or parsed.password:
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
        or parsed.hostname.casefold() not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
    ):
        return None
    path = re.sub(r"/+", "/", unquote(parsed.path or "/"))
    if not any(path.startswith(prefix) for prefix in ALLOWED_ARTICLE_PREFIXES):
        return None
    if path.rstrip("/") in {INDEX_PATH, "/stiri-locale"}:
        return None
    return urlunsplit(("https", "isuvl.igsu.ro", path, parsed.query, ""))


class IndexParser(html.parser.HTMLParser):
    """Collect visible-text tokens and official article anchors."""

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
            href = dict(attrs).get("href") or ""
            normalized = normalize_article_url(href)
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
            title = clean_text(" ".join(self.current_parts))
            self.links.append({
                "url": self.current_href,
                "title": title,
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
        day = int(match.group(1))
        month = MONTHS[match.group(2).casefold()]
        value = _valid_date(day, month, int(match.group(3)))
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


def classify(title: str, context: str, *, date_status: str) -> str:
    if date_status != "EXPLICIT_INDEX_METADATA":
        return "HOLD"
    value = fold(f"{title} {context}")
    if any(hint in value for hint in SUMMARY_HINTS):
        return "PUBLIC_SAFETY_ACTIVITY_SUMMARY"
    if any(hint in value for hint in EXERCISE_HINTS):
        return "EMERGENCY_EXERCISE"
    if any(hint in value for hint in CIVIL_PROTECTION_HINTS):
        return "CIVIL_PROTECTION_REFERENCE"
    if any(hint in value for hint in ADVISORY_HINTS):
        return "PUBLIC_SAFETY_ADVISORY"
    if any(hint in value for hint in INCIDENT_HINTS):
        return "PUBLIC_SAFETY_INCIDENT_REPORT"
    return "HOLD"


def signal_id(*, url: str, title: str) -> str:
    basis = "\0".join([SOURCE_ID, url, fold(title)])
    return "isu-safety-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:20]


def extract_signals(html_text: str, *, final_url: str = SOURCE_URL) -> list[dict[str, Any]]:
    if not official_index_url(final_url):
        raise ValueError(f"ISU adapter refused unexpected source URL: {final_url}")
    if placeholder_response(html_text):
        raise ValueError("ISU source returned a placeholder/challenge response")

    parser = IndexParser()
    parser.feed(html_text)
    parser.close()

    rows: dict[str, dict[str, Any]] = {}
    for index, link in enumerate(parser.links):
        title = clean_text(link["title"])
        if len(title) < 5:
            continue
        next_start = (
            int(parser.links[index + 1]["start"])
            if index + 1 < len(parser.links)
            else len(parser.tokens)
        )
        context_tokens = parser.tokens[int(link["start"]):next_start]
        context = clean_text(" ".join(context_tokens))
        dates, date_status = publication_dates(context)
        if date_status == "MISSING":
            previous_end = int(parser.links[index - 1]["end"]) if index else 0
            fallback = clean_text(" ".join(parser.tokens[max(previous_end, int(link["start"]) - 3):int(link["end"])]))
            fallback_dates, fallback_status = publication_dates(fallback)
            if fallback_status != "MISSING":
                context = fallback
                dates, date_status = fallback_dates, fallback_status
        signal_class = classify(title, context, date_status=date_status)
        sid = signal_id(url=link["url"], title=title)
        rows[sid] = {
            "signal_id": sid,
            "source_id": SOURCE_ID,
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
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
                "authority": "ISU_VALCEA_OFFICIAL_PRESS_RELEASE_INDEX",
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


def html_response_ok(content_type: str, body: bytes) -> bool:
    return "html" in content_type.casefold() or b"<html" in body[:2000].lower()


def fetch_html(url: str = SOURCE_URL) -> tuple[str, str, str]:
    if not official_index_url(url):
        raise ValueError("ISU fetch is restricted to the canonical press-release index")
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with urlopen(request, timeout=20, context=ssl.create_default_context()) as response:
        final_url = str(response.geturl())
        if not official_index_url(final_url):
            raise ValueError(f"ISU adapter refused redirect outside canonical source surface: {final_url}")
        body = response.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            raise ValueError("ISU source response exceeds bounded body limit")
        content_type = str(response.headers.get("Content-Type") or "")
        if not html_response_ok(content_type, body):
            raise ValueError(f"ISU source did not return HTML: {content_type or 'unknown'}")
        charset = response.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace"), final_url, hashlib.sha256(body).hexdigest()


def build_document(html_text: str, *, final_url: str, content_sha256: str) -> dict[str, Any]:
    signals = extract_signals(html_text, final_url=final_url)
    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR ISU public-safety signals",
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
      <div class="item">
        <a href="/comunicate-de-presa/misiunile-pompierilor-valceni-in-ultimele-48-de-ore-762">Misiunile pompierilor vâlceni în ultimele 48 de ore</a>
        <span>26 august 2026</span><span>Buletin informativ</span>
      </div>
      <div class="item">
        <a href="https://isuvl.igsu.ro/comunicate-de-presa/incendiu-izbucnit-la-un-autoturism-999">Incendiu izbucnit la un autoturism</a>
        <span>18 august 2026</span>
      </div>
      <div class="item">
        <a href="/comunicate-de-presa/recomandari-pentru-prevenirea-incendiilor-998">Recomandări pentru prevenirea incendiilor</a>
        <span>17.08.2026</span>
      </div>
      <div class="item">
        <a href="/comunicate-de-presa/exercitiu-de-alarmare-publica-997">Exercițiu de alarmare publică</a>
        <span>16 august 2026</span>
      </div>
      <div class="item">
        <a href="/comunicate-de-presa/situatia-fondului-de-adapostire-995">Situația fondului de adăpostire din județul Vâlcea</a>
        <span>15 august 2026</span>
      </div>
      <div class="item">
        <a href="/comunicate-de-presa/material-neclar-996">Material neclar</a>
        <span>31 februarie 2026</span>
      </div>
      <a href="https://evil.example/comunicate-de-presa/incendiu">Incendiu extern</a>
    </body></html>
    """
    signals = extract_signals(sample)
    by_title = {row["title"]: row for row in signals}

    summary = by_title["Misiunile pompierilor vâlceni în ultimele 48 de ore"]
    assert summary["signal_class"] == "PUBLIC_SAFETY_ACTIVITY_SUMMARY"
    assert summary["publication_dates"] == ["2026-08-26"]
    assert summary["current_incident_claim_allowed"] is False
    assert summary["publication_date_is_not_live_status"] is True

    incident = by_title["Incendiu izbucnit la un autoturism"]
    assert incident["signal_class"] == "PUBLIC_SAFETY_INCIDENT_REPORT"
    assert incident["article_body_ingest_allowed"] is False

    advisory = by_title["Recomandări pentru prevenirea incendiilor"]
    assert advisory["signal_class"] == "PUBLIC_SAFETY_ADVISORY"

    exercise = by_title["Exercițiu de alarmare publică"]
    assert exercise["signal_class"] == "EMERGENCY_EXERCISE"

    shelter = by_title["Situația fondului de adăpostire din județul Vâlcea"]
    assert shelter["signal_class"] == "CIVIL_PROTECTION_REFERENCE"

    invalid = by_title["Material neclar"]
    assert invalid["signal_class"] == "HOLD"
    assert invalid["publication_date_status"] in {"ANOMALOUS", "PARTIAL_ANOMALY", "AMBIGUOUS_MULTIPLE_DATES"}

    assert normalize_article_url("https://evil.example/comunicate-de-presa/incendiu") is None
    assert normalize_article_url("https://isuvl.igsu.ro/contact") is None
    assert official_index_url(SOURCE_URL)
    assert not official_index_url("https://isuvl.igsu.ro/")
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
