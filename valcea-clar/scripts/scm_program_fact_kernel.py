#!/usr/bin/env python3
"""Build one fail-closed service-news Fact Kernel from SCM Râmnicu Vâlcea's official program.

The source page is rendered by SportsPress. We consume only structured event-list
fields (date, time, home, away and venue), never free-form press copy. The parser
prefers the machine-readable startDate attribute and has a bounded fallback to
the visible SportsPress date/time cells when the deployed theme omits that
attribute. It does not depend on the surrounding table wrapper class: a row is
eligible only when it exposes the exact SportsPress data-date/data-time/data-home/
data-away cells. The result is validated by the canonical Editorial Writer before
it may enter the facts registry. A transport, parse or validation failure produces
no publication.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import sys
from copy import deepcopy
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import editorial_writer  # noqa: E402

TZ = ZoneInfo("Europe/Bucharest")
SOURCE_URL = "https://scmramnicuvalcea.ro/program/"
SOURCE_NAME = "SCM Râmnicu Vâlcea — program oficial"
AUTO_SCOPE = "scm_official_program_fact_kernel"
DEFAULT_FACTS = ROOT / "editorial" / "facts_registry.json"
USER_AGENT = "Mozilla/5.0 VÂLCEA-CLAR/1.0 (+https://valceaclar.ro/)"
MAX_BODY_BYTES = 2_000_000
LOOKAHEAD_DAYS = 10
RO_MONTHS = {
    1: "ianuarie", 2: "februarie", 3: "martie", 4: "aprilie", 5: "mai", 6: "iunie",
    7: "iulie", 8: "august", 9: "septembrie", 10: "octombrie", 11: "noiembrie", 12: "decembrie",
}
RO_MONTH_NUMBERS = {
    "ian": 1, "ianuarie": 1,
    "feb": 2, "februarie": 2,
    "mar": 3, "martie": 3,
    "apr": 4, "aprilie": 4,
    "mai": 5,
    "iun": 6, "iunie": 6,
    "iul": 7, "iulie": 7,
    "aug": 8, "august": 8,
    "sept": 9, "sep": 9, "septembrie": 9,
    "oct": 10, "octombrie": 10,
    "nov": 11, "noiembrie": 11,
    "dec": 12, "decembrie": 12,
}
SPORTSPRESS_EVENT_CELLS = ("data-date", "data-home", "data-away", "data-time", "data-venue")


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: root must be object")
    return value


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_visible_start(date_text: str, time_text: str) -> datetime | None:
    """Parse only the explicit SportsPress visible date/time cells."""
    date_value = clean_text(date_text).casefold().replace(".", "")
    time_value = clean_text(time_text)
    date_match = re.fullmatch(r"(\d{1,2})\s+([a-zăâîșşțţ]+),?\s+(\d{4})", date_value)
    time_match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", time_value)
    if not date_match or not time_match:
        return None
    day = int(date_match.group(1))
    month = RO_MONTH_NUMBERS.get(date_match.group(2))
    year = int(date_match.group(3))
    if month is None:
        return None
    try:
        return datetime(year, month, day, int(time_match.group(1)), int(time_match.group(2)), tzinfo=TZ)
    except ValueError:
        return None


class SportsPressEventListParser(HTMLParser):
    """Scan HTML tables but accept only rows carrying exact SportsPress event-cell classes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.table_depth = 0
        self.in_row = False
        self.current_cell: str | None = None
        self.current: dict[str, Any] = {}
        self.events: list[dict[str, Any]] = []

    @staticmethod
    def attrs_dict(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {str(k): str(v or "") for k, v in attrs}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = self.attrs_dict(attrs)
        classes = set(a.get("class", "").split())
        if tag == "table":
            self.table_depth += 1
            return
        if self.table_depth <= 0:
            return
        if tag == "tr":
            self.in_row = True
            self.current = {"text": {}, "team_meta": {}, "recognized_cells": set()}
            return
        if not self.in_row:
            return
        if tag == "td":
            self.current_cell = None
            for key in SPORTSPRESS_EVENT_CELLS:
                if key in classes:
                    self.current_cell = key
                    self.current["recognized_cells"].add(key)
                    self.current["text"].setdefault(key, [])
                    if key == "data-date" and a.get("itemprop") == "startDate" and a.get("content"):
                        self.current["start"] = a["content"]
                    break
            return
        if tag == "meta" and self.current_cell in {"data-home", "data-away"}:
            if a.get("itemprop") == "name" and a.get("content"):
                self.current["team_meta"][self.current_cell] = clean_text(a["content"])

    def handle_data(self, data: str) -> None:
        if self.table_depth > 0 and self.in_row and self.current_cell:
            text = clean_text(data)
            if text:
                self.current["text"].setdefault(self.current_cell, []).append(text)

    def handle_endtag(self, tag: str) -> None:
        if self.table_depth <= 0:
            return
        if tag == "td":
            self.current_cell = None
            return
        if tag == "tr" and self.in_row:
            event = self._finish_row(self.current)
            if event:
                self.events.append(event)
            self.in_row = False
            self.current_cell = None
            self.current = {}
            return
        if tag == "table":
            self.table_depth = max(0, self.table_depth - 1)

    @staticmethod
    def _finish_row(row: dict[str, Any]) -> dict[str, Any] | None:
        recognized = set(row.get("recognized_cells") or set())
        required = {"data-date", "data-time", "data-home", "data-away"}
        if not required.issubset(recognized):
            return None
        text = row.get("text") or {}
        meta = row.get("team_meta") or {}
        home = clean_text(str(meta.get("data-home") or " ".join(text.get("data-home") or [])))
        away = clean_text(str(meta.get("data-away") or " ".join(text.get("data-away") or [])))
        venue = clean_text(" ".join(text.get("data-venue") or []))
        date_text = clean_text(" ".join(text.get("data-date") or []))
        time_text = clean_text(" ".join(text.get("data-time") or []))
        if not home or not away or not date_text or not time_text:
            return None
        return {
            "start": clean_text(str(row.get("start") or "")),
            "date_text": date_text,
            "home": home,
            "away": away,
            "venue": venue,
            "time_text": time_text,
        }


def fetch_html(url: str = SOURCE_URL) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    context = ssl.create_default_context()
    with urlopen(req, timeout=15, context=context) as response:
        body = response.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            raise ValueError("SCM program response exceeds bounded body limit")
        charset = response.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace")


def parse_events(html: str) -> list[dict[str, Any]]:
    parser = SportsPressEventListParser()
    parser.feed(html)
    result: list[dict[str, Any]] = []
    for row in parser.events:
        start: datetime | None = None
        raw_start = clean_text(str(row.get("start") or ""))
        if raw_start:
            try:
                start = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
            except ValueError:
                start = None
        if start is None:
            start = parse_visible_start(str(row.get("date_text") or ""), str(row.get("time_text") or ""))
        if start is None:
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=TZ)
        row = dict(row)
        row["start_dt"] = start.astimezone(TZ)
        row["start_provenance"] = "STARTDATE_ATTRIBUTE" if raw_start else "VISIBLE_EVENT_TABLE_DATE_TIME"
        result.append(row)
    result.sort(key=lambda row: row["start_dt"])
    return result


def is_valcea_team(name: str) -> bool:
    folded = name.casefold().replace("â", "a").replace("ă", "a").replace("î", "i").replace("ș", "s").replace("ş", "s").replace("ț", "t").replace("ţ", "t")
    return "ramnicu valcea" in folded


def select_next(events: list[dict[str, Any]], now: datetime) -> dict[str, Any] | None:
    horizon = now + timedelta(days=LOOKAHEAD_DAYS)
    for event in events:
        start = event["start_dt"]
        if start < now or start > horizon:
            continue
        if is_valcea_team(str(event["home"])) or is_valcea_team(str(event["away"])):
            return event
    return None


def ro_date(value: datetime) -> str:
    return f"{value.day} {RO_MONTHS[value.month]} {value.year}"


def event_id(event: dict[str, Any]) -> str:
    raw = "|".join([
        event["start_dt"].isoformat(timespec="minutes"),
        str(event["home"]), str(event["away"]), str(event.get("venue") or ""),
    ])
    return "scm-program-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def make_fact(event: dict[str, Any]) -> dict[str, Any]:
    start: datetime = event["start_dt"]
    home = clean_text(str(event["home"]))
    away = clean_text(str(event["away"]))
    venue = clean_text(str(event.get("venue") or "")) or "stadionul indicat în programul oficial"
    date_label = ro_date(start)
    time_label = start.strftime("%H:%M")
    source_urls = [SOURCE_URL]
    headline = f"{home} – {away}: meci programat pe {date_label}, de la {time_label}"
    dek = f"Programul oficial al SCM Râmnicu Vâlcea listează partida la {venue}. Informația este verificată direct în calendarul clubului."
    return {
        "id": event_id(event),
        "status": "verified",
        "section": "SPORT",
        "priority": 88,
        "confidence": 99,
        "valid_from": (start - timedelta(days=7)).isoformat(timespec="minutes"),
        "valid_until": (start + timedelta(hours=4)).isoformat(timespec="minutes"),
        "slots": ["morning", "evening"],
        "editorial_type": "service",
        "material_fact_gate": "PASS",
        "sources": [{"name": SOURCE_NAME, "url": SOURCE_URL, "tier": "T1B"}],
        "auto_generated": True,
        "auto_scope": AUTO_SCOPE,
        "official_event": {
            "start": start.isoformat(timespec="minutes"),
            "start_provenance": str(event.get("start_provenance") or "UNKNOWN"),
            "home": home,
            "away": away,
            "venue": venue,
            "source_url": SOURCE_URL,
            "parser": "SPORTSPRESS_EVENT_CELLS_V3",
        },
        "fact_kernel": {
            "format_hint": "service_news",
            "headline": {"text": headline, "source_urls": source_urls},
            "dek": {"text": dek, "source_urls": source_urls},
            "claims": [
                {
                    "id": "fixture",
                    "role": "who_what_when_where",
                    "kind": "fact",
                    "text": f"În programul oficial al SCM Râmnicu Vâlcea, partida {home} – {away} este programată pe {date_label}, la ora {time_label}.",
                    "source_urls": source_urls,
                },
                {
                    "id": "venue",
                    "role": "reader_service",
                    "kind": "reader_service",
                    "text": f"Programul oficial indică pentru această partidă locația {venue}.",
                    "source_urls": source_urls,
                },
            ],
        },
    }


def validate_fact(fact: dict[str, Any]) -> tuple[bool, str | None]:
    manual = editorial_writer.load(editorial_writer.MANUAL)
    editorial_writer.validate_manual(manual)
    product = editorial_writer.transform_item(deepcopy(fact), manual)
    editorial = product.get("editorial_product") or {}
    if str(editorial.get("writer_mode") or "") != "FACT_KERNEL_COMPOSED":
        return False, str(editorial.get("hold_reason") or "writer_not_fact_kernel")
    if product.get("status") == "editorial_hold":
        return False, str(editorial.get("hold_reason") or "editorial_hold")
    if editorial.get("claim_trace_complete") is not True or editorial.get("source_level_trace") is not True:
        return False, "claim_or_source_trace_incomplete"
    if editorial.get("auto_publish_eligible_by_format") is not True:
        return False, "format_not_auto_publishable"
    return True, None


def apply_fact(registry: dict[str, Any], fact: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    rows = registry.get("facts")
    if not isinstance(rows, list):
        raise ValueError("facts registry missing facts array")
    before = json.dumps(rows, ensure_ascii=False, sort_keys=True)
    kept = [
        row for row in rows
        if not (isinstance(row, dict) and row.get("auto_scope") == AUTO_SCOPE and row.get("id") != fact["id"])
    ]
    by_id = {str(row.get("id")): row for row in kept if isinstance(row, dict) and row.get("id")}
    by_id[str(fact["id"])] = fact
    order = [str(row.get("id")) for row in kept if isinstance(row, dict) and row.get("id") and str(row.get("id")) != fact["id"]]
    order.append(str(fact["id"]))
    registry["facts"] = [by_id[key] for key in order if key in by_id]
    policy = registry.setdefault("policy", {})
    policy["scm_official_program_fact_kernel"] = "SPORTSPRESS_EVENT_CELLS_V3"
    policy["scm_program_fail_closed"] = True
    policy["scm_visible_date_fallback_requires_explicit_24h_time"] = True
    after = json.dumps(registry["facts"], ensure_ascii=False, sort_keys=True)
    return registry, before != after


def run(facts_path: Path, *, write: bool, html: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    now = (now or datetime.now(TZ)).astimezone(TZ)
    events = parse_events(html if html is not None else fetch_html())
    event = select_next(events, now)
    if event is None:
        return {
            "status": "PASS",
            "changed": False,
            "reason": "no_upcoming_valcea_fixture_within_window",
            "events_parsed": len(events),
        }
    fact = make_fact(event)
    ok, reason = validate_fact(fact)
    if not ok:
        raise ValueError(f"SCM fixture Fact Kernel rejected: {reason}")
    registry = load(facts_path)
    registry, changed = apply_fact(registry, fact)
    if write and changed:
        facts_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "PASS",
        "changed": changed,
        "fact_id": fact["id"],
        "start": event["start_dt"].isoformat(timespec="minutes"),
        "start_provenance": event.get("start_provenance"),
        "home": event["home"],
        "away": event["away"],
        "venue": event.get("venue"),
        "events_parsed": len(events),
    }


def self_test() -> int:
    html = '''
    <table class="custom-theme-table"><tbody>
      <tr>
        <td class="data-date" itemprop="startDate" content="2026-08-15T11:00:00+03:00">15 aug., 2026</td>
        <td class="data-home"><meta itemprop="name" content="CSM Ramnicu Valcea">CSM Ramnicu Valcea</td>
        <td class="data-time">1 - 2</td>
        <td class="data-away"><meta itemprop="name" content="Slatina">Slatina</td>
        <td class="data-venue">Stadionul Municipal</td>
      </tr>
      <tr>
        <td class="data-date">22 aug., 2026</td>
        <td class="data-time">11:00</td>
        <td class="data-home">CSM Ramnicu Valcea</td>
        <td class="data-away">FC Bacau</td>
        <td class="data-venue">Stadionul Municipal</td>
      </tr>
    </tbody></table>'''
    events = parse_events(html)
    assert len(events) == 2
    assert events[1]["start_provenance"] == "VISIBLE_EVENT_TABLE_DATE_TIME"
    next_event = select_next(events, datetime(2026, 8, 18, 15, 0, tzinfo=TZ))
    assert next_event is not None
    assert next_event["away"] == "FC Bacau"
    assert next_event["start_dt"] == datetime(2026, 8, 22, 11, 0, tzinfo=TZ)
    fact = make_fact(next_event)
    assert fact["material_fact_gate"] == "PASS"
    assert len(fact["fact_kernel"]["claims"]) == 2
    ok, reason = validate_fact(fact)
    assert ok is True, reason
    assert "azi" not in json.dumps(fact, ensure_ascii=False).casefold()
    assert parse_visible_start("22 aug., 2026", "1 - 2") is None
    assert parse_visible_start("22 aug., 2026", "11:00") == datetime(2026, 8, 22, 11, 0, tzinfo=TZ)
    print("VÂLCEA CLAR SCM official-program Fact Kernel self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--facts-registry", default=str(DEFAULT_FACTS))
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    report = run(Path(args.facts_registry), write=not args.no_write)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
