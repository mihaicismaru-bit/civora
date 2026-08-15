#!/usr/bin/env python3
"""Deterministic Recurring Series Engine for LOCAL NEWS OS social publications.

The engine decides whether a configured recurring series has an occurrence due
now and which already-validated story candidates belong in that occurrence. It
never writes copy, predicts engagement, fetches analytics, or publishes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PUBLISHED = {"published", "corrected", "replaced"}
REPLAY = {"new_story_only", "material_update", "evergreen_refresh"}


def clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def parse_instant(value: Any, field: str) -> dt.datetime:
    raw = clean(value)
    if not raw:
        raise ValueError(f"{field} is required")
    parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def parse_clock(value: Any) -> dt.time:
    raw = clean(value)
    try:
        hh, mm = raw.split(":", 1)
        hour, minute = int(hh), int(mm)
    except (ValueError, AttributeError) as exc:
        raise ValueError("slot.time must be HH:MM") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("slot.time must be a valid 24-hour clock")
    return dt.time(hour, minute)


def published_history(history: dict[str, Any]) -> list[tuple[dt.datetime, dict[str, Any]]]:
    records = history.get("records", [])
    if not isinstance(records, list):
        raise ValueError("history.records must be a list")
    result = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("history.records entries must be objects")
        if clean(record.get("status")) in PUBLISHED:
            result.append((parse_instant(record.get("published_at"), "history.records[].published_at"), record))
    return sorted(result, key=lambda pair: pair[0])


def identity_blocks(channel: dict[str, Any], registry: dict[str, Any], pool: dict[str, Any], history: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    values = [clean(obj.get("instance_id")) for obj in (channel, registry, pool, history)]
    if not all(values) or len(set(values)) != 1:
        blocks.append("INSTANCE_MISMATCH")
    channel_id = clean(channel.get("channel_id"))
    for obj in (pool, history):
        if clean(obj.get("channel_id")) != channel_id or not channel_id:
            blocks.append("CHANNEL_MISMATCH")
            break
    if channel.get("status") not in {"active", "outbox_only"}:
        blocks.append("CHANNEL_NOT_ACTIVE")
    return sorted(set(blocks))


def declared_series(channel: dict[str, Any]) -> set[str]:
    series = channel.get("series", [])
    if not isinstance(series, list):
        return set()
    return {clean(item.get("series_id")) for item in series if isinstance(item, dict) and clean(item.get("series_id"))}


def channel_policies(channel: dict[str, Any], registry: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    channels = registry.get("channels")
    if not isinstance(channels, dict):
        return [], ["REGISTRY_CHANNELS_NOT_OBJECT"]
    cid = clean(channel.get("channel_id"))
    raw = channels.get(cid, [])
    if not isinstance(raw, list):
        return [], ["CHANNEL_SERIES_POLICY_NOT_ARRAY"]
    declared = declared_series(channel)
    native = set(channel.get("native_formats", [])) if isinstance(channel.get("native_formats"), list) else set()
    seen: set[str] = set()
    policies: list[dict[str, Any]] = []
    errors: list[str] = []
    required = {"series_id", "priority", "slots", "preferred_formats", "eligible_topics", "min_interval_hours", "max_occurrences_7d", "replay_policy", "resurface_after_hours", "min_items", "max_items"}
    for policy in raw:
        if not isinstance(policy, dict):
            errors.append("SERIES_POLICY_NOT_OBJECT")
            continue
        sid = clean(policy.get("series_id"))
        if not sid or sid not in declared:
            errors.append(f"UNDECLARED_SERIES:{sid or 'missing'}")
            continue
        if sid in seen:
            errors.append(f"DUPLICATE_SERIES:{sid}")
            continue
        seen.add(sid)
        missing = sorted(required - set(policy))
        if missing:
            errors.append(f"MISSING_FIELDS:{sid}:{','.join(missing)}")
            continue
        slots = policy.get("slots")
        if not isinstance(slots, list) or not slots:
            errors.append(f"INVALID_SLOTS:{sid}")
            continue
        slot_error = False
        for slot in slots:
            if not isinstance(slot, dict):
                slot_error = True
                break
            days = slot.get("days")
            if not isinstance(days, list) or not days or any(not isinstance(day, int) or day < 0 or day > 6 for day in days):
                slot_error = True
                break
            try:
                parse_clock(slot.get("time"))
            except ValueError:
                slot_error = True
                break
            window = slot.get("window_minutes")
            if not isinstance(window, int) or not 1 <= window <= 1440:
                slot_error = True
                break
        if slot_error:
            errors.append(f"INVALID_SLOTS:{sid}")
            continue
        preferred = policy.get("preferred_formats")
        if not isinstance(preferred, list) or not preferred or any(clean(fmt) not in native for fmt in preferred):
            errors.append(f"FORMAT_NOT_NATIVE:{sid}")
            continue
        if clean(policy.get("replay_policy")) not in REPLAY:
            errors.append(f"INVALID_REPLAY_POLICY:{sid}")
            continue
        numeric = {
            "priority": (0, 100), "min_interval_hours": (0, 720),
            "max_occurrences_7d": (1, 100), "resurface_after_hours": (0, 8760),
            "min_items": (1, 20), "max_items": (1, 20),
        }
        bad = [key for key, (lo, hi) in numeric.items() if not isinstance(policy.get(key), int) or not lo <= policy[key] <= hi]
        if bad or policy["min_items"] > policy["max_items"]:
            errors.append(f"INVALID_NUMERIC_POLICY:{sid}")
            continue
        policies.append(policy)
    return policies, errors


def matching_slot(now_local: dt.datetime, series_id: str, slots: list[dict[str, Any]]) -> str | None:
    keys = []
    for index, slot in enumerate(slots):
        if now_local.weekday() not in slot["days"]:
            continue
        start = dt.datetime.combine(now_local.date(), parse_clock(slot["time"]), tzinfo=now_local.tzinfo)
        if start <= now_local < start + dt.timedelta(minutes=slot["window_minutes"]):
            keys.append(f"{series_id}:{now_local.date().isoformat()}:{index}:{slot['time']}")
    return sorted(keys)[0] if keys else None


def candidate_allowed(candidate: dict[str, Any], policy: dict[str, Any], channel: dict[str, Any], series_history: list[tuple[dt.datetime, dict[str, Any]]], now_utc: dt.datetime) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    sid = clean(policy["series_id"])
    if clean(candidate.get("series_id")) != sid:
        return False, ["SERIES_MISMATCH"]
    if candidate.get("eligible") is not True:
        reasons.append("CANDIDATE_NOT_ELIGIBLE")
    if clean(candidate.get("instance_id")) != clean(channel.get("instance_id")):
        reasons.append("INSTANCE_MISMATCH")
    if clean(candidate.get("channel_id")) != clean(channel.get("channel_id")):
        reasons.append("CHANNEL_MISMATCH")
    story_id = clean(candidate.get("story_id"))
    if not story_id:
        reasons.append("MISSING_STORY_ID")
    content_hash = clean(candidate.get("content_hash")).lower()
    if len(content_hash) != 64 or any(ch not in "0123456789abcdef" for ch in content_hash):
        reasons.append("INVALID_CONTENT_HASH")
    allowed_topics = {clean(x) for x in policy.get("eligible_topics", []) if clean(x)}
    topics = {clean(x) for x in candidate.get("topic_ids", []) if clean(x)} if isinstance(candidate.get("topic_ids"), list) else set()
    if allowed_topics and not topics.intersection(allowed_topics):
        reasons.append("TOPIC_NOT_ELIGIBLE")
    preferred = {clean(x) for x in policy.get("preferred_formats", [])}
    formats = {clean(x) for x in candidate.get("native_formats", []) if clean(x)} if isinstance(candidate.get("native_formats"), list) else set()
    if preferred and not formats.intersection(preferred):
        reasons.append("NO_SERIES_NATIVE_FORMAT")
    same_story = [(stamp, rec) for stamp, rec in series_history if clean(rec.get("story_id")) == story_id]
    if same_story:
        stamp, record = same_story[-1]
        replay = clean(policy.get("replay_policy"))
        if replay == "new_story_only":
            reasons.append("STORY_ALREADY_USED_IN_SERIES")
        elif replay == "material_update":
            if candidate.get("material_update") is not True:
                reasons.append("MATERIAL_UPDATE_NOT_DECLARED")
            if clean(record.get("content_hash")).lower() == content_hash:
                reasons.append("CONTENT_HASH_UNCHANGED")
        elif replay == "evergreen_refresh":
            age_hours = (now_utc - stamp).total_seconds() / 3600
            changed = clean(record.get("content_hash")).lower() != content_hash
            if not changed and age_hours < policy["resurface_after_hours"]:
                reasons.append("EVERGREEN_RESURFACE_TOO_SOON")
    return not reasons, reasons


def evaluate_series(channel: dict[str, Any], registry: dict[str, Any], pool: dict[str, Any], history: dict[str, Any], *, now: str) -> dict[str, Any]:
    if not all(isinstance(obj, dict) for obj in (channel, registry, pool, history)):
        raise TypeError("channel, registry, pool and history must be mappings")
    now_utc = parse_instant(now, "now")
    blocks = identity_blocks(channel, registry, pool, history)
    result: dict[str, Any] = {
        "schema_version": "1.0", "instance_id": clean(channel.get("instance_id")) or None,
        "channel_id": clean(channel.get("channel_id")) or None,
        "evaluated_at": now_utc.isoformat().replace("+00:00", "Z"), "eligible": False,
        "decision": "BLOCKED_IDENTITY" if blocks else "HOLD_NO_OPEN_SLOT",
        "hard_blocks": blocks, "series_blocks": [], "occurrence": None, "considered_series": [],
    }
    if blocks:
        result["decision_fingerprint_sha256"] = digest(result)
        return result
    policies, errors = channel_policies(channel, registry)
    if errors:
        result["decision"] = "BLOCKED_CONFIG"
        result["hard_blocks"] = ["INVALID_SERIES_REGISTRY", *errors]
        result["decision_fingerprint_sha256"] = digest(result)
        return result
    if not policies:
        result["decision"] = "HOLD_NO_SERIES_CONFIGURED"
        result["decision_fingerprint_sha256"] = digest(result)
        return result
    cadence = channel.get("cadence")
    if not isinstance(cadence, dict):
        result["decision"], result["hard_blocks"] = "BLOCKED_CONFIG", ["MISSING_CADENCE_CONFIG"]
        result["decision_fingerprint_sha256"] = digest(result)
        return result
    try:
        zone = ZoneInfo(clean(cadence.get("timezone")))
    except ZoneInfoNotFoundError:
        result["decision"], result["hard_blocks"] = "BLOCKED_CONFIG", ["INVALID_TIMEZONE"]
        result["decision_fingerprint_sha256"] = digest(result)
        return result
    candidates = pool.get("candidates", [])
    if not isinstance(candidates, list) or any(not isinstance(x, dict) for x in candidates):
        result["decision"], result["hard_blocks"] = "BLOCKED_INPUT", ["INVALID_CANDIDATE_POOL"]
        result["decision_fingerprint_sha256"] = digest(result)
        return result
    records = published_history(history)
    now_local = now_utc.astimezone(zone)
    due = []
    for policy in policies:
        slot_key = matching_slot(now_local, clean(policy["series_id"]), policy["slots"])
        if slot_key:
            due.append((-policy["priority"], clean(policy["series_id"]), slot_key, policy))
    if not due:
        result["decision_fingerprint_sha256"] = digest(result)
        return result
    considered = []
    week_cutoff = now_utc - dt.timedelta(days=7)
    for _, sid, slot_key, policy in sorted(due):
        series_history = [(stamp, rec) for stamp, rec in records if clean(rec.get("series_id")) == sid]
        if any(clean(rec.get("series_slot_key")) == slot_key for _, rec in series_history):
            considered.append({"series_id": sid, "slot_key": slot_key, "blocks": ["SERIES_SLOT_ALREADY_PUBLISHED"]})
            continue
        if len([(stamp, rec) for stamp, rec in series_history if stamp > week_cutoff]) >= policy["max_occurrences_7d"]:
            considered.append({"series_id": sid, "slot_key": slot_key, "blocks": ["SERIES_WEEKLY_CAP"]})
            continue
        if series_history:
            next_at = series_history[-1][0] + dt.timedelta(hours=policy["min_interval_hours"])
            if now_utc < next_at:
                considered.append({"series_id": sid, "slot_key": slot_key, "blocks": ["SERIES_MIN_INTERVAL"], "next_eligible_at": next_at.isoformat().replace("+00:00", "Z")})
                continue
        eligible, rejected = [], []
        for candidate in candidates:
            if clean(candidate.get("series_id")) != sid:
                continue
            ok, reasons = candidate_allowed(candidate, policy, channel, series_history, now_utc)
            if ok:
                eligible.append(candidate)
            else:
                rejected.append({"candidate_id": clean(candidate.get("candidate_id")) or None, "story_id": clean(candidate.get("story_id")) or None, "reasons": reasons})
        def order(item: dict[str, Any]) -> tuple[Any, ...]:
            priority = item.get("priority") if isinstance(item.get("priority"), int) else 0
            updated = parse_instant(item["story_updated_at"], "story_updated_at") if clean(item.get("story_updated_at")) else dt.datetime.min.replace(tzinfo=dt.timezone.utc)
            return (-priority, -updated.timestamp(), clean(item.get("story_id")), clean(item.get("candidate_id")))
        eligible.sort(key=order)
        selected = eligible[:policy["max_items"]]
        if len(selected) < policy["min_items"]:
            considered.append({"series_id": sid, "slot_key": slot_key, "blocks": ["NOT_ENOUGH_ELIGIBLE_CANDIDATES"], "eligible_candidate_count": len(eligible), "min_items": policy["min_items"], "candidate_rejections": rejected})
            continue
        seed = {"instance_id": channel["instance_id"], "channel_id": channel["channel_id"], "series_id": sid, "series_slot_key": slot_key, "story_ids": [clean(x.get("story_id")) for x in selected], "content_hashes": [clean(x.get("content_hash")).lower() for x in selected]}
        occurrence = {
            "schema_version": "1.0", "occurrence_id": f"{sid}-{digest(seed)[:16]}",
            "instance_id": channel["instance_id"], "channel_id": channel["channel_id"],
            "series_id": sid, "series_slot_key": slot_key,
            "selected_candidate_ids": [clean(x.get("candidate_id")) for x in selected],
            "selected_story_ids": [clean(x.get("story_id")) for x in selected],
            "selected_content_hashes": [clean(x.get("content_hash")).lower() for x in selected],
            "topic_ids": sorted({clean(topic) for x in selected if isinstance(x.get("topic_ids"), list) for topic in x["topic_ids"] if clean(topic)}),
            "preferred_formats": list(policy["preferred_formats"]), "related_group_id": f"series:{sid}",
            "publication_class": "normal", "replay_policy": policy["replay_policy"],
            "generated_at": now_utc.isoformat().replace("+00:00", "Z"),
        }
        result.update({"eligible": True, "decision": "SERIES_READY", "occurrence": occurrence, "considered_series": considered + [{"series_id": sid, "slot_key": slot_key, "blocks": [], "eligible_candidate_count": len(eligible), "selected_count": len(selected)}]})
        result["decision_fingerprint_sha256"] = digest(result)
        return result
    result["decision"] = "HOLD_SERIES_POLICY"
    result["considered_series"] = considered
    result["series_blocks"] = sorted({block for entry in considered for block in entry.get("blocks", [])})
    result["decision_fingerprint_sha256"] = digest(result)
    return result


def load(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("channel")
    parser.add_argument("series_registry")
    parser.add_argument("candidate_pool")
    parser.add_argument("history")
    parser.add_argument("--now", required=True)
    args = parser.parse_args()
    decision = evaluate_series(load(args.channel), load(args.series_registry), load(args.candidate_pool), load(args.history), now=args.now)
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not decision.get("hard_blocks") else 2


if __name__ == "__main__":
    raise SystemExit(main())
