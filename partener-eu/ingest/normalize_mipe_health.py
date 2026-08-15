#!/usr/bin/env python3
"""Normalize MIPE ingestion health after a direct-only run.

A successful refresh of an ancillary official URL (for example the previously
verified MySMIS registry item) must not make the whole MIPE ingestion look
healthy while the explicit PDDS priority seed or all primary MIPE discovery
roots are unavailable.  This keeps the public feed fail-closed and makes
source outages visible without deleting last-known-good verified items.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "partener-eu" / "ingest" / "state" / "mipe_state.json"
WEB_PATH = ROOT / "partener-eu" / "web" / "mipe-news.js"
PDDS_PRIORITY_SEED = "https://mfe.gov.ro/pdds/despre-program-programare/"


def is_direct_success(row: dict) -> bool:
    return bool(row.get("ok")) and str(row.get("transport") or "").startswith("direct")


def normalize_state(state: dict) -> tuple[dict, bool]:
    run = state.get("lastRun") or {}
    roots = run.get("roots") or []
    items = state.get("items") or []

    priority_rows = [row for row in roots if row.get("target") == PDDS_PRIORITY_SEED]
    priority_ok = any(is_direct_success(row) for row in priority_rows)
    primary_root_ok = any(is_direct_success(row) for row in roots)

    run["prioritySeed"] = PDDS_PRIORITY_SEED
    run["prioritySeedAvailable"] = priority_ok
    run["primaryOfficialRootAvailable"] = primary_root_ok

    previous_status = str(run.get("status") or state.get("status") or "")
    normalized_status = previous_status

    # The explicit PDDS seed is a critical source. A successful fetch of an
    # ancillary candidate cannot mask its failure. If no primary root succeeds,
    # the same fail-closed rule applies even when a preserved candidate URL can
    # still be refreshed directly.
    if not priority_ok or not primary_root_ok:
        normalized_status = (
            "DEGRADED_LAST_KNOWN_GOOD_PRESERVED"
            if items
            else "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED"
        )
        run["sourceHealth"] = (
            "PDDS_PRIORITY_SEED_UNAVAILABLE"
            if not priority_ok
            else "PRIMARY_MIPE_ROOTS_UNAVAILABLE"
        )
        run["healthNormalizationReason"] = (
            "A direct success on an ancillary/previous candidate does not make "
            "the MIPE source healthy while the explicit PDDS priority seed or "
            "primary discovery roots are unavailable."
        )
        if not primary_root_ok:
            run["transportMode"] = "primary-direct-unavailable"
    else:
        run["sourceHealth"] = "PRIMARY_SOURCES_AVAILABLE"
        run.pop("healthNormalizationReason", None)

    changed = normalized_status != previous_status
    run["status"] = normalized_status
    state["status"] = normalized_status
    state["lastRun"] = run

    # Keep the latest run history internally consistent as well.
    runs = state.get("runs") or []
    if runs and runs[-1].get("observedAt") == run.get("observedAt"):
        runs[-1] = dict(run)
        state["runs"] = runs

    return state, changed


def write_feed(state: dict) -> None:
    run = state.get("lastRun") or {}
    payload = {
        "status": state.get("status"),
        "asOf": run.get("observedAt"),
        "source": "MIPE official web properties",
        "roots": run.get("roots", []),
        "searchTransports": run.get("searchTransports", []),
        "itemCount": len(state.get("items", [])),
        "currentVerifiedCount": run.get("currentVerifiedCount", 0),
        "transportMode": run.get("transportMode", "unavailable"),
        "lastKnownGoodPreserved": run.get("lastKnownGoodPreserved", False),
        "prioritySeed": run.get("prioritySeed"),
        "prioritySeedAvailable": run.get("prioritySeedAvailable"),
        "primaryOfficialRootAvailable": run.get("primaryOfficialRootAvailable"),
        "sourceHealth": run.get("sourceHealth"),
    }
    text = "window.PARTENER_DATA=window.PARTENER_DATA||{};\n"
    text += "window.PARTENER_DATA.mipeIngestion=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n"
    text += "window.PARTENER_DATA.mipeNews=" + json.dumps(state.get("items", []), ensure_ascii=False, separators=(",", ":")) + ";\n"
    WEB_PATH.write_text(text, encoding="utf-8")


def main() -> int:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    state, changed = normalize_state(state)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_feed(state)
    run = state.get("lastRun") or {}
    print(json.dumps({
        "status": state.get("status"),
        "prioritySeedAvailable": run.get("prioritySeedAvailable"),
        "primaryOfficialRootAvailable": run.get("primaryOfficialRootAvailable"),
        "lastKnownGoodPreserved": run.get("lastKnownGoodPreserved"),
        "currentVerifiedCount": run.get("currentVerifiedCount"),
        "publishedItemCount": run.get("publishedItemCount"),
        "normalized": changed,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
