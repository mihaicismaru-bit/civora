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
from public_presence_os.meta_read_only_gate import (
    REQUIRED_FUTURE_EVIDENCE,
    MetaReadOnlyGateHold,
    compile_meta_read_only_gate,
    render_meta_read_only_gate_json,
    validate_meta_read_only_gate_receipt,
)
from public_presence_os.meta_transport_twin import (
    SyntheticCredentialEnvelope,
    SyntheticTransportBinding,
    compile_transport_test_twin,
)
from public_presence_os.operator_provisioning import compile_operator_provisioning_packet

ROOT = Path(__file__).resolve().parents[1]


def h(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def runtime_policy() -> dict:
    return json.loads((ROOT / "config" / "runtime_policy.json").read_text(encoding="utf-8"))


def bound_evidence(platform: str, mode: str) -> OfflineCapabilityEvidence:
    contract = static_capability_contract(platform, mode)
    return OfflineCapabilityEvidence(
        state="OFFLINE_EVIDENCE_BOUND",
        evidence_artifact_sha256=h(f"cp55-evidence:{platform}:{mode}"),
        observed_permissions=contract["required_permissions"],
        observed_capabilities=contract["required_capabilities"],
        expiry_state="KNOWN",
        expires_at_utc="2026-12-31T23:59:59Z",
    )


def make_twin(tmp_path, platform: str, mode: str):
    kwargs = dict(
        source_binding_hash=h(f"cp55-source:{platform}:{mode}"),
        platform=platform,
        mode=mode,
        text="Synthetic CP55 read-only gate contract check only.",
    )
    if mode == SINGLE_IMAGE:
        kwargs.update(
            media_asset_sha256=h(f"cp55-media:{platform}"),
            alt_text="Synthetic image used only for the CP55 offline gate contract.",
            staging_url_ref=STAGING_URL_REF,
        )
    plan = compile_offline_request(OfflinePublishIntent(**kwargs))
    locator = {
        "FACEBOOK_PAGE": "ENV:PPOS_META_FB_PAGE_TOKEN",
        "INSTAGRAM_PROFESSIONAL": "ENV:PPOS_META_INSTAGRAM_TOKEN",
        "THREADS": "OS_KEYCHAIN:ppos/meta/threads",
    }[platform]
    profile = compile_connection_profile(ConnectionProfileSpec(
        platform,
        mode,
        locator,
        evidence=bound_evidence(platform, mode),
    ))
    vault = SecretReferenceVault(tmp_path / f"cp55-{platform.lower()}-{mode.lower()}.sqlite3")
    vault_receipt = vault.stage(
        profile,
        request_id=f"cp55-vault-{platform.lower()}-{mode.lower()}",
        event_time_utc="2026-09-06T21:50:00Z",
    )
    preflight = compile_synthetic_preflight(
        plan,
        profile,
        vault=vault,
        vault_receipt=vault_receipt,
        request_id=f"cp55-preflight-{platform.lower()}-{mode.lower()}",
        event_time_utc="2026-09-06T21:51:00Z",
    )
    packet = compile_operator_provisioning_packet(preflight, profile)
    binding = SyntheticTransportBinding(
        destination_id="TEST_DESTINATION_LOCAL_PPOS_055",
        api_version="TEST_API_VERSION_V1",
        staging_url="https://example.invalid/ppos/cp55/image.png" if mode == SINGLE_IMAGE else None,
    )
    credentials = SyntheticCredentialEnvelope(
        auth_reference_kind=plan.auth_reference_kind,
        bearer_token="TEST_ONLY_TOKEN_LOCAL_PPOS_CP55ABCDEF123456",
        signing_secret="TEST_ONLY_SIGNING_SECRET_LOCAL_PPOS_CP55ABCDEF123456",
    )
    return compile_transport_test_twin(
        plan,
        preflight,
        packet,
        binding=binding,
        credentials=credentials,
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
def test_cp55_active_lane_gate_receipts_are_deterministic_and_zero_authority(tmp_path, platform, mode):
    twin = make_twin(tmp_path, platform, mode)
    first = compile_meta_read_only_gate(twin, runtime_policy())
    second = compile_meta_read_only_gate(twin, runtime_policy())

    assert first == second
    assert first.state == "PASS_READ_ONLY_GATE_CONTRACT_LOCAL_ONLY"
    assert first.transport_twin_id == twin.twin_id
    assert first.transport_twin_hash == twin.twin_hash
    assert first.platform == platform
    assert first.mode == mode
    assert first.read_only_method_allowlist == ("GET",)
    assert first.mutating_methods_forbidden == ("POST", "PUT", "PATCH", "DELETE")
    assert first.probe_mode == "CONTRACT_ONLY_NO_NETWORK"
    assert first.kill_switch.required is True
    assert first.kill_switch.engaged is True
    assert first.kill_switch.automatic_disengage_allowed is False
    assert first.kill_switch.operator_override_allowed is False
    assert tuple(item.code for item in first.evidence_requirements) == REQUIRED_FUTURE_EVIDENCE
    assert all(item.state == "NOT_CAPTURED" for item in first.evidence_requirements)
    for flag in (
        "live_endpoint_materialized", "live_probe_authorized", "secret_reference_resolved",
        "environment_read", "keychain_read", "oauth_attempted", "real_account_lookup_attempted",
        "account_connected", "network_attempted", "publish_attempted", "external_write_performed",
        "deploy_performed", "live_entitlement_verified", "live_connection_verified", "pilot_publish_ready",
    ):
        assert getattr(first, flag) is False


def test_cp55_serialized_receipt_never_pretends_live_evidence(tmp_path):
    receipt = compile_meta_read_only_gate(make_twin(tmp_path, "THREADS", TEXT), runtime_policy())
    payload = json.loads(render_meta_read_only_gate_json(receipt))
    assert payload["probe_mode"] == "CONTRACT_ONLY_NO_NETWORK"
    assert payload["live_probe_authorized"] is False
    assert payload["network_attempted"] is False
    assert payload["account_connected"] is False
    assert payload["live_connection_verified"] is False
    assert payload["pilot_publish_ready"] is False
    assert all(row["state"] == "NOT_CAPTURED" for row in payload["evidence_requirements"])


def test_cp55_runtime_kill_switch_and_external_authority_are_hard_interlocks(tmp_path):
    twin = make_twin(tmp_path, "FACEBOOK_PAGE", TEXT)
    drift = runtime_policy()
    drift["global_kill_switch_engaged"] = False
    with pytest.raises(MetaReadOnlyGateHold, match="HOLD_READ_ONLY_GATE_RUNTIME_POLICY_INVALID"):
        compile_meta_read_only_gate(twin, drift)

    for key in ("network_enabled", "real_accounts_connected", "account_connection_enabled", "publish_enabled"):
        drift = runtime_policy()
        drift[key] = True
        with pytest.raises(MetaReadOnlyGateHold, match="HOLD_READ_ONLY_GATE_RUNTIME_POLICY_INVALID"):
            compile_meta_read_only_gate(twin, drift)


def test_cp55_receipt_tampering_fails_closed(tmp_path):
    receipt = compile_meta_read_only_gate(
        make_twin(tmp_path, "INSTAGRAM_PROFESSIONAL", SINGLE_IMAGE),
        runtime_policy(),
    )
    with pytest.raises(MetaReadOnlyGateHold, match="HOLD_READ_ONLY_GATE_EXTERNAL_AUTHORITY_FORBIDDEN"):
        validate_meta_read_only_gate_receipt(replace(receipt, live_probe_authorized=True))
    with pytest.raises(MetaReadOnlyGateHold, match="HOLD_READ_ONLY_GATE_KILL_SWITCH_INTERLOCK_DRIFT"):
        validate_meta_read_only_gate_receipt(replace(receipt, kill_switch=replace(receipt.kill_switch, engaged=False)))
    rows = list(receipt.evidence_requirements)
    rows[0] = replace(rows[0], state="CAPTURED")
    with pytest.raises(MetaReadOnlyGateHold, match="HOLD_READ_ONLY_GATE_PRETENDED_LIVE_EVIDENCE"):
        validate_meta_read_only_gate_receipt(replace(receipt, evidence_requirements=tuple(rows)))


def test_cp55_policy_registry_priority_and_runtime_remain_fail_closed():
    policy = json.loads((ROOT / "config" / "meta_read_only_gate_policy.json").read_text(encoding="utf-8"))
    registry = json.loads((ROOT / "config" / "module_registry.json").read_text(encoding="utf-8"))
    priority = json.loads((ROOT / "config" / "reimplementation_priority.json").read_text(encoding="utf-8"))
    runtime = runtime_policy()

    assert policy["checkpoint"] == "CP55"
    assert tuple(policy["active_platforms"]) == ("FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS")
    contract = policy["gate_contract"]
    assert contract["contract_only"] is True
    assert contract["global_kill_switch_must_be_engaged"] is True
    assert contract["read_only_method_allowlist"] == ["GET"]
    assert contract["mutating_methods_forbidden"] == ["POST", "PUT", "PATCH", "DELETE"]
    assert policy["required_future_evidence"] == list(REQUIRED_FUTURE_EVIDENCE)
    assert all(value is False for value in policy["authority"].values())

    assert registry["checkpoint"] == "CP57"
    assert any(
        row["id"] == "M24_META_READ_ONLY_GATE" and row["status"] == "CP55_READ_ONLY_CONNECTION_GATE_CONTRACT_LOCAL_ONLY"
        for row in registry["modules"]
    )
    assert any(
        row["id"] == "M25_META_LIVE_READ_ONLY_PROBE" and row["status"] == "CP56_RUNBOOK_EVIDENCE_CAPTURE_CONTRACT_LOCAL_ONLY"
        for row in registry["modules"]
    )
    assert priority["checkpoint"] == "CP57"
    assert priority["next"] == "CP58_META_PILOT_READINESS_AGGREGATOR_AND_LIVE_CONNECTION_AUTHORIZATION_GATE"
    assert runtime["global_kill_switch_engaged"] is True
    assert runtime["network_enabled"] is False
    assert runtime["real_accounts_connected"] is False
    assert runtime["publish_enabled"] is False
    assert runtime["deploy_enabled"] is False


def test_cp55_source_contains_no_network_secret_resolution_or_kill_switch_unlock():
    import public_presence_os.meta_read_only_gate as module

    src = inspect.getsource(module)
    forbidden_import_roots = ("requests", "httpx", "aiohttp", "urllib.request", "http.client", "socket")
    for package in forbidden_import_roots:
        pattern = rf"^\s*(?:from\s+{re.escape(package)}(?:\.|\s)|import\s+{re.escape(package)}(?:\.|\s|$))"
        assert not re.search(pattern, src, re.I | re.M)
    for forbidden_literal in ("os.environ", "os.getenv", "keyring", "subprocess"):
        assert forbidden_literal not in src
    for forbidden_function in (
        "resolve_secret(", "read_secret(", "refresh_token(", "oauth_exchange(",
        "execute_http(", "publish_live(", "connect_account(", "disengage_kill_switch(",
        "unlock_kill_switch(",
    ):
        assert forbidden_function not in src
