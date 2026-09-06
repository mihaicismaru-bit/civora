from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import re

from .control import EXPECTED_ACTIVE, canonical_json

META_ADAPTER_MODEL_VERSION = "PPOS_META_OFFLINE_REQUEST_COMPILER_V1"
META_ADAPTER_ENGINE_VERSION = "ppos-meta-offline-request-compiler-v1.0.0"
TRANSPORT_MODE = "OFFLINE_COMPILE_ONLY"
DESTINATION_REF = "DESTINATION_ID_REQUIRED"
API_VERSION_REF = "API_VERSION_REQUIRED"
STAGING_URL_REF = "STAGING_URL_REQUIRED"
CONTAINER_ID_REF = "{{STEP_1_CONTAINER_ID}}"
HEX64 = re.compile(r"^[0-9a-f]{64}$")

TEXT = "TEXT"
SINGLE_IMAGE = "SINGLE_IMAGE"

_PLATFORM_CONTRACTS = {
    "FACEBOOK_PAGE": {
        "host": "graph.facebook.com",
        "auth_reference_kind": "PAGE_ACCESS_TOKEN_REF",
        "permissions": ("pages_show_list", "pages_read_engagement", "pages_manage_posts"),
        "modes": {
            TEXT: ("publish_text",),
            SINGLE_IMAGE: ("publish_single_image",),
        },
        "evidence_state": "AUTH_CURRENT_2026_09_06_PUBLISH_TEMPLATE_CANON_REVERIFY_BEFORE_LIVE",
    },
    "INSTAGRAM_PROFESSIONAL": {
        "host": "graph.instagram.com",
        "auth_reference_kind": "INSTAGRAM_USER_TOKEN_REF",
        "permissions": ("instagram_business_basic", "instagram_business_content_publish"),
        "modes": {
            SINGLE_IMAGE: ("publish_single_image",),
        },
        "evidence_state": "PUBLISH_CONTRACT_CURRENT_2026_09_06_REVERIFY_BEFORE_LIVE",
    },
    "THREADS": {
        "host": "graph.threads.net",
        "auth_reference_kind": "THREADS_USER_TOKEN_REF",
        "permissions": ("threads_basic", "threads_content_publish"),
        "modes": {
            TEXT: ("publish_text",),
            SINGLE_IMAGE: ("publish_single_image",),
        },
        "evidence_state": "PUBLISH_CONTRACT_CURRENT_2026_09_06_REVERIFY_BEFORE_LIVE",
    },
}


class MetaAdapterError(ValueError):
    pass


class MetaAdapterHold(MetaAdapterError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class OfflinePublishIntent:
    source_binding_hash: str
    platform: str
    mode: str
    text: str
    media_asset_sha256: str | None = None
    alt_text: str | None = None
    destination_ref: str = DESTINATION_REF
    api_version_ref: str = API_VERSION_REF
    staging_url_ref: str | None = None


@dataclass(frozen=True)
class RequestStep:
    ordinal: int
    operation: str
    method: str
    host: str
    path_template: str
    body: tuple[tuple[str, str], ...]
    output_id_ref: str | None = None

    def to_dict(self) -> dict:
        return {
            "ordinal": self.ordinal,
            "operation": self.operation,
            "method": self.method,
            "host": self.host,
            "path_template": self.path_template,
            "body": [{"key": key, "value": value} for key, value in self.body],
            "output_id_ref": self.output_id_ref,
        }


@dataclass(frozen=True)
class OfflineRequestPlan:
    plan_id: str
    plan_hash: str
    model_version: str
    engine_version: str
    source_binding_hash: str
    platform: str
    mode: str
    payload_text_sha256: str
    media_asset_sha256: str | None
    alt_text_sha256: str | None
    auth_reference_kind: str
    required_permissions: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    endpoint_contract_evidence_state: str
    steps: tuple[RequestStep, ...]
    transport_mode: str = TRANSPORT_MODE
    network_allowed: bool = False
    credential_resolution_allowed: bool = False
    real_account_lookup_allowed: bool = False
    account_connection_allowed: bool = False
    publish_execution_allowed: bool = False
    external_write_allowed: bool = False
    deploy_allowed: bool = False
    wire_idempotency_headers_allowed: bool = False
    global_kill_switch_required: bool = True
    live_reverification_required: bool = True
    state: str = "OFFLINE_REQUEST_PLAN_ONLY"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["steps"] = [step.to_dict() for step in self.steps]
        return data


def _hash(value) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _text_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _validate_intent(intent: OfflinePublishIntent) -> dict:
    if not isinstance(intent, OfflinePublishIntent):
        raise MetaAdapterHold("HOLD_META_INTENT_TYPE")
    if intent.platform not in EXPECTED_ACTIVE or intent.platform not in _PLATFORM_CONTRACTS:
        raise MetaAdapterHold("HOLD_META_PLATFORM_NOT_ACTIVE")
    if not HEX64.fullmatch(intent.source_binding_hash):
        raise MetaAdapterHold("HOLD_META_SOURCE_BINDING_INVALID")
    if intent.destination_ref != DESTINATION_REF:
        raise MetaAdapterHold("HOLD_META_REAL_DESTINATION_FORBIDDEN")
    if intent.api_version_ref != API_VERSION_REF:
        raise MetaAdapterHold("HOLD_META_LITERAL_API_VERSION_FORBIDDEN")
    if not isinstance(intent.text, str):
        raise MetaAdapterHold("HOLD_META_TEXT_TYPE")
    if len(intent.text.encode("utf-8")) > 65536:
        raise MetaAdapterHold("HOLD_META_TEXT_HOUSE_LIMIT")
    contract = _PLATFORM_CONTRACTS[intent.platform]
    if intent.mode not in contract["modes"]:
        raise MetaAdapterHold("HOLD_META_MODE_NOT_SUPPORTED")
    if intent.mode == TEXT:
        if not intent.text.strip():
            raise MetaAdapterHold("HOLD_META_TEXT_REQUIRED")
        if intent.staging_url_ref is not None or intent.media_asset_sha256 is not None or intent.alt_text is not None:
            raise MetaAdapterHold("HOLD_META_MEDIA_BINDING_FOR_TEXT_FORBIDDEN")
    if intent.mode == SINGLE_IMAGE:
        if intent.staging_url_ref != STAGING_URL_REF:
            raise MetaAdapterHold("HOLD_META_STAGING_URL_PLACEHOLDER_REQUIRED")
        if not isinstance(intent.media_asset_sha256, str) or not HEX64.fullmatch(intent.media_asset_sha256):
            raise MetaAdapterHold("HOLD_META_MEDIA_ASSET_HASH_REQUIRED")
        if not isinstance(intent.alt_text, str) or not intent.alt_text.strip():
            raise MetaAdapterHold("HOLD_META_ALT_TEXT_REQUIRED")
        if len(intent.alt_text.encode("utf-8")) > 8192:
            raise MetaAdapterHold("HOLD_META_ALT_TEXT_HOUSE_LIMIT")
    return contract


def _steps(intent: OfflinePublishIntent, contract: dict) -> tuple[RequestStep, ...]:
    host = contract["host"]
    base = "/{API_VERSION}/{DESTINATION_ID}"
    if intent.platform == "FACEBOOK_PAGE":
        if intent.mode == TEXT:
            return (RequestStep(1, "CREATE_PAGE_FEED_POST", "POST", host, base + "/feed", (("message", intent.text),)),)
        return (RequestStep(
            1,
            "CREATE_PAGE_PHOTO_POST",
            "POST",
            host,
            base + "/photos",
            (("caption", intent.text), ("url", STAGING_URL_REF)),
        ),)
    if intent.platform == "INSTAGRAM_PROFESSIONAL":
        return (
            RequestStep(
                1,
                "CREATE_IMAGE_CONTAINER",
                "POST",
                host,
                base + "/media",
                (("caption", intent.text), ("image_url", STAGING_URL_REF)),
                output_id_ref=CONTAINER_ID_REF,
            ),
            RequestStep(
                2,
                "PUBLISH_IMAGE_CONTAINER",
                "POST",
                host,
                base + "/media_publish",
                (("creation_id", CONTAINER_ID_REF),),
            ),
        )
    if intent.platform == "THREADS":
        body = [("media_type", "TEXT" if intent.mode == TEXT else "IMAGE"), ("text", intent.text)]
        if intent.mode == SINGLE_IMAGE:
            body.extend((("image_url", STAGING_URL_REF), ("alt_text", intent.alt_text or "")))
        return (
            RequestStep(
                1,
                "CREATE_THREADS_CONTAINER",
                "POST",
                host,
                base + "/threads",
                tuple(body),
                output_id_ref=CONTAINER_ID_REF,
            ),
            RequestStep(
                2,
                "PUBLISH_THREADS_CONTAINER",
                "POST",
                host,
                base + "/threads_publish",
                (("creation_id", CONTAINER_ID_REF),),
            ),
        )
    raise MetaAdapterHold("HOLD_META_PLATFORM_NOT_ACTIVE")


def _plan_body(*, intent: OfflinePublishIntent, contract: dict, steps: tuple[RequestStep, ...]) -> dict:
    return {
        "model_version": META_ADAPTER_MODEL_VERSION,
        "engine_version": META_ADAPTER_ENGINE_VERSION,
        "source_binding_hash": intent.source_binding_hash,
        "platform": intent.platform,
        "mode": intent.mode,
        "payload_text_sha256": _text_hash(intent.text),
        "media_asset_sha256": intent.media_asset_sha256,
        "alt_text_sha256": _text_hash(intent.alt_text) if intent.alt_text is not None else None,
        "auth_reference_kind": contract["auth_reference_kind"],
        "required_permissions": list(contract["permissions"]),
        "required_capabilities": list(contract["modes"][intent.mode]),
        "endpoint_contract_evidence_state": contract["evidence_state"],
        "steps": [step.to_dict() for step in steps],
        "transport_mode": TRANSPORT_MODE,
        "network_allowed": False,
        "credential_resolution_allowed": False,
        "real_account_lookup_allowed": False,
        "account_connection_allowed": False,
        "publish_execution_allowed": False,
        "external_write_allowed": False,
        "deploy_allowed": False,
        "wire_idempotency_headers_allowed": False,
        "global_kill_switch_required": True,
        "live_reverification_required": True,
        "state": "OFFLINE_REQUEST_PLAN_ONLY",
    }


def compile_offline_request(intent: OfflinePublishIntent) -> OfflineRequestPlan:
    contract = _validate_intent(intent)
    steps = _steps(intent, contract)
    body = _plan_body(intent=intent, contract=contract, steps=steps)
    plan_hash = _hash(body)
    plan = OfflineRequestPlan(
        plan_id="map_" + plan_hash[:24],
        plan_hash=plan_hash,
        model_version=META_ADAPTER_MODEL_VERSION,
        engine_version=META_ADAPTER_ENGINE_VERSION,
        source_binding_hash=intent.source_binding_hash,
        platform=intent.platform,
        mode=intent.mode,
        payload_text_sha256=_text_hash(intent.text),
        media_asset_sha256=intent.media_asset_sha256,
        alt_text_sha256=_text_hash(intent.alt_text) if intent.alt_text is not None else None,
        auth_reference_kind=contract["auth_reference_kind"],
        required_permissions=tuple(contract["permissions"]),
        required_capabilities=tuple(contract["modes"][intent.mode]),
        endpoint_contract_evidence_state=contract["evidence_state"],
        steps=steps,
    )
    validate_request_plan(plan)
    return plan


def validate_request_plan(plan: OfflineRequestPlan) -> None:
    if not isinstance(plan, OfflineRequestPlan):
        raise MetaAdapterHold("HOLD_META_PLAN_TYPE")
    if plan.model_version != META_ADAPTER_MODEL_VERSION or plan.engine_version != META_ADAPTER_ENGINE_VERSION:
        raise MetaAdapterHold("HOLD_META_PLAN_VERSION")
    if plan.platform not in EXPECTED_ACTIVE or plan.platform not in _PLATFORM_CONTRACTS:
        raise MetaAdapterHold("HOLD_META_PLATFORM_NOT_ACTIVE")
    contract = _PLATFORM_CONTRACTS[plan.platform]
    if plan.mode not in contract["modes"]:
        raise MetaAdapterHold("HOLD_META_MODE_NOT_SUPPORTED")
    if not HEX64.fullmatch(plan.source_binding_hash) or not HEX64.fullmatch(plan.payload_text_sha256):
        raise MetaAdapterHold("HOLD_META_PLAN_BINDING_INVALID")
    if plan.mode == TEXT and (plan.media_asset_sha256 is not None or plan.alt_text_sha256 is not None):
        raise MetaAdapterHold("HOLD_META_TEXT_PLAN_MEDIA_BINDING")
    if plan.mode == SINGLE_IMAGE:
        if not isinstance(plan.media_asset_sha256, str) or not HEX64.fullmatch(plan.media_asset_sha256):
            raise MetaAdapterHold("HOLD_META_MEDIA_ASSET_HASH_REQUIRED")
        if not isinstance(plan.alt_text_sha256, str) or not HEX64.fullmatch(plan.alt_text_sha256):
            raise MetaAdapterHold("HOLD_META_ALT_TEXT_HASH_REQUIRED")
    if plan.auth_reference_kind != contract["auth_reference_kind"]:
        raise MetaAdapterHold("HOLD_META_AUTH_REFERENCE_KIND_MISMATCH")
    if plan.required_permissions != tuple(contract["permissions"]):
        raise MetaAdapterHold("HOLD_META_PERMISSION_CONTRACT_DRIFT")
    if plan.required_capabilities != tuple(contract["modes"][plan.mode]):
        raise MetaAdapterHold("HOLD_META_CAPABILITY_CONTRACT_DRIFT")
    if plan.endpoint_contract_evidence_state != contract["evidence_state"]:
        raise MetaAdapterHold("HOLD_META_EVIDENCE_STATE_DRIFT")
    if plan.transport_mode != TRANSPORT_MODE or plan.state != "OFFLINE_REQUEST_PLAN_ONLY":
        raise MetaAdapterHold("HOLD_META_TRANSPORT_STATE_INVALID")
    if any((
        plan.network_allowed,
        plan.credential_resolution_allowed,
        plan.real_account_lookup_allowed,
        plan.account_connection_allowed,
        plan.publish_execution_allowed,
        plan.external_write_allowed,
        plan.deploy_allowed,
        plan.wire_idempotency_headers_allowed,
    )) or not plan.global_kill_switch_required or not plan.live_reverification_required:
        raise MetaAdapterHold("HOLD_META_EXTERNAL_AUTHORITY_FORBIDDEN")
    if not plan.steps:
        raise MetaAdapterHold("HOLD_META_EMPTY_PLAN")
    for expected_ordinal, step in enumerate(plan.steps, start=1):
        if step.ordinal != expected_ordinal or step.method != "POST":
            raise MetaAdapterHold("HOLD_META_STEP_SEQUENCE_INVALID")
        if step.host != contract["host"]:
            raise MetaAdapterHold("HOLD_META_HOST_DRIFT")
        if "{API_VERSION}" not in step.path_template or "{DESTINATION_ID}" not in step.path_template:
            raise MetaAdapterHold("HOLD_META_LITERAL_DESTINATION_OR_VERSION")
        lowered_keys = {key.lower() for key, _ in step.body}
        if lowered_keys & {
            "access_token",
            "page_access_token",
            "threads_token",
            "authorization",
            "cookie",
            "client_secret",
            "app_secret",
        }:
            raise MetaAdapterHold("HOLD_META_CREDENTIAL_PARAMETER_FORBIDDEN")
    body = plan.to_dict()
    body.pop("plan_id")
    body.pop("plan_hash")
    expected_hash = _hash(body)
    if not HEX64.fullmatch(plan.plan_hash) or plan.plan_hash != expected_hash:
        raise MetaAdapterHold("HOLD_META_PLAN_HASH_MISMATCH")
    if plan.plan_id != "map_" + plan.plan_hash[:24]:
        raise MetaAdapterHold("HOLD_META_PLAN_ID_MISMATCH")


def static_capability_contract(platform: str, mode: str) -> dict:
    if platform not in EXPECTED_ACTIVE or platform not in _PLATFORM_CONTRACTS:
        raise MetaAdapterHold("HOLD_META_PLATFORM_NOT_ACTIVE")
    contract = _PLATFORM_CONTRACTS[platform]
    if mode not in contract["modes"]:
        raise MetaAdapterHold("HOLD_META_MODE_NOT_SUPPORTED")
    return {
        "platform": platform,
        "mode": mode,
        "required_permissions": tuple(contract["permissions"]),
        "required_capabilities": tuple(contract["modes"][mode]),
        "static_contract_supported": True,
        "real_entitlement_asserted": False,
        "network_authority": False,
        "publish_authority": False,
        "live_reverification_required": True,
    }
