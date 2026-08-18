#!/usr/bin/env python3
"""Durable, fail-closed native correction outbox materialization.

This boundary consumes only routes produced by ``correction_dispatch_router`` with
``MATERIALIZE_NATIVE_CORRECTION_OUTBOX``. It creates channel-local sidecar outbox
documents that carry correction provenance and regeneration requirements, never
editorial copy or credentials.

The declared publication outbox is never overwritten. Correction state is derived
under ``<declared-outbox-parent>/corrections/<channel>.json`` so channels that share
one publication outbox still have independent durable correction state.

No network I/O is performed. Persistence uses atomic local replacement and verifies
that the durable state still matches the materialized document after write.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

SCHEMA_VERSION = "1.0"
MATERIALIZE_DECISION = "MATERIALIZE_NATIVE_CORRECTION_OUTBOX"
READY_STATUS = "READY_FOR_NATIVE_REGENERATION"
FORBIDDEN_SECRET_KEY_PARTS = {
    "token", "secret", "password", "authorization", "api_key", "apikey", "cookie", "bearer",
}
FORBIDDEN_COPY_KEYS = {
    "text", "caption", "message", "copy", "body", "headline", "hook", "script", "description",
}
CHANNEL_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    text = _clean(value).lower()
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text)


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


def _contains_copy_field(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if _clean(key).lower() in FORBIDDEN_COPY_KEYS:
                return True
            if _contains_copy_field(child):
                return True
    elif isinstance(value, list):
        return any(_contains_copy_field(item) for item in value)
    return False


def _safe_relative_posix_path(value: Any) -> PurePosixPath | None:
    text = _clean(value).replace("\\", "/")
    if not text:
        return None
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        return None
    return path


def derive_correction_outbox_path(route: Mapping[str, Any]) -> str:
    """Return a channel-local correction sidecar path without touching the normal outbox."""
    declared = _safe_relative_posix_path(route.get("outbox"))
    channel = _clean(route.get("channel_id")).lower()
    if declared is None:
        raise ValueError("CORRECTION_DECLARED_OUTBOX_PATH_INVALID")
    if not CHANNEL_RE.fullmatch(channel):
        raise ValueError("CORRECTION_CHANNEL_ID_PATH_UNSAFE")
    return str(declared.parent / "corrections" / f"{channel}.json")


def _route_errors(route: Mapping[str, Any], instance_id: str) -> list[str]:
    errors: list[str] = []
    if _clean(route.get("decision")).upper() != MATERIALIZE_DECISION:
        errors.append("CORRECTION_ROUTE_NOT_MATERIALIZATION")
    if route.get("dispatchable") is not False:
        errors.append("CORRECTION_OUTBOX_ROUTE_MUST_NOT_BE_DISPATCHABLE")
    if _clean(route.get("instance_id")) != instance_id:
        errors.append("CORRECTION_ROUTE_INSTANCE_MISMATCH")
    channel = _clean(route.get("channel_id")).lower()
    if not CHANNEL_RE.fullmatch(channel):
        errors.append("CORRECTION_ROUTE_CHANNEL_ID_INVALID")
    if not _clean(route.get("platform")):
        errors.append("CORRECTION_ROUTE_PLATFORM_MISSING")
    if not _clean(route.get("route_id")):
        errors.append("CORRECTION_ROUTE_ID_MISSING")
    if not _clean(route.get("action_id")):
        errors.append("CORRECTION_ROUTE_ACTION_ID_MISSING")
    if not _clean(route.get("correction_story_id")):
        errors.append("CORRECTION_ROUTE_STORY_ID_MISSING")
    if not _clean(route.get("affected_publication_id")):
        errors.append("CORRECTION_AFFECTED_PUBLICATION_ID_MISSING")
    if not _clean(route.get("remote_publication_id")):
        errors.append("CORRECTION_REMOTE_PUBLICATION_ID_MISSING")
    if not _is_sha256(route.get("fact_kernel_sha256")):
        errors.append("CORRECTION_FACT_KERNEL_FINGERPRINT_INVALID")
    if route.get("native_regeneration_required") is not True:
        errors.append("CORRECTION_NATIVE_REGENERATION_REQUIRED")
    if route.get("reuse_prior_copy") is not False:
        errors.append("CORRECTION_PRIOR_COPY_REUSE_FORBIDDEN")
    if route.get("verbatim_cross_platform_reuse_allowed") is not False:
        errors.append("CORRECTION_VERBATIM_CROSS_PLATFORM_REUSE_FORBIDDEN")
    if route.get("network_dispatch_performed") is not False:
        errors.append("CORRECTION_ROUTE_NETWORK_DISPATCH_FORBIDDEN")
    if route.get("credential_values_read") is not False:
        errors.append("CORRECTION_ROUTE_CREDENTIAL_READ_FORBIDDEN")
    if route.get("zero_paid_dependency") is not True:
        errors.append("CORRECTION_ROUTE_ZERO_PAID_REQUIRED")
    if _safe_relative_posix_path(route.get("outbox")) is None:
        errors.append("CORRECTION_DECLARED_OUTBOX_PATH_INVALID")
    if _contains_forbidden_secret_field(route):
        errors.append("CORRECTION_ROUTE_CONTAINS_SECRET_FIELD")
    if _contains_copy_field(route):
        errors.append("CORRECTION_ROUTE_CONTAINS_EDITORIAL_COPY")
    return sorted(set(errors))


def _item_from_route(route: Mapping[str, Any], dispatch_plan_fingerprint: str) -> dict[str, Any]:
    route_binding = {
        "route_id": _clean(route.get("route_id")),
        "action_id": _clean(route.get("action_id")),
        "instance_id": _clean(route.get("instance_id")),
        "channel_id": _clean(route.get("channel_id")).lower(),
        "platform": _clean(route.get("platform")).lower(),
        "correction_story_id": _clean(route.get("correction_story_id")),
        "affected_story_id": _clean(route.get("affected_story_id")) or None,
        "affected_publication_id": _clean(route.get("affected_publication_id")),
        "remote_publication_id": _clean(route.get("remote_publication_id")),
        "fact_kernel_sha256": _clean(route.get("fact_kernel_sha256")).lower(),
        "declared_publication_outbox": _clean(route.get("outbox")),
    }
    item_id = "correction-outbox:" + _digest(route_binding)[:24]
    item = {
        "item_id": item_id,
        "status": READY_STATUS,
        "instance_id": route_binding["instance_id"],
        "channel_id": route_binding["channel_id"],
        "platform": route_binding["platform"],
        "correction_story_id": route_binding["correction_story_id"],
        "affected_story_id": route_binding["affected_story_id"],
        "affected_publication_id": route_binding["affected_publication_id"],
        "remote_publication_id": route_binding["remote_publication_id"],
        "source_route_id": route_binding["route_id"],
        "source_action_id": route_binding["action_id"],
        "source_dispatch_plan_fingerprint_sha256": dispatch_plan_fingerprint,
        "corrected_fact_kernel_sha256": route_binding["fact_kernel_sha256"],
        "native_regeneration": {
            "required": True,
            "source": "VERIFIED_CORRECTED_FACT_KERNEL",
            "reuse_prior_copy": False,
            "verbatim_cross_platform_reuse_allowed": False,
        },
        "dispatch": {
            "network_dispatch_allowed": False,
            "remote_edit_claimed": False,
            "requires_regenerated_native_product": True,
        },
        "provenance": {
            "route_binding_sha256": _digest(route_binding),
            "declared_publication_outbox": route_binding["declared_publication_outbox"],
        },
        "guards": {
            "credential_values_present": False,
            "editorial_copy_present": False,
            "network_calls_performed": False,
            "zero_paid_dependency": True,
        },
    }
    item["item_fingerprint_sha256"] = _digest(item)
    return item


def _validate_existing_outbox(
    existing: Mapping[str, Any],
    *,
    instance_id: str,
    channel_id: str,
    platform: str,
    correction_outbox_path: str,
    declared_publication_outbox: str,
) -> list[str]:
    errors: list[str] = []
    if _clean(existing.get("instance_id")) != instance_id:
        errors.append("EXISTING_CORRECTION_OUTBOX_INSTANCE_MISMATCH")
    if _clean(existing.get("channel_id")).lower() != channel_id:
        errors.append("EXISTING_CORRECTION_OUTBOX_CHANNEL_MISMATCH")
    if _clean(existing.get("platform")).lower() != platform:
        errors.append("EXISTING_CORRECTION_OUTBOX_PLATFORM_MISMATCH")
    if _clean(existing.get("correction_outbox_path")) != correction_outbox_path:
        errors.append("EXISTING_CORRECTION_OUTBOX_PATH_MISMATCH")
    if _clean(existing.get("declared_publication_outbox")) != declared_publication_outbox:
        errors.append("EXISTING_PUBLICATION_OUTBOX_BINDING_MISMATCH")
    claimed_outbox_fingerprint = _clean(existing.get("outbox_fingerprint_sha256")).lower()
    fingerprint_body = dict(existing)
    fingerprint_body.pop("outbox_fingerprint_sha256", None)
    if not _is_sha256(claimed_outbox_fingerprint) or claimed_outbox_fingerprint != _digest(fingerprint_body):
        errors.append("EXISTING_CORRECTION_OUTBOX_FINGERPRINT_INVALID")
    if existing.get("guards", {}).get("zero_paid_dependency") is not True:
        errors.append("EXISTING_CORRECTION_OUTBOX_ZERO_PAID_GUARD_MISSING")
    if _contains_forbidden_secret_field(existing):
        errors.append("EXISTING_CORRECTION_OUTBOX_CONTAINS_SECRET_FIELD")
    if _contains_copy_field(existing):
        errors.append("EXISTING_CORRECTION_OUTBOX_CONTAINS_EDITORIAL_COPY")
    items = existing.get("items")
    if not isinstance(items, list):
        errors.append("EXISTING_CORRECTION_OUTBOX_ITEMS_INVALID")
    else:
        ids: set[str] = set()
        for row in items:
            if not isinstance(row, dict):
                errors.append("EXISTING_CORRECTION_OUTBOX_ITEM_INVALID")
                continue
            item_id = _clean(row.get("item_id"))
            if not item_id:
                errors.append("EXISTING_CORRECTION_OUTBOX_ITEM_ID_MISSING")
            elif item_id in ids:
                errors.append("EXISTING_CORRECTION_OUTBOX_DUPLICATE_ITEM_ID")
            ids.add(item_id)
            claimed = _clean(row.get("item_fingerprint_sha256")).lower()
            body = dict(row)
            body.pop("item_fingerprint_sha256", None)
            if not _is_sha256(claimed) or claimed != _digest(body):
                errors.append("EXISTING_CORRECTION_OUTBOX_ITEM_FINGERPRINT_INVALID")
    return sorted(set(errors))


def _build_outbox_document(
    *,
    route: Mapping[str, Any],
    dispatch_plan_fingerprint: str,
    existing: Mapping[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[str], bool]:
    instance_id = _clean(route.get("instance_id"))
    channel_id = _clean(route.get("channel_id")).lower()
    platform = _clean(route.get("platform")).lower()
    declared = _clean(route.get("outbox"))
    correction_path = derive_correction_outbox_path(route)
    new_item = _item_from_route(route, dispatch_plan_fingerprint)
    existing_items: list[dict[str, Any]] = []
    if existing is not None:
        errors = _validate_existing_outbox(
            existing,
            instance_id=instance_id,
            channel_id=channel_id,
            platform=platform,
            correction_outbox_path=correction_path,
            declared_publication_outbox=declared,
        )
        if errors:
            return None, errors, False
        existing_items = [dict(row) for row in existing.get("items", [])]

    same_id = [row for row in existing_items if _clean(row.get("item_id")) == new_item["item_id"]]
    if same_id:
        if same_id[0] != new_item:
            return None, ["CORRECTION_OUTBOX_DEDUPE_FINGERPRINT_CONFLICT"], False
        changed = False
    else:
        same_correction = [
            row for row in existing_items
            if _clean(row.get("correction_story_id")) == new_item["correction_story_id"]
            and _clean(row.get("affected_publication_id")) == new_item["affected_publication_id"]
        ]
        if same_correction:
            return None, ["CORRECTION_OUTBOX_CORRECTION_IDENTITY_CONFLICT"], False
        existing_items.append(new_item)
        changed = True

    existing_items.sort(key=lambda row: (_clean(row.get("correction_story_id")), _clean(row.get("item_id"))))
    document = {
        "schema_version": SCHEMA_VERSION,
        "instance_id": instance_id,
        "channel_id": channel_id,
        "platform": platform,
        "declared_publication_outbox": declared,
        "correction_outbox_path": correction_path,
        "items": existing_items,
        "guards": {
            "channel_local_state": True,
            "normal_publication_outbox_overwritten": False,
            "credential_values_present": False,
            "editorial_copy_present": False,
            "network_calls_performed": False,
            "zero_paid_dependency": True,
        },
    }
    document["outbox_fingerprint_sha256"] = _digest(document)
    return document, [], changed


def materialize_native_correction_outboxes(
    dispatch_plan: Mapping[str, Any],
    existing_outboxes: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Materialize all safe correction-outbox routes into channel-local documents."""
    if not isinstance(dispatch_plan, Mapping):
        raise TypeError("dispatch_plan must be a mapping")
    if existing_outboxes is not None and not isinstance(existing_outboxes, Mapping):
        raise TypeError("existing_outboxes must be a mapping")

    instance_id = _clean(dispatch_plan.get("instance_id"))
    hard_blocks: list[str] = []
    if not instance_id:
        hard_blocks.append("CORRECTION_DISPATCH_PLAN_INSTANCE_ID_MISSING")
    if dispatch_plan.get("blocked") is True or _clean(dispatch_plan.get("status")).upper() == "BLOCKED":
        hard_blocks.append("UPSTREAM_CORRECTION_DISPATCH_PLAN_BLOCKED")
    fingerprint = _clean(dispatch_plan.get("dispatch_plan_fingerprint_sha256")).lower()
    if not _is_sha256(fingerprint):
        hard_blocks.append("CORRECTION_DISPATCH_PLAN_FINGERPRINT_INVALID")
    guards = dispatch_plan.get("guards") if isinstance(dispatch_plan.get("guards"), Mapping) else {}
    if guards.get("zero_paid_dependency") is not True:
        hard_blocks.append("CORRECTION_DISPATCH_PLAN_ZERO_PAID_GUARD_MISSING")
    if guards.get("network_calls_performed") is not False:
        hard_blocks.append("CORRECTION_DISPATCH_PLAN_NETWORK_GUARD_INVALID")
    if guards.get("prior_social_copy_reused") is not False:
        hard_blocks.append("CORRECTION_DISPATCH_PLAN_COPY_REUSE_GUARD_INVALID")
    if _contains_forbidden_secret_field(dispatch_plan):
        hard_blocks.append("CORRECTION_DISPATCH_PLAN_CONTAINS_SECRET_FIELD")

    routes = dispatch_plan.get("routes")
    if not isinstance(routes, list):
        hard_blocks.append("CORRECTION_DISPATCH_PLAN_ROUTES_INVALID")
        routes = []

    if hard_blocks:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "BLOCKED",
            "blocked": True,
            "instance_id": instance_id or None,
            "hard_blocks": sorted(set(hard_blocks)),
            "outboxes": [],
            "holds": [],
            "guards": {
                "network_calls_performed": False,
                "credential_values_read": False,
                "editorial_copy_materialized": False,
                "normal_publication_outbox_overwritten": False,
                "zero_paid_dependency": True,
            },
        }

    existing_outboxes = existing_outboxes or {}
    outbox_map: dict[str, dict[str, Any]] = {}
    holds: list[dict[str, Any]] = []
    skipped_non_materialization = 0

    for raw in routes:
        if not isinstance(raw, Mapping):
            holds.append({"route_id": None, "reasons": ["CORRECTION_ROUTE_NOT_MAPPING"]})
            continue
        if _clean(raw.get("decision")).upper() != MATERIALIZE_DECISION:
            skipped_non_materialization += 1
            continue
        errors = _route_errors(raw, instance_id)
        if errors:
            holds.append({
                "route_id": _clean(raw.get("route_id")) or None,
                "channel_id": _clean(raw.get("channel_id")) or None,
                "reasons": errors,
            })
            continue
        correction_path = derive_correction_outbox_path(raw)
        prior_row = outbox_map.get(correction_path)
        if prior_row is not None:
            existing = prior_row["document"]
        else:
            existing = existing_outboxes.get(correction_path)
        if existing is not None and not isinstance(existing, Mapping):
            holds.append({
                "route_id": _clean(raw.get("route_id")) or None,
                "channel_id": _clean(raw.get("channel_id")) or None,
                "reasons": ["EXISTING_CORRECTION_OUTBOX_INVALID"],
            })
            continue
        document, doc_errors, changed = _build_outbox_document(
            route=raw,
            dispatch_plan_fingerprint=fingerprint,
            existing=existing,
        )
        if doc_errors or document is None:
            holds.append({
                "route_id": _clean(raw.get("route_id")) or None,
                "channel_id": _clean(raw.get("channel_id")) or None,
                "reasons": doc_errors or ["CORRECTION_OUTBOX_BUILD_FAILED"],
            })
            continue
        outbox_map[correction_path] = {
            "path": correction_path,
            "changed": bool(changed or (prior_row and prior_row.get("changed"))),
            "document": document,
        }

    outboxes = sorted(outbox_map.values(), key=lambda row: row["path"])
    holds.sort(key=_canonical)
    status = "PASS" if not holds else ("PARTIAL" if outboxes else "BLOCKED")
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "blocked": status == "BLOCKED",
        "instance_id": instance_id,
        "dispatch_plan_fingerprint_sha256": fingerprint,
        "materialized_outbox_count": len(outboxes),
        "changed_outbox_count": sum(1 for row in outboxes if row["changed"]),
        "skipped_non_materialization_route_count": skipped_non_materialization,
        "outboxes": outboxes,
        "holds": holds,
        "guards": {
            "channel_local_state": True,
            "network_calls_performed": False,
            "credential_values_read": False,
            "editorial_copy_materialized": False,
            "normal_publication_outbox_overwritten": False,
            "zero_paid_dependency": True,
        },
    }
    result["materialization_fingerprint_sha256"] = _digest({
        "instance_id": instance_id,
        "dispatch_plan_fingerprint_sha256": fingerprint,
        "outboxes": outboxes,
        "holds": holds,
    })
    return result


def persist_materialized_outboxes(materialization: Mapping[str, Any], repo_root: str | Path) -> dict[str, Any]:
    """Persist PASS/PARTIAL materialization outputs atomically and read them back exactly."""
    if not isinstance(materialization, Mapping):
        raise TypeError("materialization must be a mapping")
    if materialization.get("blocked") is True or _clean(materialization.get("status")).upper() == "BLOCKED":
        raise ValueError("BLOCKED_CORRECTION_MATERIALIZATION_MUST_NOT_PERSIST")
    root = Path(repo_root).resolve()
    outboxes = materialization.get("outboxes")
    if not isinstance(outboxes, list):
        raise ValueError("CORRECTION_MATERIALIZATION_OUTBOXES_INVALID")

    persisted: list[dict[str, Any]] = []
    for row in outboxes:
        if not isinstance(row, Mapping):
            raise ValueError("CORRECTION_MATERIALIZATION_OUTBOX_ROW_INVALID")
        rel = _safe_relative_posix_path(row.get("path"))
        document = row.get("document")
        if rel is None or not isinstance(document, Mapping):
            raise ValueError("CORRECTION_MATERIALIZATION_OUTBOX_ROW_INVALID")
        target = (root / Path(*rel.parts)).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError("CORRECTION_OUTBOX_PATH_ESCAPES_REPO_ROOT") from exc
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.is_symlink():
            raise ValueError("CORRECTION_OUTBOX_SYMLINK_TARGET_FORBIDDEN")
        payload = json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent), text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        readback = json.loads(target.read_text(encoding="utf-8"))
        if readback != dict(document):
            raise RuntimeError("CORRECTION_OUTBOX_POST_WRITE_READBACK_MISMATCH")
        persisted.append({
            "path": str(rel),
            "outbox_fingerprint_sha256": _clean(document.get("outbox_fingerprint_sha256")),
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "persisted_count": len(persisted),
        "persisted": persisted,
        "guards": {
            "network_calls_performed": False,
            "credential_values_read": False,
            "normal_publication_outbox_overwritten": False,
            "zero_paid_dependency": True,
        },
    }
