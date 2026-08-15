#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

MODULE = Path(__file__).with_name("recurring_series.py")
spec = importlib.util.spec_from_file_location("recurring_series", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def channel():
    return {
        "schema_version": "1.0", "channel_id": "valcea-facebook", "instance_id": "valcea",
        "platform": "facebook", "status": "active", "native_formats": ["text", "single_photo"],
        "cadence": {"timezone": "Europe/Bucharest"},
        "series": [
            {"series_id": "editia-de-dimineata", "promise": "Sumar local verificat pentru începutul zilei."},
            {"series_id": "banii-publici", "promise": "Explicații documentate despre bani și contracte publice."}
        ],
    }


def registry():
    return {
        "schema_version": "1.0", "instance_id": "valcea", "channels": {
            "valcea-facebook": [
                {
                    "series_id": "editia-de-dimineata", "priority": 90,
                    "slots": [{"days": [0,1,2,3,4,5,6], "time": "07:00", "window_minutes": 180}],
                    "preferred_formats": ["single_photo", "text"],
                    "eligible_topics": ["civic_updates", "local_events", "service_journalism"],
                    "min_interval_hours": 12, "max_occurrences_7d": 7,
                    "replay_policy": "new_story_only", "resurface_after_hours": 0,
                    "min_items": 2, "max_items": 4,
                },
                {
                    "series_id": "banii-publici", "priority": 80,
                    "slots": [{"days": [5], "time": "12:00", "window_minutes": 180}],
                    "preferred_formats": ["single_photo", "text"], "eligible_topics": ["public_money"],
                    "min_interval_hours": 24, "max_occurrences_7d": 3,
                    "replay_policy": "material_update", "resurface_after_hours": 0,
                    "min_items": 1, "max_items": 2,
                }
            ]
        }
    }


def pool(series="editia-de-dimineata"):
    return {
        "instance_id": "valcea", "channel_id": "valcea-facebook", "candidates": [
            {"candidate_id": "c1", "instance_id": "valcea", "channel_id": "valcea-facebook", "series_id": series,
             "story_id": "story-a", "content_hash": "a"*64, "eligible": True, "priority": 95,
             "story_updated_at": "2026-08-15T04:30:00Z", "topic_ids": ["local_events"], "native_formats": ["single_photo"]},
            {"candidate_id": "c2", "instance_id": "valcea", "channel_id": "valcea-facebook", "series_id": series,
             "story_id": "story-b", "content_hash": "b"*64, "eligible": True, "priority": 80,
             "story_updated_at": "2026-08-15T04:40:00Z", "topic_ids": ["service_journalism"], "native_formats": ["text"]},
            {"candidate_id": "c3", "instance_id": "valcea", "channel_id": "valcea-facebook", "series_id": series,
             "story_id": "story-c", "content_hash": "c"*64, "eligible": True, "priority": 70,
             "story_updated_at": "2026-08-15T04:50:00Z", "topic_ids": ["civic_updates"], "native_formats": ["single_photo"]},
        ]
    }


def history(records=None):
    return {"instance_id": "valcea", "channel_id": "valcea-facebook", "records": records or []}


def published(**kw):
    row = {"status": "published", "published_at": "2026-08-14T05:00:00Z", "series_id": "editia-de-dimineata",
           "series_slot_key": "old-slot", "story_id": "old-story", "content_hash": "d"*64}
    row.update(kw)
    return row


def run(name, fn):
    fn(); print(f"PASS {name}")


def open_slot_priority():
    out = mod.evaluate_series(channel(), registry(), pool(), history(), now="2026-08-15T05:00:00Z")
    assert out["decision"] == "SERIES_READY"
    assert out["occurrence"]["selected_story_ids"] == ["story-a", "story-b", "story-c"]
    assert out["occurrence"]["series_slot_key"] == "editia-de-dimineata:2026-08-15:0:07:00"


def outside_slot():
    out = mod.evaluate_series(channel(), registry(), pool(), history(), now="2026-08-15T10:00:00Z")
    assert out["decision"] in {"HOLD_NO_OPEN_SLOT", "HOLD_SERIES_POLICY"}
    assert not out["eligible"]


def slot_dedupe():
    rec = published(published_at="2026-08-15T04:30:00Z", series_slot_key="editia-de-dimineata:2026-08-15:0:07:00")
    out = mod.evaluate_series(channel(), registry(), pool(), history([rec]), now="2026-08-15T05:00:00Z")
    assert "SERIES_SLOT_ALREADY_PUBLISHED" in out["series_blocks"]


def min_interval():
    rec = published(published_at="2026-08-15T00:30:00Z")
    out = mod.evaluate_series(channel(), registry(), pool(), history([rec]), now="2026-08-15T05:00:00Z")
    assert "SERIES_MIN_INTERVAL" in out["series_blocks"]


def weekly_cap():
    reg = registry(); reg["channels"]["valcea-facebook"][0]["max_occurrences_7d"] = 2
    recs = [published(published_at="2026-08-12T05:00:00Z", series_slot_key="s1"), published(published_at="2026-08-13T05:00:00Z", series_slot_key="s2")]
    out = mod.evaluate_series(channel(), reg, pool(), history(recs), now="2026-08-15T05:00:00Z")
    assert "SERIES_WEEKLY_CAP" in out["series_blocks"]


def new_story_only():
    rec = published(story_id="story-a", content_hash="a"*64, published_at="2026-08-13T05:00:00Z")
    out = mod.evaluate_series(channel(), registry(), pool(), history([rec]), now="2026-08-15T05:00:00Z")
    assert out["occurrence"]["selected_story_ids"] == ["story-b", "story-c"]


def material_update_changed():
    p = pool("banii-publici"); p["candidates"] = [p["candidates"][0]]
    p["candidates"][0].update({"story_id": "money-a", "topic_ids": ["public_money"], "content_hash": "e"*64, "material_update": True})
    rec = published(series_id="banii-publici", story_id="money-a", content_hash="f"*64, published_at="2026-08-13T09:00:00Z")
    out = mod.evaluate_series(channel(), registry(), p, history([rec]), now="2026-08-15T10:00:00Z")
    assert out["decision"] == "SERIES_READY"


def material_update_same_hash():
    p = pool("banii-publici"); p["candidates"] = [p["candidates"][0]]
    p["candidates"][0].update({"story_id": "money-a", "topic_ids": ["public_money"], "content_hash": "e"*64, "material_update": True})
    rec = published(series_id="banii-publici", story_id="money-a", content_hash="e"*64, published_at="2026-08-13T09:00:00Z")
    out = mod.evaluate_series(channel(), registry(), p, history([rec]), now="2026-08-15T10:00:00Z")
    assert out["decision"] == "HOLD_SERIES_POLICY"
    assert "CONTENT_HASH_UNCHANGED" in out["considered_series"][0]["candidate_rejections"][0]["reasons"]


def evergreen_refresh():
    reg = registry(); s = reg["channels"]["valcea-facebook"][0]
    s.update({"replay_policy": "evergreen_refresh", "resurface_after_hours": 24, "min_items": 1})
    p = pool(); p["candidates"] = [p["candidates"][0]]
    rec = published(story_id="story-a", content_hash="a"*64, published_at="2026-08-13T04:00:00Z")
    out = mod.evaluate_series(channel(), reg, p, history([rec]), now="2026-08-15T05:00:00Z")
    assert out["decision"] == "SERIES_READY"


def identity_isolation():
    p = pool(); p["instance_id"] = "other"
    out = mod.evaluate_series(channel(), registry(), p, history(), now="2026-08-15T05:00:00Z")
    assert out["decision"] == "BLOCKED_IDENTITY" and "INSTANCE_MISMATCH" in out["hard_blocks"]


def topic_format_filter():
    reg = registry(); reg["channels"]["valcea-facebook"][0]["min_items"] = 1
    p = pool(); p["candidates"] = [p["candidates"][0]]
    p["candidates"][0].update({"topic_ids": ["public_money"], "native_formats": ["short"]})
    out = mod.evaluate_series(channel(), reg, p, history(), now="2026-08-15T05:00:00Z")
    reasons = out["considered_series"][0]["candidate_rejections"][0]["reasons"]
    assert "TOPIC_NOT_ELIGIBLE" in reasons and "NO_SERIES_NATIVE_FORMAT" in reasons


def deterministic_channel_specific():
    a = mod.evaluate_series(channel(), registry(), pool(), history(), now="2026-08-15T05:00:00Z")
    b = mod.evaluate_series(copy.deepcopy(channel()), copy.deepcopy(registry()), copy.deepcopy(pool()), copy.deepcopy(history()), now="2026-08-15T05:00:00Z")
    assert a == b
    other = channel(); other["channel_id"] = "other-channel"
    reg = registry(); reg["channels"]["other-channel"] = copy.deepcopy(reg["channels"]["valcea-facebook"])
    p = pool(); p["channel_id"] = "other-channel"
    for item in p["candidates"]: item["channel_id"] = "other-channel"
    h = history(); h["channel_id"] = "other-channel"
    c = mod.evaluate_series(other, reg, p, h, now="2026-08-15T05:00:00Z")
    assert c["occurrence"]["occurrence_id"] != a["occurrence"]["occurrence_id"]


if __name__ == "__main__":
    tests = [open_slot_priority, outside_slot, slot_dedupe, min_interval, weekly_cap, new_story_only,
             material_update_changed, material_update_same_hash, evergreen_refresh, identity_isolation,
             topic_format_filter, deterministic_channel_specific]
    for fn in tests: run(fn.__name__.replace("_", "-"), fn)
    print(f"Recurring Series Engine acceptance tests: PASS ({len(tests)})")
