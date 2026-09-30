from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from public_presence_os.meta_read_only_runtime_contract import (
    SECRET_KEYS,
    MetaRuntimeContractHold,
    inspect_read_only_runtime_bindings,
    redacted_runtime_contract,
)

ROOT = Path(__file__).resolve().parents[1]


def valid_bindings() -> dict[str, str]:
    return {
        "PPOS_META_PAGE_ID": "2816314015107071",
        "PPOS_META_IG_USER_ID": "17841429701593250",
        "PPOS_THREADS_USER_ID": "28391623420464631",
        "PPOS_META_GRAPH_API_VERSION": "v26.0",
        "PPOS_THREADS_API_VERSION": "v1.0",
        "PPOS_META_USER_ACCESS_TOKEN": "EAA_FAKE_USER_TOKEN_123456789012345",
        "PPOS_META_PAGE_ACCESS_TOKEN": "EAA_FAKE_PAGE_TOKEN_123456789012345",
        "PPOS_THREADS_USER_ACCESS_TOKEN": "TH_FAKE_USER_TOKEN_123456789012345",
    }


def test_sa2_1_complete_binding_is_redacted_and_zero_authority():
    values = valid_bindings()
    receipt = inspect_read_only_runtime_bindings(values)
    encoded = json.dumps(receipt.to_dict(), sort_keys=True)

    assert receipt.state == "READY_FOR_EXPLICIT_READ_ONLY_TRANSPORT_WIRING"
    assert receipt.facebook_page_id == "2816314015107071"
    assert receipt.instagram_user_id == "17841429701593250"
    assert receipt.threads_user_id == "28391623420464631"
    assert receipt.network_authority is False
    assert receipt.external_write_authority is False
    assert receipt.publish_authority is False
    assert receipt.deploy_authority is False
    assert receipt.kill_switch_must_remain_engaged is True
    for key in SECRET_KEYS:
        assert values[key] not in encoded
        assert key in encoded


def test_sa2_1_wrong_identity_fails_closed():
    values = valid_bindings()
    values["PPOS_META_PAGE_ID"] = "999"
    with pytest.raises(MetaRuntimeContractHold, match="HOLD_SA2_IDENTITY_MISMATCH_PPOS_META_PAGE_ID"):
        inspect_read_only_runtime_bindings(values)


@pytest.mark.parametrize("key", SECRET_KEYS)
def test_sa2_1_missing_or_placeholder_secret_fails_closed(key):
    values = valid_bindings()
    values[key] = "REDACTED"
    with pytest.raises(MetaRuntimeContractHold, match="HOLD_SA2_SECRET_NOT_PROVISIONED"):
        inspect_read_only_runtime_bindings(values)


def test_sa2_1_redacted_operator_contract_contains_names_not_values():
    contract = redacted_runtime_contract()
    assert set(contract["secret_env_names"]) == set(SECRET_KEYS)
    assert contract["network_authority"] is False
    assert contract["external_write_authority"] is False
    assert "pages_manage_posts" in contract["write_scopes_forbidden"]
    assert "threads_content_publish" in contract["write_scopes_forbidden"]


def test_sa2_1_policy_matches_real_identity_evidence_and_zero_write():
    policy = json.loads((ROOT / "config" / "meta_read_only_runtime_contract_policy.json").read_text(encoding="utf-8"))
    assert policy["checkpoint"] == "S-A2.1"
    assert policy["expected_identities"]["facebook_page_id"] == "2816314015107071"
    assert policy["expected_identities"]["instagram_professional_id"] == "17841429701593250"
    assert policy["expected_identities"]["threads_user_id"] == "28391623420464631"
    assert policy["authority"]["implicit_environment_read"] is False
    assert policy["authority"]["network_allowed"] is False
    assert policy["authority"]["external_write_allowed"] is False
    assert policy["authority"]["publish_allowed"] is False
    assert policy["authority"]["deploy_allowed"] is False
    assert policy["authority"]["global_kill_switch_required"] is True


def test_sa2_1_source_has_no_implicit_secret_or_network_io():
    import public_presence_os.meta_read_only_runtime_contract as module

    src = inspect.getsource(module)
    assert "os.environ" not in src
    assert "os.getenv" not in src
    for item in ("requests", "httpx", "aiohttp", "urllib.request", "http.client", "socket"):
        assert f"import {item}" not in src
        assert f"from {item}" not in src
