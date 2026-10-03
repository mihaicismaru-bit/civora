from __future__ import annotations

from public_presence_os.meta_live_runtime import MetaEventStore
from public_presence_os.meta_shadow_runtime import (
    EVALUATION_FIELDS,
    MetaShadowStore,
    compile_shadow_decision,
    run_shadow,
)
from public_presence_os.pilot_growth_operations import load_policy


def seed(store, object_type, external_id, text):
    key = "message" if object_type in {"POST", "COMMENT"} else "text"
    return store.ingest(
        platform="THREADS" if object_type == "REPLY" else "FACEBOOK_PAGE",
        object_type=object_type,
        external_id=external_id,
        observed_at="2026-10-03T00:00:00Z",
        fetched_at="2026-10-03T00:01:00Z",
        provenance="OFFICIAL_META_API",
        normalized={"id": external_id, key: text},
        cursor="cursor-1",
    )


def test_real_read_only_events_reuse_cp92_and_never_gain_write_authority(tmp_path):
    events = MetaEventStore(tmp_path / "events.sqlite3")
    receipt = seed(events, "REPLY", "reply-1", "Can you clarify the source?")
    event = events.events()[0]
    decision = compile_shadow_decision(event, policy=load_policy())
    assert decision.evidence_event_id == receipt.event_id
    assert decision.action == "REPLY"
    assert decision.risk_class == "AMBER"
    assert decision.external_write_allowed is False
    assert decision.social_api_call_allowed is False
    assert decision.kill_switch_required is True


def test_shadow_run_is_idempotent_and_reports_unmet_real_sample(tmp_path):
    events = MetaEventStore(tmp_path / "events.sqlite3")
    seed(events, "COMMENT", "comment-1", "Nice")
    seed(events, "COMMENT", "comment-2", "Where is the source?")
    decisions = MetaShadowStore(tmp_path / "shadow.sqlite3")
    first = run_shadow(events, decisions)
    second = run_shadow(events, decisions)
    assert first["sample_size"] == 2
    assert first["accepted_this_run"] == 2
    assert first["actions"] == {"IGNORE": 1, "REPLY": 1}
    assert first["risk_classes"] == {"AMBER": 1, "GREEN": 1}
    assert first["sample_target_met"] is False
    assert first["calibration_complete"] is False
    assert first["external_write_count"] == 0
    assert second["accepted_this_run"] == 0
    assert second["duplicates_this_run"] == 2


def test_calibration_requires_all_fields_and_does_not_lower_sample_gate(tmp_path):
    events = MetaEventStore(tmp_path / "events.sqlite3")
    seed(events, "POST", "post-1", "A useful public update")
    shadow = MetaShadowStore(tmp_path / "shadow.sqlite3")
    run_shadow(events, shadow)
    decision = compile_shadow_decision(events.events()[0], policy=load_policy())
    shadow.evaluate(decision.decision_id, {field: "PASS" for field in EVALUATION_FIELDS})
    report = shadow.report()
    assert report["evaluated_count"] == 1
    assert report["sample_target_met"] is False
    assert report["calibration_complete"] is False
