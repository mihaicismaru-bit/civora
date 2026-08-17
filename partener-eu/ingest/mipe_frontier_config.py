#!/usr/bin/env python3
"""Small, testable frontier extensions for the Romanian MIPE browser collector."""
from __future__ import annotations

from typing import Any

CALENDAR_URL = "https://mfe.gov.ro/calendar-apeluri-de-proiecte/"
CALENDAR_SCOPE = "/calendar-apeluri-de-proiecte/"
CALENDAR_KEYWORDS = ("calendar", "lansar")


def extend_frontier(collector: Any) -> None:
    """Add the official consolidated calls calendar without weakening filters.

    The v2 collector intentionally treats every explicit seed as a listing page.
    The consolidated calendar is different: the page itself is decision-useful
    evidence because it carries the authoritative document links. We therefore
    keep it as an explicit root but allow it to be accepted as a normal verified
    item when it passes the existing semantic quality gates.
    """
    if getattr(collector, "_partener_calendar_frontier_applied", False):
        return

    scopes = tuple(getattr(collector, "SCOPES", ()))
    if CALENDAR_SCOPE not in scopes:
        collector.SCOPES = (*scopes, CALENDAR_SCOPE)

    seeds = list(getattr(collector, "SEEDS", ()))
    if CALENDAR_URL not in seeds:
        seeds.append(CALENDAR_URL)
        collector.SEEDS = seeds

    keywords = list(getattr(collector, "KW", ()))
    for token in CALENDAR_KEYWORDS:
        if token not in keywords:
            keywords.append(token)
    collector.KW = keywords

    original_is_listing_url = collector.is_listing_url

    def is_listing_url(url: str) -> bool:
        if str(url or "").rstrip("/") == CALENDAR_URL.rstrip("/"):
            return False
        return original_is_listing_url(url)

    collector.is_listing_url = is_listing_url
    collector._partener_calendar_frontier_applied = True
