#!/usr/bin/env python3
"""Deterministic publication-date provenance resolver for LOCAL NEWS OS.

The resolver is deliberately fail-closed. It prefers article-level structured
publication metadata, then an article-scoped date immediately after the H1,
and only then a unique plain-text date across the page. It never treats the
first arbitrary page date as publication time when multiple page dates exist.

This module has no instance identity, brand, geography or source-specific
constants and is safe to reuse across LOCAL NEWS OS instances.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from zoneinfo import ZoneInfo

RO_MONTHS = {
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

NUMERIC_DATE_RE = re.compile(r"\b([0-3]?\d)[\s.\-/]+([01]?\d)[\s.\-/]+(20\d{2})\b", re.I)
MONTH_NAME_RE = re.compile(
    rf"\b([0-3]?\d)\s+({'|'.join(RO_MONTHS)})\s+(20\d{{2}})\b",
    re.I,
)


@dataclass(frozen=True)
class DateCandidate:
    published_at: datetime
    provenance: str
    priority: int
    offset: int


@dataclass(frozen=True)
class PublicationDateResolution:
    published_at: datetime | None
    provenance: str | None
    status: str
    candidate_count: int
    distinct_days: tuple[str, ...]


def clean_text(value: str) -> str:
    value = html.unescape(re.sub(r"<[^>]+>", " ", value or ""))
    return re.sub(r"\s+", " ", value).strip()


def parse_iso(value: str, timezone: ZoneInfo) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(html.unescape(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def _plain_candidates(fragment: str, timezone: ZoneInfo, provenance: str, priority: int) -> list[DateCandidate]:
    plain = clean_text(fragment).casefold()
    result: list[DateCandidate] = []
    for match in NUMERIC_DATE_RE.finditer(plain):
        try:
            value = datetime(int(match.group(3)), int(match.group(2)), int(match.group(1)), 12, 0, tzinfo=timezone)
        except ValueError:
            continue
        result.append(DateCandidate(value, provenance, priority, match.start()))
    for match in MONTH_NAME_RE.finditer(plain):
        try:
            value = datetime(
                int(match.group(3)),
                RO_MONTHS[match.group(2).casefold()],
                int(match.group(1)),
                12,
                0,
                tzinfo=timezone,
            )
        except ValueError:
            continue
        result.append(DateCandidate(value, provenance, priority, match.start()))
    return sorted(result, key=lambda item: item.offset)


def _structured_candidates(text: str, timezone: ZoneInfo) -> list[DateCandidate]:
    patterns: tuple[tuple[str, str, int], ...] = (
        (r'"datePublished"\s*:\s*"([^"]+)"', "structured.datePublished", 100),
        (
            r'<meta\b(?=[^>]*(?:property|name)=["\'](?:article:published_time|datePublished)["\'])'
            r'(?=[^>]*content=["\']([^"\']+)["\'])[^>]*>',
            "meta.article_published",
            100,
        ),
        (r'<time\b[^>]*datetime=["\']([^"\']+)["\']', "time.datetime", 90),
    )
    result: list[DateCandidate] = []
    for pattern, provenance, priority in patterns:
        for match in re.finditer(pattern, text, flags=re.I | re.S):
            parsed = parse_iso(match.group(1), timezone)
            if parsed is not None:
                result.append(DateCandidate(parsed, provenance, priority, match.start()))
    return result


def _distinct_days(candidates: Iterable[DateCandidate]) -> tuple[str, ...]:
    return tuple(sorted({candidate.published_at.date().isoformat() for candidate in candidates}))


def _select_same_day(candidates: list[DateCandidate], status: str) -> PublicationDateResolution:
    if not candidates:
        return PublicationDateResolution(None, None, "REJECT_NO_DATE", 0, ())
    days = _distinct_days(candidates)
    if len(days) != 1:
        return PublicationDateResolution(None, None, "REJECT_AMBIGUOUS_DATE", len(candidates), days)
    selected = sorted(candidates, key=lambda item: (-item.priority, item.offset))[0]
    return PublicationDateResolution(
        selected.published_at,
        selected.provenance,
        status,
        len(candidates),
        days,
    )


def resolve_publication_date(
    text: str,
    *,
    timezone: ZoneInfo,
    article_scope_chars: int = 6000,
    page_scope_chars: int = 500_000,
) -> PublicationDateResolution:
    """Resolve article publication time with explicit provenance and ambiguity gates."""
    structured = _structured_candidates(text, timezone)
    if structured:
        top_priority = max(candidate.priority for candidate in structured)
        top = [candidate for candidate in structured if candidate.priority == top_priority]
        return _select_same_day(top, "PASS_STRUCTURED_DATE")

    h1 = re.search(r"<h1\b[^>]*>.*?</h1\s*>", text, flags=re.I | re.S)
    if h1:
        scoped = text[h1.end() : h1.end() + article_scope_chars]
        article_dates = _plain_candidates(scoped, timezone, "article_scope.after_h1", 70)
        if article_dates:
            # Publication dates are normally adjacent to the headline. Choose the
            # first article-scoped date rather than scanning global chrome.
            selected = article_dates[0]
            return PublicationDateResolution(
                selected.published_at,
                selected.provenance,
                "PASS_ARTICLE_SCOPED_DATE",
                len(article_dates),
                _distinct_days(article_dates),
            )

    page_dates = _plain_candidates(text[:page_scope_chars], timezone, "page_plain_unique", 40)
    if page_dates:
        # Plain full-page text is accepted only when it contains exactly one
        # distinct calendar day. Multiple days are ambiguous and fail closed.
        return _select_same_day(page_dates, "PASS_UNIQUE_PAGE_DATE")

    return PublicationDateResolution(None, None, "REJECT_NO_DATE", 0, ())


def self_test() -> int:
    tz = ZoneInfo("Europe/Bucharest")

    structured = '<html><head><meta property="article:published_time" content="2026-08-15T07:30:00+03:00"></head><body><h1>Știre</h1></body></html>'
    result = resolve_publication_date(structured, timezone=tz)
    assert result.status == "PASS_STRUCTURED_DATE"
    assert result.published_at == datetime(2026, 8, 15, 7, 30, tzinfo=tz)
    assert result.provenance == "meta.article_published"

    # Regression fixture from the VÂLCEA pilot pattern: a global/current date
    # appears before the article H1 while the real article date follows it.
    global_before_article = (
        '<html><body><header>15/08/2026</header>'
        '<h1>Locuri de muncă vacante la nivel județean – 30 iunie 2026</h1>'
        '<div class="entry-meta">30/06/2026 Comunicate de presă</div>'
        '</body></html>'
    )
    result = resolve_publication_date(global_before_article, timezone=tz)
    assert result.status == "PASS_ARTICLE_SCOPED_DATE"
    assert result.published_at == datetime(2026, 6, 30, 12, 0, tzinfo=tz)
    assert result.provenance == "article_scope.after_h1"

    ambiguous = '<html><body><div>15/08/2026</div><div>30/06/2026</div></body></html>'
    result = resolve_publication_date(ambiguous, timezone=tz)
    assert result.status == "REJECT_AMBIGUOUS_DATE"
    assert result.published_at is None

    unique = '<html><body><div>Publicat 14 august 2026</div></body></html>'
    result = resolve_publication_date(unique, timezone=tz)
    assert result.status == "PASS_UNIQUE_PAGE_DATE"
    assert result.published_at == datetime(2026, 8, 14, 12, 0, tzinfo=tz)

    print("LOCAL NEWS OS publication-date provenance self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
