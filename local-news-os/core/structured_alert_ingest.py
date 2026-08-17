#!/usr/bin/env python3
"""Ingest geo-scoped primary alerts into deterministic structured events.

The parser is source-contract aware but instance-agnostic. It may extract only
explicit fields from a primary alert page: official issue date/time, source,
road/location, traffic state and narrowly defined incident fields. It never uses
crawl time as freshness and never emits reader-facing prose or publication state.
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
        "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "structured": fields,
        "publication_authority": "PRIMARY_STRUCTURED_EVENT_ONLY",
        "reader_copy_generated": False,
    }


def collect_source(instance: dict[str, Any], source: dict[str, Any], tz: ZoneInfo, now: datetime) -> dict[str, Any]:
    if source.get("enabled") is not True:
        return {"source_id": source.get("id"), "status": "DISABLED", "events": []}
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
