from __future__ import annotations

from dataclasses import replace
import inspect
import json
from pathlib import Path

import pytest

from public_presence_os.meta_read_only_runtime_contract import inspect_read_only_runtime_bindings
from public_presence_os.meta_read_only_transport import (
    UNKNOWN,
    MetaReadOnlyTransportHold,
    allowed_operations,
    compile_read_only_request,
    normalize_read_only_response,
    validate_read_only_request_plan,
)

ROOT = Path(__file__).resolve().parents[1]


def runtime_receipt():
    return inspect_read_only_runtime_bindings({
        "PPOS_META_PAGE_ID": "2816314015107071",
        "PPOS_META_IG_USER_ID": "17841429701593250",
        "PPOS_THREADS_USER_ID": "28391623420464631",
        "PPOS_META_GRAPH_API_VERSION": "v26.0",
        "PPOS_THREADS_API_VERSION": "v1.0",
        "PPOS_META_USER_ACCESS_TOKEN": "EAA_FAKE_USER_TOKEN_123456789012345",
        "PPOS_META_PAGE_ACCESS_TOKEN": "EAA_FAKE_PAGE_TOKEN_123456789012345",
        "PPOS_THREADS_USER_ACCESS_TOKEN": "TH_FAKE_USER_TOKEN_123456789012345",
    })


def test_sa2_2_allowlist_compiles_get_only_without_secret_values():
    receipt = runtime_receipt()
    plans = {op: compile_read_only_request(receipt, op) for op in allowed_operations()}
    assert set(plans) == {
        "FACEBOOK_MANAGED_PAGES", "FACEBOOK_PAGE_IDENTITY", "INSTAGRAM_PROFILE", "THREADS_PROFILE"
    }
    assert all(plan.method == "GET" for plan in plans.values())
    assert all(plan.network_execution_authority is False for plan in plans.values())
    assert all(plan.external_write_authority is False for plan in plans.values())
    assert plans["INSTAGRAM_PROFILE"].host == "graph.facebook.com"
    assert plans["THREADS_PROFILE"].host == "graph.threads.net"
    encoded = json.dumps({key: value.to_dict() for key, value in plans.items()}, sort_keys=True)
    assert "EAA_FAKE" not in encoded
    assert "TH_FAKE" not in encoded


def test_sa2_2_facebook_managed_pages_normalizes_exact_binding():
    plan = compile_read_only_request(runtime_receipt(), "FACEBOOK_MANAGED_PAGES")
    record = normalize_read_only_response(plan, {
        "data": [{
            "id": "2816314015107071",
            "name": "Mihai Cismaru",
            "instagram_business_account": {"id": "17841429701593250"},
            "tasks": ["MODERATE", "ANALYZE", "MANAGE"],
        }]
    })
    assert record.external_id == "2816314015107071"
    assert record.linked_instagram_id == "17841429701593250"
    assert record.tasks == ("ANALYZE", "MANAGE", "MODERATE")
    assert record.username == UNKNOWN


def test_sa2_2_instagram_and_threads_profiles_normalize_identity():
    receipt = runtime_receipt()
    ig = normalize_read_only_response(
        compile_read_only_request(receipt, "INSTAGRAM_PROFILE"),
        {"id": "17841429701593250", "username": "m.cismaru", "name": "Mihai Cismaru"},
    )
    th = normalize_read_only_response(
        compile_read_only_request(receipt, "THREADS_PROFILE"),
        {"id": "28391623420464631", "username": "m.cismaru", "name": "Mihai Cismaru"},
    )
    assert ig.username == "m.cismaru"
    assert th.username == "m.cismaru"
    assert ig.unknown_fields == ()
    assert th.unknown_fields == ()


def test_sa2_2_missing_optional_fields_are_unknown_not_invented():
    plan = compile_read_only_request(runtime_receipt(), "INSTAGRAM_PROFILE")
    record = normalize_read_only_response(plan, {"id": "17841429701593250"})
    assert record.name == UNKNOWN
    assert record.username == UNKNOWN
    assert record.unknown_fields == ("name", "username")


def test_sa2_2_identity_or_binding_drift_fails_closed():
    receipt = runtime_receipt()
    ig_plan = compile_read_only_request(receipt, "INSTAGRAM_PROFILE")
    with pytest.raises(MetaReadOnlyTransportHold, match="HOLD_SA2_2_RESPONSE_IDENTITY_MISMATCH"):
        normalize_read_only_response(ig_plan, {"id": "999", "username": "m.cismaru"})

    page_plan = compile_read_only_request(receipt, "FACEBOOK_PAGE_IDENTITY")
    with pytest.raises(MetaReadOnlyTransportHold, match="HOLD_SA2_2_INSTAGRAM_BINDING_MISMATCH"):
        normalize_read_only_response(page_plan, {
            "id": "2816314015107071",
            "name": "Mihai Cismaru",
            "instagram_business_account": {"id": "999"},
        })


def test_sa2_2_secret_bearing_response_is_rejected():
    plan = compile_read_only_request(runtime_receipt(), "FACEBOOK_MANAGED_PAGES")
    with pytest.raises(MetaReadOnlyTransportHold, match="HOLD_SA2_2_SECRET_BEARING_RESPONSE_FORBIDDEN"):
        normalize_read_only_response(plan, {"data": [{
            "id": "2816314015107071",
            "access_token": "must-not-enter-normalizer",
            "instagram_business_account": {"id": "17841429701593250"},
        }]})


def test_sa2_2_unknown_operation_and_non_get_tamper_fail_closed():
    receipt = runtime_receipt()
    with pytest.raises(MetaReadOnlyTransportHold, match="HOLD_SA2_2_OPERATION_NOT_ALLOWLISTED"):
        compile_read_only_request(receipt, "PUBLISH_POST")
    plan = compile_read_only_request(receipt, "THREADS_PROFILE")
    with pytest.raises(MetaReadOnlyTransportHold, match="HOLD_SA2_2_METHOD_HOST_PLATFORM_DRIFT"):
        validate_read_only_request_plan(replace(plan, method="POST"))


def test_sa2_2_policy_is_get_only_and_zero_network_authority():
    policy = json.loads((ROOT / "config" / "meta_read_only_transport_policy.json").read_text(encoding="utf-8"))
    assert policy["checkpoint"] == "S-A2.2"
    assert all(row["method"] == "GET" for row in policy["operations"].values())
    assert policy["normalization"]["missing_field_value"] == "UNKNOWN"
    assert policy["normalization"]["secret_bearing_response_forbidden"] is True
    assert policy["authority"]["method_allowlist"] == ["GET"]
    assert policy["authority"]["network_execution_allowed"] is False
    assert policy["authority"]["token_resolution_allowed"] is False
    assert policy["authority"]["external_write_allowed"] is False
    assert policy["authority"]["publish_allowed"] is False
    assert policy["authority"]["deploy_allowed"] is False


def test_sa2_2_source_has_no_network_client_or_secret_resolution():
    import public_presence_os.meta_read_only_transport as module

    src = inspect.getsource(module)
    for item in ("requests", "httpx", "aiohttp", "urllib.request", "http.client", "socket"):
        assert f"import {item}" not in src
        assert f"from {item}" not in src
    for forbidden in ("os.environ", "os.getenv", "resolve_secret(", "refresh_token(", "oauth_exchange("):
        assert forbidden not in src
