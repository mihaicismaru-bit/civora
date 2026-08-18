#!/usr/bin/env python3
"""Augment the general VÂLCEA CLAR opportunity queue with performing-arts products.

This adapter runs after the generic Editorial Opportunity Engine. It does not
create a second queue and has no publication authority. Performing-arts monitors
become first-class opportunities in the same ranked queue as council, health,
infrastructure, jobs and business monitoring.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MONITORS = ROOT / "editorial" / "monitor_registry.json"
QUEUE = ROOT / "editorial" / "editorial_opportunity_queue.json"
PUBLICATION_AUTHORITY = "NONE"


def load(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def stable_id(monitor_id: str, product_type: str) -> str:
    raw = f"performing-arts|{monitor_id}|{product_type}"
    return "opp-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def sources(mon: dict) -> list[dict]:
    rows = []
    seen = set()
    for src in mon.get("source_bindings") or []:
        if not isinstance(src, dict):
            continue
        url = str(src.get("url") or "").strip()
        key = (str(src.get("id") or ""), url)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "id": src.get("id"),
            "ref_type": src.get("ref_type") or "url",
            "publisher": src.get("publisher"),
            "url": url or None,
            "tier": src.get("tier"),
        })
    return rows


def opportunity(mon: dict, product_type: str, lane: str, score: int, evidence_hint: str, *, current: bool, writer: str = "explainer") -> dict:
    monitor_id = str(mon.get("id") or "")
    return {
        "id": stable_id(monitor_id, product_type),
        "publication_authority": PUBLICATION_AUTHORITY,
        "public_projection": False,
        "lane": lane,
        "product_type": product_type,
        "writer_format": writer,
        "section": "CULTURĂ",
        "priority_score": min(100, max(score, int(mon.get("priority") or 0))),
        "monitor_id": monitor_id,
        "monitor_ids": [monitor_id],
        "monitor_family": "performing_arts",
        "subject_id": monitor_id,
        "subject_label": mon.get("label") or monitor_id,
        "fact_recency_required": False,
        "current_status_verification_required": current,
        "why_now": (
            f"Monitor cultural permanent: {product_type} reutilizează programul și documentele instituționale, "
            "dar orice afirmație despre programul curent, bilete, distribuție sau bani este reverificată înainte de publicare."
        ),
        "evidence_hint": evidence_hint,
        "evidence_status": "CURRENT_REVERIFY_REQUIRED" if current else "DOCUMENTARY_BASELINE_AVAILABLE",
        "next_stage": "CURRENT_PRIMARY_EVIDENCE_COLLECTION" if current else "DOCUMENT_EXTRACTION_AND_FACT_KERNEL",
        "source_bindings": sources(mon),
        "lead_verification_status": None,
        "normal_story_ready_gate_required": True,
        "event_date_is_not_published_at": True,
    }


def products_for(mon: dict) -> list[dict]:
    mid = str(mon.get("id") or "")
    if mid == "performing-arts-valcea-agenda":
        return [
            opportunity(
                mon, "CULTURAL_AGENDA", "service", 96,
                "Build a dated cross-institution agenda from official event calendars. Preserve event_start/event_end separately from source published_at and verify cancellations, venue and ticket status before publication.",
                current=True, writer="service_news",
            )
        ]
    rows = [
        opportunity(
            mon, "PREMIERE_REPERTOIRE_TRACKER", "monitor", 92,
            "Track premieres, repertory returns, guest productions, touring and festival selections; each current performance must be verified from the institution or another attributable primary source.",
            current=True,
        ),
        opportunity(
            mon, "CAST_CREATOR_INDEX", "knowledge", 86,
            "Connect productions and concerts to verified actors, directors, conductors, soloists, ensembles and creative teams, using Artist Intelligence without attaching ambiguous external identities.",
            current=False,
        ),
    ]
    if mid in {"performing-arts-filarmonica-valcea", "performing-arts-anton-pann", "performing-arts-ariel-valcea"}:
        rows.append(
            opportunity(
                mon, "MONEY_TRACE", "knowledge", 94 if "anton-pann" in mid else 90,
                "Separate institutional subsidy, own revenue, procurement, contracts, fees, investment and budget execution. Never infer a production cost from the institution's total budget.",
                current=True,
            )
        )
    return rows


def recount(doc: dict) -> None:
    opportunities = doc.get("opportunities") or []
    doc["opportunity_count"] = len(opportunities)
    for target, field in (("lane_counts", "lane"), ("product_counts", "product_type"), ("family_counts", "monitor_family")):
        counts: dict[str, int] = {}
        for row in opportunities:
            key = str(row.get(field) or "")
            if key:
                counts[key] = counts.get(key, 0) + 1
        doc[target] = counts


def build() -> tuple[dict, int]:
    queue = load(QUEUE, {}) or {}
    if queue.get("publication_authority") not in {None, PUBLICATION_AUTHORITY}:
        raise ValueError("general opportunity queue publication authority mismatch")
    monitor_doc = load(MONITORS, {}) or {}
    cultural = [
        row for row in monitor_doc.get("monitors") or []
        if isinstance(row, dict) and str(row.get("id") or "").startswith("performing-arts-")
    ]
    additions = []
    for mon in cultural:
        additions.extend(products_for(mon))
    existing = {
        str(row.get("id") or ""): row
        for row in queue.get("opportunities") or [] if isinstance(row, dict) and row.get("id")
    }
    for row in additions:
        existing[row["id"]] = row
    ranked = sorted(existing.values(), key=lambda row: (-int(row.get("priority_score") or 0), str(row.get("id") or "")))
    queue["opportunities"] = ranked
    queue["publication_authority"] = PUBLICATION_AUTHORITY
    queue["public_projection"] = False
    policy = queue.setdefault("policy", {})
    policy["performing_arts_feed_general_queue"] = True
    policy["event_date_is_not_published_at"] = True
    policy["calendar_change_may_publish_directly"] = False
    recount(queue)
    return queue, len(additions)


def self_test() -> None:
    mon = {"id":"performing-arts-valcea-agenda","priority":91,"label":"Agenda","source_bindings":[]}
    rows = products_for(mon)
    assert len(rows) == 1 and rows[0]["product_type"] == "CULTURAL_AGENDA"
    assert rows[0]["publication_authority"] == "NONE"
    assert rows[0]["event_date_is_not_published_at"] is True
    theatre = {"id":"performing-arts-anton-pann","priority":90,"label":"Anton Pann","source_bindings":[]}
    kinds = {row["product_type"] for row in products_for(theatre)}
    assert {"PREMIERE_REPERTOIRE_TRACKER", "CAST_CREATOR_INDEX", "MONEY_TRACE"}.issubset(kinds)
    print("VÂLCEA CLAR performing arts opportunity adapter self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test(); return 0
    doc, added = build()
    if args.check:
        assert added >= 1
        assert all(row.get("publication_authority") == "NONE" for row in doc.get("opportunities") or [])
        print(json.dumps({"status":"PASS","performing_arts_products":added,"opportunities":doc.get("opportunity_count")}, ensure_ascii=False))
        return 0
    QUEUE.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status":"UPDATED","performing_arts_products":added,"opportunities":doc.get("opportunity_count")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
