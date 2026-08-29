#!/usr/bin/env python3
"""Evidence-first IPJ Vâlcea news-index signal adapter."""
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

SOURCE_ID = "signal-ipj-valcea-stiri"
SOURCE_NAME = "IPJ Vâlcea — Știri"
SOURCE_URL = "https://vl.politiaromana.ro/ro/stiri-si-media/stiri"
SOURCE_TIER = "T1"
SOURCE_KIND = "PUBLIC_SAFETY_OFFICIAL_POLICE_NEWS"
ALLOWED_HOST = "vl.politiaromana.ro"
INDEX_PATH = "/ro/stiri-si-media/stiri"
ARTICLE_PREFIXES = ("/ro/stiri/", "/ro/stiri-si-media/stiri/")
USER_AGENT = "Mozilla/5.0 VÂLCEA-CLAR-IPJ-News/1.0 (+https://valceaclar.ro/)"
MAX_BODY_BYTES = 3_000_000
TIMEOUT_SECONDS = 20
LOOKBACK_TOKENS = 8

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
ROMANIAN_DATE_RE = re.compile(rf"\b([0-3]?\d)\s+({MONTH_PATTERN})\s+((?:20)\d{{2}})\b", re.I)
NUMERIC_DATE_RE = re.compile(r"\b([0-3]?\d)[./-]([01]?\d)[./-]((?:20)\d{2})\b")

SENSITIVE_PERSON_HINTS = (
    "persoana disparuta", "persoana disparut", "disparuta de la domiciliu",
    "disparut de la domiciliu", "minor disparut", "minora disparuta",
    "copil disparut", "copila disparuta", "urmarit", "most wanted",
)
INCIDENT_HINTS = (
    "accident rutier", "eveniment rutier", "blocaj total", "trafic blocat",
    "circulatia este blocata", "circulatie blocata", "coliziune",
)
TRAFFIC_HINTS = (
    "restrictii de trafic", "restrictie de trafic", "siguranta rutiera",
    "sigurantei rutiere", "serviciului rutier", "biroului rutier",
    "roadpol", "speed", "trafic rutier", "circulatie rutiera",
)
PREVENTION_HINTS = (
    "actiuni preventive", "activitati preventive", "prevenirea",
    "prevenire", "siguranta scolara", "campania", "recomandari",
)
ENFORCEMENT_HINTS = (
    "retinut", "retinuta", "retinuti", "arestat", "arestata", "arestati",
    "depistat", "depistata", "depistati", "perchezitie", "perchezitii",
    "dosar penal", "mandat", "contrabanda", "evaziune fiscala",
    "cercetat", "cercetata", "cercetati",
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
    parsed = urlsplit(urljoin(base_url, clean_text(value)))
    if (
        parsed.scheme.casefold() != "https"
        or parsed.hostname is None
        or parsed.hostname.casefold() != ALLOWED_HOST
        or parsed.username
        or parsed.password
    ):
        return None
    path = re.sub(r"/+", "/", unquote(parsed.path or "/"))
    if not any(path.startswith(prefix) for prefix in ARTICLE_PREFIXES):
        return None
    if path.rstrip("/") == INDEX_PATH:
        return None
    return urlunsplit(("https", ALLOWED_HOST, path, "", ""))


class IndexParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.tokens: list[str] = []
        self.href: str | None = None
        self.parts: list[str] = []
        self.start = 0
        self.links: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
            return
        if self.skip_depth or tag != "a":
            return
        normalized = normalize_article_url(dict(attrs).get("href") or "")
        if normalized:
            self.href, self.parts, self.start = normalized, [], len(self.tokens)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth or tag != "a" or self.href is None:
            return
        self.links.append({
            "url": self.href,
            "title": clean_text(" ".join(self.parts)),
            "start": self.start,
        })
        self.href, self.parts = None, []

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = clean_text(data)
        if not text:
            return
        self.tokens.append(text)
        if self.href is not None:
            self.parts.append(text)


def placeholder_response(html_text: str) -> bool:
    visible = fold(re.sub(r"<[^>]+>", " ", html_text))[:5000]
    return any(fold(term) in visible for term in PLACEHOLDER_TERMS)


def _valid_date(day: int, month: int, year: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def dates_in_token(text: str) -> tuple[list[str], bool]:
    values: list[str] = []
    anomalous = False
    for match in ROMANIAN_DATE_RE.finditer(fold(text)):
        value = _valid_date(int(match.group(1)), MONTHS[match.group(2).casefold()], int(match.group(3)))
        anomalous |= value is None
        if value and value not in values:
            values.append(value)
    for match in NUMERIC_DATE_RE.finditer(text):
        value = _valid_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        anomalous |= value is None
        if value and value not in values:
            values.append(value)
    return values, anomalous


def publication_date_before_link(tokens: list[str], start: int) -> tuple[list[str], str]:
    window = tokens[max(0, start - LOOKBACK_TOKENS):start]
    for index in range(len(window) - 1, -1, -1):
        values, anomalous = dates_in_token(window[index])
        if anomalous:
            return values[:2], "ANOMALOUS_PUBLICATION_DATE"
        if not values:
            continue
        if len(values) > 1:
            return values[:2], "AMBIGUOUS_PUBLICATION_DATE"
        tail = fold(" ".join(window[index:]))
        if not all(marker in tail for marker in ("sursa", "ipj", "valcea")):
            return values, "MISSING_SOURCE_MARKER"
        return values, "EXPLICIT_INDEX_METADATA"
    return [], "MISSING"


def classify(title: str, date_status: str) -> tuple[str, bool]:
    value = fold(title)
    sensitive = any(hint in value for hint in SENSITIVE_PERSON_HINTS)
    if sensitive:
        return "HOLD_SENSITIVE_PERSON_ALERT_REVIEW_REQUIRED", True
    if date_status != "EXPLICIT_INDEX_METADATA":
        return "HOLD", False
    if any(hint in value for hint in INCIDENT_HINTS):
        return "PUBLIC_SAFETY_INCIDENT_REPORT", False
    if any(hint in value for hint in TRAFFIC_HINTS):
        return "TRAFFIC_SAFETY_NOTICE", False
    if any(hint in value for hint in PREVENTION_HINTS):
        return "CRIME_PREVENTION_ADVISORY", False
    if any(hint in value for hint in ENFORCEMENT_HINTS):
        return "LAW_ENFORCEMENT_ACTIVITY_REPORT", False
    return "HOLD", False


def signal_id(url: str, title: str) -> str:
    basis = "\0".join([SOURCE_ID, url, fold(title)])
    return "ipj-news-" + hashlib.sha256(basis.encode()).hexdigest()[:20]


def extract_signals(html_text: str, *, final_url: str = SOURCE_URL) -> list[dict[str, Any]]:
    if not official_index_url(final_url):
        raise ValueError(f"IPJ news adapter refused unexpected source URL: {final_url}")
    if placeholder_response(html_text):
        raise ValueError("IPJ news source returned a placeholder/challenge response")

    parser = IndexParser()
    parser.feed(html_text)
    parser.close()
    rows: dict[str, dict[str, Any]] = {}
    for link in parser.links:
        raw_title = clean_text(link["title"])
        if len(raw_title) < 5:
            continue
        dates, date_status = publication_date_before_link(parser.tokens, int(link["start"]))
        signal_class, sensitive = classify(raw_title, date_status)
        sid = signal_id(link["url"], raw_title)
        rows[sid] = {
            "signal_id": sid,
            "source_id": SOURCE_ID,
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "source_surface": "stiri-si-media/stiri",
            "final_url": final_url,
            "source_tier": SOURCE_TIER,
            "source_kind": SOURCE_KIND,
            "article_url": None if sensitive else link["url"],
            "article_locator_sha256": hashlib.sha256(link["url"].encode()).hexdigest(),
            "article_url_withheld_for_sensitive_person_alert": sensitive,
            "title": "[SENSITIVE_PERSON_ALERT_WITHHELD]" if sensitive else raw_title,
            "title_sha256": hashlib.sha256(raw_title.encode()).hexdigest(),
            "signal_class": signal_class,
            "publication_dates": dates,
            "publication_date_status": date_status,
            "summary_excerpt": None,
            "article_body_ingest_allowed": False,
            "current_incident_claim_allowed": False,
            "current_traffic_state_claim_allowed": False,
            "publication_date_is_not_incident_time": True,
            "publication_date_is_not_live_status": True,
            "person_level_data_extraction_allowed": False,
            "missing_person_identity_ingest_allowed": False,
            "law_enforcement_person_identity_ingest_allowed": False,
            "victim_identity_ingest_allowed": False,
            "casualty_count_inference_allowed": False,
            "medical_inference_allowed": False,
            "media_candidates": [],
            "media_public_reuse_allowed": False,
            "publication_authority": "NONE",
            "public_projection": False,
            "auto_publication": False,
            "persistence_allowed": False,
            "fact_kernel_authority": False,
            "source_recheck_required": True,
            "lifecycle": (
                "HOLD_SENSITIVE_PERSON_ALERT_REVIEW_REQUIRED" if sensitive
                else "SIGNAL_ONLY_SOURCE_RECHECK_REQUIRED" if signal_class != "HOLD"
                else "HOLD_AMBIGUOUS_CLASS_OR_PUBLICATION_DATE"
            ),
            "provenance": {
                "authority": "IPJ_VALCEA_OFFICIAL_NEWS_INDEX",
                "retrieval_surface": SOURCE_URL,
                "metadata_basis": "VISIBLE_OFFICIAL_INDEX_HTML",
                "publication_date_basis": "NEAREST_PRECEDING_IPJ_INDEX_METADATA_TOKEN",
                "article_body_basis": "OFFICIAL_ARTICLE_LINK_DISCOVERED_BODY_NOT_FETCHED",
            },
        }
    return sorted(
        rows.values(),
        key=lambda row: (
            row["signal_class"].startswith("HOLD"),
            -(int(row["publication_dates"][0].replace("-", "")) if row["publication_dates"] else 0),
            row["title"].casefold(),
            row["signal_id"],
        ),
    )


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise ValueError(f"IPJ news adapter refused redirect: {newurl}")


def fetch_html(url: str = SOURCE_URL) -> tuple[str, str, str]:
    if not official_index_url(url):
        raise ValueError("IPJ news fetch is restricted to the canonical index")
    opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        final_url = str(response.geturl())
        if not official_index_url(final_url):
            raise ValueError(f"IPJ news adapter refused unexpected final URL: {final_url}")
        body = response.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            raise ValueError("IPJ news response exceeds bounded body limit")
        content_type = str(response.headers.get("Content-Type") or "")
        if "html" not in content_type.casefold() and b"<html" not in body[:2000].lower():
            raise ValueError(f"IPJ news source did not return HTML: {content_type or 'unknown'}")
        charset = response.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace"), final_url, hashlib.sha256(body).hexdigest()


def build_document(html_text: str, *, final_url: str, content_sha256: str) -> dict[str, Any]:
    signals = extract_signals(html_text, final_url=final_url)
    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR IPJ news signals",
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
            "current_traffic_state_claim_allowed": False,
            "publication_date_is_not_incident_time": True,
            "publication_date_is_not_live_status": True,
            "article_body_ingest_allowed": False,
            "person_level_data_extraction_allowed": False,
            "missing_person_identity_ingest_allowed": False,
            "law_enforcement_person_identity_ingest_allowed": False,
            "victim_identity_ingest_allowed": False,
            "casualty_count_inference_allowed": False,
            "medical_inference_allowed": False,
            "media_public_reuse_allowed": False,
            "source_recheck_required": True,
        },
    }


def self_test() -> int:
    sample = """
    <html><body>
    <span>28 August 2026 Sursa: IPJ VALCEA</span>
    <a href="/ro/stiri/actiune-pentru-cresterea-sigurantei-rutiere-pe-dn-7">ACȚIUNE PENTRU CREȘTEREA SIGURANȚEI RUTIERE PE DN 7</a>
    <p>La data de 27 august 2026...</p>
    <span>27 August 2026 Sursa: IPJ VALCEA</span>
    <a href="/ro/stiri/retinut-pentru-24-de-ore">REȚINUT PENTRU 24 DE ORE</a>
    <p>Un bărbat de 46 de ani...</p>
    <span>26 August 2026 Sursa: IPJ VALCEA</span>
    <a href="/ro/stiri/accident-rutier-mortal-pe-dn-7">ACCIDENT RUTIER MORTAL PE DN 7</a>
    <p>În seara zilei de 25 august 2026...</p>
    <span>25 August 2026 Sursa: IPJ VALCEA</span>
    <a href="/ro/stiri/persoana-disparuta-ana-popescu">PERSOANĂ DISPĂRUTĂ - ANA POPESCU</a>
    <span>31 februarie 2026 Sursa: IPJ VALCEA</span>
    <a href="/ro/stiri/accident-cu-data-invalida">ACCIDENT RUTIER CU DATĂ INVALIDĂ</a>
    <span>24 August 2026</span>
    <a href="/ro/stiri/fara-marcaj-sursa">ACȚIUNE PENTRU SIGURANȚA RUTIERĂ</a>
    <a href="https://evil.example/ro/stiri/test">ACCIDENT EXTERN</a>
    </body></html>
    """
    signals = extract_signals(sample)
    by_title = {row["title"]: row for row in signals}
    traffic = by_title["ACȚIUNE PENTRU CREȘTEREA SIGURANȚEI RUTIERE PE DN 7"]
    assert traffic["signal_class"] == "TRAFFIC_SAFETY_NOTICE"
    assert traffic["publication_dates"] == ["2026-08-28"]
    assert traffic["summary_excerpt"] is None
    enforcement = by_title["REȚINUT PENTRU 24 DE ORE"]
    assert enforcement["signal_class"] == "LAW_ENFORCEMENT_ACTIVITY_REPORT"
    assert enforcement["publication_dates"] == ["2026-08-27"]
    assert enforcement["person_level_data_extraction_allowed"] is False
    incident = by_title["ACCIDENT RUTIER MORTAL PE DN 7"]
    assert incident["signal_class"] == "PUBLIC_SAFETY_INCIDENT_REPORT"
    assert incident["publication_dates"] == ["2026-08-26"]
    assert incident["current_incident_claim_allowed"] is False
    sensitive = next(row for row in signals if row["signal_class"] == "HOLD_SENSITIVE_PERSON_ALERT_REVIEW_REQUIRED")
    assert sensitive["title"] == "[SENSITIVE_PERSON_ALERT_WITHHELD]"
    assert sensitive["article_url"] is None
    assert sensitive["missing_person_identity_ingest_allowed"] is False
    invalid = by_title["ACCIDENT RUTIER CU DATĂ INVALIDĂ"]
    assert invalid["publication_date_status"] == "ANOMALOUS_PUBLICATION_DATE"
    assert invalid["signal_class"] == "HOLD"
    no_source = by_title["ACȚIUNE PENTRU SIGURANȚA RUTIERĂ"]
    assert no_source["publication_date_status"] == "MISSING_SOURCE_MARKER"
    assert no_source["signal_class"] == "HOLD"
    assert normalize_article_url("https://evil.example/ro/stiri/test") is None
    assert normalize_article_url("https://vl.politiaromana.ro/ro/stiri/test")
    assert normalize_article_url("https://vl.politiaromana.ro/ro/stiri-si-media/comunicate/test") is None
    assert official_index_url(SOURCE_URL)
    assert not official_index_url("http://vl.politiaromana.ro/ro/stiri-si-media/stiri")
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
