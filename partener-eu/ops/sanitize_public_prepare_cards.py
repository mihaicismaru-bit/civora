#!/usr/bin/env python3
"""Sanitize stale filing-window snippets from PARTENER.EU prepare-card summaries.

This is a render-only guard. Canonical dossiers and detail-page evidence are not
modified. Only generic audience paragraphs inside static cards whose lifecycle is
EXPECTED/ANNOUNCED/UPCOMING/PREPARE_NOW are eligible for suppression, and only
when they explicitly state an application window that is already over at the
canonical decision-products clock.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRODUCTS = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
DEFAULT_WEB = ROOT / "partener-eu" / "web"
RO_TZ = dt.timezone(dt.timedelta(hours=3))
PREPARE_STATUS_CLASSES = {
    "status-expected",
    "status-announced",
    "status-upcoming",
    "status-prepare_now",
    "status-prepare-now",
}
ARTICLE_RE = re.compile(r'<article class="staticCard"[^>]*>.*?</article>', re.S)
PLAIN_PARAGRAPH_RE = re.compile(r'(?P<full>\s*<p>(?P<body>.*?)</p>)', re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
NUMERIC_RANGE_RE = re.compile(
    r"\b(?:perioada\s+)?\d{1,2}[./]\d{1,2}(?:[./](?:20)?\d{2})?\s*[-–—]\s*"
    r"(?P<day>\d{1,2})[./](?P<month>\d{1,2})[./](?P<year>20\d{2})\b",
    re.I,
)
TEXT_RANGE_RE = re.compile(
    r"\b(?:perioada\s+)?\d{1,2}\s+(?:ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)"
    r"(?:\s+20\d{2})?\s*[-–—]\s*(?P<day>\d{1,2})\s+"
    r"(?P<month>ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)\s+"
    r"(?P<year>20\d{2})\b",
    re.I,
)
ISO_RANGE_RE = re.compile(
    r"\b(?:perioada\s+)?20\d{2}-\d{2}-\d{2}\s*[-–—]\s*(?P<year>20\d{2})-(?P<month>\d{2})-(?P<day>\d{2})\b",
    re.I,
)
MONTHS = {
    "ianuarie": 1,
    "februarie": 2,
    "martie": 3,
    "aprilie": 4,
    "mai": 5,
    "iunie": 6,
    "iulie": 7,
    "august": 8,
    "septembrie": 9,
    "octombrie": 10,
    "noiembrie": 11,
    "decembrie": 12,
}


def fold(value: Any) -> str:
    import unicodedata

    text = "".join(
        ch
        for ch in unicodedata.normalize("NFKD", str(value or ""))
        if not unicodedata.combining(ch)
    )
    return re.sub(r"\s+", " ", text.lower()).strip()


def parse_clock(value: Any) -> dt.datetime:
    raw = str(value or "").strip()
    if not raw:
        return dt.datetime.now(dt.timezone.utc)
    parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def end_of_day(year: int, month: int, day: int) -> dt.datetime | None:
    try:
        return dt.datetime(year, month, day, 23, 59, 59, tzinfo=RO_TZ).astimezone(dt.timezone.utc)
    except ValueError:
        return None


def application_window_end(value: Any) -> dt.datetime | None:
    """Parse only explicit application-period ranges, never arbitrary dates."""
    text = fold(value)
    if "cererile de finantare se pot depune in perioada" not in text:
        return None

    match = NUMERIC_RANGE_RE.search(text)
    if match:
        return end_of_day(int(match.group("year")), int(match.group("month")), int(match.group("day")))

    match = TEXT_RANGE_RE.search(text)
    if match:
        return end_of_day(
            int(match.group("year")), MONTHS[match.group("month").lower()], int(match.group("day"))
        )

    match = ISO_RANGE_RE.search(text)
    if match:
        return end_of_day(int(match.group("year")), int(match.group("month")), int(match.group("day")))

    return None


def historical_application_window(value: Any, clock: dt.datetime) -> bool:
    closes = application_window_end(value)
    return closes is not None and closes < clock.astimezone(dt.timezone.utc)


def plain_text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", fragment))).strip()


def is_prepare_card(article: str) -> bool:
    return any(css_class in article for css_class in PREPARE_STATUS_CLASSES)


def sanitize_article(article: str, clock: dt.datetime) -> tuple[str, int]:
    if not is_prepare_card(article):
        return article, 0
    removed = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal removed
        text = plain_text(match.group("body"))
        if historical_application_window(text, clock):
            removed += 1
            return ""
        return match.group("full")

    return PLAIN_PARAGRAPH_RE.sub(replace, article), removed


def sanitize_html(raw: str, clock: dt.datetime) -> tuple[str, int]:
    removed = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal removed
        article, count = sanitize_article(match.group(0), clock)
        removed += count
        return article

    return ARTICLE_RE.sub(replace, raw), removed


def scan_unsafe(raw: str, clock: dt.datetime) -> int:
    unsafe = 0
    for article_match in ARTICLE_RE.finditer(raw):
        article = article_match.group(0)
        if not is_prepare_card(article):
            continue
        for p_match in PLAIN_PARAGRAPH_RE.finditer(article):
            if historical_application_window(plain_text(p_match.group("body")), clock):
                unsafe += 1
    return unsafe


def decision_clock(products: Path) -> dt.datetime:
    payload = json.loads(products.read_text(encoding="utf-8"))
    return parse_clock(payload.get("generatedAt"))


def update_manifest(web_root: Path, suppressed: int) -> None:
    path = web_root / "static-public-manifest.json"
    if not path.exists():
        return
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["prepareCardHistoricalWindowsSuppressed"] = suppressed
    manifest.setdefault("policy", {})["historicalFilingWindowsHiddenFromPrepareCards"] = True
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sanitize_tree(web_root: Path, clock: dt.datetime) -> tuple[int, int]:
    changed_files = 0
    suppressed = 0
    for path in sorted(web_root.rglob("*.html")):
        raw = path.read_text(encoding="utf-8")
        clean, count = sanitize_html(raw, clock)
        if count:
            path.write_text(clean, encoding="utf-8")
            changed_files += 1
            suppressed += count
    update_manifest(web_root, suppressed)
    return changed_files, suppressed


def check_tree(web_root: Path, clock: dt.datetime) -> int:
    unsafe = 0
    for path in sorted(web_root.rglob("*.html")):
        raw = path.read_text(encoding="utf-8")
        count = scan_unsafe(raw, clock)
        if count:
            print(f"FAIL {path}: {count} expired filing-window snippet(s) remain in prepare cards", file=sys.stderr)
            unsafe += count
    manifest_path = web_root / "static-public-manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not (manifest.get("policy") or {}).get("historicalFilingWindowsHiddenFromPrepareCards"):
            print("FAIL static-public-manifest missing historical filing-window projection policy", file=sys.stderr)
            unsafe += 1
    return unsafe


def self_test() -> None:
    clock = parse_clock("2026-09-24T12:00:00Z")
    old_numeric = "Cererile de finanțare se pot depune în perioada 31.01-31.03.2025 prin MySMIS 2021."
    old_text = "Cererile de finanțare se pot depune în perioada 20 iunie 2025 – 7 august 2025 prin MySMIS 2021."
    future = "Cererile de finanțare se pot depune în perioada 28.09-20.11.2026 prin MySMIS 2021."
    unrelated = "Document actualizat la 31.03.2025; solicitant eligibil: UAT."
    assert historical_application_window(old_numeric, clock)
    assert historical_application_window(old_text, clock)
    assert not historical_application_window(future, clock)
    assert not historical_application_window(unrelated, clock)

    fixture = f'''<article class="staticCard" data-dossier-id="prepare-old">
<span class="status status-expected">ÎN PREGĂTIRE</span>
<p class="standfirst">Oportunitate în pregătire.</p><div class="cardFacts"></div>
<p>{old_numeric}</p><a>Deschide dosarul</a></article>
<article class="staticCard" data-dossier-id="prepare-future">
<span class="status status-upcoming">ÎN PREGĂTIRE</span><p>{future}</p></article>
<article class="staticCard" data-dossier-id="open-old">
<span class="status status-open">DESCHIS</span><p>{old_numeric}</p></article>'''
    clean, removed = sanitize_html(fixture, clock)
    assert removed == 1, removed
    assert old_numeric not in re.search(r'data-dossier-id="prepare-old".*?</article>', clean, re.S).group(0)
    assert "Oportunitate în pregătire." in clean
    assert future in clean
    assert old_numeric in re.search(r'data-dossier-id="open-old".*?</article>', clean, re.S).group(0)
    assert scan_unsafe(clean, clock) == 0
    print("PASS prepare-card historical filing-window sanitizer regression")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--products", type=Path, default=DEFAULT_PRODUCTS)
    parser.add_argument("--web-root", type=Path, default=DEFAULT_WEB)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0

    clock = decision_clock(args.products)
    if args.check:
        unsafe = check_tree(args.web_root, clock)
        if unsafe:
            return 2
        print("PASS no expired application-window snippets remain in prepare-card summaries")
        return 0

    changed_files, suppressed = sanitize_tree(args.web_root, clock)
    print(json.dumps({
        "changedFiles": changed_files,
        "suppressedPrepareCardHistoricalWindows": suppressed,
        "clock": clock.isoformat(),
        "canonicalDossiersModified": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
