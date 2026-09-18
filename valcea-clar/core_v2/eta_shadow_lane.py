from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any


PASSENGER_IMPACT_CLASSES = {"SCHEDULE_CHANGE", "SERVICE_ALERT", "FARE_OR_ACCESS_CHANGE"}


def _parse_iso_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def adjudicate_eta_signal(signal: dict[str, Any], *, as_of: date) -> dict[str, Any]:
    signal_id = str(signal.get("signal_id") or signal.get("article_url") or "UNKNOWN")
    classification = str(signal.get("classification") or "HOLD")
    boundaries = signal.get("boundaries") or {}

    base = {
        "signal_id": signal_id,
        "source_kind": "eta",
        "classification": classification,
        "title": str(signal.get("title") or "").strip(),
        "source_url": str(signal.get("article_url") or "").strip(),
        "publication_authority": "NONE",
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
    }

    if boundaries and str(boundaries.get("publication_authority") or "NONE") != "NONE":
        return {**base, "state": "BLOCKED", "reason": "source_adapter_publication_boundary_violation"}

    if classification not in PASSENGER_IMPACT_CLASSES:
        return {**base, "state": "NO_STORY", "reason": "no_supported_current_passenger_impact_class"}

    effective_start = _parse_iso_date(signal.get("effective_start"))
    effective_end = _parse_iso_date(signal.get("effective_end"))
    if effective_start is None:
        return {
            **base,
            "state": "BLOCKED",
            "reason": "passenger_impact_without_explicit_effective_start",
            "currentness": "UNPROVEN",
        }
    if effective_end is not None and effective_end < effective_start:
        return {
            **base,
            "state": "BLOCKED",
            "reason": "invalid_effective_window",
            "currentness": "UNPROVEN",
        }
    if effective_end is not None and effective_end < as_of:
        return {
            **base,
            "state": "NO_STORY",
            "reason": "explicit_effective_window_expired",
            "currentness": "EXPIRED",
            "effective_start": effective_start.isoformat(),
            "effective_end": effective_end.isoformat(),
        }

    if effective_start > as_of:
        currentness = "UPCOMING_EXPLICIT"
    elif effective_end is not None and effective_start <= as_of <= effective_end:
        currentness = "ACTIVE_EXPLICIT_WINDOW"
    elif effective_end is None and effective_start >= as_of - timedelta(days=1):
        currentness = "RECENT_EXPLICIT_START_NO_END"
    else:
        return {
            **base,
            "state": "BLOCKED",
            "reason": "open_ended_operational_state_requires_fresh_reverification",
            "currentness": "UNPROVEN",
            "effective_start": effective_start.isoformat(),
            "effective_end": None,
        }

    visual_candidate = signal.get("visual_candidate") or {}
    photo_truth = "NO_SOURCE_IMAGE"
    if visual_candidate:
        if visual_candidate.get("public_reuse_allowed") is True:
            photo_truth = "UNADJUDICATED_REUSABLE_SOURCE_IMAGE"
        else:
            photo_truth = "BLOCKED_UNCLEARED_SOURCE_IMAGE"

    return {
        **base,
        "state": "MATERIAL_SIGNAL_SHADOW",
        "reason": "explicit_passenger_impact_with_bounded_currentness",
        "currentness": currentness,
        "effective_start": effective_start.isoformat(),
        "effective_end": effective_end.isoformat() if effective_end else None,
        "effective_time": signal.get("effective_time"),
        "cms_published_at": signal.get("cms_published_at"),
        "cms_timestamp_semantics": signal.get("cms_timestamp_semantics"),
        "evidence": signal.get("evidence") or {},
        "photo_truth_status": photo_truth,
        "visual_candidate_promoted": False,
    }


def verify_eta_signals(signals: list[dict[str, Any]], *, as_of: date | None = None) -> dict[str, Any]:
    current_date = as_of or date.today()
    rows = [adjudicate_eta_signal(signal, as_of=current_date) for signal in signals if isinstance(signal, dict)]
    return {
        "schema_version": "1.0",
        "mode": "ETA_CURRENT_MATERIAL_SIGNAL_SHADOW",
        "source_kind": "eta",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "as_of_date": current_date.isoformat(),
        "signal_count": len(rows),
        "material_signal_shadow_count": sum(row.get("state") == "MATERIAL_SIGNAL_SHADOW" for row in rows),
        "no_story_count": sum(row.get("state") == "NO_STORY" for row in rows),
        "blocked_count": sum(row.get("state") == "BLOCKED" for row in rows),
        "rows": rows,
        "truth_rule": (
            "ETA notices may cross only the signal/currentness boundary here. CMS publication time is not service time; "
            "old open-ended operational notices require fresh reverification; static timetables are not live status; "
            "source images with unclear reuse rights never cross the photo gate."
        ),
    }


def _load_eta_adapter():
    path = Path(__file__).resolve().parents[1] / "scripts" / "eta_valcea_signal_adapter.py"
    spec = importlib.util.spec_from_file_location("core_v2_eta_valcea_signal_adapter", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("eta_adapter_load_failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _live_signals(limit: int) -> list[dict[str, Any]]:
    adapter = _load_eta_adapter()
    return list(adapter.discover_and_enrich(limit=limit))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bounded ETA current-material signal gate in Core v2 shadow mode")
    parser.add_argument("--input")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--as-of")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if bool(args.input) == bool(args.live):
        raise SystemExit("provide exactly one of --input or --live")

    current_date = date.fromisoformat(args.as_of) if args.as_of else date.today()
    try:
        signals = _live_signals(args.limit) if args.live else json.loads(Path(args.input).read_text(encoding="utf-8"))
        if not isinstance(signals, list):
            raise ValueError("ETA input must be a list of signals")
        result = verify_eta_signals(signals, as_of=current_date)
    except Exception as exc:
        result = {
            "schema_version": "1.0",
            "mode": "ETA_CURRENT_MATERIAL_SIGNAL_SHADOW",
            "source_kind": "eta",
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "production_writer_ready": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
            "status": "BLOCKED_SOURCE_UNAVAILABLE",
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "rows": [],
        }

    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result.get("status", "PASS_SHADOW"),
        "signal_count": result.get("signal_count", 0),
        "material_signal_shadow_count": result.get("material_signal_shadow_count", 0),
        "no_story_count": result.get("no_story_count", 0),
        "blocked_count": result.get("blocked_count", 0),
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
