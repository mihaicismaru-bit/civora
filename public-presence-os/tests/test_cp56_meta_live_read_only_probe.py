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
from public_presence_os.meta_live_read_only_probe import (
    EVIDENCE_REPRESENTATIONS,
    FORBIDDEN_PERSISTED_KEYS,
    PROBE_RUNBOOK_STATE,
    RUNBOOK_MODE,
    RUNBOOK_STEP_CODES,
    MetaLiveReadOnlyProbeHold,
    compile_meta_live_read_only_probe_runbook,
    render_meta_live_read_only_probe_runbook_json,
    validate_meta_live_read_only_probe_runbook_receipt,
)
from public_presence_os.meta_read_only_gate import compile_meta_read_only_gate
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
        evidence_artifact_sha256=h(f"cp56-evidence:{platform}:{mode}"),
        observed_permissions=contract["required_permissions"],
        observed_capabilities=contract["required_capabilities"],
        expiry_state="KNOWN",
        expires_at_utc="2026-12-31T23:59:59Z",
    )


def make_gate(tmp_path, platform: str, mode: str):
    kwargs = dict(
        source_binding_hash=h(f"cp56-source:{platform}:{mode}"),
        platform=platform,
        mode=mode,
        text="Synthetic CP56 runbook contract check only.",
    )
    if mode == SINGLE_IMAGE:
        kwargs.update(
            media_asset_sha256=h(f"cp56-media:{platform}"),
            alt_text="Synthetic image used only for the CP56 local runbook contract test.",
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
    vault = SecretReferenceVault(tmp_path / f"cp56-{platform.lower()}-{mode.lower()}.sqlite3")
    vault_receipt = vault.stage(
        profile,
        request_id=f"cp56-vault-{platform.lower()}-{mode.lower()}",
        event_time_utc="2026-09-06T22:20:00Z",
    )
    preflight = compile_synthetic_preflight(
        plan,
        profile,
        vault=vault,
        vault_receipt=vault_receipt,
        request_id=f"cp56-preflight-{platform.lower()}-{mode.lower()}",
        event_time_utc="2026-09-06T22:21:00Z",
    )
    packet = compile_operator_provisioning_packet(preflight, profile)
    binding = SyntheticTransportBinding(
        destination_id="TEST_DESTINATION_LOCAL_PPOS_056",
        api_version="TEST_API_VERSION_V1",
        staging_url="https://example.invalid/ppos/cp56/image.png" if mode == SINGLE_IMAGE else None,
    )
    credentials = SyntheticCredentialEnvelope(
        auth_reference_kind=plan.auth_reference_kind,
        bearer_token="TEST_ONLY_TOKEN_LOCAL_PPOS_CP56ABCDEF123456",
        signing_secret="TEST_ONLY_SIGNING_SECRET_LOCAL_PPOS_CP56ABCDEF123456",
    )
    twin = compile_transport_test_twin(
        plan,
        preflight,
        packet,
        binding=binding,
        credentials=credentials,
    )
    return compile_meta_read_only_gate(twin, runtime_policy())


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
def test_cp56_active_lane_runbooks_are_deterministic_zero_authority_and_exact_bound(tmp_path, platform, mode):
    gate = make_gate(tmp_path, platform, mode)
    first = compile_meta_live_read_only_probe_runbook(gate, runtime_policy())
    second = compile_meta_live_read_only_probe_runbook(gate, runtime_policy())

    assert first == second
    assert first.state == PROBE_RUNBOOK_STATE
    assert first.runbook_mode == RUNBOOK_MODE
    assert first.gate_id == gate.gate_id
    assert first.gate_hash == gate.gate_hash
    assert first.transport_twin_id == gate.transport_twin_id
    assert first.transport_twin_hash == gate.transport_twin_hash
    assert first.runtime_policy_sha256 == gate.runtime_policy_sha256
    assert first.platform == platform
    assert first.mode == mode
    assert first.read_only_method_allowlist == ("GET",)
    assert first.mutating_methods_forbidden == ("POST", "PUT", "PATCH", "DELETE")
    assert tuple(item.code for item in first.evidence_slots) == tuple(code for code, _ in EVIDENCE_REPRESENTATIONS)
    assert all(item.state == "NOT_CAPTURED" for item in first.evidence_slots)
    assert all(item.raw_value_persistence_allowed is False for item in first.evidence_slots)
    assert tuple(step.code for step in first.steps) == RUNBOOK_STEP_CODES
    assert all(step.may_execute_in_cp56 is False for step in first.steps)
    assert first.redaction.forbidden_persisted_keys == FORBIDDEN_PERSISTED_KEYS
    assert first.redaction.redact_before_hash is True
    assert first.redaction.raw_response_persistence_allowed is False
    assert first.recovery.rollback_target == "CP55"
    assert first.recovery.kill_switch_must_remain_engaged is True
    for flag in (
        "endpoint_materialized", "execution_authorized", "secret_reference_resolved", "environment_read",
        "keychain_read", "oauth_attempted", "network_attempted", "live_response_observed",
        "real_account_lookup_attempted", "account_connected", "publish_attempted",
        "external_write_performed", "deploy_performed", "live_entitlement_verified",
        "live_connection_verified", "pilot_publish_ready",
    ):
        assert getattr(first, flag) is False


def test_cp56_serialized_runbook_persists_schema_not_live_values_or_authority(tmp_path):
    gate = make_gate(tmp_path, "THREADS", TEXT)
    receipt = compile_meta_live_read_only_probe_runbook(gate, runtime_policy())
    payload = json.loads(render_meta_live_read_only_probe_runbook_json(receipt))

    assert payload["runbook_mode"] == "CONTRACT_AND_EVIDENCE_SCHEMA_ONLY_NO_EXECUTION"
    assert payload["execution_authorized"] is False
    assert payload["endpoint_materialized"] is False
    assert payload["network_attempted"] is False
    assert payload["live_response_observed"] is False
    assert payload["live_connection_verified"] is False
    assert payload["pilot_publish_ready"] is False
    assert all(row["state"] == "NOT_CAPTURED" for row in payload["evidence_slots"])
    assert all(row["raw_value_persistence_allowed"] is False for row in payload["evidence_slots"])


def test_cp56_requires_the_exact_runtime_policy_hash_bound_by_cp55(tmp_path):
    gate = make_gate(tmp_path, "FACEBOOK_PAGE", TEXT)
    drift = runtime_policy()
    drift["mode"] = "PRE_PILOT_DRY_RUN_CHANGED"
    with pytest.raises(MetaLiveReadOnlyProbeHold, match="HOLD_PROBE_RUNBOOK_RUNTIME_POLICY_BINDING_MISMATCH"):
        compile_meta_live_read_only_probe_runbook(gate, drift)


def test_cp56_runtime_authority_or_kill_switch_drift_fails_closed(tmp_path):
    gate = make_gate(tmp_path, "THREADS", TEXT)
    for key, value in (
        ("global_kill_switch_engaged", False),
        ("network_enabled", True),
        ("real_accounts_connected", True),
        ("publish_enabled", True),
        ("deploy_enabled", True),
    ):
        drift = runtime_policy()
        drift[key] = value
        with pytest.raises(MetaLiveReadOnlyProbeHold, match="HOLD_PROBE_RUNBOOK_RUNTIME_POLICY_INVALID"):
            compile_meta_live_read_only_probe_runbook(gate, drift)


def test_cp56_receipt_tampering_fails_closed(tmp_path):
    gate = make_gate(tmp_path, "INSTAGRAM_PROFESSIONAL", SINGLE_IMAGE)
    receipt = compile_meta_live_read_only_probe_runbook(gate, runtime_policy())

    with pytest.raises(MetaLiveReadOnlyProbeHold, match="HOLD_PROBE_RUNBOOK_EXTERNAL_AUTHORITY_FORBIDDEN"):
        validate_meta_live_read_only_probe_runbook_receipt(replace(receipt, execution_authorized=True))

    slots = list(receipt.evidence_slots)
    slots[0] = replace(slots[0], state="CAPTURED")
    with pytest.raises(MetaLiveReadOnlyProbeHold, match="HOLD_PROBE_RUNBOOK_EVIDENCE_SCHEMA_DRIFT"):
        validate_meta_live_read_only_probe_runbook_receipt(replace(receipt, evidence_slots=tuple(slots)))

    steps = list(receipt.steps)
    steps[0] = replace(steps[0], may_execute_in_cp56=True)
    with pytest.raises(MetaLiveReadOnlyProbeHold, match="HOLD_PROBE_RUNBOOK_STEP_CONTRACT_DRIFT"):
        validate_meta_live_read_only_probe_runbook_receipt(replace(receipt, steps=tuple(steps)))

    with pytest.raises(MetaLiveReadOnlyProbeHold, match="HOLD_PROBE_RUNBOOK_REDACTION_CONTRACT_DRIFT"):
        validate_meta_live_read_only_probe_runbook_receipt(
            replace(receipt, redaction=replace(receipt.redaction, raw_response_persistence_allowed=True))
        )

    with pytest.raises(MetaLiveReadOnlyProbeHold, match="HOLD_PROBE_RUNBOOK_RECOVERY_CONTRACT_DRIFT"):
        validate_meta_live_read_only_probe_runbook_receipt(
            replace(receipt, recovery=replace(receipt.recovery, kill_switch_must_remain_engaged=False))
        )


def test_cp56_policy_registry_priority_and_runtime_remain_fail_closed():
    policy = json.loads((ROOT / "config" / "meta_live_read_only_probe_policy.json").read_text(encoding="utf-8"))
    registry = json.loads((ROOT / "config" / "module_registry.json").read_text(encoding="utf-8"))
    priority = json.loads((ROOT / "config" / "reimplementation_priority.json").read_text(encoding="utf-8"))
    runtime = runtime_policy()

    assert policy["checkpoint"] == "CP56"
    assert tuple(policy["active_platforms"]) == ("FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS")
    contract = policy["runbook_contract"]
    assert contract["contract_only"] is True
    assert contract["exact_cp55_gate_binding_required"] is True
    assert contract["global_kill_switch_must_be_engaged"] is True
    assert contract["execution_authorized"] is False
    assert contract["endpoint_materialization_allowed"] is False
    assert contract["secret_resolution_allowed"] is False
    assert contract["network_allowed"] is False
    assert contract["read_only_method_allowlist"] == ["GET"]
    assert contract["mutating_methods_forbidden"] == ["POST", "PUT", "PATCH", "DELETE"]
    assert contract["pilot_publish_ready"] is False
    assert all(row["state"] == "NOT_CAPTURED" for row in policy["evidence_schema"])
    assert all(row["raw_value_persistence_allowed"] is False for row in policy["evidence_schema"])
    assert all(value is False for value in policy["authority"].values())

    assert registry["checkpoint"] == "CP56"
    assert any(
        row["id"] == "M25_META_LIVE_READ_ONLY_PROBE_RUNBOOK"
        and row["status"] == "CP56_LIVE_READ_ONLY_PROBE_RUNBOOK_CONTRACT_LOCAL_ONLY"
        for row in registry["modules"]
    )
    assert priority["checkpoint"] == "CP56"
    assert priority["next"] == "CP57_META_READ_ONLY_EVIDENCE_VALIDATOR_AND_SYNTHETIC_FIXTURE_PACK"
    assert runtime["global_kill_switch_engaged"] is True
    assert runtime["network_enabled"] is False
    assert runtime["real_accounts_connected"] is False
    assert runtime["publish_enabled"] is False
    assert runtime["deploy_enabled"] is False


def test_cp56_source_contains_no_network_secret_resolution_or_execution_path():
    import public_presence_os.meta_live_read_only_probe as module

    src = inspect.getsource(module)
    forbidden_import_roots = ("requests", "httpx", "aiohttp", "urllib.request", "http.client", "socket")
    for package in forbidden_import_roots:
        pattern = rf"^\s*(?:from\s+{re.escape(package)}(?:\.|\s)|import\s+{re.escape(package)}(?:\.|\s|$))"
        assert not re.search(pattern, src, re.I | re.M)
    for forbidden_literal in ("os.environ", "os.getenv", "keyring", "subprocess"):
        assert forbidden_literal not in src
    for forbidden_function in (
        "resolve_secret(", "read_secret(", "refresh_token(", "oauth_exchange(",
        "execute_http(", "publish_live(", "connect_account(", "http_get(",
        "disengage_kill_switch(", "unlock_kill_switch(",
    ):
        assert forbidden_function not in src
