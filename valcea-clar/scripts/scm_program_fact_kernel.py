#!/usr/bin/env python3
"""Build a fail-closed service-news Fact Kernel from SCM Râmnicu Vâlcea's official program.

The deployed SCM theme currently strips SportsPress wrapper/cell classes and the
machine-readable ``startDate`` attribute while retaining a stable semantic table:
Dată | Timp | Acasă | Deplasare | Stadion. This parser therefore discovers the
columns from those visible headers, then consumes only the corresponding cells.
It never parses prose or infers missing fields. The resulting Fact Kernel must
pass the canonical Editorial Writer before it can enter the facts registry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import sys
import unicodedata
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
    "ian": 1, "ianuarie": 1, "feb": 2, "februarie": 2, "mar": 3, "martie": 3,
    "apr": 4, "aprilie": 4, "mai": 5, "iun": 6, "iunie": 6, "iul": 7, "iulie": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "septembrie": 9, "oct": 10,
    "octombrie": 10, "nov": 11, "noiembrie": 11, "dec": 12, "decembrie": 12,
}
HEADER_ALIASES = {
    "date": {"data", "date"},
    "time": {"timp", "ora", "time"},
    "home": {"acasa", "home"},
    "away": {"deplasare", "away", "oaspeti", "oaspetii"},
    "venue": {"stadion", "locatie", "arena", "venue"},
}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: root must be object")
    return value


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", clean_text(value).casefold())
    asciiish = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    asciiish = asciiish.replace("ş", "s").replace("ș", "s").replace("ţ", "t").replace("ț", "t")
    return re.sub(r"[^a-z0-9]+", " ", asciiish).strip()


def dedupe_repeated_label(value: str) -> str:
    text = clean_text(value)
    tokens = text.split()
    if len(tokens) >= 2 and len(tokens) % 2 == 0:
        half = len(tokens) // 2
        if [fold(x) for x in tokens[:half]] == [fold(x) for x in tokens[half:]]:
            return " ".join(tokens[:half])
    return text


def parse_visible_start(date_text: str, time_text: str) -> datetime | None:
    date_value = clean_text(date_text).casefold().replace(".", "")
    time_value = clean_text(time_text)
    date_match = re.fullmatch(r"(\d{1,2})\s+([a-zăâîșşțţ]+),?\s+(\d{4})", date_value)
    time_match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", time_value)
    if not date_match or not time_match:
        return None
    month = RO_MONTH_NUMBERS.get(date_match.group(2))
    if month is None:
        return None
    try:
        return datetime(
            int(date_match.group(3)), month, int(date_match.group(1)),
            int(time_match.group(1)), int(time_match.group(2)), tzinfo=TZ,
        )
    except ValueError:
        return None


class SemanticTableParser(HTMLParser):
    """Collect visible table cells, including image alt/meta labels for teams."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.table_depth = 0
        self.current_table: list[list[dict[str, Any]]] | None = None
        self.current_row: list[dict[str, Any]] | None = None
        self.current_cell: dict[str, Any] | None = None
        self.tables: list[list[list[dict[str, Any]]]] = []

    @staticmethod
    def attrs_dict(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {str(k): str(v or "") for k, v in attrs}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = self.attrs_dict(attrs)
        if tag == "table":
            if self.table_depth == 0:
                self.current_table = []
            self.table_depth += 1
            return
        if self.table_depth != 1:
            return
        if tag == "tr":
            self.current_row = []
            return
        if tag in {"th", "td"} and self.current_row is not None:
            self.current_cell = {"tag": tag, "attrs": attr, "text": [], "labels": []}
            self.current_row.append(self.current_cell)
            return
        if self.current_cell is not None and tag == "img" and attr.get("alt"):
            self.current_cell["labels"].append(clean_text(attr["alt"]))
        if self.current_cell is not None and tag == "meta" and attr.get("itemprop") == "name" and attr.get("content"):
            self.current_cell["labels"].append(clean_text(attr["content"]))

    def handle_data(self, data: str) -> None:
        if self.table_depth == 1 and self.current_cell is not None:
            text = clean_text(data)
            if text:
                self.current_cell["text"].append(text)

    def handle_endtag(self, tag: str) -> None:
        if self.table_depth == 1 and tag in {"th", "td"}:
            self.current_cell = None
            return
        if self.table_depth == 1 and tag == "tr":
            if self.current_table is not None and self.current_row:
                self.current_table.append(self.current_row)
            self.current_row = None
            self.current_cell = None
            return
        if tag == "table" and self.table_depth > 0:
            self.table_depth -= 1
            if self.table_depth == 0:
                if self.current_table:
                    self.tables.append(self.current_table)
                self.current_table = None
                self.current_row = None
                self.current_cell = None


def cell_value(cell: dict[str, Any]) -> str:
    text = clean_text(" ".join(cell.get("text") or []))
    labels = [clean_text(x) for x in cell.get("labels") or [] if clean_text(x)]
    if text:
        return dedupe_repeated_label(text)
    if labels:
        return dedupe_repeated_label(labels[0])
    return ""


def header_key(value: str) -> str | None:
    token = fold(value)
    for key, aliases in HEADER_ALIASES.items():
        if token in aliases:
            return key
    return None


def event_rows_from_tables(tables: list[list[list[dict[str, Any]]]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for table in tables:
        mapping: dict[str, int] | None = None
        header_index = -1
        for index, row in enumerate(table):
            candidate: dict[str, int] = {}
            for col, cell in enumerate(row):
                key = header_key(cell_value(cell))
                if key and key not in candidate:
                    candidate[key] = col
            if {"date", "time", "home", "away"}.issubset(candidate):
                mapping = candidate
                header_index = index
                break
        if mapping is None:
            continue
        required_max = max(mapping[k] for k in ("date", "time", "home", "away"))
        for row in table[header_index + 1:]:
            if len(row) <= required_max:
                continue
            date_cell = row[mapping["date"]]
            date_text = cell_value(date_cell)
            time_text = cell_value(row[mapping["time"]])
            home = cell_value(row[mapping["home"]])
            away = cell_value(row[mapping["away"]])
            venue = cell_value(row[mapping["venue"]]) if "venue" in mapping and len(row) > mapping["venue"] else ""
            if not date_text or not time_text or not home or not away:
                continue
            start: datetime | None = None
            attrs = date_cell.get("attrs") or {}
            raw_start = clean_text(str(attrs.get("content") or "")) if attrs.get("itemprop") == "startDate" else ""
            if raw_start:
                try:
                    start = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
                except ValueError:
                    start = None
            if start is None:
                start = parse_visible_start(date_text, time_text)
            if start is None:
                continue
            if start.tzinfo is None:
                start = start.replace(tzinfo=TZ)
            events.append({
                "start_dt": start.astimezone(TZ),
                "start_provenance": "STARTDATE_ATTRIBUTE" if raw_start else "SEMANTIC_TABLE_HEADER_DATE_TIME",
                "home": dedupe_repeated_label(home),
                "away": dedupe_repeated_label(away),
                "venue": clean_text(venue),
            })
    events.sort(key=lambda row: row["start_dt"])
    return events


def fetch_html(url: str = SOURCE_URL) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with urlopen(request, timeout=15, context=ssl.create_default_context()) as response:
        body = response.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            raise ValueError("SCM program response exceeds bounded body limit")
        charset = response.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace")


def parse_events(html: str) -> list[dict[str, Any]]:
    parser = SemanticTableParser()
    parser.feed(html)
    return event_rows_from_tables(parser.tables)


def is_valcea_team(name: str) -> bool:
    return "ramnicu valcea" in fold(name)


def select_next(events: list[dict[str, Any]], now: datetime) -> dict[str, Any] | None:
    horizon = now + timedelta(days=LOOKAHEAD_DAYS)
    for event in events:
        start = event["start_dt"]
        if now <= start <= horizon and (is_valcea_team(str(event["home"])) or is_valcea_team(str(event["away"]))):
            return event
    return None


def ro_date(value: datetime) -> str:
    return f"{value.day} {RO_MONTHS[value.month]} {value.year}"


def event_id(event: dict[str, Any]) -> str:
    raw = "|".join([
        event["start_dt"].isoformat(timespec="minutes"), str(event["home"]),
        str(event["away"]), str(event.get("venue") or ""),
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
            "parser": "SCM_SEMANTIC_PROGRAM_TABLE_V4",
        },
        "fact_kernel": {
            "format_hint": "service_news",
            "headline": {
                "text": f"{home} – {away}: meci programat pe {date_label}, de la {time_label}",
                "source_urls": source_urls,
            },
            "dek": {
                "text": f"Programul oficial al SCM Râmnicu Vâlcea listează partida la {venue}. Informația este verificată direct în calendarul clubului.",
                "source_urls": source_urls,
            },
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
    policy["scm_official_program_fact_kernel"] = "SCM_SEMANTIC_PROGRAM_TABLE_V4"
    policy["scm_program_fail_closed"] = True
    policy["scm_program_requires_semantic_table_headers"] = True
    after = json.dumps(registry["facts"], ensure_ascii=False, sort_keys=True)
    return registry, before != after


def run(facts_path: Path, *, write: bool, html: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    now = (now or datetime.now(TZ)).astimezone(TZ)
    events = parse_events(html if html is not None else fetch_html())
    event = select_next(events, now)
    if event is None:
        return {"status": "PASS", "changed": False, "reason": "no_upcoming_valcea_fixture_within_window", "events_parsed": len(events)}
    fact = make_fact(event)
    ok, reason = validate_fact(fact)
    if not ok:
        raise ValueError(f"SCM fixture Fact Kernel rejected: {reason}")
    registry = load(facts_path)
    registry, changed = apply_fact(registry, fact)
    if write and changed:
        facts_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "PASS", "changed": changed, "fact_id": fact["id"],
        "start": event["start_dt"].isoformat(timespec="minutes"),
        "start_provenance": event.get("start_provenance"),
        "home": event["home"], "away": event["away"], "venue": event.get("venue"),
        "events_parsed": len(events),
    }


def self_test() -> int:
    html = '''
    <table><thead><tr><th>Dată</th><th>Timp</th><th>Acasă</th><th>Deplasare</th><th>Stadion</th></tr></thead><tbody>
      <tr><td>15 aug., 2026</td><td>11:00</td><td><img alt="CSM Ramnicu Valcea"> CSM Ramnicu Valcea</td><td><img alt="Slatina"> Slatina</td><td>Stadionul Municipal</td></tr>
      <tr><td>22 aug., 2026</td><td>11:00</td><td><img alt="CSM Ramnicu Valcea"></td><td><img alt="FC Bacau"></td><td>Stadionul Municipal</td></tr>
    </tbody></table>'''
    events = parse_events(html)
    assert len(events) == 2
    next_event = select_next(events, datetime(2026, 8, 18, 15, 0, tzinfo=TZ))
    assert next_event is not None
    assert next_event["home"] == "CSM Ramnicu Valcea"
    assert next_event["away"] == "FC Bacau"
    assert next_event["start_dt"] == datetime(2026, 8, 22, 11, 0, tzinfo=TZ)
    assert next_event["start_provenance"] == "SEMANTIC_TABLE_HEADER_DATE_TIME"
    fact = make_fact(next_event)
    assert fact["material_fact_gate"] == "PASS"
    assert len(fact["fact_kernel"]["claims"]) == 2
    ok, reason = validate_fact(fact)
    assert ok is True, reason
    assert "azi" not in json.dumps(fact, ensure_ascii=False).casefold()
    assert parse_visible_start("22 aug., 2026", "1 - 2") is None
    print("VÂLCEA CLAR SCM semantic program Fact Kernel self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--facts-registry", default=str(DEFAULT_FACTS))
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    print(json.dumps(run(Path(args.facts_registry), write=not args.no_write), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
