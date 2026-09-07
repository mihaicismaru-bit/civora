from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import inspect
import json
from pathlib import Path

import pytest

from public_presence_os.meta_adapters import (
    SINGLE_IMAGE,
    STAGING_URL_REF,
    TEXT,
    MetaAdapterHold,
    OfflinePublishIntent,
    compile_offline_request,
    static_capability_contract,
    validate_request_plan,
)

ROOT = Path(__file__).resolve().parents[1]


def h(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def image_intent(platform: str) -> OfflinePublishIntent:
    return OfflinePublishIntent(
        source_binding_hash=h("outbox-binding"),
        platform=platform,
        mode=SINGLE_IMAGE,
        text="Text pentru fotografie.",
        media_asset_sha256=h("asset-bytes"),
        alt_text="Descriere accesibilă a fotografiei.",
        staging_url_ref=STAGING_URL_REF,
    )


def test_cp50_facebook_text_request_is_deterministic_and_offline():
    intent = OfflinePublishIntent(h("fb-source"), "FACEBOOK_PAGE", TEXT, "Mesaj local.")
    first = compile_offline_request(intent)
    second = compile_offline_request(intent)
    assert first == second
    assert first.plan_hash == second.plan_hash
    assert first.auth_reference_kind == "PAGE_ACCESS_TOKEN_REF"
    assert first.required_permissions == ("pages_show_list", "pages_read_engagement", "pages_manage_posts")
    assert first.required_capabilities == ("publish_text",)
    assert len(first.steps) == 1
    assert first.steps[0].host == "graph.facebook.com"
    assert first.steps[0].path_template == "/{API_VERSION}/{DESTINATION_ID}/feed"
    assert first.steps[0].body == (("message", "Mesaj local."),)
    assert first.transport_mode == "OFFLINE_COMPILE_ONLY"
    assert first.network_allowed is False
    assert first.publish_execution_allowed is False
    assert first.external_write_allowed is False


def test_cp50_facebook_single_image_binds_asset_and_placeholder():
    plan = compile_offline_request(image_intent("FACEBOOK_PAGE"))
    assert plan.required_capabilities == ("publish_single_image",)
    assert plan.media_asset_sha256 == h("asset-bytes")
    assert plan.alt_text_sha256 == h("Descriere accesibilă a fotografiei.")
    assert plan.steps[0].path_template.endswith("/photos")
    assert ("url", STAGING_URL_REF) in plan.steps[0].body
    assert not any(value.startswith(("http://", "https://")) for _, value in plan.steps[0].body)


def test_cp50_instagram_single_image_is_two_phase_current_login_family():
    plan = compile_offline_request(image_intent("INSTAGRAM_PROFESSIONAL"))
    assert plan.auth_reference_kind == "INSTAGRAM_USER_TOKEN_REF"
    assert plan.required_permissions == ("instagram_business_basic", "instagram_business_content_publish")
    assert [step.host for step in plan.steps] == ["graph.instagram.com", "graph.instagram.com"]
    assert [step.operation for step in plan.steps] == ["CREATE_IMAGE_CONTAINER", "PUBLISH_IMAGE_CONTAINER"]
    assert [step.path_template for step in plan.steps] == [
        "/{API_VERSION}/{DESTINATION_ID}/media",
        "/{API_VERSION}/{DESTINATION_ID}/media_publish",
    ]
    assert plan.steps[1].body == (("creation_id", "{{STEP_1_CONTAINER_ID}}"),)


def test_cp50_instagram_text_only_is_fail_closed():
    with pytest.raises(MetaAdapterHold, match="HOLD_META_MODE_NOT_SUPPORTED"):
        compile_offline_request(OfflinePublishIntent(h("ig"), "INSTAGRAM_PROFESSIONAL", TEXT, "text"))


def test_cp50_threads_text_and_image_are_two_phase():
    text_plan = compile_offline_request(OfflinePublishIntent(h("th-text"), "THREADS", TEXT, "Text Threads."))
    image_plan = compile_offline_request(image_intent("THREADS"))
    assert text_plan.auth_reference_kind == "THREADS_USER_TOKEN_REF"
    assert text_plan.required_permissions == ("threads_basic", "threads_content_publish")
    assert len(text_plan.steps) == 2
    assert text_plan.steps[0].host == "graph.threads.net"
    assert ("media_type", "TEXT") in text_plan.steps[0].body
    assert ("media_type", "IMAGE") in image_plan.steps[0].body
    assert ("image_url", STAGING_URL_REF) in image_plan.steps[0].body
    assert ("alt_text", "Descriere accesibilă a fotografiei.") in image_plan.steps[0].body
    assert text_plan.steps[1].path_template.endswith("/threads_publish")


@pytest.mark.parametrize("platform", ["LINKEDIN", "X", "BLUESKY"])
def test_cp50_non_active_lanes_are_structurally_rejected(platform):
    with pytest.raises(MetaAdapterHold, match="HOLD_META_PLATFORM_NOT_ACTIVE"):
        compile_offline_request(OfflinePublishIntent(h(platform), platform, TEXT, "text"))


def test_cp50_refuses_real_destination_literal_api_version_or_media_url():
    with pytest.raises(MetaAdapterHold, match="HOLD_META_REAL_DESTINATION_FORBIDDEN"):
        compile_offline_request(OfflinePublishIntent(
            h("dest"), "FACEBOOK_PAGE", TEXT, "text", destination_ref="123456789"
        ))
    with pytest.raises(MetaAdapterHold, match="HOLD_META_LITERAL_API_VERSION_FORBIDDEN"):
        compile_offline_request(OfflinePublishIntent(
            h("version"), "FACEBOOK_PAGE", TEXT, "text", api_version_ref="v99.0"
        ))
    with pytest.raises(MetaAdapterHold, match="HOLD_META_STAGING_URL_PLACEHOLDER_REQUIRED"):
        compile_offline_request(OfflinePublishIntent(
            h("media"),
            "FACEBOOK_PAGE",
            SINGLE_IMAGE,
            "caption",
            media_asset_sha256=h("media-asset"),
            alt_text="alt",
            staging_url_ref="https://example.invalid/a.png",
        ))


def test_cp50_image_requires_exact_media_and_alt_text_binding():
    with pytest.raises(MetaAdapterHold, match="HOLD_META_MEDIA_ASSET_HASH_REQUIRED"):
        compile_offline_request(OfflinePublishIntent(
            h("image"), "THREADS", SINGLE_IMAGE, "caption", alt_text="alt", staging_url_ref=STAGING_URL_REF
        ))
    with pytest.raises(MetaAdapterHold, match="HOLD_META_ALT_TEXT_REQUIRED"):
        compile_offline_request(OfflinePublishIntent(
            h("image"), "THREADS", SINGLE_IMAGE, "caption", media_asset_sha256=h("asset"),
            staging_url_ref=STAGING_URL_REF
        ))


def test_cp50_plan_tamper_fails_exact_hash_validation():
    plan = compile_offline_request(OfflinePublishIntent(h("tamper"), "FACEBOOK_PAGE", TEXT, "Original"))
    with pytest.raises(MetaAdapterHold, match="HOLD_META_PLAN_HASH_MISMATCH"):
        validate_request_plan(replace(plan, payload_text_sha256=h("changed")))


def test_cp50_static_capability_gate_never_asserts_real_entitlement():
    gate = static_capability_contract("THREADS", SINGLE_IMAGE)
    assert gate["static_contract_supported"] is True
    assert gate["real_entitlement_asserted"] is False
    assert gate["network_authority"] is False
    assert gate["publish_authority"] is False
    assert gate["live_reverification_required"] is True


def test_cp50_policy_registry_and_runtime_remain_fail_closed():
    policy = json.loads((ROOT / "config" / "meta_adapter_policy.json").read_text(encoding="utf-8"))
    registry = json.loads((ROOT / "config" / "module_registry.json").read_text(encoding="utf-8"))
    runtime = json.loads((ROOT / "config" / "runtime_policy.json").read_text(encoding="utf-8"))
    priority = json.loads((ROOT / "config" / "reimplementation_priority.json").read_text(encoding="utf-8"))

    assert policy["checkpoint"] == "CP50"
    assert tuple(policy["active_platforms"]) == ("FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS")
    assert policy["transport_mode"] == "OFFLINE_COMPILE_ONLY"
    assert policy["global_kill_switch_required"] is True
    for key in (
        "network_allowed",
        "credential_resolution_allowed",
        "real_account_lookup_allowed",
        "account_connection_allowed",
        "publish_execution_allowed",
        "external_write_allowed",
        "deploy_allowed",
        "wire_idempotency_headers_allowed",
    ):
        assert policy["authority"][key] is False

    assert registry["checkpoint"] == "CP57"
    assert any(m["id"] == "M19_META_ADAPTERS" and m["status"] == "CP50_OFFLINE_REQUEST_COMPILER" for m in registry["modules"])
    assert any(m["id"] == "M21_META_PREFLIGHT" and m["status"] == "CP52_SYNTHETIC_PROVISIONING_READBACK_LOCAL_ONLY" for m in registry["modules"])
    assert any(m["id"] == "M22_META_OPERATOR_PROVISIONING" and m["status"] == "CP53_OFFLINE_OPERATOR_PACKET_CHECKLIST" for m in registry["modules"])
    assert any(m["id"] == "M23_META_TRANSPORT_TWIN" and m["status"] == "CP54_SYNTHETIC_TRANSPORT_TEST_TWIN_ONLY" for m in registry["modules"])
    assert any(m["id"] == "M24_META_READ_ONLY_GATE" and m["status"] == "CP55_READ_ONLY_CONNECTION_GATE_CONTRACT_LOCAL_ONLY" for m in registry["modules"])
    assert any(m["id"] == "M25_META_LIVE_READ_ONLY_PROBE" and m["status"] == "CP56_RUNBOOK_EVIDENCE_CAPTURE_CONTRACT_LOCAL_ONLY" for m in registry["modules"])
    assert priority["checkpoint"] == "CP57"
    assert priority["next"] == "CP58_META_PILOT_READINESS_AGGREGATOR_AND_LIVE_CONNECTION_AUTHORIZATION_GATE"

    assert runtime["global_kill_switch_engaged"] is True
    assert runtime["network_enabled"] is False
    assert runtime["real_accounts_connected"] is False
    assert runtime["publish_enabled"] is False
    assert runtime["deploy_enabled"] is False


def test_cp50_source_has_no_network_client_or_secret_resolution():
    import public_presence_os.meta_adapters as module

    src = inspect.getsource(module)
    forbidden_imports = ("requests", "httpx", "aiohttp", "urllib.request", "http.client", "socket")
    for item in forbidden_imports:
        assert f"import {item}" not in src
        assert f"from {item}" not in src
    for forbidden_function in ("resolve_secret(", "refresh_token(", "oauth_exchange(", "execute_http(", "publish_live("):
        assert forbidden_function not in src
