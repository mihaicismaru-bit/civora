#!/usr/bin/env python3
"""Autonomous latest-meeting selector for Râmnicu Vâlcea Council Watch.

The legacy reader has a safe, well-tested exact-date contract, but its target
meeting was originally a fixed 2026-08-14 recovery checkpoint.  This adapter
keeps all of those parsing/evidence guards and changes only target selection:
the target is always the newest date that actually appears in the official
HOTARARI ADOPTATE register.

No agenda date is inferred and no future meeting is guessed.  A date becomes a
target only after at least one adopted HCL carrying that date exists in the
municipality's official register.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import council_watch_rm_valcea as base

OUTPUT = base.OUTPUT
SELECTOR_ID = "LATEST_OFFICIAL_ADOPTED_DECISION_DATE_V1"
WEEKDAYS_RO = ["luni", "marți", "miercuri", "joi", "vineri", "sâmbătă", "duminică"]


def latest_adopted_date(register: list[dict[str, Any]]) -> str | None:
    dates = sorted({
        str(row.get("decision_date") or "").strip()
        for row in register
        if isinstance(row, dict) and str(row.get("decision_date") or "").strip()
    })
    return dates[-1] if dates else None


def weekday_ro(value: str) -> str:
    parsed = date.fromisoformat(value)
    return WEEKDAYS_RO[parsed.weekday()]


def discover_latest_target() -> tuple[str | None, dict[str, Any]]:
    result = base.fetch(base.ADOPTED_VIEW)
    if not result.get("ok"):
        return None, result
    register = base.parse_register(base.to_text(str(result.get("body") or "")))
    return latest_adopted_date(register), result


def build_state() -> dict[str, Any]:
    latest_date, discovery = discover_latest_target()
    if not latest_date:
        # Preserve the base fail-closed error state if the official register is
        # unreachable or contains no resolvable adopted-decision dates.
        state = base.build_state()
        state.setdefault("target_selection", {})["selector_id"] = SELECTOR_ID
        state["target_selection"]["status"] = "NO_LATEST_ADOPTED_DATE_RESOLVED"
        state["target_selection"]["register_reachable"] = bool(discovery.get("ok"))
        return state

    previous_target = str(base.TARGET_DATE_ISO)
    base.TARGET_DATE_ISO = latest_date
    state = base.build_state()
    target = state.setdefault("target_meeting", {})
    target["date"] = latest_date
    target["weekday"] = weekday_ro(latest_date)
    target["selection"] = SELECTOR_ID
    target["selection_rule"] = "newest date present in official adopted-HCL register"
    state["target_selection"] = {
        "selector_id": SELECTOR_ID,
        "previous_static_recovery_target": previous_target,
        "selected_date": latest_date,
        "selected_only_after_official_adoption": True,
        "future_meeting_date_inference_forbidden": True,
        "agenda_date_is_not_selection_evidence": True,
    }
    state.setdefault("policy", {})["target_meeting_is_latest_official_adopted_date"] = True
    state["policy"]["static_target_date_required"] = False
    return state


def self_test() -> int:
    rows = [
        {"decision_number": 305, "decision_date": "2026-08-14", "title": "a"},
        {"decision_number": 312, "decision_date": "2026-08-14", "title": "b"},
        {"decision_number": 313, "decision_date": "2026-08-20", "title": "c"},
        {"decision_number": 314, "decision_date": "2026-08-20", "title": "d"},
        {"decision_number": 315, "decision_date": None, "title": "invalid"},
    ]
    assert latest_adopted_date(rows) == "2026-08-20"
    assert weekday_ro("2026-08-14") == "vineri"
    assert weekday_ro("2026-08-20") == "joi"
    print("Râmnicu Vâlcea Council Watch latest-adopted selector v2 self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    state = build_state()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": (state.get("target_meeting") or {}).get("status"),
        "selector": SELECTOR_ID,
        "selected_date": (state.get("target_meeting") or {}).get("date"),
        "selected_weekday": (state.get("target_meeting") or {}).get("weekday"),
        "target_decisions": len(state.get("target_decisions") or []),
        "latest_official_decision": state.get("latest_official_decision"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
