#!/usr/bin/env python3
"""Deterministic, non-persistent APAVIL outage freshness and revision state.

The state builder consumes repeated evidence-first snapshots from
apavil_valcea_signal_adapter.py. It expires old service windows objectively,
threads stable official-attachment revisions only when snapshot order is known,
and can link explicit cancellation/reschedule notices conservatively.

No persistence, Fact Kernel, Writer, public projection, live-status claim, or
publication authority is introduced here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, time
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

SOURCE_ID = "signal-apavil-valcea-scheduled-outages"
SOURCE_KIND = "PUBLIC_WATER_UTILITY_SCHEDULED_OUTAGES"
SOURCE_URL = "https://apavil.ro/?page_id=962"
ALLOWED_CLASSES = {"SCHEDULED_WATER_OUTAGE", "HOLD"}
BUCHAREST = ZoneInfo("Europe/Bucharest")

UPDATE_RE = re.compile(
    r"\b(?:actualizare|actualizat[ăa]?|modific(?:are|at[ăa]?)|reprogram(?:are|at[ăa]?)|"
    r"prelung(?:ire|it[ăa]?)|anular(?:e|ea)|anulat[ăa]?|suspend(?:are|at[ăa]?))\b",
    re.IGNORECASE,
)
CANCEL_RE = re.compile(
    r"\b(?:anular(?:e|ea)|anulat[ăa]?|nu\s+se\s+mai\s+efectueaz[ăa]|"
    r"se\s+revoc[ăa]|revocat[ăa]?)\b",
    re.IGNORECASE,
)


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", clean_text(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def parse_as_of(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(clean_text(value))
    except ValueError as exc:
        raise ValueError("as_of requires an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("as_of requires an offset-aware timestamp")
    return parsed.astimezone(BUCHAREST)


def parse_observed_at(value: Any) -> datetime:
    text = clean_text(value)
    if not text:
        raise ValueError("snapshot observed_at is required")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("snapshot observed_at requires an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("snapshot observed_at requires an offset-aware timestamp")
    return parsed.astimezone(BUCHAREST)


def parse_iso_date(value: Any, field: str) -> date:
    text = clean_text(value)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field} requires YYYY-MM-DD") from exc


def parse_clock(value: Any, field: str) -> time:
    text = clean_text(value)
    try:
        parsed = time.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field} requires HH:MM[:SS]") from exc
    if parsed.tzinfo is not None:
        raise ValueError(f"{field} must be a local wall-clock time")
    return parsed


def canonical_attachment_url(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    parsed = urlsplit(text)
    if parsed.scheme != "https" or parsed.hostname not in {"apavil.ro", "www.apavil.ro"}:
        raise ValueError("APAVIL state refuses non-official attachment URL")
    if not parsed.path.casefold().startswith("/materiale/anunturi/") or not parsed.path.casefold().endswith(".pdf"):
        raise ValueError("APAVIL state requires canonical official PDF attachment path")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("APAVIL state refuses ambiguous attachment URL")
    return "https://apavil.ro" + parsed.path


def normalize_geography(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()
    if not isinstance(values, list):
        raise ValueError("explicit_geography must be a list")
    out = {fold(item) for item in values if clean_text(item)}
    return tuple(sorted(out))


def signal_fingerprint(signal: dict[str, Any]) -> str:
    public = {key: value for key, value in signal.items() if not key.startswith("_")}
    return json.dumps(public, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_signal(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("APAVIL state signals must be objects")
    if raw.get("source_id") != SOURCE_ID or raw.get("source_kind") != SOURCE_KIND:
        raise ValueError("APAVIL state accepts only canonical APAVIL scheduled-outage signals")
    if raw.get("source_url") != SOURCE_URL or raw.get("final_url") != SOURCE_URL:
        raise ValueError("APAVIL state refuses source URL drift")

    signal_id = clean_text(raw.get("signal_id"))
    if not re.fullmatch(r"apavil-outage-[0-9a-f]{20}", signal_id):
        raise ValueError("APAVIL state requires canonical signal_id")

    signal_class = clean_text(raw.get("signal_class")).upper()
    if signal_class not in ALLOWED_CLASSES:
        raise ValueError("APAVIL state refuses unknown signal_class")

    if raw.get("publication_authority") != "NONE":
        raise ValueError("APAVIL state refuses publication authority drift")
    required_false = (
        "public_projection",
        "auto_publication",
        "persistence_allowed",
        "fact_kernel_authority",
        "current_status_claim_allowed",
        "attachment_fetch_allowed",
        "attachment_body_ingest_allowed",
        "media_public_reuse_allowed",
    )
    if any(raw.get(field) is not False for field in required_false):
        raise ValueError("APAVIL state refuses authority or safety boundary drift")

    title = clean_text(raw.get("title"))
    if not title:
        raise ValueError("APAVIL state requires title")

    raw_dates = raw.get("effective_dates")
    if not isinstance(raw_dates, list):
        raise ValueError("effective_dates must be a list")
    dates = tuple(parse_iso_date(item, "effective_dates") for item in raw_dates)
    if tuple(sorted(set(dates))) != dates:
        raise ValueError("effective_dates must be unique and ascending")
    if len(dates) > 2:
        raise ValueError("APAVIL state supports at most a start/end date pair")

    date_status = clean_text(raw.get("effective_date_status"))
    if signal_class == "SCHEDULED_WATER_OUTAGE":
        if date_status != "EXPLICIT_VISIBLE_TEXT" or not dates:
            raise ValueError("scheduled outage requires explicit valid effective date")
    elif signal_class == "HOLD" and date_status == "EXPLICIT_VISIBLE_TEXT" and dates:
        pass

    time_range = raw.get("time_range")
    start_clock: time | None = None
    end_clock: time | None = None
    if time_range is not None:
        if not isinstance(time_range, dict) or time_range.get("basis") != "EXPLICIT_VISIBLE_TEXT":
            raise ValueError("APAVIL state refuses non-explicit time range")
        start_clock = parse_clock(time_range.get("start"), "time_range.start")
        end_clock = parse_clock(time_range.get("end"), "time_range.end")
        if len(dates) == 1 and end_clock < start_clock:
            raise ValueError("single-day outage cannot have inverted time range")

    attachment = canonical_attachment_url(raw.get("attachment_url"))
    geography = normalize_geography(raw.get("explicit_geography"))

    out = dict(raw)
    out.update(
        {
            "signal_id": signal_id,
            "signal_class": signal_class,
            "title": title,
            "_dates": dates,
            "_start_clock": start_clock,
            "_end_clock": end_clock,
            "_attachment": attachment,
            "_geography": geography,
            "_update_hint": bool(UPDATE_RE.search(title)),
            "_cancel_hint": bool(CANCEL_RE.search(title)),
        }
    )
    return out


def validate_snapshot(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("APAVIL state snapshots must be objects")
    observed_at = parse_observed_at(raw.get("observed_at"))
    sha = clean_text(raw.get("source_content_sha256"))
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("snapshot source_content_sha256 requires SHA-256")
    signals_raw = raw.get("signals")
    if not isinstance(signals_raw, list):
        raise ValueError("snapshot signals must be a list")

    signals: dict[str, dict[str, Any]] = {}
    for item in signals_raw:
        signal = validate_signal(item)
        prior = signals.get(signal["signal_id"])
        if prior is not None and signal_fingerprint(prior) != signal_fingerprint(signal):
            raise ValueError("snapshot reuses signal_id with conflicting payload")
        signals[signal["signal_id"]] = signal

    return {
        "observed_at": observed_at,
        "source_content_sha256": sha,
        "signals": signals,
    }


def logical_id(seed: str) -> str:
    return "apavil-service-thread-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def identity_seed(signal: dict[str, Any]) -> str:
    if signal["_attachment"]:
        return "attachment:" + signal["_attachment"]
    basis = "|".join(
        [
            "no-attachment",
            ",".join(day.isoformat() for day in signal["_dates"]),
            ",".join(signal["_geography"]),
            fold(signal["title"]),
        ]
    )
    return basis


def revision_key(signal: dict[str, Any]) -> str:
    return signal["_attachment"] or signal["signal_id"]


def same_incident_shape(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if not left["_geography"] or left["_geography"] != right["_geography"]:
        return False
    if not left["_dates"] or left["_dates"] != right["_dates"]:
        return False
    if left["signal_class"] == "HOLD" and right["signal_class"] == "HOLD":
        return False
    return left["_update_hint"] or right["_update_hint"] or left["_cancel_hint"] or right["_cancel_hint"]


def effective_state(signal: dict[str, Any], as_of: datetime) -> str:
    if signal["signal_class"] == "HOLD" or not signal["_dates"]:
        return "DATE_OR_CLASSIFICATION_HOLD"
    if signal["_cancel_hint"]:
        return "CANCELLATION_REPORTED_RECHECK_REQUIRED"

    start_date = signal["_dates"][0]
    end_date = signal["_dates"][-1]
    today = as_of.date()
    if today < start_date:
        return "NOT_YET_EFFECTIVE"
    if today > end_date:
        return "EXPLICIT_WINDOW_ENDED"

    start_clock = signal["_start_clock"]
    end_clock = signal["_end_clock"]
    if len(signal["_dates"]) == 1 and start_clock and end_clock:
        local_clock = as_of.timetz().replace(tzinfo=None)
        if local_clock < start_clock:
            return "NOT_YET_EFFECTIVE_TODAY"
        if local_clock > end_clock:
            return "EXPLICIT_TIME_WINDOW_ENDED"

    return "WITHIN_EXPLICIT_WINDOW_RECHECK_REQUIRED"


def render_signal(signal: dict[str, Any], observed_at: datetime) -> dict[str, Any]:
    return {
        "signal_id": signal["signal_id"],
        "observed_at": observed_at.isoformat(),
        "signal_class": signal["signal_class"],
        "title": signal["title"],
        "effective_dates": [item.isoformat() for item in signal["_dates"]],
        "time_range": signal.get("time_range"),
        "explicit_geography": signal.get("explicit_geography") or [],
        "attachment_url": signal["_attachment"],
        "update_hint": signal["_update_hint"],
        "cancellation_hint": signal["_cancel_hint"],
    }


def build_state(snapshots: list[dict[str, Any]], *, as_of: str) -> dict[str, Any]:
    if not isinstance(snapshots, list):
        raise ValueError("APAVIL state requires a snapshots list")
    as_of_dt = parse_as_of(as_of)

    validated = [validate_snapshot(item) for item in snapshots]
    validated.sort(key=lambda item: (item["observed_at"], item["source_content_sha256"]))

    seen_snapshot_sha: dict[str, datetime] = {}
    unique_snapshots: list[dict[str, Any]] = []
    duplicate_snapshot_count = 0
    for snapshot in validated:
        prior = seen_snapshot_sha.get(snapshot["source_content_sha256"])
        if prior is not None:
            duplicate_snapshot_count += 1
            continue
        seen_snapshot_sha[snapshot["source_content_sha256"]] = snapshot["observed_at"]
        unique_snapshots.append(snapshot)

    versions_by_identity: dict[str, list[tuple[datetime, dict[str, Any]]]] = {}
    signal_first_seen: dict[str, tuple[datetime, str]] = {}

    for snapshot in unique_snapshots:
        for signal_id, signal in snapshot["signals"].items():
            prior = signal_first_seen.get(signal_id)
            fingerprint = signal_fingerprint(signal)
            if prior is not None:
                if prior[1] != fingerprint:
                    raise ValueError("APAVIL state detected conflicting signal_id across snapshots")
                continue
            signal_first_seen[signal_id] = (snapshot["observed_at"], fingerprint)
            versions_by_identity.setdefault(revision_key(signal), []).append((snapshot["observed_at"], signal))

    threads: list[dict[str, Any]] = []
    for key, versions in versions_by_identity.items():
        versions.sort(key=lambda pair: (pair[0], pair[1]["signal_id"]))
        if len({pair[0] for pair in versions}) != len(versions):
            raise ValueError("APAVIL state refuses ambiguous same-time revisions")
        latest = versions[-1][1]
        threads.append(
            {
                "logical_thread_id": logical_id(identity_seed(versions[0][1])),
                "identity_key": key,
                "versions": versions,
                "latest": latest,
                "linked_identity_keys": {key},
            }
        )

    # Conservative cross-attachment linking for explicit cancellation/reschedule notices.
    merged_into: dict[int, int] = {}
    for idx, thread in enumerate(threads):
        if idx in merged_into:
            continue
        latest = thread["latest"]
        if not (latest["_update_hint"] or latest["_cancel_hint"]):
            continue
        candidates: list[int] = []
        for other_idx, other in enumerate(threads):
            if other_idx == idx or other_idx in merged_into:
                continue
            if other["versions"][-1][0] >= thread["versions"][-1][0]:
                continue
            if same_incident_shape(other["latest"], latest):
                candidates.append(other_idx)
        if len(candidates) == 1:
            parent_idx = candidates[0]
            parent = threads[parent_idx]
            combined = sorted(parent["versions"] + thread["versions"], key=lambda pair: (pair[0], pair[1]["signal_id"]))
            parent["versions"] = combined
            parent["latest"] = combined[-1][1]
            parent["linked_identity_keys"].update(thread["linked_identity_keys"])
            merged_into[idx] = parent_idx

    rendered: list[dict[str, Any]] = []
    for idx, thread in enumerate(threads):
        if idx in merged_into:
            continue
        versions = thread["versions"]
        latest_observed, latest = versions[-1]
        state = effective_state(latest, as_of_dt)
        rendered.append(
            {
                "logical_thread_id": thread["logical_thread_id"],
                "latest_signal_id": latest["signal_id"],
                "latest_observed_at": latest_observed.isoformat(),
                "revision_count": len(versions),
                "linked_identity_keys": sorted(thread["linked_identity_keys"]),
                "revisions": [render_signal(signal, observed) for observed, signal in versions],
                "effective_state": state,
                "expired_for_current_service_surface": state in {
                    "EXPLICIT_WINDOW_ENDED",
                    "EXPLICIT_TIME_WINDOW_ENDED",
                    "DATE_OR_CLASSIFICATION_HOLD",
                    "CANCELLATION_REPORTED_RECHECK_REQUIRED",
                },
                "current_status_claim_allowed": False,
                "reader_facing_eligible": False,
                "source_recheck_required": True,
                "lifecycle": "INTERNAL_APAVIL_SERVICE_THREAD_NEEDS_SOURCE_RECHECK",
            }
        )

    rendered.sort(key=lambda item: (item["latest_observed_at"], item["latest_signal_id"]), reverse=True)
    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR internal APAVIL outage freshness/revision state",
        "as_of": as_of_dt.isoformat(),
        "snapshot_count": len(unique_snapshots),
        "duplicate_snapshot_count": duplicate_snapshot_count,
        "unique_signal_count": len(signal_first_seen),
        "thread_count": len(rendered),
        "threads": rendered,
        "policy": {
            "reader_facing_eligible": False,
            "publication_authority": "NONE",
            "public_projection": False,
            "auto_publication": False,
            "persistence_authority": "NONE",
            "fact_kernel_authority": "NONE",
            "writer_authority": "NONE",
            "current_status_claim_allowed": False,
            "freshness_threshold_policy": "NONE_EXPLICIT_EFFECTIVE_WINDOW_ONLY",
            "source_recheck_required_before_current_status_claim": True,
            "cross_attachment_linking": "EXACT_GEOGRAPHY_AND_EFFECTIVE_DATES_PLUS_EXPLICIT_UPDATE_OR_CANCELLATION_AND_UNIQUE_PRIOR_CANDIDATE",
        },
    }


def sample_signal(
    signal_id: str,
    *,
    title: str,
    dates: list[str],
    attachment: str,
    geography: list[str],
    time_range: dict[str, str] | None = None,
    signal_class: str = "SCHEDULED_WATER_OUTAGE",
) -> dict[str, Any]:
    return {
        "signal_id": signal_id,
        "source_id": SOURCE_ID,
        "source_name": "APAVIL S.A. Vâlcea — Opriri programate",
        "source_url": SOURCE_URL,
        "final_url": SOURCE_URL,
        "source_tier": "T1",
        "source_kind": SOURCE_KIND,
        "title": title,
        "signal_class": signal_class,
        "effective_dates": dates,
        "effective_date_status": "EXPLICIT_VISIBLE_TEXT" if dates else "MISSING",
        "time_range": time_range,
        "explicit_geography": geography,
        "attachment_url": attachment,
        "attachment_type": "PDF",
        "attachment_fetch_allowed": False,
        "attachment_body_ingest_allowed": False,
        "current_status_claim_allowed": False,
        "publication_authority": "NONE",
        "public_projection": False,
        "auto_publication": False,
        "persistence_allowed": False,
        "fact_kernel_authority": False,
        "media_public_reuse_allowed": False,
        "lifecycle": "SIGNAL_ONLY_NEEDS_FRESHNESS_RECHECK",
        "provenance": {"authority": "APAVIL_OFFICIAL_SCHEDULED_OUTAGES_INDEX"},
    }


def self_test() -> int:
    old = sample_signal(
        "apavil-outage-" + "1" * 20,
        title="Anunț întrerupere furnizare apă în municipiul Râmnicu Vâlcea în data de 10.08.2026",
        dates=["2026-08-10"],
        attachment="https://apavil.ro/materiale/anunturi/2026/old.pdf",
        geography=["municipiul Râmnicu Vâlcea"],
        time_range={"start": "09:00", "end": "15:00", "basis": "EXPLICIT_VISIBLE_TEXT"},
    )
    future = sample_signal(
        "apavil-outage-" + "2" * 20,
        title="Anunț întrerupere furnizare apă în localitatea Horezu în data de 02.09.2026",
        dates=["2026-09-02"],
        attachment="https://apavil.ro/materiale/anunturi/2026/future.pdf",
        geography=["localitatea Horezu"],
        time_range={"start": "09:00", "end": "15:00", "basis": "EXPLICIT_VISIBLE_TEXT"},
    )
    today = sample_signal(
        "apavil-outage-" + "3" * 20,
        title="Anunț întrerupere furnizare apă în comuna Bujoreni în data de 29.08.2026",
        dates=["2026-08-29"],
        attachment="https://apavil.ro/materiale/anunturi/2026/today.pdf",
        geography=["comuna Bujoreni"],
        time_range={"start": "09:00", "end": "15:00", "basis": "EXPLICIT_VISIBLE_TEXT"},
    )
    today_revision = sample_signal(
        "apavil-outage-" + "4" * 20,
        title="Actualizare: întrerupere furnizare apă în comuna Bujoreni în data de 29.08.2026",
        dates=["2026-08-29"],
        attachment="https://apavil.ro/materiale/anunturi/2026/today.pdf",
        geography=["comuna Bujoreni"],
        time_range={"start": "10:00", "end": "16:00", "basis": "EXPLICIT_VISIBLE_TEXT"},
    )
    cancellation = sample_signal(
        "apavil-outage-" + "5" * 20,
        title="Anulare: întrerupere furnizare apă în localitatea Horezu în data de 02.09.2026",
        dates=["2026-09-02"],
        attachment="https://apavil.ro/materiale/anunturi/2026/future-cancel.pdf",
        geography=["localitatea Horezu"],
        time_range={"start": "09:00", "end": "15:00", "basis": "EXPLICIT_VISIBLE_TEXT"},
    )

    snapshots = [
        {"observed_at": "2026-08-29T08:00:00+03:00", "source_content_sha256": "a" * 64, "signals": [old, future, today]},
        {"observed_at": "2026-08-29T10:00:00+03:00", "source_content_sha256": "b" * 64, "signals": [old, future, today_revision]},
        {"observed_at": "2026-08-29T11:00:00+03:00", "source_content_sha256": "c" * 64, "signals": [old, cancellation, today_revision]},
        {"observed_at": "2026-08-29T11:05:00+03:00", "source_content_sha256": "c" * 64, "signals": [old, cancellation, today_revision]},
    ]
    state = build_state(snapshots, as_of="2026-08-29T12:00:00+03:00")
    assert state["duplicate_snapshot_count"] == 1
    assert state["policy"]["current_status_claim_allowed"] is False

    old_thread = next(t for t in state["threads"] if t["latest_signal_id"] == old["signal_id"])
    assert old_thread["effective_state"] == "EXPLICIT_WINDOW_ENDED"
    assert old_thread["expired_for_current_service_surface"] is True

    today_thread = next(t for t in state["threads"] if t["latest_signal_id"] == today_revision["signal_id"])
    assert today_thread["revision_count"] == 2
    assert today_thread["effective_state"] == "WITHIN_EXPLICIT_WINDOW_RECHECK_REQUIRED"

    cancel_thread = next(t for t in state["threads"] if t["latest_signal_id"] == cancellation["signal_id"])
    assert cancel_thread["revision_count"] == 2
    assert cancel_thread["effective_state"] == "CANCELLATION_REPORTED_RECHECK_REQUIRED"
    assert cancel_thread["current_status_claim_allowed"] is False

    after = build_state(snapshots[:2], as_of="2026-08-29T17:00:00+03:00")
    after_today = next(t for t in after["threads"] if t["latest_signal_id"] == today_revision["signal_id"])
    assert after_today["effective_state"] == "EXPLICIT_TIME_WINDOW_ENDED"

    bad = dict(today)
    bad["public_projection"] = True
    try:
        build_state(
            [{"observed_at": "2026-08-29T12:00:00+03:00", "source_content_sha256": "d" * 64, "signals": [bad]}],
            as_of="2026-08-29T12:00:00+03:00",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("authority drift must fail closed")

    print("APAVIL outage freshness/revision state self-test: ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--input", help="JSON file containing a snapshots array")
    parser.add_argument("--as-of", help="Offset-aware ISO timestamp")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.input or not args.as_of:
        parser.error("--input and --as-of are required unless --self-test is used")
    with open(args.input, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    snapshots = payload["snapshots"] if isinstance(payload, dict) else payload
    print(json.dumps(build_state(snapshots, as_of=args.as_of), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
