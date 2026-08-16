#!/usr/bin/env python3
"""Acceptance tests for recurring-series adapter-gated dispatch handoff."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import series_adapter_dispatch_handoff
import series_publication_state_bridge
import test_series_publication_state_bridge as series_fixture

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
REGISTRY_PATH = REPO_ROOT / "valcea-clar/social/channel_registry.json"
CAPABILITIES_PATH = REPO_ROOT / "valcea-clar/social/adapter_capabilities.json"
PRESENT_REFS = {
    "facebook": {"VALCEA_FB_PAGE_ACCESS_TOKEN"},
    "instagram": {"VALCEA_IG_ACCOUNT_ID", "VALCEA_IG_ACCESS_TOKEN"},
}


def registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def capabilities() -> dict:
    return json.loads(CAPABILITIES_PATH.read_text(encoding="utf-8"))


def series_result(
    platform: str,
    *,
    link_mode: str = "optional",
    low_risk_auto: bool = True,
    now: str = "2026-08-16T12:00:00Z",
) -> dict:
    ch = series_fixture.channel(platform, link_mode=link_mode, low_risk_auto=low_risk_auto)
    comp = series_fixture.composition(platform, ch)
    kwargs = {}
    if comp["product"]["visual_requirement"]["required"] is True:
        kwargs["visual_result"] = series_fixture.visual(comp, ch)
    result = series_publication_state_bridge.bridge_series_publication(
        comp,
        ch,
        series_fixture.history(ch),
        now=now,
        **kwargs,
    )
    assert result["blocked"] is False
    return result


def handoff(platform: str, *, result: dict | None = None, refs=None, reg: dict | None = None, caps: dict | None = None, outbox: dict | None = None) -> dict:
    return series_adapter_dispatch_handoff.bridge_ready_series_handoff(
        copy.deepcopy(result or series_result(platform)),
        copy.deepcopy(reg or registry()),
        copy.deepcopy(caps or capabilities()),
        copy.deepcopy(PRESENT_REFS.get(platform, set()) if refs is None else refs),
        copy.deepcopy(outbox),
    )


def test_facebook_ready_series_becomes_direct_ready_without_dispatch() -> None:
    source = series_result("facebook")
    result = handoff("facebook", result=source)
    assert result["blocked"] is False
    assert result["dispatch_disposition"] == "DIRECT_READY"
    assert result["publication_status_after_bridge"] == "READY"
    assert result["adapter_handoff"]["dispatch_allowed"] is True
    assert result["capability_gate"]["compatible"] is True
    assert result["commit_bundle"]["atomic_persist_required"] is True
    assert result["guards"]["network_dispatch_performed"] is False
    assert result["guards"]["native_product_rewritten"] is False
    item = next(iter(result["commit_bundle"]["dispatch_handoff_outbox"]["items"].values()))
    assert item["adapter_payload"]["publication_kind"] == "recurring_series"
    assert item["adapter_payload"]["source_story_ids"] == ["story-a", "story-b"]
    assert item["adapter_payload"]["native_product"] == source["outbox_item"]["product"]


def test_instagram_carousel_series_uses_truthful_native_capability() -> None:
    source = series_result("instagram")
    assert source["outbox_item"]["product"]["native_format"] == "carousel"
    assert len(source["outbox_item"]["visual_binding"]["selected_assets"]) == 2
    result = handoff("instagram", result=source)
    assert result["blocked"] is False
    assert result["dispatch_disposition"] == "DIRECT_READY"
    assert result["capability_gate"]["native_format"] == "carousel"
    assert result["capability_gate"]["selected_media_assets"] == 2
    assert result["capability_gate"]["compatible"] is True


def test_outbox_only_series_never_creates_adapter_handoff() -> None:
    source = series_result("telegram")
    assert source["record"]["status"] == "OUTBOX_READY"
    result = handoff("telegram", result=source, refs=set())
    assert result["blocked"] is False
    assert result["decision"] == "NO_HANDOFF_UPSTREAM_SERIES_STATE"
    assert result["dispatch_disposition"] == "HOLD_UPSTREAM"
    assert result["adapter_handoff"] is None
    assert result["commit_bundle"] is None


def test_link_hold_never_reaches_runtime_or_capability_gate() -> None:
    source = series_result("facebook", link_mode="required")
    assert source["record"]["status"] == "HOLD_LINK_BINDING"
    result = handoff("facebook", result=source)
    assert result["blocked"] is False
    assert result["dispatch_disposition"] == "HOLD_UPSTREAM"
    assert result["runtime_gate"] is None
    assert result["capability_gate"] is None
    assert result["adapter_handoff"] is None


def test_timing_hold_never_creates_adapter_bundle() -> None:
    source = series_result("facebook", now="2026-08-16T20:30:00Z")
    assert source["record"]["status"] == "HOLD_TIMING"
    result = handoff("facebook", result=source)
    assert result["blocked"] is False
    assert result["publication_status"] == "HOLD_TIMING"
    assert result["commit_bundle"] is None


def test_human_approval_hold_remains_nondispatchable() -> None:
    source = series_result("facebook", low_risk_auto=False)
    assert source["record"]["status"] == "AWAITING_APPROVAL"
    result = handoff("facebook", result=source)
    assert result["blocked"] is False
    assert result["dispatch_disposition"] == "HOLD_UPSTREAM"
    assert result["adapter_handoff"] is None


def test_missing_credential_reference_synchronizes_series_state_and_outbox() -> None:
    source = series_result("facebook")
    result = handoff("facebook", result=source, refs=set())
    assert result["blocked"] is False
    assert result["dispatch_disposition"] == "BLOCKED_MISSING_CREDENTIALS"
    assert result["publication_status_after_bridge"] == "BLOCKED_AUTH"
    assert result["adapter_handoff"]["dispatch_allowed"] is False
    assert "VALCEA_FB_PAGE_ACCESS_TOKEN" in result["adapter_handoff"]["missing_reference_names"]
    publication_id = source["record"]["publication_id"]
    state_record = result["commit_bundle"]["series_publication_state"]["records"][publication_id]
    source_item = result["commit_bundle"]["series_publication_outbox"]["items"][0]
    assert state_record["status"] == "BLOCKED_AUTH"
    assert source_item["status"] == "BLOCKED_AUTH"
    assert source_item["dispatch"]["blocked_missing_credentials"] is True
    assert state_record["remote_publication_id"] is None


def test_capability_gap_demotes_exact_native_product_to_outbox_only() -> None:
    source = series_result("facebook")
    caps = capabilities()
    fb = next(row for row in caps["adapters"] if row["platform"] == "facebook")
    fb["supported_native_formats"] = ["text"]
    result = handoff("facebook", result=source, caps=caps)
    assert result["blocked"] is False
    assert result["dispatch_disposition"] == "OUTBOX_ONLY"
    assert result["publication_status_after_bridge"] == "OUTBOX_READY"
    assert "UNSUPPORTED_NATIVE_FORMAT:single_photo" in result["capability_gap_reasons"]
    item = next(iter(result["commit_bundle"]["dispatch_handoff_outbox"]["items"].values()))
    assert item["adapter_payload"]["native_product"] == source["outbox_item"]["product"]
    assert result["guards"]["fallback_format_invented"] is False
    assert result["guards"]["native_product_rewritten"] is False


def test_source_outbox_fingerprint_tamper_is_fail_closed() -> None:
    source = series_result("facebook")
    source["outbox_item"]["status"] = "READY_TAMPERED"
    result = handoff("facebook", result=source)
    assert result["blocked"] is True
    assert "SERIES_OUTBOX_ITEM_FINGERPRINT_MISMATCH" in result["hard_blocks"]
    assert result["commit_bundle"] is None


def test_registry_instance_isolation_is_fail_closed() -> None:
    reg = registry()
    reg["instance_id"] = "cluj"
    result = handoff("facebook", reg=reg)
    assert result["blocked"] is True
    assert "REGISTRY_INSTANCE_MISMATCH" in result["hard_blocks"]


def test_capability_adapter_path_mismatch_is_fail_closed() -> None:
    caps = capabilities()
    fb = next(row for row in caps["adapters"] if row["platform"] == "facebook")
    fb["adapter"] = "valcea-clar/social/not-the-installed-adapter.py"
    result = handoff("facebook", caps=caps)
    assert result["blocked"] is True
    assert "CAPABILITY_ADAPTER_PATH_MISMATCH" in result["hard_blocks"]


def test_secret_like_present_reference_is_rejected_without_exposure() -> None:
    result = handoff("facebook", refs={"EAA_THIS_LOOKS_LIKE_A_TOKEN"})
    assert result["blocked"] is True
    assert "PRESENT_REFERENCE_NOT_NAME" in result["hard_blocks"]
    assert result["guards"]["credential_values_exposed"] is False


def test_repeated_handoff_is_idempotent_and_bundle_stable() -> None:
    source = series_result("instagram")
    first = handoff("instagram", result=source)
    second = handoff(
        "instagram",
        result=source,
        outbox=first["commit_bundle"]["dispatch_handoff_outbox"],
    )
    assert second["blocked"] is False
    assert second["decision"] == "DEDUPE_EXISTING_SERIES_HANDOFF"
    assert second["adapter_handoff"]["handoff_id"] == first["adapter_handoff"]["handoff_id"]
    assert second["bundle_fingerprint_sha256"] == first["bundle_fingerprint_sha256"]
    assert second["commit_bundle"] == first["commit_bundle"]


def test_zero_paid_registry_policy_cannot_be_weakened() -> None:
    reg = registry()
    reg["policy"]["paid_social_scheduler_required"] = True
    reg["policy"]["paid_llm_api_required"] = True
    result = handoff("facebook", reg=reg)
    assert result["blocked"] is True
    assert "PAID_SCHEDULER_POLICY_VIOLATION" in result["hard_blocks"]
    assert "PAID_LLM_POLICY_VIOLATION" in result["hard_blocks"]


def test_predictive_or_secret_fields_cannot_enter_native_series_handoff() -> None:
    source = series_result("facebook")
    product = source["outbox_item"]["product"]
    product["predicted_views"] = 999999
    product["access_token"] = "DO-NOT-STORE"
    payload = copy.deepcopy(product)
    payload.pop("product_fingerprint_sha256", None)
    product["product_fingerprint_sha256"] = series_adapter_dispatch_handoff._digest(payload)
    source["record"]["product_fingerprint_sha256"] = product["product_fingerprint_sha256"]
    source["outbox_item"]["product_fingerprint_sha256"] = product["product_fingerprint_sha256"]
    source["outbox_item"]["outbox_item_fingerprint_sha256"] = series_adapter_dispatch_handoff._digest({
        key: value for key, value in source["outbox_item"].items() if key != "outbox_item_fingerprint_sha256"
    })
    source["state"]["records"][source["record"]["publication_id"]]["product_fingerprint_sha256"] = product["product_fingerprint_sha256"]
    source["outbox"]["items"][0] = copy.deepcopy(source["outbox_item"])
    result = handoff("facebook", result=source)
    assert result["blocked"] is True
    assert "PREDICTIVE_ANALYTICS_FORBIDDEN" in result["hard_blocks"]
    assert "SECRET_VALUE_IN_NATIVE_SERIES_PRODUCT" in result["hard_blocks"]
    assert "DO-NOT-STORE" not in json.dumps(result, ensure_ascii=False)


def main() -> int:
    tests = [
        test_facebook_ready_series_becomes_direct_ready_without_dispatch,
        test_instagram_carousel_series_uses_truthful_native_capability,
        test_outbox_only_series_never_creates_adapter_handoff,
        test_link_hold_never_reaches_runtime_or_capability_gate,
        test_timing_hold_never_creates_adapter_bundle,
        test_human_approval_hold_remains_nondispatchable,
        test_missing_credential_reference_synchronizes_series_state_and_outbox,
        test_capability_gap_demotes_exact_native_product_to_outbox_only,
        test_source_outbox_fingerprint_tamper_is_fail_closed,
        test_registry_instance_isolation_is_fail_closed,
        test_capability_adapter_path_mismatch_is_fail_closed,
        test_secret_like_present_reference_is_rejected_without_exposure,
        test_repeated_handoff_is_idempotent_and_bundle_stable,
        test_zero_paid_registry_policy_cannot_be_weakened,
        test_predictive_or_secret_fields_cannot_enter_native_series_handoff,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"Series Adapter-Gated Dispatch Handoff acceptance: PASS ({len(tests)}/{len(tests)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
