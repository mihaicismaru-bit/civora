#!/usr/bin/env python3
"""Deterministic cadence and fatigue gate for LOCAL NEWS OS social publications.

This module decides *when* an already-validated native social product may be
published. It does not rank stories, rewrite copy, invent urgency, fetch
analytics, or publish anything. Decisions are derived only from CHANNEL_CONFIG,
an instance/channel-scoped publication history, an explicit candidate payload,
and an explicit clock value.

Safety properties:
- fail closed on instance/channel identity conflicts;
- local-time daily limits and quiet hours use zoneinfo, never server local time;
- same-story cooldown and related-topic fatigue are separate controls;
- breaking news may bypass quiet hours only when CHANNEL_CONFIG explicitly
  permits it; it does not silently bypass other fatigue gates;
- a real correction may bypass cadence/fatigue only when corrections_priority
  is enabled and correction_of is explicit;
- no external dependencies and no observed metrics are required.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _parse_instant(value: Any, field: str) -> dt.datetime:
    raw = _clean(value)
    if not raw:
        raise ValueError(f"{field} is required")
    parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def _parse_clock(value: Any, field: str) -> dt.time:
    raw = _clean(value)
    try:
        hour, minute = raw.split(":", 1)
        h, m = int(hour), int(minute)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{field} must be HH:MM") from exc
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"{field} must be a valid 24-hour clock")
    return dt.time(hour=h, minute=m)


def _localize(day: dt.date, clock: dt.time, zone: ZoneInfo) -> dt.datetime:
    return dt.datetime.combine(day, clock, tzinfo=zone)


def _quiet_window(now_local: dt.datetime, quiet: dict[str, Any]) -> tuple[bool, dt.datetime | None]:
    start_t = _parse_clock(quiet.get("start"), "cadence.quiet_hours.start")
    end_t = _parse_clock(quiet.get("end"), "cadence.quiet_hours.end")
    if start_t == end_t:
        return False, None

    current = now_local.timetz().replace(tzinfo=None)
    if start_t < end_t:
        if start_t <= current < end_t:
            return True, _localize(now_local.date(), end_t, now_local.tzinfo)  # type: ignore[arg-type]
        return False, None

    # Crossing midnight, e.g. 23:00 -> 06:00.
    if current >= start_t:
        return True, _localize(now_local.date() + dt.timedelta(days=1), end_t, now_local.tzinfo)  # type: ignore[arg-type]
    if current < end_t:
        return True, _localize(now_local.date(), end_t, now_local.tzinfo)  # type: ignore[arg-type]
    return False, None


def _candidate_topics(candidate: dict[str, Any]) -> set[str]:
    topics = candidate.get("topic_ids")
    if not isinstance(topics, list):
        return set()
    return {_clean(item) for item in topics if _clean(item)}


def _record_topics(record: dict[str, Any]) -> set[str]:
    topics = record.get("topic_ids")
    if not isinstance(topics, list):
        return set()
    return {_clean(item) for item in topics if _clean(item)}


def _is_related(candidate: dict[str, Any], record: dict[str, Any]) -> bool:
    candidate_group = _clean(candidate.get("related_group_id"))
    record_group = _clean(record.get("related_group_id"))
    if candidate_group and record_group:
        return candidate_group == record_group
    candidate_topics = _candidate_topics(candidate)
    return bool(candidate_topics and candidate_topics.intersection(_record_topics(record)))


def _eligible_history_records(history: dict[str, Any]) -> list[tuple[dt.datetime, dict[str, Any]]]:
    records = history.get("records", [])
    if not isinstance(records, list):
        raise ValueError("history.records must be a list")
    result: list[tuple[dt.datetime, dict[str, Any]]] = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("history.records entries must be objects")
        if _clean(record.get("status")) not in {"published", "corrected", "replaced"}:
            continue
        published_at = _parse_instant(record.get("published_at"), "history.records[].published_at")
        result.append((published_at, record))
    result.sort(key=lambda pair: pair[0])
    return result


def _base_blocks(candidate: dict[str, Any], channel: dict[str, Any], history: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    candidate_instance = _clean(candidate.get("instance_id"))
    channel_instance = _clean(channel.get("instance_id"))
    history_instance = _clean(history.get("instance_id"))
    identities = {value for value in (candidate_instance, channel_instance, history_instance) if value}
    if not identities:
        blocks.append("MISSING_INSTANCE_ID")
    elif len(identities) != 1 or not all((candidate_instance, channel_instance, history_instance)):
        blocks.append("INSTANCE_MISMATCH")

    candidate_channel = _clean(candidate.get("channel_id"))
    configured_channel = _clean(channel.get("channel_id"))
    history_channel = _clean(history.get("channel_id"))
    channels = {value for value in (candidate_channel, configured_channel, history_channel) if value}
    if not channels:
        blocks.append("MISSING_CHANNEL_ID")
    elif len(channels) != 1 or not all((candidate_channel, configured_channel, history_channel)):
        blocks.append("CHANNEL_MISMATCH")

    if not _clean(candidate.get("story_id")):
        blocks.append("MISSING_STORY_ID")
    if channel.get("status") not in {"active", "outbox_only"}:
        blocks.append("CHANNEL_NOT_ACTIVE")
    return blocks


def evaluate_cadence(
    candidate: dict[str, Any],
    channel: dict[str, Any],
    history: dict[str, Any],
    *,
    now: str,
) -> dict[str, Any]:
    """Return a deterministic publication-time decision for one social candidate."""
    if not all(isinstance(value, dict) for value in (candidate, channel, history)):
        raise TypeError("candidate, channel and history must be mappings")

    base_blocks = _base_blocks(candidate, channel, history)
    now_utc = _parse_instant(now, "now")
    channel_id = _clean(channel.get("channel_id")) or None
    instance_id = _clean(channel.get("instance_id")) or None
    story_id = _clean(candidate.get("story_id")) or None

    result: dict[str, Any] = {
        "schema_version": "1.0",
        "instance_id": instance_id,
        "channel_id": channel_id,
        "story_id": story_id,
        "evaluated_at": now_utc.isoformat().replace("+00:00", "Z"),
        "eligible": False,
        "decision": "BLOCKED_IDENTITY" if base_blocks else "HOLD_CADENCE",
        "hard_blocks": base_blocks,
        "cadence_blocks": [],
        "overrides": [],
        "next_eligible_at": None,
        "counters": {},
    }
    if base_blocks:
        result["decision_fingerprint_sha256"] = _digest(result)
        return result

    cadence = channel.get("cadence")
    fatigue = channel.get("fatigue")
    if not isinstance(cadence, dict) or not isinstance(fatigue, dict):
        result["hard_blocks"] = ["MISSING_CADENCE_OR_FATIGUE_CONFIG"]
        result["decision"] = "BLOCKED_CONFIG"
        result["decision_fingerprint_sha256"] = _digest(result)
        return result

    timezone_name = _clean(cadence.get("timezone"))
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        result["hard_blocks"] = ["INVALID_TIMEZONE"]
        result["decision"] = "BLOCKED_CONFIG"
        result["decision_fingerprint_sha256"] = _digest(result)
        return result

    now_local = now_utc.astimezone(zone)
    records = _eligible_history_records(history)
    publication_class = _clean(candidate.get("publication_class")).lower() or "normal"
    is_correction = (
        publication_class == "correction"
        and bool(_clean(candidate.get("correction_of")))
        and isinstance(channel.get("approval_gates"), dict)
        and channel["approval_gates"].get("corrections_priority") is True
    )
    is_breaking = publication_class == "breaking"

    if is_correction:
        result["eligible"] = True
        result["decision"] = "PUBLISH_CORRECTION_PRIORITY"
        result["overrides"] = [
            "CORRECTION_OVERRIDES_QUIET_HOURS",
            "CORRECTION_OVERRIDES_DAILY_CAP",
            "CORRECTION_OVERRIDES_MIN_SPACING",
            "CORRECTION_OVERRIDES_SAME_STORY_COOLDOWN",
            "CORRECTION_OVERRIDES_RELATED_FATIGUE",
        ]
        result["counters"] = {"published_today": 0, "related_last_24h": 0}
        result["decision_fingerprint_sha256"] = _digest(result)
        return result

    blocks: list[str] = []
    unblock_times: list[dt.datetime] = []

    # Quiet hours.
    quiet = cadence.get("quiet_hours")
    if not isinstance(quiet, dict):
        result["hard_blocks"] = ["MISSING_QUIET_HOURS_CONFIG"]
        result["decision"] = "BLOCKED_CONFIG"
        result["decision_fingerprint_sha256"] = _digest(result)
        return result
    in_quiet, quiet_end = _quiet_window(now_local, quiet)
    if in_quiet:
        if is_breaking and quiet.get("breaking_override") is True:
            result["overrides"].append("BREAKING_OVERRIDES_QUIET_HOURS")
        else:
            blocks.append("QUIET_HOURS")
            if quiet_end is not None:
                unblock_times.append(quiet_end.astimezone(dt.timezone.utc))

    # Daily cap in channel local time.
    max_posts = int(cadence.get("max_posts_per_day", 0))
    published_today = sum(1 for stamp, _ in records if stamp.astimezone(zone).date() == now_local.date())
    if max_posts <= 0:
        result["hard_blocks"] = ["INVALID_DAILY_CAP"]
        result["decision"] = "BLOCKED_CONFIG"
        result["decision_fingerprint_sha256"] = _digest(result)
        return result
    if published_today >= max_posts:
        blocks.append("DAILY_CAP_REACHED")
        tomorrow = now_local.date() + dt.timedelta(days=1)
        next_day = dt.datetime.combine(tomorrow, dt.time.min, tzinfo=zone)
        # If midnight itself is quiet, advance to that quiet window's end.
        next_in_quiet, next_quiet_end = _quiet_window(next_day, quiet)
        if next_in_quiet and next_quiet_end is not None:
            next_day = next_quiet_end
        unblock_times.append(next_day.astimezone(dt.timezone.utc))

    # Minimum spacing between any channel publications.
    min_spacing = int(cadence.get("min_spacing_minutes", 0))
    if min_spacing < 0:
        result["hard_blocks"] = ["INVALID_MIN_SPACING"]
        result["decision"] = "BLOCKED_CONFIG"
        result["decision_fingerprint_sha256"] = _digest(result)
        return result
    if records:
        last_published_at = records[-1][0]
        spacing_until = last_published_at + dt.timedelta(minutes=min_spacing)
        if now_utc < spacing_until:
            blocks.append("MIN_SPACING")
            unblock_times.append(spacing_until)

    # Same-story cooldown.
    cooldown_hours = int(fatigue.get("same_story_cooldown_hours", 0))
    same_story = [stamp for stamp, record in records if _clean(record.get("story_id")) == story_id]
    if same_story:
        cooldown_until = same_story[-1] + dt.timedelta(hours=cooldown_hours)
        if now_utc < cooldown_until:
            blocks.append("SAME_STORY_COOLDOWN")
            unblock_times.append(cooldown_until)

    # Related-topic fatigue within a rolling 24h window.
    max_related = int(fatigue.get("max_related_posts_24h", 0))
    related_cutoff = now_utc - dt.timedelta(hours=24)
    related_records = [
        (stamp, record)
        for stamp, record in records
        if stamp > related_cutoff and _is_related(candidate, record)
    ]
    if max_related <= 0:
        result["hard_blocks"] = ["INVALID_RELATED_CAP"]
        result["decision"] = "BLOCKED_CONFIG"
        result["decision_fingerprint_sha256"] = _digest(result)
        return result
    if len(related_records) >= max_related:
        blocks.append("RELATED_TOPIC_FATIGUE")
        # The oldest counted related post must leave the rolling window.
        related_records.sort(key=lambda pair: pair[0])
        index = len(related_records) - max_related
        unblock_times.append(related_records[index][0] + dt.timedelta(hours=24))

    result["cadence_blocks"] = blocks
    result["counters"] = {
        "published_today": published_today,
        "daily_cap": max_posts,
        "related_last_24h": len(related_records),
        "related_cap": max_related,
        "same_story_publications_seen": len(same_story),
    }
    if blocks:
        result["eligible"] = False
        result["decision"] = "HOLD_CADENCE"
        if unblock_times:
            next_time = max(unblock_times)
            result["next_eligible_at"] = next_time.isoformat().replace("+00:00", "Z")
    else:
        result["eligible"] = True
        result["decision"] = "PUBLISH_NOW"

    result["decision_fingerprint_sha256"] = _digest(result)
    return result


def _load(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate")
    parser.add_argument("channel")
    parser.add_argument("history")
    parser.add_argument("--now", required=True, help="timezone-aware ISO-8601 instant")
    args = parser.parse_args()
    decision = evaluate_cadence(_load(args.candidate), _load(args.channel), _load(args.history), now=args.now)
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if decision.get("hard_blocks") == [] else 2


if __name__ == "__main__":
    raise SystemExit(main())
