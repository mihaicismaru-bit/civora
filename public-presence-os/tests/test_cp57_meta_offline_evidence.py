from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import inspect
import json
from pathlib import Path
import re

import pytest

from public_presence_os.control import canonical_json
from public_presence_os.meta_live_read_only_probe import (
    CAPTURE_KIND_BY_CODE,
    PLATFORM_PROBE_CLASSES,
    PROBE_CONTRACT_ENGINE_VERSION,
    PROBE_CONTRACT_MODEL_VERSION,
    EvidenceCaptureContract,
    MetaLiveReadOnlyProbeContract,
    ProbeStep,
    RecoveryContract,
    validate_live_read_only_probe_contract,
)
from public_presence_os.meta_offline_evidence import (
    FIXTURE_SCOPE,
    STATE,
    SYNTHETIC_API_VERSION,
    SYNTHETIC_ENDPOINT_SELECTOR,
    MetaOfflineEvidenceHold,
    build_synthetic_evidence_fixture,
    compile_offline_evidence_bundle,
    render_offline_evidence_bundle_json,
    validate_offline_evidence_bundle_receipt,
)
from public_presence_os.meta_read_only_gate import REQUIRED_FUTURE_EVIDENCE

ROOT = Path(__file__).resolve().parents[1]


def h(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def cp57_policy() -> dict:
    return json.loads((ROOT / "config" / "meta_offline_evidence_validator_policy.json").read_text(encoding="utf-8"))


def make_cp56_contract(platform: str, mode: str = "TEXT") -> MetaLiveReadOnlyProbeContract:
    steps = tuple(
        ProbeStep(order=index + 1, step_id=f"S{index + 1:02d}", request_class=request_class)
        for index, request_class in enumerate(PLATFORM_PROBE_CLASSES[platform])
    )
    evidence = tuple(
        EvidenceCaptureContract(code=code, capture_kind=CAPTURE_KIND_BY_CODE[code])
        for code in REQUIRED_FUTURE_EVIDENCE
    )
    provisional = MetaLiveReadOnlyProbeContract(
        contract_id="pending",
        contract_hash="0" * 64,
        model_version=PROBE_CONTRACT_MODEL_VERSION,
        engine_version=PROBE_CONTRACT_ENGINE_VERSION,
        read_only_gate_id="mrog_synthetic_cp57_contract",
        read_only_gate_hash=h(f"cp57-gate:{platform}:{mode}"),
        platform=platform,
        mode=mode,
        runbook_policy_sha256=h("cp56-runbook-policy-synthetic-test-binding"),
        steps=steps,
        evidence_contract=evidence,
        recovery=RecoveryContract(),
    )
    body = provisional.to_dict()
    body.pop("contract_id")
    body.pop("contract_hash")
    digest = sha256(canonical_json(body).encode("utf-8")).hexdigest()
    receipt = replace(provisional, contract_id="mlrop_" + digest[:24], contract_hash=digest)
    validate_live_read_only_probe_contract(receipt)
    return receipt


@pytest.mark.parametrize("platform", ["FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS"])
def test_cp57_bundle_is_deterministic_exactly_bound_and_synthetic(platform):
    contract = make_cp56_contract(platform)
    first = compile_offline_evidence_bundle(
        contract,
        cp57_policy(),
        operator_timestamp_utc="2026-09-07T00:10:00Z",
    )
    second = compile_offline_evidence_bundle(
        contract,
        cp57_policy(),
        operator_timestamp_utc="2026-09-07T00:10:00Z",
    )

    assert first == second
    assert first.state == STATE
    assert first.cp56_contract_id == contract.contract_id
    assert first.cp56_contract_hash == contract.contract_hash
    assert first.platform == platform
    assert first.api_version_literal == SYNTHETIC_API_VERSION
    assert first.global_kill_switch_engaged is True
    assert first.synthetic_fixture_only is True
    assert first.evidence_code_set_exact is True
    assert first.zero_write_confirmed is True
    assert first.operator_dry_run_passed is True
    assert first.live_evidence_claimed is False
    assert first.live_entitlement_verified is False
    assert first.live_connection_verified is False
    assert first.pilot_publish_ready is False


def test_cp57_evidence_bundle_is_exact_redacted_canonical_and_hash_bound():
    contract = make_cp56_contract("THREADS")
    receipt = compile_offline_evidence_bundle(
        contract,
        cp57_policy(),
        operator_timestamp_utc="2026-09-07T00:11:00Z",
    )

    assert tuple(item.code for item in receipt.evidence) == REQUIRED_FUTURE_EVIDENCE
    for item in receipt.evidence:
        assert item.fixture_scope == FIXTURE_SCOPE
        assert item.state == "SYNTHETIC_VALIDATED"
        assert item.redacted is True
        assert item.canonicalized is True
        assert item.hash_algorithm == "SHA256"
        assert item.live_evidence is False
        assert item.raw_secret_material_present is False
        assert item.external_upload_performed is False
        assert item.payload_sha256 == sha256(item.canonical_payload.encode("utf-8")).hexdigest()
        payload = json.loads(item.canonical_payload)
        assert payload["fixture_scope"] == FIXTURE_SCOPE

    rendered = json.loads(render_offline_evidence_bundle_json(receipt))
    assert rendered["network_attempted"] is False
    assert rendered["account_connected"] is False
    assert rendered["publish_attempted"] is False
    assert rendered["external_write_performed"] is False
    assert rendered["deploy_performed"] is False
    assert rendered["pilot_publish_ready"] is False


def test_cp57_operator_dry_run_is_get_only_synthetic_endpoint_and_zero_authority():
    contract = make_cp56_contract("INSTAGRAM_PROFESSIONAL", "SINGLE_IMAGE")
    receipt = compile_offline_evidence_bundle(
        contract,
        cp57_policy(),
        operator_timestamp_utc="2026-09-07T00:12:00Z",
    )

    assert tuple(step.request_class for step in receipt.dry_run_steps) == PLATFORM_PROBE_CLASSES[contract.platform]
    assert tuple(step.order for step in receipt.dry_run_steps) == tuple(range(1, len(receipt.dry_run_steps) + 1))
    for step in receipt.dry_run_steps:
        assert step.method == "GET"
        assert step.endpoint_selector == SYNTHETIC_ENDPOINT_SELECTOR
        assert step.result == "PASS_SYNTHETIC_SERIALIZATION_ONLY"
        assert step.endpoint_materialized is False
        assert step.secret_reference_resolved is False
        assert step.network_attempted is False
        assert step.external_write_performed is False

    for flag in (
        "secret_reference_resolved", "environment_read", "keychain_read", "oauth_attempted",
        "real_account_lookup_attempted", "account_connected", "network_attempted", "publish_attempted",
        "external_write_performed", "deploy_performed", "live_evidence_claimed", "live_entitlement_verified",
        "live_connection_verified", "pilot_publish_ready",
    ):
        assert getattr(receipt, flag) is False


def test_cp57_fixture_rejects_secret_material_missing_codes_and_zero_write_drift():
    contract = make_cp56_contract("FACEBOOK_PAGE")
    fixture = build_synthetic_evidence_fixture(contract, "2026-09-07T00:13:00Z")

    secret_fixture = dict(fixture)
    secret_payload = dict(secret_fixture["LIVE_TOKEN_DEBUG_REDACTED"])
    secret_payload["access_token"] = "TEST_ONLY_RAW_VALUE_SHOULD_NEVER_PERSIST"
    secret_fixture["LIVE_TOKEN_DEBUG_REDACTED"] = secret_payload
    with pytest.raises(MetaOfflineEvidenceHold, match="HOLD_CP57_RAW_SECRET_FIELD_FORBIDDEN"):
        compile_offline_evidence_bundle(
            contract,
            cp57_policy(),
            operator_timestamp_utc="2026-09-07T00:13:00Z",
            fixture=secret_fixture,
        )

    missing = dict(fixture)
    missing.pop("LIVE_EXPIRY_STATE")
    with pytest.raises(MetaOfflineEvidenceHold, match="HOLD_CP57_EVIDENCE_CODE_SET_DRIFT"):
        compile_offline_evidence_bundle(
            contract,
            cp57_policy(),
            operator_timestamp_utc="2026-09-07T00:13:00Z",
            fixture=missing,
        )

    write_drift = dict(fixture)
    zero = dict(write_drift["ZERO_WRITE_CONFIRMATION"])
    zero["external_write_performed"] = True
    write_drift["ZERO_WRITE_CONFIRMATION"] = zero
    with pytest.raises(MetaOfflineEvidenceHold, match="HOLD_CP57_ZERO_WRITE_FIXTURE_DRIFT"):
        compile_offline_evidence_bundle(
            contract,
            cp57_policy(),
            operator_timestamp_utc="2026-09-07T00:13:00Z",
            fixture=write_drift,
        )


def test_cp57_receipt_tampering_fails_closed():
    receipt = compile_offline_evidence_bundle(
        make_cp56_contract("THREADS"),
        cp57_policy(),
        operator_timestamp_utc="2026-09-07T00:14:00Z",
    )

    with pytest.raises(MetaOfflineEvidenceHold, match="HOLD_CP57_EXTERNAL_AUTHORITY_FORBIDDEN"):
        validate_offline_evidence_bundle_receipt(replace(receipt, network_attempted=True))

    steps = list(receipt.dry_run_steps)
    steps[0] = replace(steps[0], method="POST")
    with pytest.raises(MetaOfflineEvidenceHold, match="HOLD_CP57_DRY_RUN_METHOD_OR_ENDPOINT_DRIFT"):
        validate_offline_evidence_bundle_receipt(replace(receipt, dry_run_steps=tuple(steps)))

    evidence = list(receipt.evidence)
    evidence[0] = replace(evidence[0], payload_sha256="0" * 64)
    with pytest.raises(MetaOfflineEvidenceHold, match="HOLD_CP57_EVIDENCE_HASH_MISMATCH"):
        validate_offline_evidence_bundle_receipt(replace(receipt, evidence=tuple(evidence)))


def test_cp57_policy_registry_priority_and_runtime_remain_fail_closed():
    policy = cp57_policy()
    registry = json.loads((ROOT / "config" / "module_registry.json").read_text(encoding="utf-8"))
    priority = json.loads((ROOT / "config" / "reimplementation_priority.json").read_text(encoding="utf-8"))
    runtime = json.loads((ROOT / "config" / "runtime_policy.json").read_text(encoding="utf-8"))

    assert policy["checkpoint"] == "CP57"
    assert tuple(policy["active_platforms"]) == ("FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS")
    assert policy["validator_contract"]["offline_only"] is True
    assert policy["validator_contract"]["synthetic_fixture_only"] is True
    assert policy["validator_contract"]["method_allowlist"] == ["GET"]
    assert policy["validator_contract"]["mutating_methods_forbidden"] == ["POST", "PUT", "PATCH", "DELETE"]
    assert policy["validator_contract"]["live_evidence_claim_allowed"] is False
    assert policy["required_evidence_codes"] == list(REQUIRED_FUTURE_EVIDENCE)
    assert all(value is False for value in policy["authority"].values())

    assert registry["checkpoint"] == "CP57"
    assert any(
        row["id"] == "M26_META_OFFLINE_EVIDENCE_VALIDATOR"
        and row["status"] == "CP57_SYNTHETIC_EVIDENCE_BUNDLE_VALIDATOR_DRY_RUN_LOCAL_ONLY"
        for row in registry["modules"]
    )
    assert priority["checkpoint"] == "CP57"
    assert priority["next"] == "CP58_META_PILOT_READINESS_AGGREGATOR_AND_LIVE_CONNECTION_AUTHORIZATION_GATE"
    assert runtime["global_kill_switch_engaged"] is True
    assert runtime["network_enabled"] is False
    assert runtime["real_accounts_connected"] is False
    assert runtime["publish_enabled"] is False
    assert runtime["deploy_enabled"] is False


def test_cp57_source_contains_no_network_secret_resolution_or_live_probe_execution():
    import public_presence_os.meta_offline_evidence as module

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
