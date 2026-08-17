#!/usr/bin/env python3
"""Fail-closed guard against stale relative-time language in durable news copy.

Canonical story pages and durable editorial records must remain true when read
later. Relative terms such as "today", "tomorrow" or their locale equivalents
are therefore not allowed in durable headline/dek/body copy. Ephemeral channel
packaging may implement its own same-day freshness logic separately.

The module is instance-neutral: locale selects language rules; no publication,
geography, brand or account identifiers are embedded here.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

CONTRACT = "LOCAL_NEWS_OS_DURABLE_TEMPORAL_LANGUAGE_V1"

_LOCALE_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "ro": tuple(
        re.compile(pattern, re.I)
        for pattern in (
            r"\bazi\b",
            r"\bastăzi\b",
            r"\bastazi\b",
            r"\bmâine\b",
            r"\bmaine\b",
            r"\bpoimâine\b",
            r"\bpoimaine\b",
            r"\bieri\b",
            r"\balaltăieri\b",
            r"\balaltaieri\b",
            r"\bacum\b",
            r"\bdiseară\b",
            r"\bdiseara\b",
            r"\bîn această dimineață\b",
            r"\bin aceasta dimineata\b",
            r"\bîn această seară\b",
            r"\bin aceasta seara\b",
            r"\bîn seara asta\b",
            r"\bin seara asta\b",
            r"\bîn această săptămână\b",
            r"\bin aceasta saptamana\b",
            r"\bsăptămâna aceasta\b",
            r"\bsaptamana aceasta\b",
            r"\bweekendul acesta\b",
            r"\bîn acest weekend\b",
            r"\bin acest weekend\b",
            r"\bîn această lună\b",
            r"\bin aceasta luna\b",
            r"\bluna aceasta\b",
            r"\bîn acest an\b",
            r"\bin acest an\b",
            r"\banul acesta\b",
            r"\bîn zilele următoare\b",
            r"\bin zilele urmatoare\b",
            r"\bîn următoarele zile\b",
            r"\bin urmatoarele zile\b",
        )
    ),
    "en": tuple(
        re.compile(pattern, re.I)
        for pattern in (
            r"\btoday\b",
            r"\btomorrow\b",
            r"\byesterday\b",
            r"\bthe day after tomorrow\b",
            r"\bthe day before yesterday\b",
            r"\btonight\b",
            r"\bthis morning\b",
            r"\bthis evening\b",
            r"\bthis week\b",
            r"\bthis weekend\b",
            r"\bthis month\b",
            r"\bthis year\b",
            r"\bin the coming days\b",
            r"\bin the next few days\b",
        )
    ),
}


def _language_key(locale: str | None) -> str:
    raw = str(locale or "").strip().lower().replace("_", "-")
    return raw.split("-", 1)[0] if raw else ""


def _public_strings(item: dict) -> Iterable[tuple[str, str]]:
    for field in ("headline", "dek"):
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            yield field, value

    for index, value in enumerate(item.get("paragraphs") or []):
        if isinstance(value, str) and value.strip():
            yield f"paragraphs[{index}]", value

    for index, row in enumerate(item.get("factbox") or []):
        if not isinstance(row, dict):
            continue
        for field in ("label", "value"):
            value = row.get(field)
            if isinstance(value, str) and value.strip():
                yield f"factbox[{index}].{field}", value

    for section_index, section in enumerate(item.get("article_sections") or []):
        if not isinstance(section, dict):
            continue
        title = section.get("title")
        if isinstance(title, str) and title.strip():
            yield f"article_sections[{section_index}].title", title
        for field in ("paragraphs", "bullets"):
            for value_index, value in enumerate(section.get(field) or []):
                if isinstance(value, str) and value.strip():
                    yield f"article_sections[{section_index}].{field}[{value_index}]", value


def durable_story_temporal_violations(item: dict, locale: str | None) -> list[dict]:
    """Return all relative-time terms found in durable public story copy."""
    patterns = _LOCALE_PATTERNS.get(_language_key(locale), ())
    violations: list[dict] = []
    for path, text in _public_strings(item):
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                violations.append({
                    "contract": CONTRACT,
                    "path": path,
                    "term": match.group(0),
                    "text": text,
                })
    return violations


def durable_story_temporal_safe(item: dict, locale: str | None) -> bool:
    return not durable_story_temporal_violations(item, locale)


def self_test() -> int:
    absolute = {
        "headline": "Festivalul are loc în 17 august 2026",
        "dek": "Programul pentru 17 august este confirmat de organizator.",
        "paragraphs": ["Accesul începe la ora 18:00 în 17 august 2026."],
    }
    assert durable_story_temporal_violations(absolute, "ro-RO") == []

    relative = dict(absolute, headline="Azi are loc festivalul din centru")
    hits = durable_story_temporal_violations(relative, "ro-RO")
    assert hits and hits[0]["path"] == "headline"
    assert hits[0]["term"].casefold() == "azi"

    nested = {
        "headline": "Program verificat pentru 17 august 2026",
        "dek": "Date confirmate.",
        "paragraphs": [],
        "article_sections": [{"title": "Program", "paragraphs": ["În această seară începe programul."], "bullets": []}],
    }
    assert durable_story_temporal_violations(nested, "ro-RO")

    english = {"headline": "Today the council meets", "dek": "Confirmed agenda", "paragraphs": ["Agenda is public."]}
    assert durable_story_temporal_violations(english, "en-US")

    print(f"{CONTRACT} self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
