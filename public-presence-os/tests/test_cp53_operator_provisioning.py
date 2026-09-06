from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import inspect
import json
from pathlib import Path

import pytest

from public_presence_os.connection_preflight import compile_synthetic_preflight
from public_presence_os.connection_profiles import (
    ConnectionProfileSpec,
    OfflineCapabilityEvidence,
    SecretReferenceVault,
    compile_connection_profile,
)
from public_presence_os.meta_adapters import (
    SINGLE_IMAGE,
    STAGING_URL_REF,
    TEXT,
    OfflinePublishIntent,
    compile_offline_request,
    static_capability_contract,
)
from public_presence_os.operator_provisioning import (
    OperatorProvisioningHold,
    compile_operator_provisioning_packet,
    render_operator_packet_json,
    validate_operator_provisioning_packet,
)

ROOT = Path(__file__).resolve().parents[1]


def h(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def bound_evidence(platform: str, mode: str) -> OfflineCapabilityEvidence:
    contract = static_capability_contract(platform, mode)
    return OfflineCapabilityEvidence(
        state="OFFLINE_EVIDENCE_BOUND",
        evidence_artifact_sha256=h(f"cp53-evidence:{platform}:{mode}"),
        observed_permissions=contract["required_permissions"],
        observed_capabilities=contract["required_capabilities"],
        expiry_state="KNOWN",
        expires_at_utc="2026-12-31T23:59:59Z",
    )


def make_plan(platform: str, mode: str):
    if mode == TEXT:
        intent = OfflinePublishIntent(
            source_binding_hash=h(f"cp53-source:{platform}:{mode}"),
            platform=platform,
            mode=mode,
            text="Synthetic CP53 operator packet contract check only.",
        )
    else:
        intent = OfflinePublishIntent(
            source_binding_hash=h(f"cp53-source:{platform}:{mode}"),
            platform=platform,
            mode=mode,
            text="Synthetic CP53 image operator packet check only.",
            media_asset_sha256=h(f"cp53-media:{platform}"),
            alt_text="Synthetic image used only for an offline CP53 test.",
            staging_url_ref=STAGING_URL_REF,
        )
    return compile_offline_request(intent)


def make_profile(platform: str, mode: str):
    locator = {
        "FACEBOOK_PAGE": "ENV:PPOS_META_FB_PAGE_TOKEN",
        "INSTAGRAM_PROFESSIONAL": "ENV:PPOS_META_INSTAGRAM_TOKEN",
        "THREADS": "OS_KEYCHAIN:ppos/meta/threads",
    }[platform]
    return compile_connection_profile(ConnectionProfileSpec(
        platform,
        mode,
        locator,
        evidence=bound_evidence(platform, mode),
    ))


def make_preflight(tmp_path, platform: str, mode: str):
    plan = make_plan(platform, mode)
    profile = make_profile(platform, mode)
    vault = SecretReferenceVault(tmp_path / f"cp53-{platform.lower()}-{mode.lower()}.sqlite3")
    vault_receipt = vault.stage(
        profile,
        request_id=f"cp53-vault-{platform.lower()}-{mode.lower()}",
        event_time_utc="2026-09-06T21:30:00Z",
    )
    preflight = compile_synthetic_preflight(
        plan,
        profile,
        vault=vault,
        vault_receipt=vault_receipt,
        request_id=f"cp53-preflight-{platform.lower()}-{mode.lower()}",
        event_time_utc="2026-09-06T21:31:00Z",
    )
    return preflight, profile


@pytest.mark.parametrize(
    ("platform", "mode"),
    [
        ("FACEBOOK_PAGE", TEXT),
        ("FACEBOOK_PAGE", SINGLE_IMAGE),
        ("INSTAGRAM_PROFESSIONAL", SINGLE_IMAGE),
        ("THREADS", TEXT),
        ("THREADS", SINGLE_IMAGE),
    ],
)
def test_cp53_active_lane_packets_are_deterministic_and_fail_closed(tmp_path, platform, mode):
    preflight, profile = make_preflight(tmp_path, platform, mode)
    first = compile_operator_provisioning_packet(preflight, profile)
    second = compile_operator_provisioning_packet(preflight, profile)

    assert first == second
    assert first.packet_hash == second.packet_hash
    assert first.state == "OFFLINE_OPERATOR_PACKET_READY"
    assert first.platform == platform
    assert first.mode == mode
    assert first.preflight_receipt_hash == preflight.receipt_hash
    assert first.profile_hash == profile.profile_hash
    assert first.required_permissions == profile.required_permissions
    assert first.required_capabilities == profile.required_capabilities
    assert first.secret_reference == profile.secret_reference
    assert first.secret_material_included is False
    assert first.secret_resolved is False
    assert first.environment_read is False
    assert first.keychain_read is False
    assert first.network_attempted is False
    assert first.real_account_lookup_attempted is False
    assert first.account_connected is False
    assert first.publish_attempted is False
    assert first.external_write_performed is False
    assert first.deploy_performed is False
    assert first.live_entitlement_verified is False
    assert first.live_connection_ready is False
    assert first.pilot_publish_ready is False
    assert first.global_kill_switch_required is True
    assert first.live_reverification_required is True
    assert first.live_blockers
    assert any(item.state == "PASS_OFFLINE_CONTRACT" for item in first.checklist)
    assert any(item.state.startswith("PENDING") and item.blocking_for_live_connection for item in first.checklist)


def test_cp53_lane_prerequisites_are_specific(tmp_path):
    fb, fb_profile = make_preflight(tmp_path, "FACEBOOK_PAGE", TEXT)
    ig, ig_profile = make_preflight(tmp_path, "INSTAGRAM_PROFESSIONAL", SINGLE_IMAGE)
    threads, threads_profile = make_preflight(tmp_path, "THREADS", TEXT)

    fb_packet = compile_operator_provisioning_packet(fb, fb_profile)
    ig_packet = compile_operator_provisioning_packet(ig, ig_profile)
    threads_packet = compile_operator_provisioning_packet(threads, threads_profile)

    assert "FACEBOOK_PAGE_EXISTS" in fb_packet.lane_prerequisites
    assert "INSTAGRAM_ACCOUNT_IS_PROFESSIONAL_BUSINESS_OR_CREATOR" in ig_packet.lane_prerequisites
    assert "CREATE_THEN_PUBLISH_CONTAINER_FLOW_REVERIFIED_BEFORE_LIVE" in threads_packet.lane_prerequisites
    assert set(fb_packet.required_permissions) == {"pages_show_list", "pages_read_engagement", "pages_manage_posts"}
    assert set(ig_packet.required_permissions) == {"instagram_business_basic", "instagram_business_content_publish"}
    assert set(threads_packet.required_permissions) == {"threads_basic", "threads_content_publish"}


def test_cp53_exact_cp52_profile_binding_is_mandatory(tmp_path):
    preflight, _ = make_preflight(tmp_path, "FACEBOOK_PAGE", TEXT)
    wrong_profile = make_profile("THREADS", TEXT)
    with pytest.raises(OperatorProvisioningHold, match="HOLD_PROVISIONING_PROFILE_BINDING_MISMATCH"):
        compile_operator_provisioning_packet(preflight, wrong_profile)


def test_cp53_packet_tampering_fails_exact_hash_validation(tmp_path):
    preflight, profile = make_preflight(tmp_path, "THREADS", SINGLE_IMAGE)
    packet = compile_operator_provisioning_packet(preflight, profile)
    tampered = replace(packet, live_blockers=packet.live_blockers + ("TAMPERED",))
    with pytest.raises(OperatorProvisioningHold, match="HOLD_PROVISIONING_BLOCKER_DRIFT"):
        validate_operator_provisioning_packet(tampered)


def test_cp53_json_export_is_deterministic_and_contains_only_symbolic_secret_reference(tmp_path):
    preflight, profile = make_preflight(tmp_path, "INSTAGRAM_PROFESSIONAL", SINGLE_IMAGE)
    packet = compile_operator_provisioning_packet(preflight, profile)
    first = render_operator_packet_json(packet)
    second = render_operator_packet_json(packet)
    assert first == second
    data = json.loads(first)
    assert data["secret_reference"] == "ENV:PPOS_META_INSTAGRAM_TOKEN"
    assert data["secret_material_included"] is False
    assert data["secret_resolved"] is False
    assert data["live_connection_ready"] is False
    assert data["pilot_publish_ready"] is False


def test_cp53_policy_registry_priority_and_runtime_remain_fail_closed():
    policy = json.loads((ROOT / "config" / "meta_operator_provisioning_policy.json").read_text(encoding="utf-8"))
    registry = json.loads((ROOT / "config" / "module_registry.json").read_text(encoding="utf-8"))
    priority = json.loads((ROOT / "config" / "reimplementation_priority.json").read_text(encoding="utf-8"))
    runtime = json.loads((ROOT / "config" / "runtime_policy.json").read_text(encoding="utf-8"))

    assert policy["checkpoint"] == "CP53"
    assert tuple(policy["active_platforms"]) == ("FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS")
    assert policy["packet_contract"]["symbolic_secret_reference_only"] is True
    assert policy["packet_contract"]["secret_material_forbidden"] is True
    assert policy["packet_contract"]["live_connection_ready"] is False
    assert policy["packet_contract"]["pilot_publish_ready"] is False
    assert policy["operator_gates"]["fresh_final_pilot_authorization_required"] is True
    for key in (
        "secret_resolution_allowed",
        "environment_read_allowed",
        "keychain_read_allowed",
        "network_allowed",
        "real_account_lookup_allowed",
        "account_connection_allowed",
        "publish_execution_allowed",
        "external_write_allowed",
        "deploy_allowed",
    ):
        assert policy["authority"][key] is False

    assert registry["checkpoint"] == "CP54"
    assert any(
        m["id"] == "M22_META_OPERATOR_PROVISIONING" and m["status"] == "CP53_OFFLINE_OPERATOR_PACKET_CHECKLIST"
        for m in registry["modules"]
    )
    assert any(
        m["id"] == "M23_META_TRANSPORT_TWIN" and m["status"] == "CP54_SYNTHETIC_TRANSPORT_TEST_TWIN_ONLY"
        for m in registry["modules"]
    )
    assert priority["checkpoint"] == "CP54"
    assert priority["next"] == "CP55_META_READ_ONLY_CONNECTION_GATE_CONTRACT_AND_KILL_SWITCH_INTERLOCK"
    assert runtime["global_kill_switch_engaged"] is True
    assert runtime["network_enabled"] is False
    assert runtime["real_accounts_connected"] is False
    assert runtime["publish_enabled"] is False
    assert runtime["deploy_enabled"] is False


def test_cp53_source_has_no_secret_resolution_or_network_transport():
    import public_presence_os.operator_provisioning as module

    src = inspect.getsource(module)
    forbidden = (
        "os.environ",
        "os.getenv",
        "keyring",
        "subprocess",
        "requests",
        "httpx",
        "aiohttp",
        "urllib.request",
        "http.client",
        "socket",
    )
    for item in forbidden:
        assert item not in src
    for forbidden_function in (
        "resolve_secret(",
        "read_secret(",
        "refresh_token(",
        "oauth_exchange(",
        "execute_http(",
        "publish_live(",
        "connect_account(",
    ):
        assert forbidden_function not in src
