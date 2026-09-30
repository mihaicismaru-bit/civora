from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Mapping

from .meta_read_only_runtime_contract import EXPECTED_IDENTITIES, MetaReadOnlyRuntimeReceipt

MODEL_VERSION = "PPOS_META_NORMALIZED_READ_ONLY_TRANSPORT_V1"
ENGINE_VERSION = "ppos-meta-normalized-read-only-transport-v1.0.0"
UNKNOWN = "UNKNOWN"

SPECS = {
    "FACEBOOK_MANAGED_PAGES": ("FACEBOOK_PAGE", "graph.facebook.com", "/{version}/me/accounts", "id,name,tasks,instagram_business_account", "PPOS_META_USER_ACCESS_TOKEN", "COLLECTION"),
    "FACEBOOK_PAGE_IDENTITY": ("FACEBOOK_PAGE", "graph.facebook.com", "/{version}/{page_id}", "id,name,instagram_business_account", "PPOS_META_USER_ACCESS_TOKEN", "OBJECT"),
    "INSTAGRAM_PROFILE": ("INSTAGRAM_PROFESSIONAL", "graph.facebook.com", "/{version}/{ig_user_id}", "id,username,name", "PPOS_META_PAGE_ACCESS_TOKEN", "OBJECT"),
    "THREADS_PROFILE": ("THREADS", "graph.threads.net", "/{version}/me", "id,username,name", "PPOS_THREADS_USER_ACCESS_TOKEN", "OBJECT"),
}


class MetaReadOnlyTransportHold(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ReadOnlyRequestPlan:
    plan_id: str
    plan_hash: str
    model_version: str
    engine_version: str
    operation: str
    platform: str
    method: str
    host: str
    path: str
    fields: str
    token_env_name: str
    response_kind: str
    expected_identity_id: str
    secret_value_embedded: bool = False
    network_execution_authority: bool = False
    external_write_authority: bool = False
    publish_authority: bool = False
    deploy_authority: bool = False
    kill_switch_must_remain_engaged: bool = True
    state: str = "READ_ONLY_REQUEST_PLAN_COMPILED"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class NormalizedReadRecord:
    operation: str
    platform: str
    external_id: str
    name: str
    username: str
    linked_instagram_id: str
    tasks: tuple[str, ...]
    source_response_sha256: str
    unknown_fields: tuple[str, ...]
    state: str = "NORMALIZED_READ_ONLY_EVIDENCE"

    def to_dict(self) -> dict:
        return asdict(self)


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _validate_receipt(receipt: MetaReadOnlyRuntimeReceipt) -> None:
    if not isinstance(receipt, MetaReadOnlyRuntimeReceipt):
        raise MetaReadOnlyTransportHold("HOLD_SA2_2_RUNTIME_RECEIPT_TYPE")
    if receipt.state != "READY_FOR_EXPLICIT_READ_ONLY_TRANSPORT_WIRING":
        raise MetaReadOnlyTransportHold("HOLD_SA2_2_RUNTIME_RECEIPT_STATE")
    expected = (
        (receipt.facebook_page_id, EXPECTED_IDENTITIES["PPOS_META_PAGE_ID"]),
        (receipt.instagram_user_id, EXPECTED_IDENTITIES["PPOS_META_IG_USER_ID"]),
        (receipt.threads_user_id, EXPECTED_IDENTITIES["PPOS_THREADS_USER_ID"]),
    )
    if any(actual != wanted for actual, wanted in expected):
        raise MetaReadOnlyTransportHold("HOLD_SA2_2_IDENTITY_DRIFT")
    if any((receipt.secret_values_returned, receipt.implicit_environment_read, receipt.network_authority,
            receipt.external_write_authority, receipt.publish_authority, receipt.deploy_authority)):
        raise MetaReadOnlyTransportHold("HOLD_SA2_2_RUNTIME_AUTHORITY_DRIFT")
    if not receipt.kill_switch_must_remain_engaged:
        raise MetaReadOnlyTransportHold("HOLD_SA2_2_KILL_SWITCH_DRIFT")


def _expected_id(operation: str, receipt: MetaReadOnlyRuntimeReceipt) -> str:
    if operation.startswith("FACEBOOK_"):
        return receipt.facebook_page_id
    if operation == "INSTAGRAM_PROFILE":
        return receipt.instagram_user_id
    if operation == "THREADS_PROFILE":
        return receipt.threads_user_id
    raise MetaReadOnlyTransportHold("HOLD_SA2_2_OPERATION_NOT_ALLOWLISTED")


def compile_read_only_request(receipt: MetaReadOnlyRuntimeReceipt, operation: str) -> ReadOnlyRequestPlan:
    _validate_receipt(receipt)
    spec = SPECS.get(operation)
    if spec is None:
        raise MetaReadOnlyTransportHold("HOLD_SA2_2_OPERATION_NOT_ALLOWLISTED")
    platform, host, path_template, fields, token_env_name, response_kind = spec
    version = receipt.threads_api_version if platform == "THREADS" else receipt.meta_graph_api_version
    path = path_template.format(version=version, page_id=receipt.facebook_page_id, ig_user_id=receipt.instagram_user_id)
    body = {
        "model_version": MODEL_VERSION, "engine_version": ENGINE_VERSION, "operation": operation,
        "platform": platform, "method": "GET", "host": host, "path": path, "fields": fields,
        "token_env_name": token_env_name, "response_kind": response_kind,
        "expected_identity_id": _expected_id(operation, receipt), "secret_value_embedded": False,
        "network_execution_authority": False, "external_write_authority": False,
        "publish_authority": False, "deploy_authority": False,
        "kill_switch_must_remain_engaged": True, "state": "READ_ONLY_REQUEST_PLAN_COMPILED",
    }
    plan_hash = _hash(body)
    plan = ReadOnlyRequestPlan(
        plan_id="mrop_" + plan_hash[:24], plan_hash=plan_hash, model_version=MODEL_VERSION,
        engine_version=ENGINE_VERSION, operation=operation, platform=platform, method="GET",
        host=host, path=path, fields=fields, token_env_name=token_env_name,
        response_kind=response_kind, expected_identity_id=_expected_id(operation, receipt),
    )
    validate_read_only_request_plan(plan)
    return plan


def validate_read_only_request_plan(plan: ReadOnlyRequestPlan) -> None:
    if not isinstance(plan, ReadOnlyRequestPlan):
        raise MetaReadOnlyTransportHold("HOLD_SA2_2_PLAN_TYPE")
    spec = SPECS.get(plan.operation)
    if spec is None:
        raise MetaReadOnlyTransportHold("HOLD_SA2_2_OPERATION_NOT_ALLOWLISTED")
    platform, host, _, fields, token_env_name, response_kind = spec
    if (plan.model_version, plan.engine_version) != (MODEL_VERSION, ENGINE_VERSION):
        raise MetaReadOnlyTransportHold("HOLD_SA2_2_PLAN_VERSION")
    if plan.platform != platform or plan.host != host or plan.method != "GET":
        raise MetaReadOnlyTransportHold("HOLD_SA2_2_METHOD_HOST_PLATFORM_DRIFT")
    if plan.fields != fields or plan.token_env_name != token_env_name or plan.response_kind != response_kind:
        raise MetaReadOnlyTransportHold("HOLD_SA2_2_REQUEST_CONTRACT_DRIFT")
    if not plan.path.startswith("/") or "?" in plan.path or "access_token" in plan.path.lower():
        raise MetaReadOnlyTransportHold("HOLD_SA2_2_PATH_UNSAFE")
    if any((plan.secret_value_embedded, plan.network_execution_authority, plan.external_write_authority,
            plan.publish_authority, plan.deploy_authority)):
        raise MetaReadOnlyTransportHold("HOLD_SA2_2_EXTERNAL_AUTHORITY_FORBIDDEN")
    if not plan.kill_switch_must_remain_engaged or plan.state != "READ_ONLY_REQUEST_PLAN_COMPILED":
        raise MetaReadOnlyTransportHold("HOLD_SA2_2_PLAN_STATE")
    body = plan.to_dict()
    body.pop("plan_id")
    body.pop("plan_hash")
    expected_hash = _hash(body)
    if plan.plan_hash != expected_hash or plan.plan_id != "mrop_" + expected_hash[:24]:
        raise MetaReadOnlyTransportHold("HOLD_SA2_2_PLAN_HASH_MISMATCH")


def _text(value) -> str:
    return value if isinstance(value, str) and value else UNKNOWN


def _linked_ig(payload: Mapping) -> str:
    linked = payload.get("instagram_business_account")
    return _text(linked.get("id")) if isinstance(linked, Mapping) else UNKNOWN


def _normalize_object(plan: ReadOnlyRequestPlan, payload: Mapping) -> NormalizedReadRecord:
    external_id = _text(payload.get("id"))
    if external_id != plan.expected_identity_id:
        raise MetaReadOnlyTransportHold("HOLD_SA2_2_RESPONSE_IDENTITY_MISMATCH")
    name, username, linked = _text(payload.get("name")), _text(payload.get("username")), _linked_ig(payload)
    tasks_raw = payload.get("tasks")
    tasks = tuple(sorted(x for x in tasks_raw if isinstance(x, str))) if isinstance(tasks_raw, list) else ()
    if plan.operation == "FACEBOOK_PAGE_IDENTITY" and linked != EXPECTED_IDENTITIES["PPOS_META_IG_USER_ID"]:
        raise MetaReadOnlyTransportHold("HOLD_SA2_2_INSTAGRAM_BINDING_MISMATCH")
    unknown = []
    if name == UNKNOWN:
        unknown.append("name")
    if plan.platform in {"INSTAGRAM_PROFESSIONAL", "THREADS"} and username == UNKNOWN:
        unknown.append("username")
    if plan.operation == "FACEBOOK_PAGE_IDENTITY" and linked == UNKNOWN:
        unknown.append("linked_instagram_id")
    return NormalizedReadRecord(
        operation=plan.operation, platform=plan.platform, external_id=external_id, name=name,
        username=username, linked_instagram_id=linked, tasks=tasks,
        source_response_sha256=_hash(payload), unknown_fields=tuple(sorted(unknown)),
    )


def normalize_read_only_response(plan: ReadOnlyRequestPlan, payload: Mapping) -> NormalizedReadRecord:
    validate_read_only_request_plan(plan)
    if not isinstance(payload, Mapping):
        raise MetaReadOnlyTransportHold("HOLD_SA2_2_RESPONSE_MAPPING_REQUIRED")
    if "access_token" in payload:
        raise MetaReadOnlyTransportHold("HOLD_SA2_2_SECRET_BEARING_RESPONSE_FORBIDDEN")
    if plan.response_kind == "OBJECT":
        return _normalize_object(plan, payload)
    data = payload.get("data")
    if not isinstance(data, list):
        raise MetaReadOnlyTransportHold("HOLD_SA2_2_COLLECTION_DATA_REQUIRED")
    if any("access_token" in x for x in data if isinstance(x, Mapping)):
        raise MetaReadOnlyTransportHold("HOLD_SA2_2_SECRET_BEARING_RESPONSE_FORBIDDEN")
    matches = [x for x in data if isinstance(x, Mapping) and x.get("id") == plan.expected_identity_id]
    if len(matches) != 1:
        raise MetaReadOnlyTransportHold("HOLD_SA2_2_EXPECTED_IDENTITY_NOT_UNIQUE")
    record = _normalize_object(plan, matches[0])
    if record.linked_instagram_id != EXPECTED_IDENTITIES["PPOS_META_IG_USER_ID"]:
        raise MetaReadOnlyTransportHold("HOLD_SA2_2_INSTAGRAM_BINDING_MISMATCH")
    return record


def allowed_operations() -> tuple[str, ...]:
    return tuple(SPECS)
