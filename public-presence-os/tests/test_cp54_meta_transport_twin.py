from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import inspect
import json
from pathlib import Path
import re

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
    kwargs = dict(
        source_binding_hash=h(f"cp54-source:{platform}:{mode}"),
        platform=platform,
        mode=mode,
        text="Synthetic CP54 transport-twin check only.",
    )
    if mode == SINGLE_IMAGE:
        kwargs.update(
            media_asset_sha256=h(f"cp54-media:{platform}"),
            alt_text="Synthetic image used only for the CP54 offline transport twin.",
            staging_url_ref=STAGING_URL_REF,
        )
    return compile_offline_request(OfflinePublishIntent(**kwargs))


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
def test_cp54_active_lane_twins_are_deterministic_and_zero_authority(tmp_path, platform, mode):
    plan, preflight, packet = make_lineage(tmp_path, platform, mode)
    kwargs = dict(binding=synthetic_binding(mode), credentials=synthetic_credentials(plan.auth_reference_kind))
    first = compile_transport_test_twin(plan, preflight, packet, **kwargs)
    second = compile_transport_test_twin(plan, preflight, packet, **kwargs)

    assert first == second
    assert first.state == "PASS_SYNTHETIC_TRANSPORT_TWIN_ONLY"
    assert first.plan_hash == plan.plan_hash
    assert first.preflight_receipt_hash == preflight.receipt_hash
    assert first.provisioning_packet_hash == packet.packet_hash
    assert first.synthetic_credentials_only is True
    assert first.production_signing_semantics_asserted is False
    assert first.production_idempotency_semantics_asserted is False
    assert first.global_kill_switch_required is True
    assert first.live_reverification_required is True
    for flag in (
        "secret_reference_resolved", "environment_read", "keychain_read", "oauth_attempted",
        "real_account_lookup_attempted", "account_connected", "network_attempted", "publish_attempted",
        "external_write_performed", "deploy_performed", "live_entitlement_verified",
        "live_transport_ready", "pilot_publish_ready",
    ):
        assert getattr(first, flag) is False

    assert len(first.requests) == len(plan.steps)
    for request in first.requests:
        assert "{API_VERSION}" not in request.resolved_path
        assert "{DESTINATION_ID}" not in request.resolved_path
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


def test_cp54_serialized_receipt_contains_no_credential_material(tmp_path):
    plan, preflight, packet = make_lineage(tmp_path, "THREADS", SINGLE_IMAGE)
    creds = synthetic_credentials(plan.auth_reference_kind)
    receipt = compile_transport_test_twin(
        plan, preflight, packet, binding=synthetic_binding(SINGLE_IMAGE), credentials=creds
    )
    payload = render_transport_twin_json(receipt)
    assert creds.bearer_token not in payload
    assert creds.signing_secret not in payload
    data = json.loads(payload)
    assert data["synthetic_credentials_only"] is True
    assert all(item["credential_material_serialized"] is False for item in data["requests"])
    assert all(item["wire_signature_header_included"] is False for item in data["requests"])


def test_cp54_exact_cp50_cp52_cp53_lineage_is_required(tmp_path):
    _, preflight_fb, packet_fb = make_lineage(tmp_path, "FACEBOOK_PAGE", TEXT)
    plan_threads = make_plan("THREADS", TEXT)
    with pytest.raises(MetaTransportTwinHold, match="HOLD_TWIN_PREFLIGHT_PLAN_BINDING_MISMATCH"):
        compile_transport_test_twin(
            plan_threads,
            preflight_fb,
            packet_fb,
            binding=synthetic_binding(TEXT),
            credentials=synthetic_credentials(plan_threads.auth_reference_kind),
        )


def test_cp54_rejects_unmarked_credentials_and_production_looking_bindings(tmp_path):
    plan, preflight, packet = make_lineage(tmp_path, "INSTAGRAM_PROFESSIONAL", SINGLE_IMAGE)
    with pytest.raises(MetaTransportTwinHold, match="HOLD_TWIN_REAL_OR_UNMARKED_TOKEN_FORBIDDEN"):
        compile_transport_test_twin(
            plan, preflight, packet,
            binding=synthetic_binding(SINGLE_IMAGE),
            credentials=SyntheticCredentialEnvelope(
                plan.auth_reference_kind,
                "EAAREALLOOKINGTOKEN",
                "TEST_ONLY_SIGNING_SECRET_LOCAL_PPOS_ABCDEF123456",
            ),
        )
    creds = synthetic_credentials(plan.auth_reference_kind)
    with pytest.raises(MetaTransportTwinHold, match="HOLD_TWIN_REAL_DESTINATION_FORBIDDEN"):
        compile_transport_test_twin(
            plan, preflight, packet,
            binding=SyntheticTransportBinding("17841400000000000", "TEST_API_VERSION_V1", "https://example.invalid/a.png"),
            credentials=creds,
        )
    with pytest.raises(MetaTransportTwinHold, match="HOLD_TWIN_REAL_API_VERSION_FORBIDDEN"):
        compile_transport_test_twin(
            plan, preflight, packet,
            binding=SyntheticTransportBinding("TEST_DESTINATION_LOCAL_PPOS_001", "v25.0", "https://example.invalid/a.png"),
            credentials=creds,
        )
    with pytest.raises(MetaTransportTwinHold, match="HOLD_TWIN_NONROUTABLE_STAGING_URL_REQUIRED"):
        compile_transport_test_twin(
            plan, preflight, packet,
            binding=SyntheticTransportBinding("TEST_DESTINATION_LOCAL_PPOS_001", "TEST_API_VERSION_V1", "https://cdn.example.com/a.png"),
            credentials=creds,
        )


def test_cp54_retry_classifier_is_static_synthetic_only():
    assert classify_synthetic_response(200) == RETRY_SUCCESS
    assert classify_synthetic_response(429) == RETRY_RATE_LIMIT
    assert classify_synthetic_response(408) == RETRY_TRANSIENT
    assert classify_synthetic_response(503) == RETRY_TRANSIENT
    assert classify_synthetic_response(401) == NO_RETRY_AUTH
    assert classify_synthetic_response(422) == NO_RETRY_CLIENT
    assert classify_synthetic_response(399) == HOLD_UNKNOWN
    with pytest.raises(MetaTransportTwinHold, match="HOLD_TWIN_SYNTHETIC_STATUS_INVALID"):
        classify_synthetic_response(99)


def test_cp54_local_idempotency_and_internal_signature_are_stable(tmp_path):
    plan, preflight, packet = make_lineage(tmp_path, "THREADS", TEXT)
    kwargs = dict(binding=synthetic_binding(TEXT), credentials=synthetic_credentials(plan.auth_reference_kind))
    first = compile_transport_test_twin(plan, preflight, packet, **kwargs)
    retry = compile_transport_test_twin(plan, preflight, packet, **kwargs)
    assert [r.idempotency_key for r in first.requests] == [r.idempotency_key for r in retry.requests]
    assert [r.internal_signature_sha256 for r in first.requests] == [r.internal_signature_sha256 for r in retry.requests]
    assert all(r.wire_idempotency_header_included is False for r in retry.requests)


def test_cp54_receipt_tampering_fails_closed(tmp_path):
    plan, preflight, packet = make_lineage(tmp_path, "FACEBOOK_PAGE", TEXT)
    receipt = compile_transport_test_twin(
        plan, preflight, packet,
        binding=synthetic_binding(TEXT),
        credentials=synthetic_credentials(plan.auth_reference_kind),
    )
    tampered = replace(receipt, requests=(replace(receipt.requests[0], wire_signature_header_included=True),))
    with pytest.raises(MetaTransportTwinHold, match="HOLD_TWIN_WIRE_AUTHORITY_FORBIDDEN"):
        validate_transport_twin_receipt(tampered)


def test_cp54_policy_registry_priority_and_runtime_remain_fail_closed():
    policy = json.loads((ROOT / "config" / "meta_transport_twin_policy.json").read_text(encoding="utf-8"))
    registry = json.loads((ROOT / "config" / "module_registry.json").read_text(encoding="utf-8"))
    priority = json.loads((ROOT / "config" / "reimplementation_priority.json").read_text(encoding="utf-8"))
    runtime = json.loads((ROOT / "config" / "runtime_policy.json").read_text(encoding="utf-8"))

    assert policy["checkpoint"] == "CP54"
    assert tuple(policy["active_platforms"]) == ("FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS")
    contract = policy["transport_twin_contract"]
    assert contract["synthetic_credentials_only"] is True
    assert contract["production_signing_semantics_asserted"] is False
    assert contract["request_signature_sent_on_wire"] is False
    assert contract["production_idempotency_semantics_asserted"] is False
    assert contract["wire_idempotency_header_allowed"] is False
    assert contract["live_transport_ready"] is False
    assert contract["pilot_publish_ready"] is False
    assert all(value is False for value in policy["authority"].values())

    assert registry["checkpoint"] == "CP54"
    assert any(
        row["id"] == "M23_META_TRANSPORT_TWIN" and row["status"] == "CP54_SYNTHETIC_TRANSPORT_TEST_TWIN_ONLY"
        for row in registry["modules"]
    )
    assert priority["checkpoint"] == "CP54"
    assert priority["next"] == "CP55_META_READ_ONLY_CONNECTION_GATE_CONTRACT_AND_KILL_SWITCH_INTERLOCK"
    assert runtime["global_kill_switch_engaged"] is True
    assert runtime["network_enabled"] is False
    assert runtime["real_accounts_connected"] is False
    assert runtime["publish_enabled"] is False
    assert runtime["deploy_enabled"] is False


def test_cp54_source_contains_no_network_or_secret_resolution_implementation():
    import public_presence_os.meta_transport_twin as module

    src = inspect.getsource(module)
    forbidden_import_roots = ("requests", "httpx", "aiohttp", "urllib.request", "http.client", "socket")
    for package in forbidden_import_roots:
        pattern = rf"^\s*(?:from\s+{re.escape(package)}(?:\.|\s)|import\s+{re.escape(package)}(?:\.|\s|$))"
        assert not re.search(pattern, src, re.I | re.M)
    for forbidden_literal in ("os.environ", "os.getenv", "keyring", "subprocess"):
        assert forbidden_literal not in src
    for forbidden_function in (
        "resolve_secret(", "read_secret(", "refresh_token(", "oauth_exchange(",
        "execute_http(", "publish_live(", "connect_account(",
    ):
        assert forbidden_function not in src
