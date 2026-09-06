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
from public_presence_os.meta_transport_twin import (
    HOLD_UNKNOWN,
    NO_RETRY_AUTH,
    NO_RETRY_CLIENT,
    RETRY_RATE_LIMIT,
    RETRY_SUCCESS,
    RETRY_TRANSIENT,
    MetaTransportTwinHold,
    SyntheticCredentialEnvelope,
    SyntheticTransportBinding,
    classify_synthetic_response,
    compile_transport_test_twin,
    render_transport_twin_json,
    validate_transport_twin_receipt,
)
from public_presence_os.operator_provisioning import compile_operator_provisioning_packet

ROOT = Path(__file__).resolve().parents[1]


def h(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def bound_evidence(platform: str, mode: str) -> OfflineCapabilityEvidence:
    contract = static_capability_contract(platform, mode)
    return OfflineCapabilityEvidence(
        state="OFFLINE_EVIDENCE_BOUND",
        evidence_artifact_sha256=h(f"cp54-evidence:{platform}:{mode}"),
        observed_permissions=contract["required_permissions"],
        observed_capabilities=contract["required_capabilities"],
        expiry_state="KNOWN",
        expires_at_utc="2026-12-31T23:59:59Z",
    )


def make_plan(platform: str, mode: str):
    if mode == TEXT:
        intent = OfflinePublishIntent(
            source_binding_hash=h(f"cp54-source:{platform}:{mode}"),
            platform=platform,
            mode=mode,
            text="Synthetic CP54 transport-twin serialization check only.",
        )
    else:
        intent = OfflinePublishIntent(
            source_binding_hash=h(f"cp54-source:{platform}:{mode}"),
            platform=platform,
            mode=mode,
            text="Synthetic CP54 image transport-twin check only.",
            media_asset_sha256=h(f"cp54-media:{platform}"),
            alt_text="Synthetic image used only for the CP54 offline transport twin.",
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


def make_lineage(tmp_path, platform: str, mode: str):
    plan = make_plan(platform, mode)
    profile = make_profile(platform, mode)
    vault = SecretReferenceVault(tmp_path / f"cp54-{platform.lower()}-{mode.lower()}.sqlite3")
    vault_receipt = vault.stage(
        profile,
        request_id=f"cp54-vault-{platform.lower()}-{mode.lower()}",
        event_time_utc="2026-09-06T20:40:00Z",
    )
    preflight = compile_synthetic_preflight(
        plan,
        profile,
        vault=vault,
        vault_receipt=vault_receipt,
        request_id=f"cp54-preflight-{platform.lower()}-{mode.lower()}",
        event_time_utc="2026-09-06T20:41:00Z",
    )
    packet = compile_operator_provisioning_packet(preflight, profile)
    return plan, preflight, packet


def synthetic_binding(mode: str) -> SyntheticTransportBinding:
    return SyntheticTransportBinding(
        destination_id="TEST_DESTINATION_LOCAL_PPOS_001",
        api_version="TEST_API_VERSION_V1",
        staging_url="https://example.invalid/ppos/cp54/image.png" if mode == SINGLE_IMAGE else None,
    )


def synthetic_credentials(auth_reference_kind: str) -> SyntheticCredentialEnvelope:
    return SyntheticCredentialEnvelope(
        auth_reference_kind=auth_reference_kind,
        bearer_token="TEST_ONLY_TOKEN_LOCAL_PPOS_ABCDEF123456",
        signing_secret="TEST_ONLY_SIGNING_SECRET_LOCAL_PPOS_ABCDEF123456",
    )


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
def test_cp54_active_lane_transport_twins_are_deterministic_and_zero_network(tmp_path, platform, mode):
    plan, preflight, packet = make_lineage(tmp_path, platform, mode)
    binding = synthetic_binding(mode)
    credentials = synthetic_credentials(plan.auth_reference_kind)

    first = compile_transport_test_twin(
        plan,
        preflight,
        packet,
        binding=binding,
        credentials=credentials,
    )
    second = compile_transport_test_twin(
        plan,
        preflight,
        packet,
        binding=binding,
        credentials=credentials,
    )

    assert first == second
    assert first.twin_hash == second.twin_hash
    assert first.state == "PASS_SYNTHETIC_TRANSPORT_TWIN_ONLY"
    assert first.plan_hash == plan.plan_hash
    assert first.preflight_receipt_hash == preflight.receipt_hash
    assert first.provisioning_packet_hash == packet.packet_hash
    assert first.platform == platform
    assert first.mode == mode
    assert first.synthetic_credentials_only is True
    assert first.production_signing_semantics_asserted is False
    assert first.production_idempotency_semantics_asserted is False
    assert first.secret_reference_resolved is False
    assert first.environment_read is False
    assert first.keychain_read is False
    assert first.oauth_attempted is False
    assert first.real_account_lookup_attempted is False
    assert first.account_connected is False
    assert first.network_attempted is False
    assert first.publish_attempted is False
    assert first.external_write_performed is False
    assert first.deploy_performed is False
    assert first.live_entitlement_verified is False
    assert first.live_transport_ready is False
    assert first.pilot_publish_ready is False
    assert first.global_kill_switch_required is True
    assert first.live_reverification_required is True
    assert len(first.requests) == len(plan.steps)

    for request in first.requests:
        assert "{API_VERSION}" not in request.resolved_path
        assert "{DESTINATION_ID}" not in request.resolved_path
        assert "TEST_API_VERSION_V1" in request.resolved_path
        assert "TEST_DESTINATION_LOCAL_PPOS_001" in request.resolved_path
        assert request.authorization_scheme == "Bearer"
        assert len(request.authorization_value_sha256) == 64
        assert len(request.internal_signature_sha256) == 64
        assert len(request.request_hash) == 64
        assert request.idempotency_key.startswith("twinidem_")
        assert request.auth_scope == "SYNTHETIC_BEARER_BOUNDARY_ONLY"
        assert request.signature_scope == "TWIN_INTERNAL_HMAC_SHA256_ONLY"
        assert request.idempotency_scope == "LOCAL_DETERMINISTIC_KEY_ONLY"
        assert request.credential_material_serialized is False
        assert request.wire_signature_header_included is False
        assert request.wire_idempotency_header_included is False
        assert request.network_target_materialized is False
        assert request.network_attempted is False


def test_cp54_serialized_receipt_never_contains_synthetic_token_or_signing_secret(tmp_path):
    plan, preflight, packet = make_lineage(tmp_path, "THREADS", SINGLE_IMAGE)
    credentials = synthetic_credentials(plan.auth_reference_kind)
    receipt = compile_transport_test_twin(
        plan,
        preflight,
        packet,
        binding=synthetic_binding(SINGLE_IMAGE),
        credentials=credentials,
    )
    payload = render_transport_twin_json(receipt)
    assert credentials.bearer_token not in payload
    assert credentials.signing_secret not in payload
    data = json.loads(payload)
    assert data["synthetic_credentials_only"] is True
    assert data["production_signing_semantics_asserted"] is False
    assert all(request["credential_material_serialized"] is False for request in data["requests"])
    assert all(request["wire_signature_header_included"] is False for request in data["requests"])


def test_cp54_exact_cp50_cp52_cp53_lineage_is_required(tmp_path):
    plan_fb, preflight_fb, packet_fb = make_lineage(tmp_path, "FACEBOOK_PAGE", TEXT)
    plan_threads = make_plan("THREADS", TEXT)
    with pytest.raises(MetaTransportTwinHold, match="HOLD_TWIN_PREFLIGHT_PLAN_BINDING_MISMATCH"):
        compile_transport_test_twin(
            plan_threads,
            preflight_fb,
            packet_fb,
            binding=synthetic_binding(TEXT),
            credentials=synthetic_credentials(plan_threads.auth_reference_kind),
        )
    assert plan_fb.plan_hash == preflight_fb.plan_hash


def test_cp54_rejects_any_unmarked_or_real_looking_credentials(tmp_path):
    plan, preflight, packet = make_lineage(tmp_path, "FACEBOOK_PAGE", TEXT)
    with pytest.raises(MetaTransportTwinHold, match="HOLD_TWIN_REAL_OR_UNMARKED_TOKEN_FORBIDDEN"):
        compile_transport_test_twin(
            plan,
            preflight,
            packet,
            binding=synthetic_binding(TEXT),
            credentials=SyntheticCredentialEnvelope(
                auth_reference_kind=plan.auth_reference_kind,
                bearer_token="EAAREALLOOKINGTOKEN",
                signing_secret="TEST_ONLY_SIGNING_SECRET_LOCAL_PPOS_ABCDEF123456",
            ),
        )
    with pytest.raises(MetaTransportTwinHold, match="HOLD_TWIN_REAL_OR_UNMARKED_SIGNING_SECRET_FORBIDDEN"):
        compile_transport_test_twin(
            plan,
            preflight,
            packet,
            binding=synthetic_binding(TEXT),
            credentials=SyntheticCredentialEnvelope(
                auth_reference_kind=plan.auth_reference_kind,
                bearer_token="TEST_ONLY_TOKEN_LOCAL_PPOS_ABCDEF123456",
                signing_secret="REAL_SIGNING_SECRET",
            ),
        )


def test_cp54_rejects_real_destination_api_version_and_routable_staging(tmp_path):
    plan, preflight, packet = make_lineage(tmp_path, "INSTAGRAM_PROFESSIONAL", SINGLE_IMAGE)
    credentials = synthetic_credentials(plan.auth_reference_kind)
    with pytest.raises(MetaTransportTwinHold, match="HOLD_TWIN_REAL_DESTINATION_FORBIDDEN"):
        compile_transport_test_twin(
            plan,
            preflight,
            packet,
            binding=SyntheticTransportBinding("17841400000000000", "TEST_API_VERSION_V1", "https://example.invalid/a.png"),
            credentials=credentials,
        )
    with pytest.raises(MetaTransportTwinHold, match="HOLD_TWIN_REAL_API_VERSION_FORBIDDEN"):
        compile_transport_test_twin(
            plan,
            preflight,
            packet,
            binding=SyntheticTransportBinding("TEST_DESTINATION_LOCAL_PPOS_001", "v25.0", "https://example.invalid/a.png"),
            credentials=credentials,
        )
    with pytest.raises(MetaTransportTwinHold, match="HOLD_TWIN_NONROUTABLE_STAGING_URL_REQUIRED"):
        compile_transport_test_twin(
            plan,
            preflight,
            packet,
            binding=SyntheticTransportBinding("TEST_DESTINATION_LOCAL_PPOS_001", "TEST_API_VERSION_V1", "https://cdn.example.com/a.png"),
            credentials=credentials,
        )


def test_cp54_retry_classifier_is_static_synthetic_only():
    assert classify_synthetic_response(200) == RETRY_SUCCESS
    assert classify_synthetic_response(201) == RETRY_SUCCESS
    assert classify_synthetic_response(429) == RETRY_RATE_LIMIT
    assert classify_synthetic_response(408) == RETRY_TRANSIENT
    assert classify_synthetic_response(500) == RETRY_TRANSIENT
    assert classify_synthetic_response(503) == RETRY_TRANSIENT
    assert classify_synthetic_response(401) == NO_RETRY_AUTH
    assert classify_synthetic_response(403) == NO_RETRY_AUTH
    assert classify_synthetic_response(400) == NO_RETRY_CLIENT
    assert classify_synthetic_response(422) == NO_RETRY_CLIENT
    assert classify_synthetic_response(399) == HOLD_UNKNOWN
    with pytest.raises(MetaTransportTwinHold, match="HOLD_TWIN_SYNTHETIC_STATUS_INVALID"):
        classify_synthetic_response(99)


def test_cp54_local_idempotency_key_and_internal_signature_are_stable_across_retry_compilation(tmp_path):
    plan, preflight, packet = make_lineage(tmp_path, "THREADS", TEXT)
    binding = synthetic_binding(TEXT)
    credentials = synthetic_credentials(plan.auth_reference_kind)
    first = compile_transport_test_twin(plan, preflight, packet, binding=binding, credentials=credentials)
    retry = compile_transport_test_twin(plan, preflight, packet, binding=binding, credentials=credentials)
    assert [r.idempotency_key for r in first.requests] == [r.idempotency_key for r in retry.requests]
    assert [r.internal_signature_sha256 for r in first.requests] == [r.internal_signature_sha256 for r in retry.requests]
    assert all(r.wire_idempotency_header_included is False for r in retry.requests)


def test_cp54_receipt_tampering_fails_closed(tmp_path):
    plan, preflight, packet = make_lineage(tmp_path, "FACEBOOK_PAGE", TEXT)
    receipt = compile_transport_test_twin(
        plan,
        preflight,
        packet,
        binding=synthetic_binding(TEXT),
        credentials=synthetic_credentials(plan.auth_reference_kind),
    )
    tampered_request = replace(receipt.requests[0], wire_signature_header_included=True)
    tampered = replace(receipt, requests=(tampered_request,))
    with pytest.raises(MetaTransportTwinHold, match="HOLD_TWIN_WIRE_AUTHORITY_FORBIDDEN"):
        validate_transport_twin_receipt(tampered)


def test_cp54_policy_registry_priority_and_runtime_remain_fail_closed():
    policy = json.loads((ROOT / "config" / "meta_transport_twin_policy.json").read_text(encoding="utf-8"))
    registry = json.loads((ROOT / "config" / "module_registry.json").read_text(encoding="utf-8"))
    priority = json.loads((ROOT / "config" / "reimplementation_priority.json").read_text(encoding="utf-8"))
    runtime = json.loads((ROOT / "config" / "runtime_policy.json").read_text(encoding="utf-8"))

    assert policy["checkpoint"] == "CP54"
    assert tuple(policy["active_platforms"]) == ("FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS")
    assert policy["transport_twin_contract"]["synthetic_credentials_only"] is True
    assert policy["transport_twin_contract"]["production_signing_semantics_asserted"] is False
    assert policy["transport_twin_contract"]["request_signature_sent_on_wire"] is False
    assert policy["transport_twin_contract"]["production_idempotency_semantics_asserted"] is False
    assert policy["transport_twin_contract"]["wire_idempotency_header_allowed"] is False
    assert policy["transport_twin_contract"]["live_transport_ready"] is False
    assert policy["transport_twin_contract"]["pilot_publish_ready"] is False
    for key in (
        "real_secret_reference_resolution_allowed",
        "environment_read_allowed",
        "keychain_read_allowed",
        "oauth_allowed",
        "real_account_lookup_allowed",
        "account_connection_allowed",
        "network_allowed",
        "publish_execution_allowed",
        "external_write_allowed",
        "deploy_allowed",
    ):
        assert policy["authority"][key] is False

    assert registry["checkpoint"] == "CP54"
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


def test_cp54_source_contains_no_network_secret_resolution_or_real_transport():
    import public_presence_os.meta_transport_twin as module

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
