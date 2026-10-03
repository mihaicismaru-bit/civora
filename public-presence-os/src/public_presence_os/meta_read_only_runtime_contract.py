from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
from typing import Mapping

MODEL_VERSION = "PPOS_META_READ_ONLY_RUNTIME_CONTRACT_V1"
ENGINE_VERSION = "ppos-meta-read-only-runtime-contract-v1.0.0"

EXPECTED_IDENTITIES = {
    "PPOS_META_PAGE_ID": "2816314015107071",
    "PPOS_META_IG_USER_ID": "17841429701593250",
    "PPOS_THREADS_USER_ID": "28391623420464631",
}

API_VERSION_KEYS = (
    "PPOS_META_GRAPH_API_VERSION",
    "PPOS_THREADS_API_VERSION",
)

SECRET_KEYS = (
    "PPOS_META_USER_ACCESS_TOKEN",
    "PPOS_META_PAGE_ACCESS_TOKEN",
    "PPOS_THREADS_USER_ACCESS_TOKEN",
)

READ_SCOPE_FLOOR = {
    "FACEBOOK_PAGE": ("pages_show_list", "pages_read_engagement"),
    "INSTAGRAM_PROFESSIONAL": ("pages_show_list", "pages_read_engagement", "instagram_basic"),
    "THREADS": ("threads_basic",),
}

WRITE_SCOPES_FORBIDDEN = (
    "pages_manage_posts",
    "pages_manage_engagement",
    "instagram_content_publish",
    "instagram_manage_comments",
    "instagram_manage_messages",
    "threads_content_publish",
    "threads_manage_replies",
    "threads_delete",
)

_VERSION = re.compile(r"^v\d+\.\d+$")
_PLACEHOLDER = re.compile(r"^(?:TOKEN|CHANGEME|REDACTED|REPLACE_ME|PLACEHOLDER|NONE|NULL)$", re.I)


class MetaRuntimeContractHold(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SecretPresence:
    env_name: str
    present: bool


@dataclass(frozen=True)
class MetaReadOnlyRuntimeReceipt:
    model_version: str
    engine_version: str
    state: str
    identity_binding_hash: str
    facebook_page_id: str
    instagram_user_id: str
    threads_user_id: str
    meta_graph_api_version: str
    threads_api_version: str
    secret_presence: tuple[SecretPresence, ...]
    read_scope_floor: tuple[tuple[str, tuple[str, ...]], ...]
    write_scopes_forbidden: tuple[str, ...]
    secret_values_returned: bool = False
    implicit_environment_read: bool = False
    network_authority: bool = False
    external_write_authority: bool = False
    publish_authority: bool = False
    deploy_authority: bool = False
    kill_switch_must_remain_engaged: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def _binding_hash(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _require_string(values: Mapping[str, str], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value or value != value.strip():
        raise MetaRuntimeContractHold(f"HOLD_SA2_RUNTIME_BINDING_{key}")
    return value


def _validate_secret_reference_value(values: Mapping[str, str], key: str) -> None:
    value = _require_string(values, key)
    if len(value) < 20 or any(ch.isspace() for ch in value) or _PLACEHOLDER.fullmatch(value):
        raise MetaRuntimeContractHold(f"HOLD_SA2_SECRET_NOT_PROVISIONED_{key}")


def inspect_read_only_runtime_bindings(values: Mapping[str, str]) -> MetaReadOnlyRuntimeReceipt:
    """Validate caller-supplied bindings without reading the process environment.

    Secret values are checked for presence only and are never copied into the
    receipt, hashed, logged, persisted, or returned.
    """
    if not isinstance(values, Mapping):
        raise MetaRuntimeContractHold("HOLD_SA2_RUNTIME_BINDINGS_MAPPING_REQUIRED")

    for key, expected in EXPECTED_IDENTITIES.items():
        if _require_string(values, key) != expected:
            raise MetaRuntimeContractHold(f"HOLD_SA2_IDENTITY_MISMATCH_{key}")

    meta_version = _require_string(values, "PPOS_META_GRAPH_API_VERSION")
    threads_version = _require_string(values, "PPOS_THREADS_API_VERSION")
    if not _VERSION.fullmatch(meta_version):
        raise MetaRuntimeContractHold("HOLD_SA2_META_API_VERSION_FORMAT")
    if not _VERSION.fullmatch(threads_version):
        raise MetaRuntimeContractHold("HOLD_SA2_THREADS_API_VERSION_FORMAT")

    for key in SECRET_KEYS:
        _validate_secret_reference_value(values, key)

    non_secret_binding = {
        "identities": EXPECTED_IDENTITIES,
        "meta_graph_api_version": meta_version,
        "threads_api_version": threads_version,
        "read_scope_floor": {k: list(v) for k, v in READ_SCOPE_FLOOR.items()},
        "write_scopes_forbidden": list(WRITE_SCOPES_FORBIDDEN),
    }

    return MetaReadOnlyRuntimeReceipt(
        model_version=MODEL_VERSION,
        engine_version=ENGINE_VERSION,
        state="READY_FOR_EXPLICIT_READ_ONLY_TRANSPORT_WIRING",
        identity_binding_hash=_binding_hash(non_secret_binding),
        facebook_page_id=EXPECTED_IDENTITIES["PPOS_META_PAGE_ID"],
        instagram_user_id=EXPECTED_IDENTITIES["PPOS_META_IG_USER_ID"],
        threads_user_id=EXPECTED_IDENTITIES["PPOS_THREADS_USER_ID"],
        meta_graph_api_version=meta_version,
        threads_api_version=threads_version,
        secret_presence=tuple(SecretPresence(key, True) for key in SECRET_KEYS),
        read_scope_floor=tuple((platform, scopes) for platform, scopes in READ_SCOPE_FLOOR.items()),
        write_scopes_forbidden=WRITE_SCOPES_FORBIDDEN,
    )


def redacted_runtime_contract() -> dict:
    """Return the operator-facing contract without credential material."""
    return {
        "model_version": MODEL_VERSION,
        "engine_version": ENGINE_VERSION,
        "expected_identities": dict(EXPECTED_IDENTITIES),
        "api_version_env_names": list(API_VERSION_KEYS),
        "secret_env_names": list(SECRET_KEYS),
        "read_scope_floor": {k: list(v) for k, v in READ_SCOPE_FLOOR.items()},
        "write_scopes_forbidden": list(WRITE_SCOPES_FORBIDDEN),
        "implicit_environment_read": False,
        "network_authority": False,
        "external_write_authority": False,
        "publish_authority": False,
        "deploy_authority": False,
        "kill_switch_must_remain_engaged": True,
    }
