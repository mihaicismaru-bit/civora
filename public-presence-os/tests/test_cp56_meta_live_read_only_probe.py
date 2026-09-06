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
    API_VERSION_PIN_STATE,
    CONTRACT_MODE,
    EVIDENCE_STATE,
    PLATFORM_PROBE_CLASSES,
    PROBE_CONTRACT_STATE,
    ZERO_WRITE_PROOF_STATE,
    MetaLiveReadOnlyProbeHold,
    compile_live_read_only_probe_contract,
    render_live_read_only_probe_contract_json,
    validate_live_read_only_probe_contract,
)
from public_presence_os.meta_read_only_gate import (
    REQUIRED_FUTURE_EVIDENCE,
    compile_meta_read_only_gate,
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


def cp56_policy() -> dict:
    return json.loads((ROOT / "config" / "meta_live_read_only_probe_policy.json").read_text(encoding="utf-8"))


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
            alt_text="Synthetic image used only for the CP56 offline runbook contract.",
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
        event_time_utc="2026-09-06T22:10:00Z",
    )
    preflight = compile_synthetic_preflight(
        plan,
        profile,
        vault=vault,
        vault_receipt=vault_receipt,
        request_id=f"cp56-preflight-{platform.lower()}-{mode.lower()}",
        event_time_utc="2026-09-06T22:11:00Z",
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
def test_cp56_contract_is_deterministic_platform_native_and_zero_authority(tmp_path, platform, mode):
    gate = make_gate(tmp_path, platform, mode)
    first = compile_live_read_only_probe_contract(gate, cp56_policy())
    second = compile_live_read_only_probe_contract(gate, cp56_policy())

    assert first == second
    assert first.state == PROBE_CONTRACT_STATE
    assert first.read_only_gate_id == gate.gate_id
    assert first.read_only_gate_hash == gate.gate_hash
    assert first.platform == platform
    assert first.mode == mode
    assert first.contract_mode == CONTRACT_MODE
    assert first.method_allowlist == ("GET",)
    assert first.mutating_methods_forbidden == ("POST", "PUT", "PATCH", "DELETE")
    assert tuple(step.request_class for step in first.steps) == PLATFORM_PROBE_CLASSES[platform]
    assert tuple(step.order for step in first.steps) == tuple(range(1, len(first.steps) + 1))
    assert all(step.method == "GET" for step in first.steps)
    assert all(step.endpoint_selector == "OPERATOR_VERIFIED_META_DOCUMENTED_ENDPOINT" for step in first.steps)
    assert all(step.endpoint_materialized is False for step in first.steps)
    assert all(step.secret_reference_resolved is False for step in first.steps)
    assert all(step.network_allowed is False for step in first.steps)
    assert all(step.external_write_allowed is False for step in first.steps)
    assert first.api_version_pin_state == API_VERSION_PIN_STATE
    assert first.zero_write_proof_state == ZERO_WRITE_PROOF_STATE
    assert first.global_kill_switch_required_engaged is True
    for flag in (
        "live_endpoint_materialized", "live_probe_authorized", "secret_reference_resolved",
        "environment_read", "keychain_read", "oauth_attempted", "real_account_lookup_attempted",
        "account_connected", "network_attempted", "publish_attempted", "external_write_performed",
        "deploy_performed", "live_entitlement_verified", "live_connection_verified", "pilot_publish_ready",
    ):
        assert getattr(first, flag) is False


def test_cp56_evidence_contract_is_exact_redacted_hash_bound_and_uncaptured(tmp_path):
    gate = make_gate(tmp_path, "THREADS", TEXT)
    receipt = compile_live_read_only_probe_contract(gate, cp56_policy())

    assert tuple(item.code for item in receipt.evidence_contract) == REQUIRED_FUTURE_EVIDENCE
    for item in receipt.evidence_contract:
        assert item.state == EVIDENCE_STATE
        assert item.hash_algorithm == "SHA256"
        assert item.canonicalization_required is True
        assert item.redaction_required is True
        assert item.raw_secret_bytes_allowed is False
        assert item.raw_token_persistence_allowed is False
        assert item.external_upload_allowed is False

    payload = json.loads(render_live_read_only_probe_contract_json(receipt))
    assert all(item["state"] == "NOT_CAPTURED" for item in payload["evidence_contract"])
    assert payload["api_version_pin_state"] == "NOT_CAPTURED"
    assert payload["zero_write_proof_state"] == "NOT_CAPTURED"
    assert payload["network_attempted"] is False
    assert payload["pilot_publish_ready"] is False


def test_cp56_recovery_contract_fails_closed_and_never_auto_retries_live_probe(tmp_path):
    receipt = compile_live_read_only_probe_contract(
        make_gate(tmp_path, "FACEBOOK_PAGE", TEXT),
        cp56_policy(),
    )
    recovery = receipt.recovery
    assert recovery.keep_global_kill_switch_engaged is True
    assert recovery.abort_on_non_get_method is True
    assert recovery.abort_on_endpoint_drift is True
    assert recovery.abort_on_api_version_drift is True
    assert recovery.abort_on_permission_or_identity_mismatch is True
    assert recovery.discard_unredacted_working_material is True
    assert recovery.preserve_only_redacted_hash_bound_evidence is True
    assert recovery.auto_retry_live_probe_allowed is False
    assert recovery.rollback_mutation_required is False


def test_cp56_tampering_with_method_evidence_or_external_authority_fails_closed(tmp_path):
    receipt = compile_live_read_only_probe_contract(
        make_gate(tmp_path, "INSTAGRAM_PROFESSIONAL", SINGLE_IMAGE),
        cp56_policy(),
    )
    steps = list(receipt.steps)
    steps[0] = replace(steps[0], method="POST")
    with pytest.raises(MetaLiveReadOnlyProbeHold, match="HOLD_CP56_PROBE_STEP_EXTERNAL_AUTHORITY"):
        validate_live_read_only_probe_contract(replace(receipt, steps=tuple(steps)))

    evidence = list(receipt.evidence_contract)
    evidence[0] = replace(evidence[0], state="CAPTURED")
    with pytest.raises(MetaLiveReadOnlyProbeHold, match="HOLD_CP56_PRETENDED_LIVE_EVIDENCE"):
        validate_live_read_only_probe_contract(replace(receipt, evidence_contract=tuple(evidence)))

    with pytest.raises(MetaLiveReadOnlyProbeHold, match="HOLD_CP56_EXTERNAL_AUTHORITY_FORBIDDEN"):
        validate_live_read_only_probe_contract(replace(receipt, network_attempted=True))


def test_cp56_policy_registry_priority_and_runtime_are_fail_closed():
    policy = cp56_policy()
    registry = json.loads((ROOT / "config" / "module_registry.json").read_text(encoding="utf-8"))
    priority = json.loads((ROOT / "config" / "reimplementation_priority.json").read_text(encoding="utf-8"))
    runtime = runtime_policy()

    assert policy["checkpoint"] == "CP56"
    assert tuple(policy["active_platforms"]) == ("FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS")
    assert policy["contract"]["runbook_contract_only"] is True
    assert policy["contract"]["method_allowlist"] == ["GET"]
    assert policy["contract"]["mutating_methods_forbidden"] == ["POST", "PUT", "PATCH", "DELETE"]
    assert policy["contract"]["api_version_pin_required_later"] is True
    assert policy["contract"]["api_version_must_be_operator_verified_against_current_official_meta_docs"] is True
    assert policy["contract"]["endpoint_must_be_operator_verified_against_current_official_meta_docs"] is True
    assert policy["contract"]["redaction_before_persistence_required_later"] is True
    assert policy["contract"]["zero_write_proof_required_later"] is True
    assert policy["required_evidence_codes"] == list(REQUIRED_FUTURE_EVIDENCE)
    assert all(value is False for value in policy["authority"].values())

    assert registry["checkpoint"] == "CP56"
    assert any(
        row["id"] == "M25_META_LIVE_READ_ONLY_PROBE"
        and row["status"] == "CP56_RUNBOOK_EVIDENCE_CAPTURE_CONTRACT_LOCAL_ONLY"
        for row in registry["modules"]
    )
    assert priority["checkpoint"] == "CP56"
    assert priority["next"] == "CP57_META_OFFLINE_EVIDENCE_BUNDLE_VALIDATOR_AND_OPERATOR_DRY_RUN"
    assert runtime["global_kill_switch_engaged"] is True
    assert runtime["network_enabled"] is False
    assert runtime["real_accounts_connected"] is False
    assert runtime["publish_enabled"] is False
    assert runtime["deploy_enabled"] is False


def test_cp56_source_contains_no_network_secret_resolution_or_runtime_probe_execution():
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
        "execute_http(", "perform_request(", "run_live_probe(", "publish_live(",
        "connect_account(", "disengage_kill_switch(", "unlock_kill_switch(",
    ):
        assert forbidden_function not in src
