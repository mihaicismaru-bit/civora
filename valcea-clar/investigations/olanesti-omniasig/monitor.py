#!/usr/bin/env python3
"""Fail-closed monitor for VÂLCEA CLAR case VC-INV-2026-001."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from common import dump_json, load_json, utcnow
from engine import compare_source, event_fingerprint, inspect_source, post_issue_comment, render_comment

ROOT = Path(__file__).resolve().parent
WATCHLIST_PATH = ROOT / "watchlist.json"
STATE_PATH = ROOT / "state" / "source_state.json"
REPORT_PATH = ROOT / "state" / "latest_report.json"
DEFAULT_TIMEOUT = 18.0


def validate_watchlist(watchlist: dict[str, Any]) -> None:
    for key in ("case_id", "github_issue", "editorial_route", "alert_policy", "sources"):
        if key not in watchlist:
            raise ValueError(f"watchlist missing {key}")
    route = watchlist["editorial_route"]
    if route.get("primary_section") != "Investigații":
        raise ValueError("case must remain routed to Investigații")
    if route.get("auto_publish") is not False:
        raise ValueError("auto_publish must be false")
    source_ids = [source["id"] for source in watchlist["sources"]]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("duplicate source ids")
    for source in watchlist["sources"]:
        if not source["url"].startswith("https://"):
            raise ValueError(f"non-HTTPS source: {source['id']}")
        if source["mode"] not in {"focused_text", "rss"}:
            raise ValueError(f"invalid mode: {source['id']}")
        if source["tier"].startswith("T3") and source.get("materiality") == "high":
            raise ValueError(f"T3 source cannot be high materiality: {source['id']}")


def run(args: argparse.Namespace) -> dict[str, Any]:
    watchlist = load_json(WATCHLIST_PATH, {})
    validate_watchlist(watchlist)
    if args.validate_only:
        return {"status": "VALID", "case_id": watchlist["case_id"], "sources": len(watchlist["sources"])}

    previous_state = load_json(STATE_PATH, {"sources": {}, "runs": 0})
    previous_sources = previous_state.get("sources", {})
    baseline = not bool(previous_sources)
    threshold = int(watchlist["alert_policy"].get("comment_after_consecutive_failures", 3))
    observed_at = utcnow()
    merged_sources: dict[str, Any] = {}
    events: list[dict[str, Any]] = []

    for source in watchlist["sources"]:
        current = inspect_source(source, args.timeout, args.offline)
        merged, source_events = compare_source(source, current, previous_sources.get(source["id"]), threshold, baseline)
        merged_sources[source["id"]] = merged
        events.extend(source_events)

    fingerprint = event_fingerprint(events) if events else None
    duplicate_alert = bool(fingerprint and fingerprint == previous_state.get("last_alert_fingerprint"))
    should_comment = bool(events) and not duplicate_alert
    if args.force_summary and not events:
        events = [{
            "type": "STATUS_SUMMARY",
            "source_id": "case",
            "label": watchlist["title"],
            "url": f"https://github.com/{os.getenv('GITHUB_REPOSITORY', 'mihaicismaru-bit/civora')}/issues/{watchlist['github_issue']}",
            "materiality": "medium",
            "summary": f"Monitorizarea este activă pentru {len(watchlist['sources'])} surse; nu au fost detectate schimbări materiale.",
        }]
        should_comment = True
        fingerprint = event_fingerprint(events)

    comment_status = "NOT_REQUESTED"
    comment_error = None
    if should_comment and not args.no_comment and not args.offline:
        try:
            post_issue_comment(int(watchlist["github_issue"]), render_comment(watchlist, events, observed_at))
            comment_status = "POSTED"
        except Exception as exc:
            comment_status = "FAILED"
            comment_error = f"{type(exc).__name__}: {exc}"
    elif should_comment:
        comment_status = "SUPPRESSED_BY_FLAG"
    elif duplicate_alert:
        comment_status = "DUPLICATE_SUPPRESSED"

    state = {
        "schema_version": "1.0",
        "case_id": watchlist["case_id"],
        "observed_at": observed_at,
        "runs": int(previous_state.get("runs", 0)) + 1,
        "baseline": baseline,
        "sources": merged_sources,
        "last_alert_fingerprint": fingerprint if should_comment and comment_status in {"POSTED", "SUPPRESSED_BY_FLAG"} else previous_state.get("last_alert_fingerprint"),
        "last_comment_status": comment_status,
        "last_comment_error": comment_error,
    }
    report = {
        "schema_version": "1.0",
        "case_id": watchlist["case_id"],
        "observed_at": observed_at,
        "section": watchlist["editorial_route"],
        "status": "BASELINE_CREATED" if baseline else ("EVENTS_DETECTED" if events else "NO_MATERIAL_CHANGE"),
        "summary": {
            "sources": len(watchlist["sources"]),
            "ok": sum(item.get("health") == "OK" for item in merged_sources.values()),
            "failed": sum(item.get("health") == "FAILED" for item in merged_sources.values()),
            "offline": sum(item.get("health") == "SKIPPED_OFFLINE" for item in merged_sources.values()),
            "events": len(events),
            "comment_status": comment_status,
            "comment_error": comment_error,
        },
        "events": events,
    }
    dump_json(STATE_PATH, state)
    dump_json(REPORT_PATH, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--no-comment", action="store_true")
    parser.add_argument("--force-summary", action="store_true")
    report = run(parser.parse_args())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FATAL: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
