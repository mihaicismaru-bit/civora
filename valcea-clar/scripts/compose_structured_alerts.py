#!/usr/bin/env python3
"""Compose primary structured alerts into canonical VÂLCEA CLAR fact kernels.

The generic ingest emits evidence fields only. This instance adapter builds a
Fact Kernel exclusively from those fields, validates it through the canonical
Editorial Writer, and upserts the RAW fact kernel into facts_registry.json.
The Live Newsroom later runs the canonical writer again and remains the sole
publication gate.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import editorial_writer

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVENTS = ROOT / "editorial" / "structured_alert_events.json"
DEFAULT_FACTS = ROOT / "editorial" / "facts_registry.json"
RO_MONTHS = {
    1: "ianuarie", 2: "februarie", 3: "martie", 4: "aprilie", 5: "mai", 6: "iunie",
    7: "iulie", 8: "august", 9: "septembrie", 10: "octombrie", 11: "noiembrie", 12: "decembrie",
}
AUTO_SCOPE = "structured_primary_fact_kernel"


def load(path: Path, default=None) -> dict[str, Any]:
    if not path.is_file():
        if default is not None:
            return default
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: root must be object")
    return value


def ro_date(value: datetime) -> str:
    return f"{value.day} {RO_MONTHS[value.month]} {value.year}"


def location_label(structured: dict[str, Any]) -> str:
    parts: list[str] = []
    if structured.get("locality"):
        parts.append(f"în zona localității {structured['locality']}")
    if structured.get("kilometer"):
        parts.append(f"la kilometrul {structured['kilometer']}")
    return ", ".join(parts) if parts else "în sectorul indicat de alerta oficială"


def make_fact(event: dict[str, Any]) -> dict[str, Any] | None:
    structured = event.get("structured") or {}
    road = str(structured.get("road") or "").strip()
    traffic_state = str(structured.get("traffic_state") or "").strip()
    source_url = str(event.get("source_url") or "").strip()
    if not road or not traffic_state or not source_url:
        return None
    issued = datetime.fromisoformat(str(event["issued_at"]))
    date_label = ro_date(issued)
    loc = location_label(structured)
    victims = structured.get("victim_count")
    projected = structured.get("one_person_projected") is True

    if isinstance(victims, int) and victims > 0:
        headline = f"{road}, {date_label}: {victims} victime într-un incident rutier semnalat de INFOTRAFIC"
        dek = f"Alerta oficială emisă la ora {issued.strftime('%H:%M')} indică incidentul {loc}; la acel moment, {traffic_state} era în vigoare pe sectorul afectat."
    else:
        headline = f"{road}, {date_label}: INFOTRAFIC a semnalat {traffic_state}"
        dek = f"Alerta oficială emisă la ora {issued.strftime('%H:%M')} vizează {loc} și consemnează situația de trafic de pe sectorul indicat."

    claims: list[dict[str, Any]] = [
        {
            "id": "issued",
            "role": "who_what_when_where",
            "kind": "fact",
            "text": f"Centrul INFOTRAFIC a emis în {date_label}, la ora {issued.strftime('%H:%M')}, o alertă pentru {road}, {loc}.",
            "source_urls": [source_url],
        },
        {
            "id": "traffic",
            "role": "material_change",
            "kind": "reader_service",
            "text": f"La momentul emiterii alertei, sursa oficială indica {traffic_state} pe {road}, în sectorul descris în informarea INFOTRAFIC.",
            "source_urls": [source_url],
        },
    ]
    if isinstance(victims, int) and victims > 0:
        consequence = f"Alerta oficială consemnează {victims} victime în incidentul rutier."
        if projected:
            consequence += " Una dintre victime a fost proiectată pe carosabil, potrivit informării INFOTRAFIC."
        claims.append({
            "id": "consequence",
            "role": "consequence",
            "kind": "fact",
            "text": consequence,
            "source_urls": [source_url],
        })

    source = {"name": str(event.get("source_name") or "Centrul INFOTRAFIC — Poliția Română"), "url": source_url, "tier": "T1"}
    valid_until = issued + timedelta(hours=36)
    return {
        "id": str(event["event_id"]),
        "status": "verified",
        "section": "MOBILITATE",
        "priority": 96 if victims else 90,
        "confidence": 99,
        "valid_from": issued.isoformat(timespec="minutes"),
        "valid_until": valid_until.isoformat(timespec="minutes"),
        "slots": ["morning", "evening"],
        "editorial_type": "service",
        "material_fact_gate": "PASS",
        "sources": [source],
        "auto_generated": True,
        "auto_scope": AUTO_SCOPE,
        "structured_primary_event": {
            "source_id": event.get("source_id"),
            "parser": event.get("parser"),
            "issued_at": event.get("issued_at"),
            "official_status": event.get("official_status"),
            "body_sha256": event.get("body_sha256"),
        },
        "fact_kernel": {
            "format_hint": "service_news",
            "headline": {"text": headline, "source_urls": [source_url]},
            "dek": {"text": dek, "source_urls": [source_url]},
            "claims": claims,
        },
    }


def validate_fact(fact: dict[str, Any], manual: dict[str, Any]) -> tuple[bool, str | None]:
    product = editorial_writer.transform_item(fact, manual)
    editorial = product.get("editorial_product") or {}
    mode = str(editorial.get("writer_mode") or "")
    if mode != "FACT_KERNEL_COMPOSED":
        return False, str(editorial.get("hold_reason") or mode or "writer_rejected")
    if product.get("status") == "editorial_hold":
        return False, str(editorial.get("hold_reason") or "editorial_hold")
    if editorial.get("claim_trace_complete") is not True:
        return False, "claim_trace_incomplete"
    if editorial.get("source_level_trace") is not True:
        return False, "source_trace_incomplete"
    if editorial.get("auto_publish_eligible_by_format") is not True:
        return False, "format_not_auto_publishable"
    return True, None


def compose(events_path: Path, facts_path: Path, *, write: bool) -> dict[str, Any]:
    events_doc = load(events_path)
    if events_doc.get("contract") != "LOCAL_NEWS_OS_STRUCTURED_ALERT_EVENTS_V1":
        raise ValueError("structured alert event contract mismatch")
    manual = editorial_writer.load(editorial_writer.MANUAL)
    editorial_writer.validate_manual(manual)

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for event in events_doc.get("events") or []:
        fact = make_fact(event)
        if fact is None:
            rejected.append({"event_id": str(event.get("event_id")), "reason": "insufficient_structured_fields"})
            continue
        ok, reason = validate_fact(fact, manual)
        if not ok:
            rejected.append({"event_id": str(event.get("event_id")), "reason": str(reason)})
            continue
        accepted.append(fact)

    registry = load(facts_path)
    if not isinstance(registry.get("facts"), list):
        raise ValueError("facts registry missing facts array")
    existing = {str(row.get("id")): row for row in registry.get("facts") or [] if row.get("id")}
    for fact in accepted:
        existing[str(fact["id"])] = fact
    registry["facts"] = list(existing.values())
    registry.setdefault("policy", {})["structured_primary_fact_kernel_contract"] = "LOCAL_NEWS_OS_STRUCTURED_ALERT_EVENTS_V1"
    registry["policy"]["structured_primary_fact_kernels_fail_closed"] = True
    registry["policy"]["structured_primary_reader_copy_requires_editorial_writer"] = True
    if write:
        facts_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "PASS",
        "event_count": len(events_doc.get("events") or []),
        "accepted_fact_kernel_count": len(accepted),
        "rejected_count": len(rejected),
        "rejected": rejected,
        "accepted_ids": [str(row["id"]) for row in accepted],
    }


def self_test() -> int:
    event = {
        "event_id": "alert-test",
        "source_id": "primary-test",
        "source_name": "Sursă oficială test",
        "source_tier": "T1",
        "source_url": "https://example.test/alert",
        "parser": "RO_INFOTRAFIC_DETAIL_V1",
        "issued_at": "2026-08-17T15:45+03:00",
        "official_status": "Inactiv",
        "body_sha256": "a" * 64,
        "structured": {
            "road": "DN 7", "kilometer": "167 + 300 metri", "locality": "Exemplu",
            "victim_count": 2, "one_person_projected": True, "traffic_state": "trafic alternativ",
        },
    }
    fact = make_fact(event)
    assert fact is not None
    manual = editorial_writer.load(editorial_writer.MANUAL)
    ok, reason = validate_fact(fact, manual)
    assert ok is True, reason
    assert fact["auto_scope"] == AUTO_SCOPE
    assert "azi" not in str((fact["fact_kernel"]["headline"] or {}).get("text") or "").casefold()
    print("VÂLCEA CLAR structured alert composition self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", default=str(DEFAULT_EVENTS))
    parser.add_argument("--facts-registry", default=str(DEFAULT_FACTS))
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    report = compose(Path(args.events), Path(args.facts_registry), write=not args.no_write)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
