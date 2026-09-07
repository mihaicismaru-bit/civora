from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import inspect
import json
from pathlib import Path

import pytest

from public_presence_os.connection_profiles import (
    ConnectionProfileHold,
    ConnectionProfileSpec,
    OfflineCapabilityEvidence,
    SecretReferenceVault,
    compile_connection_profile,
    parse_secret_reference,
    validate_connection_profile,
)

ROOT = Path(__file__).resolve().parents[1]


def h(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def bound_evidence(platform: str, mode: str) -> OfflineCapabilityEvidence:
    contracts = {
        ("FACEBOOK_PAGE", "TEXT"): (
            ("pages_show_list", "pages_read_engagement", "pages_manage_posts"),
            ("publish_text",),
        ),
        ("FACEBOOK_PAGE", "SINGLE_IMAGE"): (
            ("pages_show_list", "pages_read_engagement", "pages_manage_posts"),
            ("publish_single_image",),
        ),
        ("INSTAGRAM_PROFESSIONAL", "SINGLE_IMAGE"): (
            ("instagram_business_basic", "instagram_business_content_publish"),
            ("publish_single_image",),
        ),
        ("THREADS", "TEXT"): (
            ("threads_basic", "threads_content_publish"),
            ("publish_text",),
        ),
        ("THREADS", "SINGLE_IMAGE"): (
            ("threads_basic", "threads_content_publish"),
            ("publish_single_image",),
        ),
    }
    permissions, capabilities = contracts[(platform, mode)]
    return OfflineCapabilityEvidence(
        state="OFFLINE_EVIDENCE_BOUND",
        evidence_artifact_sha256=h(f"synthetic-evidence:{platform}:{mode}"),
        observed_permissions=permissions,
        observed_capabilities=capabilities,
        expiry_state="KNOWN",
        expires_at_utc="2026-12-31T23:59:59Z",
    )


def test_cp51_secret_reference_parser_accepts_only_env_or_os_keychain():
    env = parse_secret_reference("ENV:PPOS_META_FB_PAGE_TOKEN")
    keychain = parse_secret_reference("OS_KEYCHAIN:ppos/meta/threads")
    assert env.scheme == "ENV" and env.locator == "PPOS_META_FB_PAGE_TOKEN"
    assert keychain.scheme == "OS_KEYCHAIN" and keychain.locator == "ppos/meta/threads"
    for bad in (
        "TOKEN:literal",
        "FILE:/tmp/token",
        "ENV:lowercase",
        "ENV:NAME=value",
        "OS_KEYCHAIN:https://example.invalid/secret",
    ):
        with pytest.raises(ConnectionProfileHold):
            parse_secret_reference(bad)


def test_cp51_unverified_profile_is_deterministic_and_never_live_ready():
    spec = ConnectionProfileSpec("FACEBOOK_PAGE", "TEXT", "ENV:PPOS_META_FB_PAGE_TOKEN")
    first = compile_connection_profile(spec)
    second = compile_connection_profile(spec)
    assert first == second
    assert first.profile_hash == second.profile_hash
    assert first.auth_reference_kind == "PAGE_ACCESS_TOKEN_REF"
    assert first.required_permissions == ("pages_show_list", "pages_read_engagement", "pages_manage_posts")
    assert first.required_capabilities == ("publish_text",)
    assert first.offline_contract_evidence_complete is False
    assert first.real_entitlement_asserted is False
    assert first.secret_resolution_allowed is False
    assert first.environment_read_allowed is False
    assert first.keychain_read_allowed is False
    assert first.network_allowed is False
    assert first.account_connection_allowed is False
    assert first.publish_execution_allowed is False
    assert first.state == "STAGED_SECRET_REFERENCE_ONLY"


def test_cp51_bound_offline_evidence_is_exact_contract_bound_but_not_entitlement():
    profile = compile_connection_profile(ConnectionProfileSpec(
        "THREADS",
        "SINGLE_IMAGE",
        "OS_KEYCHAIN:ppos/meta/threads",
        evidence=bound_evidence("THREADS", "SINGLE_IMAGE"),
    ))
    assert profile.offline_contract_evidence_complete is True
    assert profile.evidence.evidence_artifact_sha256 == h("synthetic-evidence:THREADS:SINGLE_IMAGE")
    assert profile.evidence.expiry_state == "KNOWN"
    assert profile.evidence.expires_at_utc == "2026-12-31T23:59:59Z"
    assert profile.real_entitlement_asserted is False
    assert profile.live_reverification_required is True


def test_cp51_evidence_permission_capability_or_expiry_drift_fails_closed():
    wrong_permission = replace(
        bound_evidence("FACEBOOK_PAGE", "TEXT"),
        observed_permissions=("pages_show_list",),
    )
    with pytest.raises(ConnectionProfileHold, match="HOLD_CONNECTION_PERMISSION_EVIDENCE_MISMATCH"):
        compile_connection_profile(ConnectionProfileSpec(
            "FACEBOOK_PAGE", "TEXT", "ENV:PPOS_META_FB_PAGE_TOKEN", evidence=wrong_permission
        ))

    wrong_capability = replace(
        bound_evidence("THREADS", "TEXT"),
        observed_capabilities=("publish_single_image",),
    )
    with pytest.raises(ConnectionProfileHold, match="HOLD_CONNECTION_CAPABILITY_EVIDENCE_MISMATCH"):
        compile_connection_profile(ConnectionProfileSpec(
            "THREADS", "TEXT", "ENV:PPOS_META_THREADS_TOKEN", evidence=wrong_capability
        ))

    bad_expiry = replace(bound_evidence("THREADS", "TEXT"), expires_at_utc="2026-12-31")
    with pytest.raises(ConnectionProfileHold, match="HOLD_CONNECTION_EVIDENCE_EXPIRY_FORMAT"):
        compile_connection_profile(ConnectionProfileSpec(
            "THREADS", "TEXT", "ENV:PPOS_META_THREADS_TOKEN", evidence=bad_expiry
        ))


def test_cp51_unverified_evidence_cannot_smuggle_observed_entitlements():
    evidence = OfflineCapabilityEvidence(
        state="STAGED_UNVERIFIED",
        observed_permissions=("threads_basic", "threads_content_publish"),
    )
    with pytest.raises(ConnectionProfileHold, match="HOLD_CONNECTION_UNVERIFIED_EVIDENCE_MUST_BE_EMPTY"):
        compile_connection_profile(ConnectionProfileSpec(
            "THREADS", "TEXT", "ENV:PPOS_META_THREADS_TOKEN", evidence=evidence
        ))


@pytest.mark.parametrize("platform", ["LINKEDIN", "X", "BLUESKY"])
def test_cp51_deferred_lanes_are_structurally_rejected(platform):
    with pytest.raises(ConnectionProfileHold, match="HOLD_CONNECTION_PLATFORM_NOT_ACTIVE"):
        compile_connection_profile(ConnectionProfileSpec(platform, "TEXT", "ENV:PPOS_META_DEFERRED_TOKEN"))


def test_cp51_real_destination_and_literal_api_version_remain_forbidden():
    with pytest.raises(ConnectionProfileHold, match="HOLD_CONNECTION_REAL_DESTINATION_FORBIDDEN"):
        compile_connection_profile(ConnectionProfileSpec(
            "FACEBOOK_PAGE", "TEXT", "ENV:PPOS_META_FB_PAGE_TOKEN", destination_ref="123456"
        ))
    with pytest.raises(ConnectionProfileHold, match="HOLD_CONNECTION_LITERAL_API_VERSION_FORBIDDEN"):
        compile_connection_profile(ConnectionProfileSpec(
            "FACEBOOK_PAGE", "TEXT", "ENV:PPOS_META_FB_PAGE_TOKEN", api_version_ref="v99.0"
        ))


def test_cp51_profile_tamper_fails_exact_hash_validation():
    profile = compile_connection_profile(ConnectionProfileSpec(
        "INSTAGRAM_PROFESSIONAL",
        "SINGLE_IMAGE",
        "ENV:PPOS_META_INSTAGRAM_TOKEN",
        evidence=bound_evidence("INSTAGRAM_PROFESSIONAL", "SINGLE_IMAGE"),
    ))
    with pytest.raises(ConnectionProfileHold, match="HOLD_CONNECTION_PROFILE_HASH_MISMATCH"):
        validate_connection_profile(replace(profile, secret_reference="ENV:PPOS_META_INSTAGRAM_TOKEN_V2"))


def test_cp51_local_vault_is_immutable_append_only_and_idempotent(tmp_path):
    vault = SecretReferenceVault(tmp_path / "connection_refs.sqlite3")
    profile = compile_connection_profile(ConnectionProfileSpec(
        "THREADS", "TEXT", "OS_KEYCHAIN:ppos/meta/threads", evidence=bound_evidence("THREADS", "TEXT")
    ))
    first = vault.stage(profile, request_id="cp51-request-0001", event_time_utc="2026-09-06T20:00:00Z")
    second = vault.stage(profile, request_id="cp51-request-0001", event_time_utc="2026-09-06T20:00:00Z")
    assert first.event_hash == second.event_hash
    assert first.stored_new_profile is True
    assert second.stored_new_profile is False
    assert vault.event_count() == 1
    stored = vault.read_profile(profile.profile_id)
    assert stored["secret_reference"] == "OS_KEYCHAIN:ppos/meta/threads"
    assert stored["secret_resolution_allowed"] is False
    assert stored["network_allowed"] is False
    assert stored["account_connection_allowed"] is False

    with pytest.raises(ConnectionProfileHold, match="HOLD_CONNECTION_IDEMPOTENCY_CONFLICT"):
        vault.stage(profile, request_id="cp51-request-0001", event_time_utc="2026-09-06T20:00:01Z")


def test_cp51_vault_receipt_proves_no_secret_network_or_account_action(tmp_path):
    vault = SecretReferenceVault(tmp_path / "refs.sqlite3")
    profile = compile_connection_profile(ConnectionProfileSpec(
        "FACEBOOK_PAGE", "TEXT", "ENV:PPOS_META_FB_PAGE_TOKEN"
    ))
    receipt = vault.stage(profile, request_id="cp51-request-0002", event_time_utc="2026-09-06T20:01:00Z")
    assert receipt.state == "LOCAL_REFERENCE_STAGED"
    assert receipt.secret_resolved is False
    assert receipt.network_attempted is False
    assert receipt.account_connected is False
    assert receipt.external_write_performed is False


def test_cp51_policy_registry_priority_and_runtime_remain_fail_closed():
    policy = json.loads((ROOT / "config" / "meta_connection_policy.json").read_text(encoding="utf-8"))
    registry = json.loads((ROOT / "config" / "module_registry.json").read_text(encoding="utf-8"))
    priority = json.loads((ROOT / "config" / "reimplementation_priority.json").read_text(encoding="utf-8"))
    runtime = json.loads((ROOT / "config" / "runtime_policy.json").read_text(encoding="utf-8"))

    assert policy["checkpoint"] == "CP51"
    assert tuple(policy["active_platforms"]) == ("FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS")
    assert tuple(policy["allowed_secret_reference_schemes"]) == ("ENV", "OS_KEYCHAIN")
    assert policy["vault"]["backend"] == "LOCAL_SQLITE"
    assert policy["vault"]["stores_secret_material"] is False
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

    assert registry["checkpoint"] == "CP57"
    assert any(
        m["id"] == "M20_META_CONNECTIONS" and m["status"] == "CP51_SECRET_REFERENCE_PROFILE_VAULT_LOCAL_ONLY"
        for m in registry["modules"]
    )
    assert any(
        m["id"] == "M21_META_PREFLIGHT" and m["status"] == "CP52_SYNTHETIC_PROVISIONING_READBACK_LOCAL_ONLY"
        for m in registry["modules"]
    )
    assert any(
        m["id"] == "M22_META_OPERATOR_PROVISIONING" and m["status"] == "CP53_OFFLINE_OPERATOR_PACKET_CHECKLIST"
        for m in registry["modules"]
    )
    assert any(
        m["id"] == "M23_META_TRANSPORT_TWIN" and m["status"] == "CP54_SYNTHETIC_TRANSPORT_TEST_TWIN_ONLY"
        for m in registry["modules"]
    )
    assert any(
        m["id"] == "M24_META_READ_ONLY_GATE" and m["status"] == "CP55_READ_ONLY_CONNECTION_GATE_CONTRACT_LOCAL_ONLY"
        for m in registry["modules"]
    )
    assert any(
        m["id"] == "M25_META_LIVE_READ_ONLY_PROBE" and m["status"] == "CP56_RUNBOOK_EVIDENCE_CAPTURE_CONTRACT_LOCAL_ONLY"
        for m in registry["modules"]
    )
    assert priority["checkpoint"] == "CP57"
    assert priority["next"] == "CP58_META_PILOT_READINESS_AGGREGATOR_AND_LIVE_CONNECTION_AUTHORIZATION_GATE"
    assert runtime["global_kill_switch_engaged"] is True
    assert runtime["network_enabled"] is False
    assert runtime["real_accounts_connected"] is False
    assert runtime["publish_enabled"] is False
    assert runtime["deploy_enabled"] is False


def test_cp51_source_does_not_resolve_env_keychain_or_network():
    import public_presence_os.connection_profiles as module

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
    ):
        assert forbidden_function not in src
