from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import inspect
import json
from pathlib import Path
import sqlite3

import pytest

from public_presence_os.connection_preflight import (
    ConnectionPreflightHold,
    SyntheticPreflightLedger,
    compile_synthetic_preflight,
    validate_synthetic_preflight_receipt,
)
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

ROOT = Path(__file__).resolve().parents[1]


def h(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def bound_evidence(platform: str, mode: str) -> OfflineCapabilityEvidence:
    contract = static_capability_contract(platform, mode)
    return OfflineCapabilityEvidence(
        state="OFFLINE_EVIDENCE_BOUND",
        evidence_artifact_sha256=h(f"cp52-synthetic-evidence:{platform}:{mode}"),
        observed_permissions=contract["required_permissions"],
        observed_capabilities=contract["required_capabilities"],
        expiry_state="KNOWN",
        expires_at_utc="2026-12-31T23:59:59Z",
    )


def make_plan(platform: str, mode: str):
    if mode == TEXT:
        intent = OfflinePublishIntent(
            source_binding_hash=h(f"cp52-source:{platform}:{mode}"),
            platform=platform,
            mode=mode,
            text="Synthetic CP52 contract check only.",
        )
    else:
        intent = OfflinePublishIntent(
            source_binding_hash=h(f"cp52-source:{platform}:{mode}"),
            platform=platform,
            mode=mode,
            text="Synthetic CP52 image contract check only.",
            media_asset_sha256=h(f"cp52-media:{platform}"),
            alt_text="Synthetic image used only for an offline preflight test.",
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


def stage_profile(tmp_path, profile, suffix: str = "0001"):
    vault = SecretReferenceVault(tmp_path / f"cp52-{suffix}.sqlite3")
    receipt = vault.stage(
        profile,
        request_id=f"cp52-vault-{suffix}",
        event_time_utc="2026-09-06T21:00:00Z",
    )
    return vault, receipt


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
def test_cp52_active_lane_contracts_preflight_deterministically(tmp_path, platform, mode):
    plan = make_plan(platform, mode)
    profile = make_profile(platform, mode)
    vault, vault_receipt = stage_profile(tmp_path, profile, suffix=f"{platform.lower()}-{mode.lower()}")

    first = compile_synthetic_preflight(
        plan,
        profile,
        vault=vault,
        vault_receipt=vault_receipt,
        request_id=f"cp52-preflight-{platform.lower()}-{mode.lower()}",
        event_time_utc="2026-09-06T21:01:00Z",
    )
    second = compile_synthetic_preflight(
        plan,
        profile,
        vault=vault,
        vault_receipt=vault_receipt,
        request_id=f"cp52-preflight-{platform.lower()}-{mode.lower()}",
        event_time_utc="2026-09-06T21:01:00Z",
    )

    assert first == second
    assert first.receipt_hash == second.receipt_hash
    assert first.state == "PASS_SYNTHETIC_PREFLIGHT_ONLY"
    assert first.synthetic_contract_pass is True
    assert first.offline_contract_evidence_complete is True
    assert first.readback.platform == platform
    assert first.readback.mode == mode
    assert first.readback.profile_hash == profile.profile_hash
    assert first.readback.vault_event_hash == vault_receipt.event_hash
    assert first.readback.entitlement_state == "SYNTHETIC_CONTRACT_ONLY"
    assert first.live_entitlement_verified is False
    assert first.secret_resolved is False
    assert first.network_attempted is False
    assert first.account_connected is False
    assert first.publish_attempted is False
    assert first.external_write_performed is False
    assert first.deploy_performed is False
    assert first.live_transport_ready is False
    assert first.pilot_publish_ready is False
    assert first.live_reverification_required is True


def test_cp52_requires_complete_cp51_offline_evidence(tmp_path):
    plan = make_plan("FACEBOOK_PAGE", TEXT)
    profile = compile_connection_profile(ConnectionProfileSpec(
        "FACEBOOK_PAGE",
        TEXT,
        "ENV:PPOS_META_FB_PAGE_TOKEN",
    ))
    vault, vault_receipt = stage_profile(tmp_path, profile)
    with pytest.raises(ConnectionPreflightHold, match="HOLD_PREFLIGHT_OFFLINE_EVIDENCE_INCOMPLETE"):
        compile_synthetic_preflight(
            plan,
            profile,
            vault=vault,
            vault_receipt=vault_receipt,
            request_id="cp52-preflight-incomplete",
            event_time_utc="2026-09-06T21:02:00Z",
        )


def test_cp52_platform_and_mode_mismatch_fail_closed(tmp_path):
    plan = make_plan("FACEBOOK_PAGE", TEXT)

    threads_profile = make_profile("THREADS", TEXT)
    threads_vault, threads_receipt = stage_profile(tmp_path, threads_profile, "threads-mismatch")
    with pytest.raises(ConnectionPreflightHold, match="HOLD_PREFLIGHT_PLATFORM_MISMATCH"):
        compile_synthetic_preflight(
            plan,
            threads_profile,
            vault=threads_vault,
            vault_receipt=threads_receipt,
            request_id="cp52-preflight-platform-mismatch",
            event_time_utc="2026-09-06T21:03:00Z",
        )

    image_profile = make_profile("FACEBOOK_PAGE", SINGLE_IMAGE)
    image_vault, image_receipt = stage_profile(tmp_path, image_profile, "mode-mismatch")
    with pytest.raises(ConnectionPreflightHold, match="HOLD_PREFLIGHT_MODE_MISMATCH"):
        compile_synthetic_preflight(
            plan,
            image_profile,
            vault=image_vault,
            vault_receipt=image_receipt,
            request_id="cp52-preflight-mode-mismatch",
            event_time_utc="2026-09-06T21:04:00Z",
        )


def test_cp52_vault_receipt_cannot_claim_secret_network_or_account_action(tmp_path):
    plan = make_plan("THREADS", TEXT)
    profile = make_profile("THREADS", TEXT)
    vault, receipt = stage_profile(tmp_path, profile)

    for field in ("secret_resolved", "network_attempted", "account_connected", "external_write_performed"):
        tampered = replace(receipt, **{field: True})
        with pytest.raises(ConnectionPreflightHold, match="HOLD_PREFLIGHT_VAULT_EXTERNAL_ACTION_FORBIDDEN"):
            compile_synthetic_preflight(
                plan,
                profile,
                vault=vault,
                vault_receipt=tampered,
                request_id=f"cp52-preflight-tamper-{field}",
                event_time_utc="2026-09-06T21:05:00Z",
            )


def test_cp52_exact_local_profile_readback_is_mandatory(tmp_path):
    plan = make_plan("INSTAGRAM_PROFESSIONAL", SINGLE_IMAGE)
    profile = make_profile("INSTAGRAM_PROFESSIONAL", SINGLE_IMAGE)
    vault, receipt = stage_profile(tmp_path, profile)

    with sqlite3.connect(vault.path) as conn:
        stored = json.loads(conn.execute(
            "SELECT profile_json FROM profiles WHERE profile_id = ?", (profile.profile_id,)
        ).fetchone()[0])
        stored["state"] = "TAMPERED"
        conn.execute(
            "UPDATE profiles SET profile_json = ? WHERE profile_id = ?",
            (json.dumps(stored, sort_keys=True, separators=(",", ":")), profile.profile_id),
        )

    with pytest.raises(ConnectionPreflightHold, match="HOLD_PREFLIGHT_PROFILE_READBACK_DRIFT"):
        compile_synthetic_preflight(
            plan,
            profile,
            vault=vault,
            vault_receipt=receipt,
            request_id="cp52-preflight-readback-drift",
            event_time_utc="2026-09-06T21:06:00Z",
        )


def test_cp52_local_ledger_is_immutable_append_only_and_idempotent(tmp_path):
    plan = make_plan("FACEBOOK_PAGE", TEXT)
    profile = make_profile("FACEBOOK_PAGE", TEXT)
    vault, vault_receipt = stage_profile(tmp_path, profile)
    receipt = compile_synthetic_preflight(
        plan,
        profile,
        vault=vault,
        vault_receipt=vault_receipt,
        request_id="cp52-preflight-ledger-0001",
        event_time_utc="2026-09-06T21:07:00Z",
    )
    ledger = SyntheticPreflightLedger(tmp_path / "preflight.sqlite3")
    first = ledger.record(receipt)
    second = ledger.record(receipt)

    assert first.event_hash == second.event_hash
    assert first.stored_new_receipt is True
    assert second.stored_new_receipt is False
    assert first.network_attempted is False
    assert first.account_connected is False
    assert first.external_write_performed is False
    assert ledger.event_count() == 1
    stored = ledger.read_receipt(receipt.receipt_id)
    assert stored["receipt_hash"] == receipt.receipt_hash
    assert stored["state"] == "PASS_SYNTHETIC_PREFLIGHT_ONLY"
    assert stored["live_transport_ready"] is False
    assert stored["pilot_publish_ready"] is False


def test_cp52_receipt_tampering_fails_exact_hash_validation(tmp_path):
    plan = make_plan("THREADS", SINGLE_IMAGE)
    profile = make_profile("THREADS", SINGLE_IMAGE)
    vault, vault_receipt = stage_profile(tmp_path, profile)
    receipt = compile_synthetic_preflight(
        plan,
        profile,
        vault=vault,
        vault_receipt=vault_receipt,
        request_id="cp52-preflight-hash-0001",
        event_time_utc="2026-09-06T21:08:00Z",
    )
    with pytest.raises(ConnectionPreflightHold, match="HOLD_PREFLIGHT_RECEIPT_HASH_MISMATCH"):
        validate_synthetic_preflight_receipt(replace(receipt, checks=receipt.checks + ("tampered",)))


def test_cp52_policy_registry_priority_and_runtime_remain_fail_closed():
    policy = json.loads((ROOT / "config" / "meta_preflight_policy.json").read_text(encoding="utf-8"))
    registry = json.loads((ROOT / "config" / "module_registry.json").read_text(encoding="utf-8"))
    priority = json.loads((ROOT / "config" / "reimplementation_priority.json").read_text(encoding="utf-8"))
    runtime = json.loads((ROOT / "config" / "runtime_policy.json").read_text(encoding="utf-8"))

    assert policy["checkpoint"] == "CP52"
    assert tuple(policy["active_platforms"]) == ("FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS")
    assert policy["inputs"]["synthetic_identifiers_only"] is True
    assert policy["result_contract"]["pass_state"] == "PASS_SYNTHETIC_PREFLIGHT_ONLY"
    assert policy["result_contract"]["live_transport_ready"] is False
    assert policy["result_contract"]["pilot_publish_ready"] is False
    assert policy["ledger"]["backend"] == "LOCAL_SQLITE"
    assert policy["ledger"]["stores_secret_material"] is False
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

    assert registry["checkpoint"] == "CP56"
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
    assert priority["checkpoint"] == "CP56"
    assert priority["next"] == "CP57_META_OFFLINE_EVIDENCE_BUNDLE_VALIDATOR_AND_OPERATOR_DRY_RUN"
    assert runtime["global_kill_switch_engaged"] is True
    assert runtime["network_enabled"] is False
    assert runtime["real_accounts_connected"] is False
    assert runtime["publish_enabled"] is False
    assert runtime["deploy_enabled"] is False


def test_cp52_source_has_no_secret_resolution_or_network_transport():
    import public_presence_os.connection_preflight as module

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
