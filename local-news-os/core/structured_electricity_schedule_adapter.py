#!/usr/bin/env python3
"""Fetch official weekly electricity schedules and parse evidence-only outages.

The adapter is intentionally generic. It discovers only links whose visible text
contains an explicit weekly date range, selects documents that intersect the
configured planning window, extracts text from HTML/plain-text or PDF documents,
and delegates row interpretation to ``structured_electricity_interruption_parser``.
No crawl timestamp becomes source freshness and no reader-facing copy is made.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener
from zoneinfo import ZoneInfo

import structured_electricity_interruption_parser as electricity

USER_AGENT = "Mozilla/5.0 (compatible; LocalNewsOS/1.0; +https://valceaclar.ro/)"
MAX_LISTING_BYTES = 2_500_000
MAX_DOCUMENT_BYTES = 12_000_000
WEEK_RANGE_RE = re.compile(
    r"\b(?:intreruperi|întreruperi)\s+(\d{1,2})[./](\d{1,2})\s*[-–—]\s*"
    r"(\d{1,2})[./](\d{1,2})[./](20\d{2})\b",
    re.I,
)


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return
        self._href = next((value for key, value in attrs if key.casefold() == "href" and value), None)
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "a" or self._href is None:
            return
        label = clean(" ".join(self._parts))
        if label:
            self.rows.append((self._href, label))
        self._href = None
        self._parts = []


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = clean(data)
        if value:
            self.parts.append(value)


@dataclass(frozen=True)
class WeeklyDocument:
    label: str
    url: str
    start_date: date
    end_date: date


def _range_dates(match: re.Match[str]) -> tuple[date, date] | None:
    start_day, start_month, end_day, end_month, end_year = (int(match.group(i)) for i in range(1, 6))
    start_year = end_year - 1 if start_month > end_month else end_year
    try:
        start = date(start_year, start_month, start_day)
        end = date(end_year, end_month, end_day)
    except ValueError:
        return None
    return (start, end) if end >= start else None


def discover_weekly_documents(listing_html: str, listing_url: str) -> list[WeeklyDocument]:
    parser = _AnchorParser()
    parser.feed(listing_html)
    rows: list[WeeklyDocument] = []
    seen: set[str] = set()
    for href, label in parser.rows:
        match = WEEK_RANGE_RE.search(label)
        if not match:
            continue
        dates = _range_dates(match)
        if not dates:
            continue
        url = urljoin(listing_url, href)
        if not url.startswith("https://") or url in seen:
            continue
        seen.add(url)
        rows.append(WeeklyDocument(label=label, url=url, start_date=dates[0], end_date=dates[1]))
    rows.sort(key=lambda row: (row.start_date, row.end_date), reverse=True)
    return rows


def relevant_documents(
    documents: list[WeeklyDocument],
    now: datetime,
    *,
    planning_horizon_hours: int,
    expiry_grace_hours: int,
    max_documents: int = 3,
) -> list[WeeklyDocument]:
    local_day = now.date()
    lower = (now - timedelta(hours=int(expiry_grace_hours))).date()
    upper = (now + timedelta(hours=int(planning_horizon_hours))).date()
    rows = [row for row in documents if row.end_date >= lower and row.start_date <= upper]
    rows.sort(key=lambda row: (abs((row.start_date - local_day).days), row.start_date))
    return rows[: max(1, int(max_documents))]


def fetch_bytes(url: str, *, max_bytes: int, timeout: int = 20) -> tuple[bytes, str, str]:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/pdf,text/plain,*/*;q=0.5",
            "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.5",
            "Cache-Control": "no-cache",
        },
    )
    # Some primary-source CMSes issue a same-URL 302 while setting a locale or
    # session cookie. Plain urlopen drops that state and sees an infinite loop;
    # a per-fetch cookie jar preserves the server's redirect contract without
    # weakening HTTPS, provenance, or freshness gates.
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    with opener.open(request, timeout=timeout) as response:
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ValueError(f"response exceeds {max_bytes} bytes")
        content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().casefold()
        return body, response.geturl(), content_type


def _decode_text(body: bytes) -> str:
    for encoding in ("utf-8", "windows-1250", "latin-1"):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="replace")


def _html_text(body: bytes) -> str:
    parser = _TextParser()
    parser.feed(_decode_text(body))
    return "\n".join(parser.parts)


def _pdf_text(body: bytes) -> str:
    executable = shutil.which("pdftotext")
    if not executable:
        raise RuntimeError("pdftotext unavailable")
    with tempfile.TemporaryDirectory(prefix="electricity-schedule-") as temp_dir:
        source = Path(temp_dir) / "schedule.pdf"
        source.write_bytes(body)
        process = subprocess.run(
            [executable, "-layout", str(source), "-"],
            capture_output=True,
            check=False,
            timeout=30,
        )
        if process.returncode != 0:
            stderr = process.stderr.decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"pdftotext failed ({process.returncode}): {stderr}")
        text = process.stdout.decode("utf-8", errors="replace")
        if not clean(text):
            raise RuntimeError("pdftotext returned empty text")
        return text


def extract_document_text(body: bytes, content_type: str, final_url: str) -> tuple[str, str]:
    lowered_url = final_url.casefold()
    if body.startswith(b"%PDF") or content_type == "application/pdf" or lowered_url.endswith(".pdf"):
        return _pdf_text(body), "pdf_pdftotext_layout"
    if content_type in {"text/html", "application/xhtml+xml"} or b"<html" in body[:1000].casefold():
        return _html_text(body), "html_text"
    if content_type.startswith("text/"):
        return _decode_text(body), "plain_text"
    raise RuntimeError(f"unsupported electricity schedule document type: {content_type or 'unknown'}")


def normalize_events(
    events: list[dict[str, Any]],
    source: dict[str, Any],
    document: WeeklyDocument,
    final_url: str,
    extraction_method: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        structured = event.get("structured") or {}
        if structured.get("utility") != "electricity":
            continue
        event_key = str(event.get("event_key") or "").strip()
        if not event_key:
            continue
        rows.append(
            {
                "event_id": event_key,
                "source_id": source["id"],
                "source_name": source["name"],
                "source_tier": source["source_tier"],
                "source_url": final_url,
                "parser": electricity.PARSER_ID,
                "event_start": event["event_start"],
                "event_end": event["event_end"],
                "source_time_basis": event["source_time_basis"],
                "body_sha256": event["body_sha256"],
                "structured": {
                    **structured,
                    "schedule_label": document.label,
                    "schedule_start": document.start_date.isoformat(),
                    "schedule_end": document.end_date.isoformat(),
                    "document_extraction": extraction_method,
                },
                "publication_authority": "PRIMARY_STRUCTURED_EVENT_ONLY",
                "reader_copy_generated": False,
            }
        )
    return rows


def collect_electricity_source(source: dict[str, Any], tz: ZoneInfo, now: datetime) -> dict[str, Any]:
    try:
        listing_body, listing_url, listing_type = fetch_bytes(
            str(source["url"]), max_bytes=MAX_LISTING_BYTES, timeout=20
        )
        if listing_type not in {"text/html", "application/xhtml+xml", ""} and b"<html" not in listing_body[:1000].casefold():
            raise RuntimeError(f"listing is not HTML: {listing_type}")
        listing_html = _decode_text(listing_body)
        discovered = discover_weekly_documents(listing_html, listing_url)
        selected = relevant_documents(
            discovered,
            now,
            planning_horizon_hours=int(source.get("planning_horizon_hours") or 336),
            expiry_grace_hours=int(source.get("expiry_grace_hours") or 1),
            max_documents=int(source.get("max_schedule_documents") or 3),
        )
        if not selected:
            return {
                "source_id": source.get("id"),
                "status": "PASS_NO_RELEVANT_SCHEDULE",
                "listing_url": listing_url,
                "documents_discovered": len(discovered),
                "documents_selected": 0,
                "events": [],
            }

        events: list[dict[str, Any]] = []
        reports: list[dict[str, Any]] = []
        for document in selected:
            body, final_url, content_type = fetch_bytes(document.url, max_bytes=MAX_DOCUMENT_BYTES, timeout=25)
            text, extraction_method = extract_document_text(body, content_type, final_url)
            # Prefix the explicit weekly label so rows that print only dd.mm can
            # inherit a year from the source document rather than crawl time.
            parse_text = document.label + "\n" + text
            parsed, candidates = electricity.parse_electricity_interruption_text(
                parse_text,
                tz,
                now,
                planning_horizon_hours=int(source.get("planning_horizon_hours") or 336),
                expiry_grace_hours=int(source.get("expiry_grace_hours") or 1),
                max_candidates=int(source.get("max_listing_candidates") or 120),
            )
            normalized = normalize_events(parsed, source, document, final_url, extraction_method)
            events.extend(normalized)
            reports.append(
                {
                    "label": document.label,
                    "url": final_url,
                    "content_type": content_type,
                    "extraction_method": extraction_method,
                    "body_sha256": hashlib.sha256(body).hexdigest(),
                    "candidates": candidates,
                    "events": len(normalized),
                }
            )

        deduped = {str(row["event_id"]): row for row in events}
        rows = sorted(deduped.values(), key=lambda row: (row["event_start"], row["event_id"]))
        return {
            "source_id": source["id"],
            "status": "PASS",
            "listing_url": listing_url,
            "documents_discovered": len(discovered),
            "documents_selected": len(selected),
            "documents": reports,
            "events": rows,
        }
    except Exception as exc:
        return {
            "source_id": source.get("id"),
            "status": "DEGRADED",
            "error": f"{type(exc).__name__}: {exc}",
            "events": [],
        }


def self_test() -> int:
    listing = """
    <html><body>
      <a href="/docs/old.pdf">Valcea - Intreruperi 17.08 - 23.08.2026</a>
      <a href="/docs/current.pdf"><span>Valcea - Intreruperi 24.08 - 30.08.2026</span></a>
      <a href="https://files.example/next.pdf">Valcea - Intreruperi 31.08 - 06.09.2026</a>
      <a href="/other">Informatii generale</a>
    </body></html>
    """
    docs = discover_weekly_documents(listing, "https://operator.example/valcea.html")
    assert len(docs) == 3
    assert docs[0].start_date.isoformat() == "2026-08-31"
    assert docs[1].url == "https://operator.example/docs/current.pdf"
    now = datetime(2026, 8, 27, 18, 0, tzinfo=ZoneInfo("Europe/Bucharest"))
    selected = relevant_documents(docs, now, planning_horizon_hours=336, expiry_grace_hours=1)
    assert [row.start_date.isoformat() for row in selected] == ["2026-08-24", "2026-08-31"]

    rollover = discover_weekly_documents(
        '<a href="/x.pdf">Valcea - Intreruperi 29.12 - 04.01.2026</a>',
        "https://operator.example/",
    )
    assert rollover[0].start_date.isoformat() == "2025-12-29"
    assert rollover[0].end_date.isoformat() == "2026-01-04"
    print("STRUCTURED_ELECTRICITY_SCHEDULE_ADAPTER_SELF_TEST_PASS")
    return 0


def live_probe(source_url: str, *, source_name: str = "Electricity operator probe") -> int:
    tz = ZoneInfo("Europe/Bucharest")
    now = datetime.now(tz)
    result = collect_electricity_source(
        {
            "id": "electricity-live-probe",
            "name": source_name,
            "url": source_url,
            "source_tier": "T1",
            "planning_horizon_hours": 336,
            "expiry_grace_hours": 1,
            "max_listing_candidates": 120,
            "max_schedule_documents": 3,
        },
        tz,
        now,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "PASS":
        return 2
    documents = result.get("documents") or []
    if not documents or not any(int(row.get("candidates") or 0) > 0 for row in documents):
        return 3
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--live-probe-url")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.live_probe_url:
        return live_probe(args.live_probe_url)
    parser.error("use --self-test or --live-probe-url")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
