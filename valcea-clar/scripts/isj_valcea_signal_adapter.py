#!/usr/bin/env python3
"""Extract evidence-first education signals from the ISJ Vâlcea press-release index.

This adapter deliberately stops at official listing metadata. The ISJ surface is a
mixed document feed, including PDFs/DOCX and material that may contain candidate
or staff data. Attachment bodies are never fetched or parsed here. Every output
remains signal-only and has no publication authority.
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
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import Request, urlopen

SOURCE_ID = "isj-valcea-comunicate"
SOURCE_NAME = "Inspectoratul Școlar Județean Vâlcea — Comunicate de presă"
SOURCE_URL = "https://www.isjvalcea.ro/avizier/comunicate-de-pres%C4%83"
SOURCE_TIER = "T1"
SOURCE_KIND = "EDUCATION_OFFICIAL_PRESS_RELEASES"
ALLOWED_HOSTS = {"isjvalcea.ro", "www.isjvalcea.ro"}
CANONICAL_PATH = "/avizier/comunicate-de-presă"
USER_AGENT = "Mozilla/5.0 VÂLCEA-CLAR-ISJ-Signal/1.0 (+https://valceaclar.ro/)"
MAX_BODY_BYTES = 3_000_000
DATE_PREFIX = re.compile(r"^\s*([0-3]?\d)[._/-]([01]?\d)[._/-]((?:20)\d{2})(?:\s*[_-]\s*|\s+)(.+?)\s*$")
EXTENSION = re.compile(r"\.(pdf|docx?|xlsx?|pptx?)\s*$", re.IGNORECASE)
PLACEHOLDER_TERMS = ("enable javascript", "access denied", "captcha", "robot", "temporarily unavailable")
SENSITIVE_TERMS = (
    "tabel nominal",
    "lista nominala",
    "lista nominală",
    "lista candidatilor",
    "lista candidaților",
    "repartizarea candidatilor",
    "repartizarea candidaților",
    "punctajele candidatilor",
    "punctajele candidaților",
    "lista persoanelor",
    "cod candidat",
)
RESULT_TERMS = ("rezultat", "contestati", "contestați", "punctaj")
EXAM_TERMS = (
    "bacalaureat", "evaluare national", "evaluare naț",
    "titularizare", "definitivat", "admitere", "simulare", "proba", "probe",
)
STAFF_TERMS = (
    "director", "detas", "detaș", "mobilitate", "posturi", "post vacant",
    "gradatii", "gradații", "cadre didactice", "metodist",
)
EVENT_TERMS = ("targ", "târg", "eveniment", "invitatie", "invitație", "olimpiad")


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", clean_text(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def canonical_title(value: str) -> str:
    value = clean_text(value)
    value = re.sub(r"(?i)^image\s+", "", value)
    value = EXTENSION.sub("", value)
    return clean_text(value).rstrip("._-")


def official_source_url(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme.casefold() != "https":
        return False
    if parsed.netloc.casefold() not in ALLOWED_HOSTS:
        return False
    return unquote(parsed.path).rstrip("/").casefold() == CANONICAL_PATH.casefold()


class VisibleIndexParser(html.parser.HTMLParser):
    """Collect visible text nodes and anchor-labelled URLs without reading documents."""

    def __init__(self, *, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.skip_depth = 0
        self.anchor_href: str | None = None
        self.anchor_parts: list[str] = []
        self.records: list[tuple[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "a":
            raw = dict(attrs).get("href")
            self.anchor_href = urljoin(self.base_url, raw) if raw else None
            self.anchor_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag == "a" and self.anchor_href is not None:
            text = clean_text(" ".join(self.anchor_parts))
            if text:
                self.records.append((text, self.anchor_href))
            self.anchor_href = None
            self.anchor_parts = []

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = clean_text(data)
        if not text:
            return
        if self.anchor_href is not None:
            self.anchor_parts.append(text)
        else:
            self.records.append((text, None))


def parse_listing_date(text: str, *, reference_year: int | None = None) -> tuple[str | None, str, str]:
    """Return ISO listing date, date status, and the remaining visible title.

    Dates are accepted only when explicit at the start of the listing text. An
    implausible year is preserved as anomalous evidence, never silently fixed.
    """
    match = DATE_PREFIX.match(clean_text(text))
    if not match:
        return None, "MISSING", clean_text(text)
    day, month, year, title = int(match.group(1)), int(match.group(2)), int(match.group(3)), match.group(4)
    reference_year = reference_year or date.today().year
    if year < 2000 or year > reference_year + 2:
        return None, "ANOMALOUS", clean_text(title)
    try:
        parsed = date(year, month, day)
    except ValueError:
        return None, "ANOMALOUS", clean_text(title)
    return parsed.isoformat(), "EXPLICIT_LISTING_DATE", clean_text(title)


def classify(title: str, *, date_status: str) -> str:
    if date_status == "ANOMALOUS":
        return "HOLD"
    value = fold(title)
    if any(fold(term) in value for term in RESULT_TERMS):
        return "EXAM_RESULTS"
    if any(fold(term) in value for term in EXAM_TERMS):
        return "EXAM_OR_ADMISSION_NOTICE"
    if any(fold(term) in value for term in STAFF_TERMS):
        return "STAFFING_OR_MOBILITY"
    if any(fold(term) in value for term in EVENT_TERMS):
        return "EDUCATION_EVENT"
    if "comunicat" in value or "presa" in value:
        return "OTHER_EDUCATION_NOTICE"
    return "OTHER_EDUCATION_NOTICE"


def is_sensitive(title: str) -> bool:
    value = fold(title)
    return any(fold(term) in value for term in SENSITIVE_TERMS)


def attachment_type(title: str, href: str | None) -> str | None:
    for value in (title, href or ""):
        match = EXTENSION.search(value)
        if match:
            return match.group(1).upper()
    return None


def evidence_id(listing_date: str | None, title: str) -> str:
    raw = "\0".join([SOURCE_ID, listing_date or "DATE_UNKNOWN", fold(canonical_title(title))])
    return "isj-edu-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def placeholder_response(html_text: str) -> bool:
    visible = fold(re.sub(r"<[^>]+>", " ", html_text))[:5000]
    return any(fold(term) in visible for term in PLACEHOLDER_TERMS)


def extract_signals(
    html_text: str,
    *,
    final_url: str = SOURCE_URL,
    reference_year: int | None = None,
) -> list[dict[str, Any]]:
    if not official_source_url(final_url):
        raise ValueError(f"ISJ adapter refused unexpected source URL: {final_url}")
    if placeholder_response(html_text):
        raise ValueError("ISJ source returned a placeholder/challenge response")

    parser = VisibleIndexParser(base_url=final_url)
    parser.feed(html_text)
    parser.close()

    by_id: dict[str, dict[str, Any]] = {}
    for raw_text, href in parser.records:
        listing_date, date_status, remainder = parse_listing_date(raw_text, reference_year=reference_year)
        if date_status == "MISSING":
            continue
        title = canonical_title(remainder)
        if len(title) < 8:
            continue

        doc_type = attachment_type(remainder, href)
        sensitive = is_sensitive(title)
        sid = evidence_id(listing_date, title)
        attachment_host = urlsplit(href).netloc.casefold() if href else None
        row = {
            "signal_id": sid,
            "source_id": SOURCE_ID,
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "final_url": final_url,
            "source_tier": SOURCE_TIER,
            "source_kind": SOURCE_KIND,
            "listing_date": listing_date,
            "listing_date_status": date_status,
            "date_semantics": "OFFICIAL_INDEX_LISTING_DATE_NOT_EFFECTIVE_OR_EVENT_DATE",
            "effective_date": None,
            "effective_date_status": "NOT_EXTRACTED_FROM_DOCUMENT_BODY",
            "title": title,
            "signal_class": classify(title, date_status=date_status),
            "attachment_url": href,
            "attachment_type": doc_type,
            "attachment_host": attachment_host,
            "attachment_body_ingest_allowed": False,
            "attachment_fetch_allowed": False,
            "sensitive_document": sensitive,
            "pii_extraction_allowed": False,
            "content_handling": "METADATA_ONLY_SENSITIVE" if sensitive else "METADATA_ONLY",
            "lifecycle": "HOLD_SOURCE_DATE_ANOMALY" if date_status == "ANOMALOUS" else "SIGNAL_ONLY_NEEDS_EDITORIAL_VERIFICATION",
            "publication_authority": "NONE",
            "public_projection": False,
            "auto_publication": False,
            "media_public_reuse_allowed": False,
            "provenance": {
                "authority": "ISJ_VALCEA_OFFICIAL_INDEX",
                "retrieval_surface": SOURCE_URL,
                "metadata_basis": "EXPLICIT_VISIBLE_OFFICIAL_INDEX_TEXT",
                "attachment_basis": "LINK_DISCOVERED_ON_OFFICIAL_INDEX_NOT_FETCHED" if href else "NO_ATTACHMENT_LINK_CAPTURED",
            },
        }
        previous = by_id.get(sid)
        if previous is None or (previous["attachment_url"] is None and href is not None):
            by_id[sid] = row
    return sorted(by_id.values(), key=lambda row: (row["listing_date"] or "9999-99-99", row["title"]), reverse=True)


def html_response_ok(content_type: str, body: bytes) -> bool:
    return "html" in content_type.casefold() or b"<html" in body[:2000].lower()


def fetch_html(url: str = SOURCE_URL) -> tuple[str, str, str]:
    request = Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    with urlopen(request, timeout=20, context=ssl.create_default_context()) as response:
        final_url = str(response.geturl())
        if not official_source_url(final_url):
            raise ValueError(f"ISJ adapter refused redirect outside canonical source: {final_url}")
        body = response.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            raise ValueError("ISJ source response exceeds bounded body limit")
        content_type = str(response.headers.get("Content-Type") or "")
        if not html_response_ok(content_type, body):
            raise ValueError(f"ISJ source did not return HTML: {content_type or 'unknown'}")
        charset = response.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace"), final_url, hashlib.sha256(body).hexdigest()


def build_document(html_text: str, *, final_url: str, content_sha256: str, reference_year: int | None = None) -> dict[str, Any]:
    signals = extract_signals(html_text, final_url=final_url, reference_year=reference_year)
    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR ISJ Vâlcea education signals",
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
            "attachment_fetch_allowed": False,
            "attachment_body_ingest_allowed": False,
            "pii_extraction_allowed": False,
            "mixed_document_feed_metadata_only": True,
            "listing_date_is_not_effective_date": True,
        },
    }


def self_test() -> int:
    sample = """
    <html><body>
      <div>2026</div>
      <div>28.07.2026 Comunicat ISJ_Rezultate CNU de Titularizare 2026</div>
      <a href="https://drive.google.com/file/d/abc/view">28.07.2026 Comunicat ISJ_Rezultate CNU de Titularizare 2026.pdf</a>
      <a href="https://docs.google.com/document/d/xyz">06.03.2026 Comunicat de presă_ISJ Vâlcea.docx</a>
      <div>05.05.2026 Comunicat ISJ _Târgul educational pentru licee</div>
      <a href="https://example.com/nominal.pdf">14.07.2026 TABEL NOMINAL CU CANDIDAȚII - Definitivat.pdf</a>
      <div>11.06.2065 Comunicat ISJ - validare fișe</div>
      <div>Text fără dată care nu trebuie transformat în semnal.</div>
    </body></html>
    """
    signals = extract_signals(sample, reference_year=2026)
    assert len(signals) == 5, signals
    results = [row for row in signals if "Rezultate" in row["title"]]
    assert len(results) == 1
    assert results[0]["signal_class"] == "EXAM_RESULTS"
    assert results[0]["listing_date"] == "2026-07-28"
    assert results[0]["attachment_body_ingest_allowed"] is False
    assert results[0]["effective_date"] is None
    assert results[0]["attachment_url"] == "https://drive.google.com/file/d/abc/view"
    docx = next(row for row in signals if "06.03" not in row["title"] and row["attachment_type"] == "DOCX")
    assert docx["content_handling"] == "METADATA_ONLY"
    sensitive = next(row for row in signals if row["sensitive_document"])
    assert sensitive["pii_extraction_allowed"] is False
    assert sensitive["content_handling"] == "METADATA_ONLY_SENSITIVE"
    assert sensitive["attachment_host"] == "example.com"
    anomaly = next(row for row in signals if row["listing_date_status"] == "ANOMALOUS")
    assert anomaly["listing_date"] is None
    assert anomaly["signal_class"] == "HOLD"
    assert anomaly["lifecycle"] == "HOLD_SOURCE_DATE_ANOMALY"
    assert all(row["publication_authority"] == "NONE" for row in signals)
    assert all(row["auto_publication"] is False for row in signals)
    assert all(row["attachment_fetch_allowed"] is False for row in signals)
    assert official_source_url(SOURCE_URL)
    assert official_source_url("https://isjvalcea.ro/avizier/comunicate-de-pres%C4%83/")
    assert not official_source_url("https://example.com/avizier/comunicate-de-pres%C4%83")
    try:
        extract_signals(sample, final_url="https://example.com/avizier/comunicate-de-pres%C4%83", reference_year=2026)
    except ValueError:
        pass
    else:
        raise AssertionError("off-domain source URL must fail closed")
    challenge = "<html><body>Enable JavaScript to continue CAPTCHA</body></html>"
    try:
        extract_signals(challenge, reference_year=2026)
    except ValueError:
        pass
    else:
        raise AssertionError("challenge response must fail closed")
    doc = build_document(sample, final_url=SOURCE_URL, content_sha256="abc", reference_year=2026)
    assert doc["policy"]["mixed_document_feed_metadata_only"] is True
    assert doc["policy"]["listing_date_is_not_effective_date"] is True
    print("VÂLCEA CLAR ISJ education signal adapter self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    html_text, final_url, body_sha = fetch_html()
    document = build_document(html_text, final_url=final_url, content_sha256=body_sha)
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "source_id": SOURCE_ID,
        "signal_count": document["signal_count"],
        "publication_authority": "NONE",
        "output": str(args.output) if args.output else None,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
