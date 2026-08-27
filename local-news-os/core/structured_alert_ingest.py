#!/usr/bin/env python3
"""Ingest geo-scoped primary alerts into deterministic structured events.

The parser is source-contract aware but instance-agnostic. It may extract only
explicit fields from a primary alert page: official issue date/time, source,
road/location, traffic state and narrowly defined incident fields. Scheduled
utility events may instead carry an explicit service window from the primary
operator listing. Crawl time is never used as source freshness and this layer
never emits reader-facing prose or publication state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

CORE = Path(__file__).resolve().parent
ROOT = CORE.parents[1]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import primary_signal_verifier as primary  # noqa: E402
import signal_radar as radar  # noqa: E402

RO_MONTHS = {
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4, "mai": 5, "iunie": 6,
    "iulie": 7, "august": 8, "septembrie": 9, "octombrie": 10, "noiembrie": 11, "decembrie": 12,
}
WATER_INTERRUPTION_PARSER = "RO_UTILITY_WATER_INTERRUPTION_LISTING_V1"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: root must be object")
    return value


def repo_file(raw: str) -> Path:
    return radar.repo_file(raw)


def instance_and_pack(instance_id: str) -> tuple[dict[str, Any], dict[str, Any], ZoneInfo]:
    instance = load(ROOT / "local-news-os" / "instances" / instance_id / "instance.json")
    if instance.get("instance_id") != instance_id:
        raise ValueError("instance id mismatch")
    source_pack = load(repo_file(str(instance.get("packs", {}).get("source_pack") or "")))
    alert_path = str(source_pack.get("structured_alert_pack") or "").strip()
    if not alert_path:
        raise ValueError("structured_alert_pack not configured")
    pack = load(repo_file(alert_path))
    if pack.get("contract") != "LOCAL_NEWS_OS_STRUCTURED_ALERT_PACK_V1" or pack.get("instance_id") != instance_id:
        raise ValueError("structured alert pack identity mismatch")
    return instance, pack, ZoneInfo(str(instance["timezone"]))


def geography_terms(instance: dict[str, Any]) -> set[str]:
    geo = instance.get("geography") or {}
    values = [geo.get("primary_name"), geo.get("county")]
    values.extend(geo.get("aliases") or [])
    terms: set[str] = set()
    for value in values:
        norm = radar.norm_text(str(value or ""))
        if norm:
            terms.add(norm)
    if not terms:
        raise ValueError("instance primary geography is empty")
    return terms


def parse_ro_issue_time(text: str, tz: ZoneInfo) -> datetime | None:
    date_match = re.search(r"\bData:\s*(\d{1,2})\s+([A-Za-zĂÂÎȘȚăâîșț]+)\s+(20\d{2})\b", text, re.I)
    time_match = re.search(r"\bOra:\s*([01]?\d|2[0-3]):([0-5]\d)\b", text, re.I)
    if not date_match or not time_match:
        return None
    month_name = radar.norm_text(date_match.group(2))
    month = RO_MONTHS.get(month_name)
    if month is None:
        return None
    try:
        return datetime(
            int(date_match.group(3)), month, int(date_match.group(1)),
            int(time_match.group(1)), int(time_match.group(2)), tzinfo=tz,
        )
    except ValueError:
        return None


def detail_body(text: str) -> str:
    match = re.search(
        r"\bOra:\s*(?:[01]?\d|2[0-3]):[0-5]\d\s+(.*?)(?=\s+Recomandări utile pentru un trafic|\s+Informații, prognoze|\s+Situația drumurilor naționale|\s+Unităţi teritoriale|$)",
        text,
        re.I | re.S,
    )
    return radar.clean(match.group(1)) if match else ""


def sentence_with_prefix(body: str, prefixes: tuple[str, ...]) -> str | None:
    sentences = [radar.clean(part) for part in re.split(r"(?<=[.!?])\s+", body) if radar.clean(part)]
    for sentence in sentences:
        norm = radar.norm_text(sentence)
        if any(norm.startswith(radar.norm_text(prefix)) for prefix in prefixes):
            return sentence
    return None


def extract_structured_fields(body: str, title: str) -> dict[str, Any]:
    road_match = re.search(r"\b(DN\s*\d+[A-Z]?|DJ\s*\d+[A-Z]?|A\s*\d+)\b", body, re.I)
    km_match = re.search(r"\bkilometrul\s+([0-9]+(?:\s*\+\s*[0-9]+)?(?:\s+de metri)?)", body, re.I)
    locality_match = re.search(r"\b(?:zona|raza)\s+localit(?:ății|atii)\s+([^,.;]+)", body, re.I)
    victims_match = re.search(r"\bau rezultat\s+(\d+)\s+victim", body, re.I)
    if not victims_match:
        victims_match = re.search(r"\brănirea\s+(?:a\s+)?(\d+)\s+persoan", body, re.I)
    traffic_sentence = sentence_with_prefix(body, ("Circulația rutieră", "Traficul rutier", "Circulația auto", "Traficul auto"))
    incident_sentence = None
    for sentence in [radar.clean(part) for part in re.split(r"(?<=[.!?])\s+", body) if radar.clean(part)]:
        norm = radar.norm_text(sentence)
        if any(term in norm for term in ("accident rutier", "coliziune", "pierdut controlul directiei", "autocamion", "autoturism")):
            incident_sentence = sentence
            break
    traffic_state = None
    title_norm = radar.norm_text(title)
    for label, token in (
        ("trafic alternativ", "trafic alternativ"),
        ("trafic blocat", "trafic blocat"),
        ("trafic oprit", "trafic oprit"),
        ("trafic întrerupt", "trafic intrerupt"),
        ("trafic restricționat", "trafic restrictionat"),
        ("trafic îngreunat", "trafic ingreunat"),
        ("circulație reluată", "circulatie reluata"),
    ):
        if token in title_norm:
            traffic_state = label
            break
    return {
        "road": radar.clean(road_match.group(1)).replace("  ", " ") if road_match else None,
        "kilometer": radar.clean(km_match.group(1)) if km_match else None,
        "locality": radar.clean(locality_match.group(1)) if locality_match else None,
        "victim_count": int(victims_match.group(1)) if victims_match else None,
        "one_person_projected": bool(re.search(r"\buna dintre (?:acestea|victime).*?proiectat", body, re.I)),
        "traffic_state": traffic_state,
        "traffic_sentence": traffic_sentence,
        "incident_sentence": incident_sentence,
    }


def parse_infotrafic_detail(raw_html: str, final_url: str, source: dict[str, Any], tz: ZoneInfo) -> dict[str, Any] | None:
    title = primary.extract_title(raw_html, "")
    plain = primary.extract_text(raw_html)
    if "INFOTRAFIC" not in plain.upper():
        return None
    issued = parse_ro_issue_time(plain, tz)
    if issued is None:
        return None
    body = detail_body(plain)
    if len(body) < 80:
        return None
    fields = extract_structured_fields(body, title)
    status_match = re.search(r"\bStatus:\s*([A-Za-zĂÂÎȘȚăâîșț]+)", plain, re.I)
    category_match = re.search(r"\bCategorie:\s*(.*?)\s+Status:", plain, re.I | re.S)
    return {
        "event_id": "alert-" + hashlib.sha256(final_url.encode()).hexdigest()[:20],
        "source_id": source["id"],
        "source_name": source["name"],
        "source_tier": source["source_tier"],
        "source_url": final_url,
        "parser": source["parser"],
        "official_title": title,
        "official_category": radar.clean(category_match.group(1)) if category_match else None,
        "official_status": radar.clean(status_match.group(1)) if status_match else None,
        "issued_at": issued.isoformat(timespec="minutes"),
        "source_time_basis": "official_issue_time",
        "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "structured": fields,
        "publication_authority": "PRIMARY_STRUCTURED_EVENT_ONLY",
        "reader_copy_generated": False,
    }


def _service_datetime(day: str, month: str, year: str, hour: str, minute: str, tz: ZoneInfo) -> datetime | None:
    try:
        h = int(hour)
        m = int(minute)
        if h > 23 or m > 59:
            return None
        return datetime(int(year), int(month), int(day), h, m, tzinfo=tz)
    except ValueError:
        return None


def parse_water_service_window(label: str, tz: ZoneInfo) -> tuple[datetime, datetime, str] | None:
    """Extract only an explicit numeric APAVIL service window from its link label."""
    text = radar.clean(label).replace("–", "-").replace("—", "-")
    cross = re.search(
        r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\s*,?\s*(?:ora\s*)?([0-2]?\d)[:.]([0-5]\d)\s*-\s*"
        r"(\d{1,2})\.(\d{1,2})\.(20\d{2})\s*,?\s*(?:ora\s*)?([0-2]?\d)[:.]([0-5]\d)\b",
        text,
        re.I,
    )
    if cross:
        start = _service_datetime(*cross.group(1, 2, 3, 4, 5), tz)
        end = _service_datetime(*cross.group(6, 7, 8, 9, 10), tz)
        if start and end and end > start:
            return start, end, radar.clean(cross.group(0))
        return None

    date_match = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b", text)
    if not date_match:
        return None
    tail = text[date_match.end():]
    times = re.findall(r"\b([0-2]?\d)[:.]([0-5]\d)\b", tail)
    if len(times) < 2:
        return None
    start = _service_datetime(*date_match.group(1, 2, 3), *times[0], tz)
    end = _service_datetime(*date_match.group(1, 2, 3), *times[1], tz)
    if not start or not end or end <= start:
        return None
    window_start = date_match.start()
    window_text = radar.clean(text[window_start:])
    return start, end, window_text


def water_affected_scope(label: str) -> str:
    """Preserve the operator's own affected-area wording; never infer geography."""
    text = radar.clean(label)
    date_match = re.search(r"\b\d{1,2}\.\d{1,2}\.20\d{2}\b", text)
    if date_match:
        text = text[:date_match.start()]
    text = re.sub(r"\b(?:în|in)\s+(?:data|perioada|intervalul)\s*(?:de)?\s*$", "", text, flags=re.I)
    return radar.clean(text).rstrip(" ,.-")


def parse_water_interruption_listing(
    raw_html: str,
    listing_url: str,
    source: dict[str, Any],
    tz: ZoneInfo,
    now: datetime,
) -> tuple[list[dict[str, Any]], int]:
    parser = radar.AnchorParser()
    parser.feed(raw_html)
    candidates = 0
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    max_candidates = int(source.get("max_listing_candidates") or 40)
    horizon = timedelta(hours=int(source.get("planning_horizon_hours") or 336))
    grace = timedelta(hours=int(source.get("expiry_grace_hours") or 1))

    for href, raw_label in parser.links:
        if candidates >= max_candidates:
            break
        label = radar.clean(raw_label)
        norm = radar.norm_text(label)
        if "intrerup" not in norm or ("apa potabila" not in norm and "alimentare cu apa" not in norm):
            continue
        absolute = urllib.parse.urljoin(listing_url, href).split("#", 1)[0]
        if not absolute or absolute.rstrip("/") == listing_url.rstrip("/"):
            continue
        dedupe_key = absolute + "\n" + label
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        candidates += 1
        window = parse_water_service_window(label, tz)
        if not window:
            continue
        event_start, event_end, window_text = window
        if event_end < now - grace or event_start > now + horizon:
            continue
        scope = water_affected_scope(label)
        if not scope:
            continue
        fingerprint = hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()
        events.append({
            "event_id": "utility-water-" + fingerprint[:20],
            "source_id": source["id"],
            "source_name": source["name"],
            "source_tier": source["source_tier"],
            "source_url": absolute,
            "parser": source["parser"],
            "official_title": label,
            "official_category": "întrerupere programată apă potabilă",
            "official_status": "programată" if event_start > now else "în desfășurare",
            "event_start": event_start.isoformat(timespec="minutes"),
            "event_end": event_end.isoformat(timespec="minutes"),
            "source_time_basis": "official_service_window",
            "body_sha256": hashlib.sha256(label.encode("utf-8")).hexdigest(),
            "structured": {
                "utility": "water",
                "service_state": "scheduled_interruption",
                "affected_scope": scope,
                "service_window_text": window_text,
            },
            "publication_authority": "PRIMARY_STRUCTURED_EVENT_ONLY",
            "reader_copy_generated": False,
        })
    events.sort(key=lambda row: row["event_start"])
    return events, candidates


def collect_water_interruption_source(source: dict[str, Any], tz: ZoneInfo, now: datetime) -> dict[str, Any]:
    try:
        listing_html, listing_url = radar.fetch(str(source["url"]), max_bytes=2_500_000, timeout=16)
    except Exception as exc:
        return {"source_id": source.get("id"), "status": "DEGRADED", "error": f"{type(exc).__name__}: {exc}", "events": []}
    events, candidates = parse_water_interruption_listing(listing_html, listing_url, source, tz, now)
    return {
        "source_id": source["id"],
        "status": "PASS",
        "listing_url": listing_url,
        "candidates": candidates,
        "events": events,
    }


def collect_source(instance: dict[str, Any], source: dict[str, Any], tz: ZoneInfo, now: datetime) -> dict[str, Any]:
    if source.get("enabled") is not True:
        return {"source_id": source.get("id"), "status": "DISABLED", "events": []}
    if source.get("parser") == WATER_INTERRUPTION_PARSER:
        return collect_water_interruption_source(source, tz, now)
    if source.get("parser") != "RO_INFOTRAFIC_DETAIL_V1":
        return {"source_id": source.get("id"), "status": "UNSUPPORTED_PARSER", "events": []}
    try:
        listing_html, listing_url = radar.fetch(str(source["url"]), max_bytes=2_500_000, timeout=16)
    except Exception as exc:
        return {"source_id": source.get("id"), "status": "DEGRADED", "error": f"{type(exc).__name__}: {exc}", "events": []}
    parser = radar.AnchorParser()
    parser.feed(listing_html)
    geo_terms = geography_terms(instance)
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    max_candidates = int(source.get("max_listing_candidates") or 40)
    for href, label in parser.links:
        absolute = urllib.parse.urljoin(listing_url, href).split("#", 1)[0]
        path = urllib.parse.urlsplit(absolute).path.casefold()
        label_norm = radar.norm_text(label)
        if "/ro/info-trafic/" not in path or absolute.rstrip("/") == listing_url.rstrip("/"):
            continue
        if not any(term in label_norm for term in geo_terms):
            continue
        if absolute not in seen:
            seen.add(absolute)
            candidates.append((absolute, radar.clean(label)))
        if len(candidates) >= max_candidates:
            break
    events: list[dict[str, Any]] = []
    max_fetches = int(source.get("max_detail_fetches") or 16)
    lookback = timedelta(hours=int(source.get("lookback_hours") or 36))
    for url, _ in candidates[:max_fetches]:
        try:
            raw, final = radar.fetch(url, max_bytes=1_800_000, timeout=14)
        except Exception:
            continue
        event = parse_infotrafic_detail(raw, final, source, tz)
        if not event:
            continue
        issued = datetime.fromisoformat(event["issued_at"])
        if issued > now + timedelta(minutes=5) or now - issued > lookback:
            continue
        events.append(event)
    events.sort(key=lambda row: row["issued_at"], reverse=True)
    return {
        "source_id": source["id"],
        "status": "PASS",
        "listing_url": listing_url,
        "candidates": len(candidates),
        "events": events,
    }


def run(instance_id: str, output: Path) -> dict[str, Any]:
    instance, pack, tz = instance_and_pack(instance_id)
    now = datetime.now(tz)
    observations = [collect_source(instance, source, tz, now) for source in pack.get("sources") or []]
    events = [event for row in observations for event in row.get("events") or []]
    doc = {
        "schema_version": "1.0",
        "contract": "LOCAL_NEWS_OS_STRUCTURED_ALERT_EVENTS_V1",
        "instance_id": instance_id,
        "generated_at": now.isoformat(timespec="seconds"),
        "publication_authority": "PRIMARY_STRUCTURED_EVENT_ONLY",
        "events_are_reader_stories": False,
        "event_count": len(events),
        "events": events,
        "sources": observations,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return doc


def self_test() -> int:
    tz = ZoneInfo("Europe/Bucharest")
    sample = """
    <html><head><meta property='og:title' content='JUDEȚUL TEST: TRAFIC ALTERNATIV PE DN 7'></head><body>
    <div>Sursa: INFOTRAFIC Categorie: Alerta trafic Status: Inactiv</div>
    <h3>JUDEȚUL TEST: TRAFIC ALTERNATIV PE DN 7</h3>
    <div>Data: 17 August 2026</div><div>Ora: 15:45</div>
    <p>Centrul INFOTRAFIC informează că pe DN 7, la kilometrul 167 + 300 metri, în zona localității Exemplu, conducătorul unui autoturism a intrat în coliziune cu un cap de pod. În urma impactului au rezultat 2 victime, una dintre acestea fiind proiectată pe carosabil.</p>
    <p>Circulația rutieră se desfășoară pe un singur fir, alternativ, prin dirijarea poliției.</p>
    <div>Recomandări utile pentru un trafic în siguranță</div></body></html>
    """
    source = {"id": "test", "name": "Primary", "source_tier": "T1", "parser": "RO_INFOTRAFIC_DETAIL_V1"}
    event = parse_infotrafic_detail(sample, "https://example.invalid/ro/info-trafic/test", source, tz)
    assert event is not None
    assert event["issued_at"] == "2026-08-17T15:45+03:00"
    assert event["structured"]["road"] == "DN 7"
    assert event["structured"]["victim_count"] == 2
    assert event["structured"]["one_person_projected"] is True
    assert event["structured"]["traffic_state"] == "trafic alternativ"

    water_sample = """
    <html><body>
    <a href='/future-water/'>Anunț întrerupere furnizare apă potabilă către consumatorii din municipiul Râmnicu Vâlcea, strada Test, în data de 29.08.2026, în intervalul orar 09:00 – 15:00</a>
    <a href='/expired-water/'>Anunț întrerupere furnizare apă potabilă către consumatorii din municipiul Râmnicu Vâlcea, strada Veche, în data de 20.08.2026, în intervalul orar 09:00 – 15:00</a>
    <a href='/noise/'>Comunicat fără întrerupere de apă</a>
    </body></html>
    """
    water_source = {
        "id": "water-test", "name": "Operator apă test", "source_tier": "T1",
        "parser": WATER_INTERRUPTION_PARSER, "planning_horizon_hours": 336,
    }
    water_events, water_candidates = parse_water_interruption_listing(
        water_sample,
        "https://water.example/opriri/",
        water_source,
        tz,
        datetime(2026, 8, 27, 14, 0, tzinfo=tz),
    )
    assert water_candidates == 2
    assert len(water_events) == 1
    assert water_events[0]["event_start"] == "2026-08-29T09:00+03:00"
    assert water_events[0]["event_end"] == "2026-08-29T15:00+03:00"
    assert water_events[0]["source_time_basis"] == "official_service_window"
    assert water_events[0]["reader_copy_generated"] is False
    cross = parse_water_service_window(
        "Anunț întrerupere apă potabilă în intervalul 30.08.2026 ora 09:00 – 31.08.2026, ora 19:00",
        tz,
    )
    assert cross is not None and cross[0].day == 30 and cross[1].day == 31
    assert parse_water_service_window("Anunț fără fereastră numerică", tz) is None
    print("LOCAL NEWS OS structured alert ingest self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance")
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.instance or not args.output:
        parser.error("--instance and --output are required")
    doc = run(args.instance, Path(args.output))
    print(json.dumps({"status": "PASS", "event_count": doc["event_count"], "publication_authority": doc["publication_authority"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
