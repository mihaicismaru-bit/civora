#!/usr/bin/env python3
"""Read-only diagnosis for VÂLCEA CLAR newsroom candidates.

Materializes the existing Editorial Writer output, then explains every curated
story's path through edition eligibility, Editorial Integrity and `story_ready`.
It has no publication authority and writes no canonical site/newsroom state.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import editorial_integrity
import generate_edition
import newsroom_decide

TZ = ZoneInfo("Europe/Bucharest")
PUBLICATION_AUTHORITY = "NONE"


def diagnose(now: datetime) -> dict:
    registry, auto_count = generate_edition.merged_registry()
    slot = generate_edition.choose_slot(now, "auto")
    eligible_ids = {
        str(item.get("id") or "")
        for item in generate_edition.eligible_facts(registry, now, slot)
    }
    held_ids = newsroom_decide.active_publication_holds()
    rows = []
    for item in sorted(registry.get("facts") or [], key=lambda row: str(row.get("id") or "")):
        story_id = str(item.get("id") or "")
        sources = item.get("sources") or []
        temporal = generate_edition.durable_story_temporal_violations(item, "ro-RO")
        eligibility_reasons: list[str] = []
        if item.get("status") not in generate_edition.ALLOWED_STATUSES:
            eligibility_reasons.append("status_not_publishable")
        if int(item.get("confidence") or 0) < generate_edition.MIN_CONFIDENCE:
            eligibility_reasons.append("confidence_below_threshold")
        if item.get("material_fact_gate") not in generate_edition.ALLOWED_GATES:
            eligibility_reasons.append("material_fact_gate_not_allowed")
        if slot not in (item.get("slots") or []):
            eligibility_reasons.append("current_slot_not_allowed")
        if not sources or any(not source.get("url") for source in sources if isinstance(source, dict)):
            eligibility_reasons.append("source_url_missing")
        try:
            valid_now = (
                generate_edition.parse_dt(str(item.get("valid_from") or ""))
                <= now
                <= generate_edition.parse_dt(str(item.get("valid_until") or ""))
            )
        except Exception:
            valid_now = False
        if not valid_now:
            eligibility_reasons.append("outside_validity_window")
        if temporal:
            eligibility_reasons.append("relative_temporal_language_not_durable")

        editorial = item.get("editorial_product") if isinstance(item.get("editorial_product"), dict) else {}
        if editorial:
            integrity_ok, integrity_reason, _ = editorial_integrity.validate_story(item)
        else:
            integrity_ok, integrity_reason = None, "no_editorial_product"

        if story_id in eligible_ids:
            ready, ready_reason = newsroom_decide.story_ready(item)
        else:
            ready, ready_reason = False, "not_edition_eligible"

        rows.append({
            "id": story_id,
            "status": item.get("status"),
            "confidence": item.get("confidence"),
            "material_fact_gate": item.get("material_fact_gate"),
            "slots": item.get("slots") or [],
            "valid_from": item.get("valid_from"),
            "valid_until": item.get("valid_until"),
            "valid_now": valid_now,
            "publication_hold": story_id in held_ids,
            "writer_mode": editorial.get("writer_mode"),
            "format": editorial.get("format"),
            "edition_eligible": story_id in eligible_ids,
            "eligibility_reasons": eligibility_reasons,
            "integrity_ok": integrity_ok,
            "integrity_reason": integrity_reason,
            "story_ready": ready,
            "story_ready_reason": ready_reason,
        })
    return {
        "schema_version": "1.0",
        "publication_authority": PUBLICATION_AUTHORITY,
        "evaluated_local": now.isoformat(timespec="seconds"),
        "slot": slot,
        "auto_fact_registry_count": auto_count,
        "candidate_count": len(rows),
        "story_ready_count": sum(1 for row in rows if row["story_ready"]),
        "candidates": rows,
    }


def self_test() -> int:
    row = diagnose(datetime(2026, 8, 18, 16, 0, tzinfo=TZ))
    assert row["publication_authority"] == "NONE"
    assert isinstance(row["candidates"], list)
    assert all("story_ready_reason" in item for item in row["candidates"])
    print("VÂLCEA CLAR newsroom candidate diagnostic self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--story-id")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    report = diagnose(datetime.now(TZ))
    if args.story_id:
        report["candidates"] = [row for row in report["candidates"] if row["id"] == args.story_id]
        report["candidate_count"] = len(report["candidates"])
        report["story_ready_count"] = sum(1 for row in report["candidates"] if row["story_ready"])
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
