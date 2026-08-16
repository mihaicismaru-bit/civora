#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

MODULE = Path(__file__).with_name("recurring_series_runtime.py")
spec = importlib.util.spec_from_file_location("recurring_series_runtime", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def channel(channel_id="valcea-facebook"):
    return {
        "schema_version": "1.0",
        "channel_id": channel_id,
        "instance_id": "valcea",
        "platform": "facebook",
        "status": "active",
        "native_formats": ["text", "single_photo"],
        "cadence": {"timezone": "Europe/Bucharest"},
        "series": [
            {"series_id": "editia-de-dimineata", "promise": "Sumar local verificat."}
        ],
        "metrics": {"observed_only": True},
        "zero_paid_dependency": True,
    }


def registry(channel_id="valcea-facebook"):
    return {
        "schema_version": "1.0",
        "instance_id": "valcea",
        "channels": {
            channel_id: [
                {
                    "series_id": "editia-de-dimineata",
                    "priority": 100,
                    "slots": [{"days": [0,1,2,3,4,5,6], "time": "07:00", "window_minutes": 180}],
                    "preferred_formats": ["single_photo", "text"],
                    "eligible_topics": ["local_events", "service_journalism", "civic_updates"],
                    "min_interval_hours": 12,
                    "max_occurrences_7d": 7,
                    "replay_policy": "new_story_only",
                    "resurface_after_hours": 0,
                    "min_items": 2,
                    "max_items": 3,
                }
            ]
        },
    }


def pool(channel_id="valcea-facebook", first_hash="a" * 64):
    return {
        "instance_id": "valcea",
        "channel_id": channel_id,
        "predicted_views": 999999,
        "candidates": [
            {
                "candidate_id": "c1",
                "instance_id": "valcea",
                "channel_id": channel_id,
                "series_id": "editia-de-dimineata",
                "story_id": "story-a",
                "content_hash": first_hash,
                "eligible": True,
                "priority": 95,
                "story_updated_at": "2026-08-15T04:30:00Z",
                "topic_ids": ["local_events"],
                "native_formats": ["single_photo"],
                "predicted_engagement": 100.0,
            },
            {
                "candidate_id": "c2",
                "instance_id": "valcea",
                "channel_id": channel_id,
                "series_id": "editia-de-dimineata",
                "story_id": "story-b",
                "content_hash": "b" * 64,
                "eligible": True,
                "priority": 80,
                "story_updated_at": "2026-08-15T04:40:00Z",
                "topic_ids": ["service_journalism"],
                "native_formats": ["text"],
            },
        ],
    }


def history(channel_id="valcea-facebook", records=None):
    return {
        "instance_id": "valcea",
        "channel_id": channel_id,
        "records": records or [],
    }


def outbox(channel_id="valcea-facebook"):
    return {
        "schema_version": "1.0",
        "instance_id": "valcea",
        "channel_id": channel_id,
        "items": [],
        "zero_paid_dependency": True,
    }


def state(channel_id="valcea-facebook"):
    return {
        "schema_version": "1.0",
        "instance_id": "valcea",
        "channel_id": channel_id,
        "occurrences": {},
        "zero_paid_dependency": True,
    }


def run(name, fn):
    fn()
    print(f"PASS {name}")


def stages_due_occurrence():
    result = mod.stage_due_occurrence(
        channel(), registry(), pool(), history(), now="2026-08-15T05:00:00Z"
    )
    assert result["staged"] is True
    assert result["disposition"] == "SERIES_COMPOSITION_PENDING"
    assert len(result["outbox"]["items"]) == 1
    item = result["outbox"]["items"][0]
    assert item["selected_story_ids"] == ["story-a", "story-b"]
    assert item["native_composition_required"] is True
    assert item["network_dispatch_performed"] is False
    assert item["source_story_text_materialized"] is False
    assert item["series_slot_key"] in result["state"]["occurrences"]


def idempotent_same_slot_same_content():
    first = mod.stage_due_occurrence(
        channel(), registry(), pool(), history(), now="2026-08-15T05:00:00Z"
    )
    second = mod.stage_due_occurrence(
        channel(), registry(), pool(), history(), now="2026-08-15T05:00:00Z",
        outbox=first["outbox"], state=first["state"],
    )
    assert second["idempotent"] is True
    assert second["disposition"] == "IDEMPOTENT_ALREADY_STAGED"
    assert len(second["outbox"]["items"]) == 1
    assert second["outbox"] == first["outbox"]
    assert second["state"] == first["state"]


def changed_content_same_slot_holds():
    first = mod.stage_due_occurrence(
        channel(), registry(), pool(), history(), now="2026-08-15T05:00:00Z"
    )
    changed = mod.stage_due_occurrence(
        channel(), registry(), pool(first_hash="c" * 64), history(),
        now="2026-08-15T05:00:00Z", outbox=first["outbox"], state=first["state"],
    )
    assert changed["staged"] is False
    assert changed["blocked"] is False
    assert changed["disposition"] == "HOLD_STAGED_SLOT_CONFLICT"
    assert "SERIES_SLOT_STAGED_WITH_DIFFERENT_CONTENT" in changed["series_blocks"]
    assert changed["outbox"] == first["outbox"]


def outside_slot_does_not_mutate_runtime_state():
    ob, st = outbox(), state()
    result = mod.stage_due_occurrence(
        channel(), registry(), pool(), history(), now="2026-08-15T12:00:00Z",
        outbox=ob, state=st,
    )
    assert result["staged"] is False
    assert result["disposition"] in {"HOLD_NO_OPEN_SLOT", "HOLD_SERIES_POLICY"}
    assert result["outbox"] == ob
    assert result["state"] == st


def published_slot_dedupe_propagates():
    published = {
        "status": "published",
        "published_at": "2026-08-15T04:30:00Z",
        "series_id": "editia-de-dimineata",
        "series_slot_key": "editia-de-dimineata:2026-08-15:0:07:00",
        "story_id": "old-story",
        "content_hash": "d" * 64,
    }
    result = mod.stage_due_occurrence(
        channel(), registry(), pool(), history(records=[published]), now="2026-08-15T05:00:00Z"
    )
    assert result["staged"] is False
    assert "SERIES_SLOT_ALREADY_PUBLISHED" in result["series_blocks"]
    assert result["outbox"]["items"] == []


def instance_isolation_blocks():
    ob = outbox()
    ob["instance_id"] = "other"
    result = mod.stage_due_occurrence(
        channel(), registry(), pool(), history(), now="2026-08-15T05:00:00Z", outbox=ob
    )
    assert result["blocked"] is True
    assert "OUTBOX_INSTANCE_MISMATCH" in result["hard_blocks"]


def channel_isolation_blocks():
    st = state()
    st["channel_id"] = "valcea-instagram"
    result = mod.stage_due_occurrence(
        channel(), registry(), pool(), history(), now="2026-08-15T05:00:00Z", state=st
    )
    assert result["blocked"] is True
    assert "STATE_CHANNEL_MISMATCH" in result["hard_blocks"]


def state_outbox_divergence_blocks():
    first = mod.stage_due_occurrence(
        channel(), registry(), pool(), history(), now="2026-08-15T05:00:00Z"
    )
    broken_state = copy.deepcopy(first["state"])
    broken_state["occurrences"] = {}
    result = mod.stage_due_occurrence(
        channel(), registry(), pool(), history(), now="2026-08-15T05:00:00Z",
        outbox=first["outbox"], state=broken_state,
    )
    assert result["blocked"] is True
    assert "SERIES_STATE_OUTBOX_DIVERGENCE" in result["hard_blocks"]


def predictive_fields_never_enter_handoff():
    result = mod.stage_due_occurrence(
        channel(), registry(), pool(), history(), now="2026-08-15T05:00:00Z"
    )
    serialized = mod._canonical(result["staged_item"])
    assert "predicted_views" not in serialized
    assert "predicted_engagement" not in serialized
    assert result["guards"]["predictive_analytics_used"] is False


def zero_paid_dependency_is_fail_closed():
    ch = channel()
    ch["zero_paid_dependency"] = False
    result = mod.stage_due_occurrence(
        ch, registry(), pool(), history(), now="2026-08-15T05:00:00Z"
    )
    assert result["blocked"] is True
    assert "ZERO_PAID_DEPENDENCY_VIOLATION" in result["hard_blocks"]


def observed_metrics_policy_is_required():
    ch = channel()
    ch["metrics"]["observed_only"] = False
    result = mod.stage_due_occurrence(
        ch, registry(), pool(), history(), now="2026-08-15T05:00:00Z"
    )
    assert result["blocked"] is True
    assert "OBSERVED_METRICS_POLICY_REQUIRED" in result["hard_blocks"]


def channel_specific_execution_identity():
    first = mod.stage_due_occurrence(
        channel(), registry(), pool(), history(), now="2026-08-15T05:00:00Z"
    )
    other_id = "valcea-facebook-secondary"
    second = mod.stage_due_occurrence(
        channel(other_id), registry(other_id), pool(other_id), history(other_id), now="2026-08-15T05:00:00Z"
    )
    assert first["staged_item"]["series_execution_id"] != second["staged_item"]["series_execution_id"]
    assert first["outbox"]["channel_id"] != second["outbox"]["channel_id"]


def deterministic_result():
    args = (channel(), registry(), pool(), history())
    a = mod.stage_due_occurrence(*copy.deepcopy(args), now="2026-08-15T05:00:00Z")
    b = mod.stage_due_occurrence(*copy.deepcopy(args), now="2026-08-15T05:00:00Z")
    assert a == b


if __name__ == "__main__":
    tests = [
        stages_due_occurrence,
        idempotent_same_slot_same_content,
        changed_content_same_slot_holds,
        outside_slot_does_not_mutate_runtime_state,
        published_slot_dedupe_propagates,
        instance_isolation_blocks,
        channel_isolation_blocks,
        state_outbox_divergence_blocks,
        predictive_fields_never_enter_handoff,
        zero_paid_dependency_is_fail_closed,
        observed_metrics_policy_is_required,
        channel_specific_execution_identity,
        deterministic_result,
    ]
    for fn in tests:
        run(fn.__name__.replace("_", "-"), fn)
    print(f"Recurring Series Runtime acceptance tests: PASS ({len(tests)})")
