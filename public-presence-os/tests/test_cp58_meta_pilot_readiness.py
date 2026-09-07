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
from public_presence_os.meta_live_read_only_probe import compile_live_read_only_probe_contract
from public_presence_os.meta_offline_evidence import compile_offline_evidence_bundle
from public_presence_os.meta_pilot_readiness import (
    AUTHORIZATION_STATE,
    LINEAGE_CODES,
    REQUIRED_BLOCKERS,
    STATE,
    MetaPilotReadinessHold,
    compile_meta_pilot_readiness,
    render_meta_pilot_readiness_json,
    validate_meta_pilot_readiness_receipt,
)
from public_presence_os.meta_read_only_gate import REQUIRED_FUTURE_EVIDENCE, compile_meta_read_only_gate
from public_presence_os.meta_transport_twin import (
    SyntheticCredentialEnvelope,
    SyntheticTransportBinding,
    compile_transport_test_twin,
)
from public_presence_os.operator_provisioning import compile_operator_provisioning_packet

ROOT = Path(__file__).resolve().parents[1]


def h(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def load(name: str) -> dict:
    return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))


def bound_evidence(platform: str, mode: str) -> OfflineCapabilityEvidence:
    contract = static_capability_contract(platform, mode)
    return OfflineCapabilityEvidence(
        state="OFFLINE_EVIDENCE_BOUND",
        evidence_artifact_sha256=h(f"cp58-evidence:{platform}:{mode}"),
        observed_permissions=contract["required_permissions"],
        observed_capabilities=contract["required_capabilities"],
        expiry_state="KNOWN",
        expires_at_utc="2026-12-31T23:59:59Z",
    )


def make_plan(platform: str, mode: str):
    kwargs = dict(
        source_binding_hash=h(f"cp58-source:{platform}:{mode}"),
        platform=platform,
        mode=mode,
        text="Synthetic CP58 readiness aggregation only.",
    )
    if mode == SINGLE_IMAGE:
        kwargs.update(
            media_asset_sha256=h(f"cp58-media:{platform}"),
            alt_text="Synthetic CP58 image used only for local readiness aggregation.",
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
    vault = SecretReferenceVault(tmp_path / f"cp58-{platform.lower()}-{mode.lower()}.sqlite3")
    vault_receipt = vault.stage(
        profile,
        request_id=f"cp58-vault-{platform.lower()}-{mode.lower()}",
        event_time_utc="2026-09-07T00:30:00Z",
    )
    preflight = compile_synthetic_preflight(
        plan,
        profile,
        vault=vault,
        vault_receipt=vault_receipt,
        request_id=f"cp58-preflight-{platform.lower()}-{mode.lower()}",
        event_time_utc="2026-09-07T00:31:00Z",
    )
    packet = compile_operator_provisioning_packet(preflight, profile)
    binding = SyntheticTransportBinding(
        destination_id="TEST_DESTINATION_LOCAL_PPOS_001",
        api_version="TEST_API_VERSION_V1",
        staging_url="https://example.invalid/ppos/cp58/image.png" if mode == SINGLE_IMAGE else None,
    )
    credentials = SyntheticCredentialEnvelope(
        auth_reference_kind=plan.auth_reference_kind,
        bearer_token="TEST_ONLY_TOKEN_LOCAL_PPOS_ABCDEF123456",
        signing_secret="TEST_ONLY_SIGNING_SECRET_LOCAL_PPOS_ABCDEF123456",
    )
    twin = compile_transport_test_twin(
        plan,
        preflight,
        packet,
        binding=binding,
        credentials=credentials,
    )
    gate = compile_meta_read_only_gate(twin, load("runtime_policy.json"))
    contract = compile_live_read_only_probe_contract(gate, load("meta_live_read_only_probe_policy.json"))
    bundle = compile_offline_evidence_bundle(
        contract,
        load("meta_offline_evidence_validator_policy.json"),
        operator_timestamp_utc="2026-09-07T00:32:00Z",
    )
    return plan, profile, preflight, packet, twin, gate, contract, bundle


def compile_readiness(tmp_path, platform: str, mode: str):
    lineage = make_lineage(tmp_path, platform, mode)
    return lineage, compile_meta_pilot_readiness(*lineage, load("meta_pilot_readiness_policy.json"))


@pytest.mark.parametrize(
    ("platform", "mode"),
    [
        ("FACEBOOK_PAGE", TEXT),
        ("INSTAGRAM_PROFESSIONAL", SINGLE_IMAGE),
        ("THREADS", TEXT),
    ],
)
def test_cp58_active_lanes_aggregate_exact_cp50_cp57_lineage_and_hold_live_authority(tmp_path, platform, mode):
    lineage, receipt = compile_readiness(tmp_path, platform, mode)
    plan, profile, preflight, packet, twin, gate, contract, bundle = lineage

    assert receipt.state == STATE
    assert receipt.authorization_state == AUTHORIZATION_STATE
    assert receipt.platform == platform
    assert receipt.mode == mode
    assert tuple(item.checkpoint for item in receipt.lineage) == LINEAGE_CODES
    assert tuple(item.artifact_hash for item in receipt.lineage) == (
        plan.plan_hash,
        profile.profile_hash,
        preflight.receipt_hash,
        packet.packet_hash,
        twin.twin_hash,
        gate.gate_hash,
        contract.contract_hash,
        bundle.bundle_hash,
    )
    assert receipt.blockers == REQUIRED_BLOCKERS
    assert receipt.required_live_evidence_codes == REQUIRED_FUTURE_EVIDENCE
    assert receipt.global_kill_switch_engaged is True
    assert receipt.exact_lineage_validated is True
    assert receipt.offline_meta_path_validated is True
    assert receipt.synthetic_operator_dry_run_validated is True

    for flag in (
        "live_evidence_captured", "live_entitlement_verified", "live_permission_capability_verified",
        "live_api_version_destination_bound", "secret_reference_resolved", "environment_read", "keychain_read",
        "oauth_attempted", "real_account_lookup_attempted", "account_connected", "network_attempted",
        "publish_attempted", "external_write_performed", "deploy_performed", "live_connection_authorized",
        "final_pilot_authorization_present", "pilot_publish_ready",
    ):
        assert getattr(receipt, flag) is False


def test_cp58_is_deterministic_for_same_exact_lineage(tmp_path):
    lineage = make_lineage(tmp_path, "THREADS", TEXT)
    policy = load("meta_pilot_readiness_policy.json")
    first = compile_meta_pilot_readiness(*lineage, policy)
    second = compile_meta_pilot_readiness(*lineage, policy)
    assert first == second
    assert first.readiness_hash == second.readiness_hash
    assert first.readiness_id == second.readiness_id


def test_cp58_rejects_cross_lane_or_cross_receipt_lineage(tmp_path):
    fb = make_lineage(tmp_path / "fb", "FACEBOOK_PAGE", TEXT)
    threads = make_lineage(tmp_path / "threads", "THREADS", TEXT)
    mixed = (threads[0],) + fb[1:]
    with pytest.raises(MetaPilotReadinessHold):
        compile_meta_pilot_readiness(*mixed, load("meta_pilot_readiness_policy.json"))


def test_cp58_receipt_tampering_cannot_grant_live_connection_or_publish_authority(tmp_path):
    _, receipt = compile_readiness(tmp_path, "FACEBOOK_PAGE", TEXT)

    with pytest.raises(MetaPilotReadinessHold, match="HOLD_CP58_RECEIPT_EXTERNAL_OR_LIVE_AUTHORITY_FORBIDDEN"):
        validate_meta_pilot_readiness_receipt(replace(receipt, live_connection_authorized=True))
    with pytest.raises(MetaPilotReadinessHold, match="HOLD_CP58_RECEIPT_EXTERNAL_OR_LIVE_AUTHORITY_FORBIDDEN"):
        validate_meta_pilot_readiness_receipt(replace(receipt, pilot_publish_ready=True))
    with pytest.raises(MetaPilotReadinessHold, match="HOLD_CP58_RECEIPT_EXTERNAL_OR_LIVE_AUTHORITY_FORBIDDEN"):
        validate_meta_pilot_readiness_receipt(replace(receipt, network_attempted=True))


def test_cp58_rendered_receipt_is_hash_bound_and_contains_no_secret_locator(tmp_path):
    _, receipt = compile_readiness(tmp_path, "INSTAGRAM_PROFESSIONAL", SINGLE_IMAGE)
    rendered = render_meta_pilot_readiness_json(receipt)
    data = json.loads(rendered)
    assert data["readiness_hash"] == receipt.readiness_hash
    assert data["authorization_state"] == AUTHORIZATION_STATE
    assert data["network_attempted"] is False
    assert data["live_connection_authorized"] is False
    assert data["pilot_publish_ready"] is False
    assert "ENV:PPOS_META_INSTAGRAM_TOKEN" not in rendered
    assert "TEST_ONLY_TOKEN_LOCAL_PPOS_ABCDEF123456" not in rendered
    assert "TEST_ONLY_SIGNING_SECRET_LOCAL_PPOS_ABCDEF123456" not in rendered


def test_cp58_policy_registry_priority_and_runtime_remain_fail_closed():
    policy = load("meta_pilot_readiness_policy.json")
    registry = load("module_registry.json")
    priority = load("reimplementation_priority.json")
    runtime = load("runtime_policy.json")

    assert policy["checkpoint"] == "CP58"
    assert tuple(policy["active_platforms"]) == ("FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS")
    assert tuple(policy["required_lineage"]) == LINEAGE_CODES
    assert tuple(policy["required_blockers"]) == REQUIRED_BLOCKERS
    assert policy["readiness_contract"]["offline_aggregation_only"] is True
    assert policy["readiness_contract"]["live_connection_authorization_default"] == "HOLD"
    assert policy["readiness_contract"]["fresh_explicit_final_authorization_required"] is True
    assert policy["readiness_contract"]["automatic_authorization_forbidden"] is True
    assert policy["readiness_contract"]["self_authorization_forbidden"] is True
    assert policy["readiness_contract"]["pilot_publish_ready"] is False
    assert all(value is False for value in policy["authority"].values())

    assert registry["checkpoint"] == "CP58"
    assert any(
        row["id"] == "M27_META_PILOT_READINESS"
        and row["status"] == "CP58_OFFLINE_READINESS_AGGREGATED_LIVE_CONNECTION_HOLD"
        for row in registry["modules"]
    )
    assert priority["checkpoint"] == "CP58"
    assert priority["next"] == "CP59_PILOT_PACKAGE_COMPLETENESS_MANIFEST_AND_FINAL_OFFLINE_ACCEPTANCE_SUITE"
    assert runtime["global_kill_switch_engaged"] is True
    assert runtime["network_enabled"] is False
    assert runtime["real_accounts_connected"] is False
    assert runtime["publish_enabled"] is False
    assert runtime["deploy_enabled"] is False


def test_cp58_source_contains_no_network_secret_resolution_or_live_authorization_execution():
    import public_presence_os.meta_pilot_readiness as module

    src = inspect.getsource(module)
    forbidden_import_roots = ("requests", "httpx", "aiohttp", "urllib.request", "http.client", "socket")
    for package in forbidden_import_roots:
        pattern = rf"^\s*(?:from\s+{re.escape(package)}(?:\.|\s)|import\s+{re.escape(package)}(?:\.|\s|$))"
        assert not re.search(pattern, src, re.I | re.M)
    for forbidden_literal in ("os.environ", "os.getenv", "keyring", "subprocess"):
        assert forbidden_literal not in src
    for forbidden_function in (
        "resolve_secret(", "read_secret(", "refresh_token(", "oauth_exchange(",
        "execute_http(", "perform_request(", "run_live_probe(", "publish_live(",
        "connect_account(", "authorize_live_connection(", "disengage_kill_switch(",
    ):
        assert forbidden_function not in src
