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
TRAFFIC_PARSER = "RO_INFOTRAFIC_DETAIL_V1"
UTILITY_PARSERS = {
    "RO_UTILITY_WATER_INTERRUPTION_LISTING_V1": {
        "utility": "water",
        "service_label": "alimentării cu apă potabilă",
        "headline_phrase": "întrerupere a alimentării cu apă potabilă",
        "priority": 94,
    },
    "RO_UTILITY_HEAT_INTERRUPTION_LISTING_V1": {
        "utility": "district_heat",
        "service_label": "furnizării agentului termic",
        "headline_phrase": "întrerupere a furnizării agentului termic",
        "priority": 94,
    },
    "RO_UTILITY_ELECTRICITY_INTERRUPTION_LISTING_V1": {
        "utility": "electricity",
        "service_label": "alimentării cu energie electrică",
        "headline_phrase": "întrerupere a alimentării cu energie electrică",
        "priority": 93,
    },
}
UTILITY_PUBLICATION_LEAD_HOURS = 72
UTILITY_EXPIRY_GRACE_HOURS = 2


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


def operator_label(event: dict[str, Any]) -> str:
    name = str(event.get("source_name") or "Operatorul serviciului").strip()
    return name.split(" — ", 1)[0].strip() or name


def service_window(event_start: datetime, event_end: datetime) -> str:
    if event_start.date() == event_end.date():
        return f"{ro_date(event_start)}, între {event_start.strftime('%H:%M')} și {event_end.strftime('%H:%M')}"
    return (
        f"între {ro_date(event_start)}, ora {event_start.strftime('%H:%M')}, "
        f"și {ro_date(event_end)}, ora {event_end.strftime('%H:%M')}"
    )


def affected_service_label(structured: dict[str, Any]) -> str | None:
    locality = str(structured.get("affected_locality") or "").strip()
    scope = str(structured.get("affected_scope") or "").strip()
    consumers = [
        str(value).strip()
        for value in (structured.get("affected_consumers") or [])
        if str(value).strip()
    ]
    if locality and scope:
        return f"{locality}: {scope}"
    if locality:
        return locality
    if scope:
        return scope
    if consumers:
        if len(consumers) <= 4:
            return "; ".join(consumers)
        return "; ".join(consumers[:4]) + f"; plus încă {len(consumers) - 4} poziții enumerate de operator"
    return None


def concise(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    clipped = text[: max(1, limit - 1)].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return clipped + "…"


def make_traffic_fact(event: dict[str, Any]) -> dict[str, Any] | None:
    structured = event.get("structured") or {}
    road = str(structured.get("road") or "").strip()
    traffic_state = str(structured.get("traffic_state") or "").strip()
    source_url = str(event.get("source_url") or "").strip()
    if not road or not traffic_state or not source_url:
        return None
    try:
        issued = datetime.fromisoformat(str(event["issued_at"]))
    except (KeyError, TypeError, ValueError):
        return None
    if issued.tzinfo is None:
        return None
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


def make_utility_fact(event: dict[str, Any], parser_spec: dict[str, Any]) -> dict[str, Any] | None:
    structured = event.get("structured") or {}
    source_url = str(event.get("source_url") or "").strip()
    if not source_url or not isinstance(structured, dict):
        return None
    expected_utility = str(parser_spec["utility"])
    if str(structured.get("utility") or "").strip() != expected_utility:
        return None
    if str(event.get("source_time_basis") or "") != "official_service_window":
        return None
    if event.get("publication_authority") != "PRIMARY_STRUCTURED_EVENT_ONLY":
        return None
    if event.get("reader_copy_generated") is not False:
        return None
    try:
        event_start = datetime.fromisoformat(str(event["event_start"]))
        event_end = datetime.fromisoformat(str(event["event_end"]))
    except (KeyError, TypeError, ValueError):
        return None
    if event_start.tzinfo is None or event_end.tzinfo is None or event_end <= event_start:
        return None
    state = str(structured.get("service_state") or "").strip()
    if state not in {"scheduled_interruption", "interruption"}:
        return None
    affected = affected_service_label(structured)
    if not affected:
        return None

    operator = operator_label(event)
    window = service_window(event_start, event_end)
    service_label = str(parser_spec["service_label"])
    headline_phrase = str(parser_spec["headline_phrase"])
    locality = str(structured.get("affected_locality") or "").strip()
    if locality:
        headline = f"{locality}: {headline_phrase}, {window}"
    else:
        headline = f"{operator}: {headline_phrase}, {window}"
    headline = concise(headline, 138)

    affected_dek = concise(affected, 150)
    dek = (
        f"{operator} indică o întrerupere a {service_label} {window}. "
        f"Zona sau consumatorii afectați, conform sursei oficiale: {affected_dek}."
    )
    dek = concise(dek, 295)

    claims: list[dict[str, Any]] = [
        {
            "id": "service_window",
            "role": "material_change",
            "kind": "reader_service",
            "text": f"{operator} indică întreruperea {service_label} {window}.",
            "source_urls": [source_url],
        },
        {
            "id": "affected_scope",
            "role": "who_what_when_where",
            "kind": "reader_service",
            "text": f"Sursa oficială indică drept zonă sau consumatori afectați: {affected}.",
            "source_urls": [source_url],
        },
    ]

    reason = str(structured.get("reason") or "").strip()
    if reason:
        claims.append({
            "id": "reason",
            "role": "context",
            "kind": "fact",
            "text": f"Motivul menționat explicit de operator pentru această întrerupere este: {reason}.",
            "source_urls": [source_url],
        })
    forms = [str(value).strip() for value in (structured.get("service_forms") or []) if str(value).strip()]
    if forms:
        claims.append({
            "id": "service_forms",
            "role": "context",
            "kind": "reader_service",
            "text": "Formele de serviciu enumerate explicit ca afectate sunt: " + "; ".join(forms) + ".",
            "source_urls": [source_url],
        })

    source_tier = str(event.get("source_tier") or "T1").strip()
    if source_tier != "T1":
        return None
    publication_from = event_start - timedelta(hours=UTILITY_PUBLICATION_LEAD_HOURS)
    valid_until = event_end + timedelta(hours=UTILITY_EXPIRY_GRACE_HOURS)
    return {
        "id": str(event["event_id"]),
        "status": "verified",
        "section": "SERVICII",
        "priority": int(parser_spec["priority"]),
        "confidence": 99,
        "valid_from": publication_from.isoformat(timespec="minutes"),
        "valid_until": valid_until.isoformat(timespec="minutes"),
        "slots": ["morning", "evening"],
        "editorial_type": "service",
        "material_fact_gate": "PASS",
        "sources": [{"name": str(event.get("source_name") or operator), "url": source_url, "tier": source_tier}],
        "auto_generated": True,
        "auto_scope": AUTO_SCOPE,
        "structured_primary_event": {
            "source_id": event.get("source_id"),
            "parser": event.get("parser"),
            "event_start": event.get("event_start"),
            "event_end": event.get("event_end"),
            "source_time_basis": event.get("source_time_basis"),
            "body_sha256": event.get("body_sha256"),
            "reader_copy_generated_by_ingest": False,
            "publication_window_policy": f"event_start_minus_{UTILITY_PUBLICATION_LEAD_HOURS}h_until_event_end_plus_{UTILITY_EXPIRY_GRACE_HOURS}h",
        },
        "fact_kernel": {
            "format_hint": "service_news",
            "headline": {"text": headline, "source_urls": [source_url]},
            "dek": {"text": dek, "source_urls": [source_url]},
            "claims": claims,
        },
    }


def make_fact(event: dict[str, Any]) -> dict[str, Any] | None:
    parser = str(event.get("parser") or "").strip()
    if parser == TRAFFIC_PARSER:
        return make_traffic_fact(event)
    parser_spec = UTILITY_PARSERS.get(parser)
    if parser_spec:
        return make_utility_fact(event, parser_spec)
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
    registry["policy"]["utility_service_news_publication_window_is_event_derived"] = True
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
    manual = editorial_writer.load(editorial_writer.MANUAL)

    traffic_event = {
        "event_id": "alert-test",
        "source_id": "primary-test",
        "source_name": "Sursă oficială test",
        "source_tier": "T1",
        "source_url": "https://example.test/alert",
        "parser": TRAFFIC_PARSER,
        "issued_at": "2026-08-17T15:45+03:00",
        "official_status": "Inactiv",
        "body_sha256": "a" * 64,
        "structured": {
            "road": "DN 7", "kilometer": "167 + 300 metri", "locality": "Exemplu",
            "victim_count": 2, "one_person_projected": True, "traffic_state": "trafic alternativ",
        },
    }
    traffic_fact = make_fact(traffic_event)
    assert traffic_fact is not None
    ok, reason = validate_fact(traffic_fact, manual)
    assert ok is True, reason
    assert traffic_fact["auto_scope"] == AUTO_SCOPE
    assert "azi" not in str((traffic_fact["fact_kernel"]["headline"] or {}).get("text") or "").casefold()

    utility_events = [
        {
            "event_id": "utility-water-test",
            "source_id": "water-test",
            "source_name": "Operator Apă — opriri programate",
            "source_tier": "T1",
            "source_url": "https://example.test/water",
            "parser": "RO_UTILITY_WATER_INTERRUPTION_LISTING_V1",
            "event_start": "2026-08-29T09:00+03:00",
            "event_end": "2026-08-29T15:00+03:00",
            "source_time_basis": "official_service_window",
            "body_sha256": "b" * 64,
            "publication_authority": "PRIMARY_STRUCTURED_EVENT_ONLY",
            "reader_copy_generated": False,
            "structured": {
                "utility": "water",
                "service_state": "scheduled_interruption",
                "affected_scope": "municipiul Exemplu, strada Test",
            },
        },
        {
            "event_id": "utility-heat-test",
            "source_id": "heat-test",
            "source_name": "Operator Termic — anunțuri",
            "source_tier": "T1",
            "source_url": "https://example.test/heat",
            "parser": "RO_UTILITY_HEAT_INTERRUPTION_LISTING_V1",
            "event_start": "2026-08-30T01:00+03:00",
            "event_end": "2026-09-01T00:00+03:00",
            "source_time_basis": "official_service_window",
            "body_sha256": "c" * 64,
            "publication_authority": "PRIMARY_STRUCTURED_EVENT_ONLY",
            "reader_copy_generated": False,
            "structured": {
                "utility": "district_heat",
                "service_state": "interruption",
                "affected_consumers": ["PT 1 Centru", "Spital Municipal"],
                "service_forms": ["apă fierbinte", "apă caldă de consum"],
                "reason": "lucrări la rețeaua primară",
            },
        },
        {
            "event_id": "utility-electricity-test",
            "source_id": "electricity-test",
            "source_name": "Operator Energie — întreruperi programate",
            "source_tier": "T1",
            "source_url": "https://example.test/electricity",
            "parser": "RO_UTILITY_ELECTRICITY_INTERRUPTION_LISTING_V1",
            "event_start": "2026-08-31T08:30+03:00",
            "event_end": "2026-08-31T16:30+03:00",
            "source_time_basis": "official_service_window",
            "body_sha256": "d" * 64,
            "publication_authority": "PRIMARY_STRUCTURED_EVENT_ONLY",
            "reader_copy_generated": False,
            "structured": {
                "utility": "electricity",
                "service_state": "scheduled_interruption",
                "affected_locality": "Băile Exemplu",
                "affected_scope": "PTA Centru, PTA Nord",
            },
        },
    ]
    for event in utility_events:
        fact = make_fact(event)
        assert fact is not None, event["event_id"]
        ok, reason = validate_fact(fact, manual)
        assert ok is True, (event["event_id"], reason)
        assert fact["section"] == "SERVICII"
        assert fact["editorial_type"] == "service"
        assert fact["fact_kernel"]["format_hint"] == "service_news"
        assert fact["structured_primary_event"]["reader_copy_generated_by_ingest"] is False
        assert "azi" not in fact["fact_kernel"]["headline"]["text"].casefold()
        assert datetime.fromisoformat(fact["valid_from"]) < datetime.fromisoformat(event["event_start"])
        assert datetime.fromisoformat(fact["valid_until"]) > datetime.fromisoformat(event["event_end"])

    mismatch = dict(utility_events[-1])
    mismatch["structured"] = dict(mismatch["structured"], utility="water")
    assert make_fact(mismatch) is None

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
