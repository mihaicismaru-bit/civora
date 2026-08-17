#!/usr/bin/env python3
"""Shared story-level social interest/freshness policy for VÂLCEA CLAR.

The site may preserve a dated service-news record after the underlying condition
has expired. Social distribution is stricter: transient traffic/service updates
must still be timely unless the story contains a durable material consequence
(e.g. casualties or a documented incident) that remains newsworthy as a dated
report. This module never grants publication authority by itself; callers must
also enforce the canonical newsroom story-ready gate and platform-specific
rules.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Bucharest")

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

TRANSIENT_TERMS = (
    "trafic alternativ",
    "trafic oprit",
    "trafic blocat",
    "circulație alternativ",
    "circulatie alternativ",
    "restricții de trafic",
    "restrictii de trafic",
    "se circulă alternativ",
    "se circula alternativ",
)

DURABLE_CONSEQUENCE_TERMS = (
    "victim",
    "rănit",
    "ranit",
    "deced",
    "persoană decedată",
    "persoana decedata",
    "accident",
    "incident rutier",
    "colizi",
    "incend",
    "exploz",
)


def corpus(story: dict[str, Any]) -> str:
    paragraphs = story.get("paragraphs") if isinstance(story.get("paragraphs"), list) else []
    values = [story.get("headline"), story.get("dek"), *paragraphs]
    return " ".join(" ".join(str(value or "").split()) for value in values if str(value or "").strip())


def _event_time(story: dict[str, Any]) -> dt.datetime | None:
    text = corpus(story).lower()
    month_names = "|".join(MONTHS)
    date_match = re.search(rf"\b(\d{{1,2}})\s+({month_names})\s+(\d{{4}})\b", text)
    time_match = re.search(r"\b(?:la\s+)?ora\s+(\d{1,2}):(\d{2})\b", text)
    if not date_match or not time_match:
        return None
    try:
        return dt.datetime(
            int(date_match.group(3)),
            MONTHS[date_match.group(2)],
            int(date_match.group(1)),
            int(time_match.group(1)),
            int(time_match.group(2)),
            tzinfo=TZ,
        )
    except ValueError:
        return None


def is_transient_service_story(story: dict[str, Any]) -> bool:
    text = corpus(story).lower()
    product = story.get("editorial_product") if isinstance(story.get("editorial_product"), dict) else {}
    service_format = str(product.get("format") or "").strip().lower() == "service_news"
    mobility = str(story.get("section") or "").strip().upper() in {"MOBILITATE", "TRAFIC"}
    return (service_format or mobility) and any(term in text for term in TRANSIENT_TERMS)


def has_durable_material_consequence(story: dict[str, Any]) -> bool:
    text = corpus(story).lower()
    return any(term in text for term in DURABLE_CONSEQUENCE_TERMS)


def social_interest_gate(
    story: dict[str, Any],
    *,
    now: dt.datetime | None = None,
    transient_max_age_minutes: int = 180,
) -> tuple[bool, str | None]:
    gate = str(story.get("material_fact_gate") or "").strip()
    if gate in {"PASS_DATE_ONLY", "PASS_TITLE_DATE_ONLY"}:
        return False, "thin_title_date_source_only"

    text = corpus(story)
    if len(text) < 120:
        return False, "insufficient_context"

    if is_transient_service_story(story) and not has_durable_material_consequence(story):
        observed = _event_time(story)
        if observed is not None:
            current = now or dt.datetime.now(TZ)
            if current.tzinfo is None:
                current = current.replace(tzinfo=TZ)
            age = current.astimezone(TZ) - observed
            if age.total_seconds() > transient_max_age_minutes * 60:
                return False, "transient_service_update_expired"

    return True, None


def self_test() -> int:
    now = dt.datetime(2026, 8, 18, 0, 30, tzinfo=TZ)
    stale = {
        "section": "MOBILITATE",
        "headline": "DN 7, 17 august 2026: INFOTRAFIC a semnalat trafic alternativ",
        "dek": "Alerta oficială emisă la ora 10:15 consemnează trafic alternativ pe sectorul indicat.",
        "paragraphs": ["La momentul emiterii alertei se circula alternativ pe DN 7, fără alte consecințe materiale confirmate."],
        "material_fact_gate": "PASS",
        "editorial_product": {"format": "service_news"},
    }
    ok, reason = social_interest_gate(stale, now=now)
    assert ok is False and reason == "transient_service_update_expired"

    durable = dict(stale)
    durable["headline"] = "DN 7, 17 august 2026: 2 victime într-un incident rutier"
    durable["dek"] = "Alerta oficială emisă la ora 15:45 indică două victime și trafic alternativ în zona Blidari."
    ok, reason = social_interest_gate(durable, now=now)
    assert ok is True and reason is None

    thin = {"headline": "Anunț", "dek": "17 august", "paragraphs": [], "material_fact_gate": "PASS_TITLE_DATE_ONLY"}
    assert social_interest_gate(thin, now=now)[0] is False
    print("VÂLCEA CLAR story social policy self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    raise SystemExit("story_social_policy is a library; use --self-test")


if __name__ == "__main__":
    raise SystemExit(main())
