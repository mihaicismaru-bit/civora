#!/usr/bin/env python3
"""Bind regenerated native correction products to durable correction outboxes.

This boundary upgrades one correction item from READY_FOR_NATIVE_REGENERATION to
READY_FOR_CORRECTION_DISPATCH_ROUTING only after a generated native-product
manifest proves exact binding to the corrected fact kernel, instance, channel and
platform. The correction sidecar never stores editorial copy, credentials or raw
provider payloads, and this module performs no network I/O.

Persistence is compare-and-swap-like: the durable correction outbox must still
have the exact source fingerprint that was bound in memory before atomic replace.
Concurrent state changes therefore fail closed instead of being overwritten.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

SCHEMA_VERSION = "1.0"
READY_FOR_REGENERATION = "READY_FOR_NATIVE_REGENERATION"
READY_FOR_DISPATCH_ROUTING = "READY_FOR_CORRECTION_DISPATCH_ROUTING"
VISUAL_FORMATS = {"image", "image_plus_text", "carousel", "video", "short_video", "reel", "story"}
FORBIDDEN_SECRET_KEY_PARTS = {
    "token", "secret", "password", "authorization", "api_key", "apikey", "cookie", "bearer",
}
FORBIDDEN_COPY_KEYS = {
    "text", "caption", "message", "copy", "body", "headline", "hook", "script", "description", "posts", "thread",
}


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    text = _clean(value).lower()
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text)


def _safe_relative_posix_path(value: Any) -> PurePosixPath | None:
    text = _clean(value).replace("\\", "/")
    if not text:
        return None
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        return None
    return path


def _contains_forbidden_secret_field(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = _clean(key).lower()
            if any(part in lowered for part in FORBIDDEN_SECRET_KEY_PARTS):
                return True
            if _contains_forbidden_secret_field(child):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_secret_field(item) for item in value)
    return False


def _contains_editorial_copy(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if _clean(key).lower() in FORBIDDEN_COPY_KEYS:
                return True
            if _contains_editorial_copy(child):
                return True
    elif isinstance(value, list):
        return any(_contains_editorial_copy(item) for item in value)
    return False


def _validate_outbox(document: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not _clean(document.get("instance_id")):
        errors.append("CORRECTION_OUTBOX_INSTANCE_ID_MISSING")
    if not _clean(document.get("channel_id")):
        errors.append("CORRECTION_OUTBOX_CHANNEL_ID_MISSING")
    if not _clean(document.get("platform")):
        errors.append("CORRECTION_OUTBOX_PLATFORM_MISSING")
    if _safe_relative_posix_path(document.get("correction_outbox_path")) is None:
        errors.append("CORRECTION_OUTBOX_PATH_INVALID")
    if document.get("guards", {}).get("zero_paid_dependency") is not True:
        errors.append("CORRECTION_OUTBOX_ZERO_PAID_GUARD_MISSING")
    if document.get("guards", {}).get("credential_values_present") is not False:
        errors.append("CORRECTION_OUTBOX_CREDENTIAL_GUARD_INVALID")
    if document.get("guards", {}).get("editorial_copy_present") is not False:
        errors.append("CORRECTION_OUTBOX_COPY_GUARD_INVALID")
    if document.get("guards", {}).get("network_calls_performed") is not False:
        errors.append("CORRECTION_OUTBOX_NETWORK_GUARD_INVALID")
    if _contains_forbidden_secret_field(document):
        errors.append("CORRECTION_OUTBOX_CONTAINS_SECRET_FIELD")
    if _contains_editorial_copy(document):
        errors.append("CORRECTION_OUTBOX_CONTAINS_EDITORIAL_COPY")

    claimed = _clean(document.get("outbox_fingerprint_sha256")).lower()
    body = dict(document)
    body.pop("outbox_fingerprint_sha256", None)
    if not _is_sha256(claimed) or claimed != _digest(body):
        errors.append("CORRECTION_OUTBOX_FINGERPRINT_INVALID")

    items = document.get("items")
    if not isinstance(items, list):
        errors.append("CORRECTION_OUTBOX_ITEMS_INVALID")
    else:
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                errors.append("CORRECTION_OUTBOX_ITEM_INVALID")
                continue
            item_id = _clean(item.get("item_id"))
            if not item_id:
                errors.append("CORRECTION_OUTBOX_ITEM_ID_MISSING")
            elif item_id in seen:
                errors.append("CORRECTION_OUTBOX_DUPLICATE_ITEM_ID")
            seen.add(item_id)
            item_claimed = _clean(item.get("item_fingerprint_sha256")).lower()
            item_body = dict(item)
            item_body.pop("item_fingerprint_sha256", None)
            if not _is_sha256(item_claimed) or item_claimed != _digest(item_body):
                errors.append("CORRECTION_OUTBOX_ITEM_FINGERPRINT_INVALID")
    return sorted(set(errors))


def _manifest_errors(item: Mapping[str, Any], document: Mapping[str, Any], manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if _clean(manifest.get("instance_id")) != _clean(document.get("instance_id")):
        errors.append("CORRECTION_PRODUCT_INSTANCE_MISMATCH")
    if _clean(manifest.get("channel_id")).lower() != _clean(document.get("channel_id")).lower():
        errors.append("CORRECTION_PRODUCT_CHANNEL_MISMATCH")
    if _clean(manifest.get("platform")).lower() != _clean(document.get("platform")).lower():
        errors.append("CORRECTION_PRODUCT_PLATFORM_MISMATCH")
    if _clean(manifest.get("correction_story_id")) != _clean(item.get("correction_story_id")):
        errors.append("CORRECTION_PRODUCT_STORY_MISMATCH")
    if _clean(manifest.get("affected_publication_id")) != _clean(item.get("affected_publication_id")):
        errors.append("CORRECTION_PRODUCT_PUBLICATION_MISMATCH")
    if _clean(manifest.get("source_fact_kernel_sha256")).lower() != _clean(item.get("corrected_fact_kernel_sha256")).lower():
        errors.append("CORRECTION_PRODUCT_FACT_KERNEL_MISMATCH")
    if not _is_sha256(manifest.get("product_fingerprint_sha256")):
        errors.append("CORRECTION_PRODUCT_FINGERPRINT_INVALID")
    if _safe_relative_posix_path(manifest.get("product_path")) is None:
        errors.append("CORRECTION_PRODUCT_PATH_INVALID")
    if not _clean(manifest.get("native_format")):
        errors.append("CORRECTION_PRODUCT_NATIVE_FORMAT_MISSING")
    if not _clean(manifest.get("generator_version")):
        errors.append("CORRECTION_PRODUCT_GENERATOR_VERSION_MISSING")
    if _clean(manifest.get("regeneration_source")).upper() != "VERIFIED_CORRECTED_FACT_KERNEL":
        errors.append("CORRECTION_PRODUCT_REGENERATION_SOURCE_INVALID")
    if manifest.get("reuse_prior_copy") is not False:
        errors.append("CORRECTION_PRODUCT_PRIOR_COPY_REUSE_FORBIDDEN")
    if manifest.get("verbatim_cross_platform_reuse_allowed") is not False:
        errors.append("CORRECTION_PRODUCT_VERBATIM_CROSS_PLATFORM_REUSE_FORBIDDEN")
    if manifest.get("network_calls_performed") is not False:
        errors.append("CORRECTION_PRODUCT_NETWORK_CALL_FORBIDDEN")
    if manifest.get("credential_values_read") is not False:
        errors.append("CORRECTION_PRODUCT_CREDENTIAL_READ_FORBIDDEN")
    if manifest.get("zero_paid_dependency") is not True:
        errors.append("CORRECTION_PRODUCT_ZERO_PAID_REQUIRED")
    if _contains_forbidden_secret_field(manifest):
        errors.append("CORRECTION_PRODUCT_MANIFEST_CONTAINS_SECRET_FIELD")
    if _contains_editorial_copy(manifest):
        errors.append("CORRECTION_PRODUCT_MANIFEST_CONTAINS_EDITORIAL_COPY")

    original_fp = _clean(manifest.get("original_publication_product_fingerprint_sha256")).lower()
    product_fp = _clean(manifest.get("product_fingerprint_sha256")).lower()
    if original_fp:
        if not _is_sha256(original_fp):
            errors.append("ORIGINAL_PUBLICATION_PRODUCT_FINGERPRINT_INVALID")
        elif original_fp == product_fp:
            errors.append("CORRECTION_PRODUCT_REUSES_ORIGINAL_PRODUCT_FINGERPRINT")

    native_format = _clean(manifest.get("native_format")).lower()
    visual_fp = _clean(manifest.get("visual_provenance_sha256")).lower()
    if native_format in VISUAL_FORMATS:
        if not _is_sha256(visual_fp):
            errors.append("CORRECTION_VISUAL_PROVENANCE_REQUIRED")
    elif visual_fp and not _is_sha256(visual_fp):
        errors.append("CORRECTION_VISUAL_PROVENANCE_INVALID")
    return sorted(set(errors))


def _binding_from_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    binding = {
        "product_path": _clean(manifest.get("product_path")).replace("\\", "/"),
        "product_fingerprint_sha256": _clean(manifest.get("product_fingerprint_sha256")).lower(),
        "source_fact_kernel_sha256": _clean(manifest.get("source_fact_kernel_sha256")).lower(),
        "native_format": _clean(manifest.get("native_format")).lower(),
        "generator_version": _clean(manifest.get("generator_version")),
        "regeneration_source": "VERIFIED_CORRECTED_FACT_KERNEL",
        "original_publication_product_fingerprint_sha256": _clean(
            manifest.get("original_publication_product_fingerprint_sha256")
        ).lower() or None,
        "visual_provenance_sha256": _clean(manifest.get("visual_provenance_sha256")).lower() or None,
        "reuse_prior_copy": False,
        "verbatim_cross_platform_reuse_allowed": False,
    }
    binding["binding_fingerprint_sha256"] = _digest(binding)
    return binding


def bind_native_correction_product(
    correction_outbox: Mapping[str, Any],
    item_id: str,
    product_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind one regenerated native product without authorizing network dispatch."""
    if not isinstance(correction_outbox, Mapping):
        raise TypeError("correction_outbox must be a mapping")
    if not isinstance(product_manifest, Mapping):
        raise TypeError("product_manifest must be a mapping")

    errors = _validate_outbox(correction_outbox)
    source_fp = _clean(correction_outbox.get("outbox_fingerprint_sha256")).lower()
    if errors:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "BLOCKED",
            "changed": False,
            "holds": errors,
            "source_outbox_fingerprint_sha256": source_fp or None,
            "document": None,
            "guards": _result_guards(),
        }

    target_id = _clean(item_id)
    items = [dict(row) for row in correction_outbox.get("items", [])]
    matches = [row for row in items if _clean(row.get("item_id")) == target_id]
    if len(matches) != 1:
        reason = "CORRECTION_OUTBOX_ITEM_NOT_FOUND" if not matches else "CORRECTION_OUTBOX_ITEM_NOT_UNIQUE"
        return _blocked(source_fp, [reason])
    target = matches[0]

    existing_binding = target.get("native_product") if isinstance(target.get("native_product"), Mapping) else None
    candidate_binding = _binding_from_manifest(product_manifest)
    if _clean(target.get("status")).upper() == READY_FOR_DISPATCH_ROUTING:
        if existing_binding == candidate_binding:
            return {
                "schema_version": SCHEMA_VERSION,
                "status": "PASS",
                "changed": False,
                "holds": [],
                "source_outbox_fingerprint_sha256": source_fp,
                "document": dict(correction_outbox),
                "guards": _result_guards(),
            }
        return _blocked(source_fp, ["CORRECTION_PRODUCT_BINDING_CONFLICT"])
    if _clean(target.get("status")).upper() != READY_FOR_REGENERATION:
        return _blocked(source_fp, ["CORRECTION_ITEM_NOT_READY_FOR_NATIVE_REGENERATION"])

    manifest_errors = _manifest_errors(target, correction_outbox, product_manifest)
    if manifest_errors:
        return _blocked(source_fp, manifest_errors)

    updated_target = dict(target)
    updated_target["status"] = READY_FOR_DISPATCH_ROUTING
    updated_target["native_product"] = candidate_binding
    updated_target["dispatch"] = {
        "network_dispatch_allowed": False,
        "remote_edit_claimed": False,
        "requires_regenerated_native_product": False,
        "requires_adapter_capability_recheck": True,
    }
    updated_target["guards"] = {
        "credential_values_present": False,
        "editorial_copy_present": False,
        "network_calls_performed": False,
        "zero_paid_dependency": True,
    }
    updated_target.pop("item_fingerprint_sha256", None)
    updated_target["item_fingerprint_sha256"] = _digest(updated_target)

    updated_items = [updated_target if _clean(row.get("item_id")) == target_id else row for row in items]
    updated_document = dict(correction_outbox)
    updated_document["items"] = updated_items
    updated_document.pop("outbox_fingerprint_sha256", None)
    updated_document["outbox_fingerprint_sha256"] = _digest(updated_document)

    post_errors = _validate_outbox(updated_document)
    if post_errors:
        return _blocked(source_fp, ["CORRECTION_PRODUCT_POST_BIND_VALIDATION_FAILED", *post_errors])

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "changed": True,
        "holds": [],
        "source_outbox_fingerprint_sha256": source_fp,
        "document": updated_document,
        "binding": candidate_binding,
        "guards": _result_guards(),
    }


def _result_guards() -> dict[str, Any]:
    return {
        "network_calls_performed": False,
        "credential_values_read": False,
        "editorial_copy_materialized": False,
        "remote_edit_claimed": False,
        "adapter_dispatch_authorized": False,
        "zero_paid_dependency": True,
    }


def _blocked(source_fp: str, reasons: list[str]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCKED",
        "changed": False,
        "holds": sorted(set(reasons)),
        "source_outbox_fingerprint_sha256": source_fp or None,
        "document": None,
        "guards": _result_guards(),
    }


def persist_bound_correction_outbox(result: Mapping[str, Any], root: str | Path) -> dict[str, Any]:
    """Persist one bound correction outbox only if durable source state is unchanged."""
    if _clean(result.get("status")).upper() != "PASS" or not isinstance(result.get("document"), Mapping):
        raise ValueError("BLOCKED_CORRECTION_PRODUCT_BINDING_MUST_NOT_PERSIST")
    document = dict(result["document"])
    if not result.get("changed"):
        return {
            "status": "PASS",
            "persisted": False,
            "reason": "IDEMPOTENT_NO_CHANGE",
            "guards": _result_guards(),
        }

    relative = _safe_relative_posix_path(document.get("correction_outbox_path"))
    if relative is None:
        raise ValueError("CORRECTION_OUTBOX_PATH_INVALID")
    root_path = Path(root).resolve()
    destination = (root_path / Path(*relative.parts)).resolve()
    try:
        destination.relative_to(root_path)
    except ValueError as exc:
        raise ValueError("CORRECTION_OUTBOX_PATH_ESCAPES_ROOT") from exc
    if not destination.exists():
        raise ValueError("CORRECTION_NATIVE_PRODUCT_SOURCE_OUTBOX_MISSING")

    try:
        current = json.loads(destination.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("CORRECTION_NATIVE_PRODUCT_SOURCE_OUTBOX_UNREADABLE") from exc
    current_errors = _validate_outbox(current)
    if current_errors:
        raise ValueError("CORRECTION_NATIVE_PRODUCT_SOURCE_OUTBOX_INVALID:" + ",".join(current_errors))
    expected_source_fp = _clean(result.get("source_outbox_fingerprint_sha256")).lower()
    if _clean(current.get("outbox_fingerprint_sha256")).lower() != expected_source_fp:
        raise ValueError("CORRECTION_NATIVE_PRODUCT_PERSIST_CONFLICT")

    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, destination)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)

    readback = json.loads(destination.read_text(encoding="utf-8"))
    if readback != document:
        raise ValueError("CORRECTION_NATIVE_PRODUCT_READBACK_MISMATCH")
    return {
        "status": "PASS",
        "persisted": True,
        "path": str(relative),
        "outbox_fingerprint_sha256": document["outbox_fingerprint_sha256"],
        "guards": _result_guards(),
    }
