#!/usr/bin/env python3
"""Acceptance tests for recurring-series publication state and durable outbox."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import content_atomizer
import native_series_compositor
import series_publication_state_bridge
import series_visual_router

HASH_A = "a" * 64
HASH_B = "b" * 64

NATIVE_FORMATS = {
    "facebook": ["single_photo", "text"],
    "instagram": ["carousel", "single_photo"],
    "telegram": ["digest", "text", "single_photo", "alert"],
}


def channel(
    platform: str,
    *,
    link_mode: str = "optional",
    low_risk_auto: bool = True,
    status: str | None = None,
) -> dict:
    return {
        "schema_version": "1.0",
        "channel_id": f"valcea-{platform}",
        "instance_id": "valcea",
        "platform": platform,
        "status": status or ("outbox_only" if platform == "telegram" else "active"),
        "native_formats": list(NATIVE_FORMATS[platform]),
        "media_policy": {
            "real_media_only": True,
            "provenance_required": True,
            "reuse_rights_required": True,
            "synthetic_real_person_forbidden": True,
        },
        "link_policy": {"mode": link_mode, "canonical_hosts": ["valceaclar.ro"]},
        "cadence": {
            "timezone": "Europe/Bucharest",
            "max_posts_per_day": 12,
            "min_spacing_minutes": 10,
            "quiet_hours": {"start": "23:00", "end": "06:00", "breaking_override": True},
        },
        "fatigue": {
            "same_story_cooldown_hours": 4,
            "max_related_posts_24h": 4,
        },
        "series": [{"series_id": "daily-brief", "promise": f"Daily brief for {platform}."}],
        "approval_gates": {
            "low_risk_auto": low_risk_auto,
            "reputational_human": True,
            "corrections_priority": True,
        },
        "metrics": {"observed_only": True},
        "zero_paid_dependency": True,
    }


def stories() -> list[dict]:
    return [
        {
            "instance_id": "valcea",
            "story_id": "story-a",
            "material_fact_gate": "PASS",
            "headline": "Podul din centru se redeschide luni",
            "dek": "Traficul va fi reluat după finalizarea lucrărilor programate.",
            "paragraphs": ["Primăria a anunțat redeschiderea pentru luni dimineață."],
            "facts": [{"fact_id": "a1", "text": "Restricțiile sunt ridicate luni la ora 06:00."}],
            "topics": ["infrastructure"],
        },
        {
            "instance_id": "valcea",
            "story_id": "story-b",
            "material_fact_gate": "PASS",
            "headline": "Festivalul din Zăvoi începe vineri",
            "dek": "Accesul la concertele din prima seară este liber.",
            "paragraphs": ["Programul publicat include concerte vineri și sâmbătă."],
            "facts": [{"fact_id": "b1", "text": "Prima seară începe la ora 19:00."}],
            "topics": ["local_events"],
        },
    ]


def story_fingerprint(story: dict) -> str:
    return content_atomizer.atomize_story(story)["source_fingerprint_sha256"]


def staged(platform: str, *, composition_seed: str = "f") -> dict:
    source_stories = stories()
    return {
        "series_execution_id": f"series-execution:{platform}-daily-{composition_seed}",
        "occurrence_id": f"occurrence:{platform}-daily",
        "instance_id": "valcea",
        "channel_id": f"valcea-{platform}",
        "series_id": "daily-brief",
        "series_slot_key": "daily-brief:2026-08-16:0:15:00",
        "status": "SERIES_COMPOSITION_PENDING",
        "publication_mode": "channel_native_series_composition_pending",
        "selected_candidate_ids": ["candidate-a", "candidate-b"],
        "selected_story_ids": [story["story_id"] for story in source_stories],
        "selected_content_hashes": [story_fingerprint(story) for story in source_stories],
        "topic_ids": ["infrastructure", "local_events"],
        "native_format_candidates": list(NATIVE_FORMATS[platform]),
        "replay_policy": "new_story_only",
        "composition_fingerprint_sha256": composition_seed * 64,
        "native_composition_required": True,
        "reuse_prior_copy": False,
        "verbatim_cross_platform_reuse_allowed": False,
        "source_story_text_materialized": False,
        "predictive_analytics_used": False,
        "credential_values_read": False,
        "network_dispatch_performed": False,
        "editorial_gates_weakened": False,
        "zero_paid_dependency": True,
    }


def composition(platform: str, ch: dict | None = None, *, composition_seed: str = "f") -> dict:
    ch = copy.deepcopy(ch or channel(platform))
    source_stories = stories()
    result = native_series_compositor.compose_staged_series(
        ch,
        staged(platform, composition_seed=composition_seed),
        {"instance_id": "valcea", "stories": source_stories},
    )
    assert result["blocked"] is False
    return result


def photo(asset_id: str, sha256: str, story_ids: list[str]) -> dict:
    return {
        "asset_id": asset_id,
        "instance_id": "valcea",
        "kind": "photograph",
        "synthetic": False,
        "subject_match": True,
        "editor_approved": True,
        "sha256": sha256,
        "source_type": "official_press",
        "source_url": "https://example.org/source",
        "direct_source_url": f"https://example.org/{asset_id}.jpg",
        "credit": "Instituție / comunicat",
        "rights_basis": "press_use",
        "license_url": None,
        "rights_note": "Utilizare editorială permisă.",
        "alt_text": "Fotografie reală relevantă pentru subiect.",
        "story_ids": list(story_ids),
    }


def visual(comp: dict, ch: dict) -> dict:
    inventory = {
        "schema_version": "1.0",
        "instance_id": "valcea",
        "assets": [
            photo("photo-a", HASH_A, ["story-a"]),
            photo("photo-b", HASH_B, ["story-b"]),
        ],
    }
    result = series_visual_router.bind_series_visuals(comp, ch, inventory)
    assert result["blocked"] is False
    return result


def history(ch: dict, records: list[dict] | None = None) -> dict:
    return {
        "instance_id": ch["instance_id"],
        "channel_id": ch["channel_id"],
        "records": copy.deepcopy(records or []),
    }


def recompute_product_fingerprint(product: dict) -> None:
    payload = copy.deepcopy(product)
    payload.pop("product_fingerprint_sha256", None)
    product["product_fingerprint_sha256"] = series_publication_state_bridge._digest(payload)


def test_text_native_series_reaches_durable_outbox_without_visual_gate() -> None:
    ch = channel("telegram")
    comp = composition("telegram", ch)
    assert comp["product"]["visual_requirement"]["required"] is False
    result = series_publication_state_bridge.bridge_series_publication(
        comp, ch, history(ch), now="2026-08-16T12:00:00Z"
    )
    assert result["blocked"] is False
    assert result["disposition"] == "REGISTERED_OUTBOX_READY"
    assert result["record"]["status"] == "OUTBOX_READY"
    assert result["outbox_item"]["visual_binding"] is None
    assert len(result["outbox"]["items"]) == 1
    assert result["handoff"]["durable_outbox_ready"] is True
    assert result["handoff"]["network_dispatch_performed"] is False


def test_active_visual_series_reaches_ready_without_dispatch() -> None:
    ch = channel("facebook")
    comp = composition("facebook", ch)
    vis = visual(comp, ch)
    result = series_publication_state_bridge.bridge_series_publication(
        comp, ch, history(ch), now="2026-08-16T12:00:00Z", visual_result=vis
    )
    assert result["blocked"] is False
    assert result["disposition"] == "REGISTERED_READY"
    assert result["record"]["status"] == "READY"
    assert result["outbox_item"]["visual_binding"]["status"] == "SERIES_VISUAL_READY"
    assert result["handoff"]["adapter_dispatch_eligible"] is True
    assert result["handoff"]["network_dispatch_performed"] is False


def test_visual_series_cannot_bypass_missing_binding() -> None:
    ch = channel("instagram")
    comp = composition("instagram", ch)
    result = series_publication_state_bridge.bridge_series_publication(
        comp, ch, history(ch), now="2026-08-16T12:00:00Z"
    )
    assert result["blocked"] is True
    assert result["disposition"] == "BLOCKED_SERIES_VISUAL"
    assert "SERIES_VISUAL_BINDING_REQUIRED" in result["hard_blocks"]
    assert result["outbox"]["items"] == []


def test_visual_binding_tamper_is_fail_closed() -> None:
    ch = channel("instagram")
    comp = composition("instagram", ch)
    vis = visual(comp, ch)
    vis["binding"]["selected_assets"][0]["credit"] = "tampered"
    result = series_publication_state_bridge.bridge_series_publication(
        comp, ch, history(ch), now="2026-08-16T12:00:00Z", visual_result=vis
    )
    assert result["blocked"] is True
    assert "SERIES_VISUAL_FINGERPRINT_MISMATCH" in result["hard_blocks"]


def test_required_link_is_durable_hold_then_promotes_without_duplicate() -> None:
    ch = channel("telegram", link_mode="required")
    comp = composition("telegram", ch)
    first = series_publication_state_bridge.bridge_series_publication(
        comp, ch, history(ch), now="2026-08-16T12:00:00Z"
    )
    assert first["blocked"] is False
    assert first["record"]["status"] == "HOLD_LINK_BINDING"
    assert first["cadence"] is None
    second = series_publication_state_bridge.bridge_series_publication(
        comp,
        ch,
        history(ch),
        now="2026-08-16T12:00:00Z",
        canonical_url="https://valceaclar.ro/stiri/daily-brief",
        publication_outbox=first["outbox"],
        publication_state=first["state"],
    )
    assert second["blocked"] is False
    assert second["disposition"] == "UPDATED_OUTBOX_READY"
    assert second["record"]["status"] == "OUTBOX_READY"
    assert second["link_binding"]["status"] == "LINK_BOUND"
    assert len(second["outbox"]["items"]) == 1


def test_wrong_canonical_host_is_blocked_before_state_registration() -> None:
    ch = channel("telegram", link_mode="required")
    comp = composition("telegram", ch)
    result = series_publication_state_bridge.bridge_series_publication(
        comp,
        ch,
        history(ch),
        now="2026-08-16T12:00:00Z",
        canonical_url="https://example.com/not-canonical",
    )
    assert result["blocked"] is True
    assert result["disposition"] == "BLOCKED_LINK_POLICY"
    assert result["hard_blocks"] == ["LINK_HOST_NOT_ALLOWED"]
    assert result["state"]["records"] == {}


def test_quiet_hours_are_persisted_as_timing_hold() -> None:
    ch = channel("telegram")
    comp = composition("telegram", ch)
    result = series_publication_state_bridge.bridge_series_publication(
        comp, ch, history(ch), now="2026-08-16T20:30:00Z"
    )
    assert result["blocked"] is False
    assert result["record"]["status"] == "HOLD_TIMING"
    assert "QUIET_HOURS" in result["cadence"]["cadence_blocks"]
    assert result["handoff"]["timing_hold"] is True


def test_series_same_story_fatigue_is_enforced() -> None:
    ch = channel("telegram")
    comp = composition("telegram", ch)
    prior = {
        "status": "published",
        "published_at": "2026-08-16T10:00:00Z",
        "story_id": "series:daily-brief",
        "topic_ids": ["series:daily-brief", "story:story-a"],
        "related_group_id": "series:daily-brief",
    }
    result = series_publication_state_bridge.bridge_series_publication(
        comp, ch, history(ch, [prior]), now="2026-08-16T12:00:00Z"
    )
    assert result["blocked"] is False
    assert result["record"]["status"] == "HOLD_TIMING"
    assert "SAME_STORY_COOLDOWN" in result["cadence"]["cadence_blocks"]


def test_human_approval_hold_promotes_to_outbox_ready() -> None:
    ch = channel("telegram", low_risk_auto=False)
    comp = composition("telegram", ch)
    first = series_publication_state_bridge.bridge_series_publication(
        comp, ch, history(ch), now="2026-08-16T12:00:00Z"
    )
    assert first["record"]["status"] == "AWAITING_APPROVAL"
    second = series_publication_state_bridge.bridge_series_publication(
        comp,
        ch,
        history(ch),
        now="2026-08-16T12:00:00Z",
        publication_outbox=first["outbox"],
        publication_state=first["state"],
        human_approved=True,
    )
    assert second["blocked"] is False
    assert second["disposition"] == "UPDATED_OUTBOX_READY"
    assert second["record"]["status"] == "OUTBOX_READY"
    assert second["record"]["human_approved"] is True


def test_identical_rerun_is_idempotent_and_does_not_duplicate_outbox() -> None:
    ch = channel("telegram")
    comp = composition("telegram", ch)
    first = series_publication_state_bridge.bridge_series_publication(
        comp, ch, history(ch), now="2026-08-16T12:00:00Z"
    )
    second = series_publication_state_bridge.bridge_series_publication(
        comp,
        ch,
        history(ch),
        now="2026-08-16T12:00:00Z",
        publication_outbox=first["outbox"],
        publication_state=first["state"],
    )
    assert second["blocked"] is False
    assert second["idempotent"] is True
    assert second["disposition"] == "IDEMPOTENT_OUTBOX_READY"
    assert second["record"]["publication_id"] == first["record"]["publication_id"]
    assert len(second["outbox"]["items"]) == 1


def test_same_slot_with_different_native_product_is_held_without_overwrite() -> None:
    ch = channel("telegram")
    first_comp = composition("telegram", ch, composition_seed="f")
    first = series_publication_state_bridge.bridge_series_publication(
        first_comp, ch, history(ch), now="2026-08-16T12:00:00Z"
    )
    second_comp = composition("telegram", ch, composition_seed="e")
    second = series_publication_state_bridge.bridge_series_publication(
        second_comp,
        ch,
        history(ch),
        now="2026-08-16T12:00:00Z",
        publication_outbox=first["outbox"],
        publication_state=first["state"],
    )
    assert second["blocked"] is False
    assert second["disposition"] == "HOLD_SERIES_SLOT_CONFLICT"
    assert second["series_blocks"] == ["SERIES_SLOT_ALREADY_BOUND_TO_DIFFERENT_PRODUCT"]
    assert len(second["outbox"]["items"]) == 1


def test_instance_isolation_is_fail_closed() -> None:
    ch = channel("telegram")
    comp = composition("telegram", ch)
    foreign = copy.deepcopy(ch)
    foreign["instance_id"] = "cluj"
    result = series_publication_state_bridge.bridge_series_publication(
        comp,
        foreign,
        {"instance_id": "cluj", "channel_id": foreign["channel_id"], "records": []},
        now="2026-08-16T12:00:00Z",
    )
    assert result["blocked"] is True
    assert "INSTANCE_MISMATCH" in result["hard_blocks"] or "PRODUCT_INSTANCE_MISMATCH" in result["hard_blocks"]


def test_product_fingerprint_tamper_is_fail_closed() -> None:
    ch = channel("telegram")
    comp = composition("telegram", ch)
    comp["product"]["series_frame"]["text"] = "Tampered copy"
    result = series_publication_state_bridge.bridge_series_publication(
        comp, ch, history(ch), now="2026-08-16T12:00:00Z"
    )
    assert result["blocked"] is True
    assert "SERIES_PRODUCT_FINGERPRINT_MISMATCH" in result["hard_blocks"]


def test_predictive_analytics_and_secret_values_are_forbidden_even_if_rehashed() -> None:
    ch = channel("telegram")
    comp = composition("telegram", ch)
    comp["product"]["predicted_views"] = 999999
    comp["product"]["access_token"] = "DO-NOT-STORE"
    recompute_product_fingerprint(comp["product"])
    result = series_publication_state_bridge.bridge_series_publication(
        comp, ch, history(ch), now="2026-08-16T12:00:00Z"
    )
    assert result["blocked"] is True
    assert "PREDICTIVE_ANALYTICS_FORBIDDEN" in result["hard_blocks"]
    assert "SECRET_VALUE_IN_DURABLE_PRODUCT" in result["hard_blocks"]
    assert "DO-NOT-STORE" not in str(result)


def test_zero_paid_and_observed_only_policies_cannot_be_weakened() -> None:
    ch = channel("telegram")
    comp = composition("telegram", ch)
    ch["zero_paid_dependency"] = False
    ch["metrics"]["observed_only"] = False
    result = series_publication_state_bridge.bridge_series_publication(
        comp, ch, history(ch), now="2026-08-16T12:00:00Z"
    )
    assert result["blocked"] is True
    assert "ZERO_PAID_DEPENDENCY_VIOLATION" in result["hard_blocks"]
    assert "OBSERVED_METRICS_POLICY_REQUIRED" in result["hard_blocks"]


def test_state_outbox_divergence_is_fail_closed() -> None:
    ch = channel("telegram")
    comp = composition("telegram", ch)
    first = series_publication_state_bridge.bridge_series_publication(
        comp, ch, history(ch), now="2026-08-16T12:00:00Z"
    )
    empty_outbox = copy.deepcopy(first["outbox"])
    empty_outbox["items"] = []
    result = series_publication_state_bridge.bridge_series_publication(
        comp,
        ch,
        history(ch),
        now="2026-08-16T12:00:00Z",
        publication_outbox=empty_outbox,
        publication_state=first["state"],
    )
    assert result["blocked"] is True
    assert "SERIES_PUBLICATION_STATE_OUTBOX_DIVERGENCE" in result["hard_blocks"]


def test_text_series_cannot_fake_a_visual_gate_bypass() -> None:
    ch = channel("telegram")
    comp = composition("telegram", ch)
    comp["product"]["next_gate"] = "VISUAL_ROUTER"
    recompute_product_fingerprint(comp["product"])
    result = series_publication_state_bridge.bridge_series_publication(
        comp, ch, history(ch), now="2026-08-16T12:00:00Z"
    )
    assert result["blocked"] is True
    assert "INVALID_SERIES_NEXT_GATE" in result["hard_blocks"]


def test_output_is_deterministic_for_identical_inputs() -> None:
    ch = channel("telegram")
    comp = composition("telegram", ch)
    first = series_publication_state_bridge.bridge_series_publication(
        comp, ch, history(ch), now="2026-08-16T12:00:00Z"
    )
    second = series_publication_state_bridge.bridge_series_publication(
        copy.deepcopy(comp), copy.deepcopy(ch), history(ch), now="2026-08-16T12:00:00Z"
    )
    assert first == second
    assert len(first["runtime_fingerprint_sha256"]) == 64


def main() -> int:
    tests = [
        test_text_native_series_reaches_durable_outbox_without_visual_gate,
        test_active_visual_series_reaches_ready_without_dispatch,
        test_visual_series_cannot_bypass_missing_binding,
        test_visual_binding_tamper_is_fail_closed,
        test_required_link_is_durable_hold_then_promotes_without_duplicate,
        test_wrong_canonical_host_is_blocked_before_state_registration,
        test_quiet_hours_are_persisted_as_timing_hold,
        test_series_same_story_fatigue_is_enforced,
        test_human_approval_hold_promotes_to_outbox_ready,
        test_identical_rerun_is_idempotent_and_does_not_duplicate_outbox,
        test_same_slot_with_different_native_product_is_held_without_overwrite,
        test_instance_isolation_is_fail_closed,
        test_product_fingerprint_tamper_is_fail_closed,
        test_predictive_analytics_and_secret_values_are_forbidden_even_if_rehashed,
        test_zero_paid_and_observed_only_policies_cannot_be_weakened,
        test_state_outbox_divergence_is_fail_closed,
        test_text_series_cannot_fake_a_visual_gate_bypass,
        test_output_is_deterministic_for_identical_inputs,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"Series Publication-State Bridge acceptance: PASS ({len(tests)}/{len(tests)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
