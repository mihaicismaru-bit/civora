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
import re
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
INFOTRAFIC_PARSER = "RO_INFOTRAFIC_DETAIL_V1"
WATER_INTERRUPTION_PARSER = "RO_UTILITY_WATER_INTERRUPTION_LISTING_V1"


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


def compact_water_scope(raw_scope: object) -> str:
    """Normalize only boilerplate already present in the operator label.

    The parser intentionally preserves APAVIL's own affected-area wording. This
    adapter may remove the repetitive announcement prefix for readable copy, but
    it must not add, expand or infer any geography.
    """
    scope = re.sub(r"\s+", " ", str(raw_scope or "")).strip(" ,.-")
    if not scope:
        return ""
    prefix = re.compile(
        r"^anunț\s+întrerupere\s+furnizare\s+"
        r"(?:(?:alimentare\s+cu\s+)?ap[ăa]\s+potabil[ăa])\s+"
        r"(?:(?:a|către|catre|la)\s+)?consumator(?:ilor|ii)(?:\s+existenți|\s+existenti)?(?:\s+din|\s+în|\s+in)?\s*",
        re.I,
    )
    cleaned = prefix.sub("", scope).strip(" ,.-")
    return cleaned or scope


def water_scope_head(scope: str) -> str:
    """Use only the first operator-supplied locality phrase in the headline."""
    head = re.split(r",\s*(?:străzile|strazile|strada|respectiv|tronson|bloc(?:ul|urile)?\b)", scope, maxsplit=1, flags=re.I)[0]
    head = head.strip(" ,.-")
    if len(head) > 72:
        head = head[:69].rstrip(" ,.-") + "…"
    return head


def make_infotrafic_fact(event: dict[str, Any]) -> dict[str, Any] | None:
    structured = event.get("structured") or {}
    road = str(structured.get("road") or "").strip()
    traffic_state = str(structured.get("traffic_state") or "").strip()
    source_url = str(event.get("source_url") or "").strip()
    if not road or not traffic_state or not source_url or not event.get("issued_at"):
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
            "source_time_basis": event.get("source_time_basis") or "official_issue_time",
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


def make_water_interruption_fact(event: dict[str, Any]) -> dict[str, Any] | None:
    structured = event.get("structured") or {}
    source_url = str(event.get("source_url") or "").strip()
    scope = compact_water_scope(structured.get("affected_scope"))
    if (
        str(event.get("parser") or "") != WATER_INTERRUPTION_PARSER
        or str(event.get("source_time_basis") or "") != "official_service_window"
        or str(structured.get("utility") or "") != "water"
        or str(structured.get("service_state") or "") != "scheduled_interruption"
        or not source_url
        or not scope
        or not event.get("event_start")
        or not event.get("event_end")
    ):
        return None
    try:
        event_start = datetime.fromisoformat(str(event["event_start"]))
        event_end = datetime.fromisoformat(str(event["event_end"]))
    except ValueError:
        return None
    if event_start.tzinfo is None or event_end.tzinfo is None or event_end <= event_start:
        return None

    date_label = ro_date(event_start)
    same_day = event_start.date() == event_end.date()
    time_label = (
        f"între orele {event_start.strftime('%H:%M')} și {event_end.strftime('%H:%M')}"
        if same_day
        else f"din {ro_date(event_start)}, ora {event_start.strftime('%H:%M')}, până în {ro_date(event_end)}, ora {event_end.strftime('%H:%M')}"
    )
    area = water_scope_head(scope)
    if not area:
        return None
    headline = f"APAVIL: întrerupere programată a apei în {area}, pe {date_label}"
    if len(headline) > 140:
        headline = f"APAVIL: întrerupere programată a apei pe {date_label}"
    dek = f"Operatorul anunță întreruperea furnizării apei {time_label}; sunt vizați consumatorii din {scope}."
    if len(dek) > 300:
        dek = f"Operatorul anunță întreruperea furnizării apei {time_label}. Lista completă a zonelor afectate este în anunțul oficial APAVIL."

    claims = [
        {
            "id": "service_window",
            "role": "material_change",
            "kind": "reader_service",
            "text": f"APAVIL a programat întreruperea furnizării apei {time_label} pentru consumatorii din {scope}.",
            "source_urls": [source_url],
        },
        {
            "id": "operator_scope",
            "role": "who_what_when_where",
            "kind": "fact",
            "text": f"Zona afectată este redată din anunțul oficial al operatorului: {scope}.",
            "source_urls": [source_url],
        },
    ]
    source = {"name": str(event.get("source_name") or "APAVIL S.A."), "url": source_url, "tier": "T1"}
    valid_from = event_start - timedelta(hours=72)
    valid_until = event_end + timedelta(hours=2)
    return {
        "id": str(event["event_id"]),
        "status": "verified",
        "section": "INFRASTRUCTURĂ",
        "priority": 93,
        "confidence": 99,
        "valid_from": valid_from.isoformat(timespec="minutes"),
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
            "event_start": event.get("event_start"),
            "event_end": event.get("event_end"),
            "source_time_basis": event.get("source_time_basis"),
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


def make_fact(event: dict[str, Any]) -> dict[str, Any] | None:
    parser = str(event.get("parser") or "")
    if parser == WATER_INTERRUPTION_PARSER:
        return make_water_interruption_fact(event)
    if parser == INFOTRAFIC_PARSER:
        return make_infotrafic_fact(event)
    return None


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
        "parser": INFOTRAFIC_PARSER,
        "issued_at": "2026-08-17T15:45+03:00",
        "source_time_basis": "official_issue_time",
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

    water_event = {
        "event_id": "utility-water-test",
        "source_id": "apavil-water-interruptions",
        "source_name": "APAVIL S.A.",
        "source_tier": "T1",
        "source_url": "https://apavil.example/oprire-test",
        "parser": WATER_INTERRUPTION_PARSER,
        "official_status": "programată",
        "event_start": "2026-08-29T09:00+03:00",
        "event_end": "2026-08-29T15:00+03:00",
        "source_time_basis": "official_service_window",
        "body_sha256": "b" * 64,
        "structured": {
            "utility": "water",
            "service_state": "scheduled_interruption",
            "affected_scope": "Anunț întrerupere furnizare apă potabilă către consumatorii din municipiul Râmnicu Vâlcea, strada Test",
            "service_window_text": "29.08.2026, în intervalul 09:00 - 15:00",
        },
    }
    water_fact = make_fact(water_event)
    assert water_fact is not None
    assert water_fact["section"] == "INFRASTRUCTURĂ"
    assert water_fact["editorial_type"] == "service"
    assert water_fact["valid_from"] == "2026-08-26T09:00+03:00"
    assert water_fact["valid_until"] == "2026-08-29T17:00+03:00"
    assert "municipiul Râmnicu Vâlcea" in water_fact["fact_kernel"]["headline"]["text"]
    assert "Anunț întrerupere" not in water_fact["fact_kernel"]["headline"]["text"]
    ok, reason = validate_fact(water_fact, manual)
    assert ok is True, reason

    malformed_water = {**water_event, "event_end": "2026-08-29T08:00+03:00"}
    assert make_fact(malformed_water) is None
    wrong_basis = {**water_event, "source_time_basis": "crawl_time"}
    assert make_fact(wrong_basis) is None
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
