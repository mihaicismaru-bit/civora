#!/usr/bin/env python3
"""Bind confirmed social publications to a durable observed-metrics catalog.

The production social runtime deliberately keeps analytics outside the publication
path. The harvest scheduler, however, needs authoritative publication context that
legacy adapter state does not contain: native format, topic keys and optional
series identity in addition to the remote publication proof.

This bridge closes that gap without reverse-engineering historical posts. It binds
one verified STORY_OBJECT and its exact Production Runtime native product to a
separately confirmed PUBLISHED record, then materializes a sealed, channel-local
catalog that the existing metrics harvest scheduler can consume directly.

Safety properties:
- no network calls and no credential values;
- remote publication proof is mandatory before a descriptor can exist;
- fact-kernel and native-product fingerprints are revalidated;
- topics come only from the verified story and native format only from the native
  product; provider/analytics payloads are never consulted;
- predictive fields and unrelated story metadata cannot enter the descriptor;
- same publication + same evidence is idempotent; conflicting evidence fails closed;
- catalog identity is isolated by instance_id + channel_id + platform;
- legacy adapter ``published`` maps are never guessed or silently backfilled;
- a metrics/catalog problem never changes the publication's already-established
  editorial or dispatch state.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

import content_atomizer
import observed_metrics_collector

SCHEMA_VERSION = "1.0"
CATALOG_ID = "local-news-os-publication-metrics-catalog"


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _valid_hash(value: Any) -> bool:
    text = _clean(value).lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _valid_timestamp(value: Any) -> bool:
    text = _clean(value)
    if not text:
        return False
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _product_fingerprint_valid(product: dict[str, Any]) -> bool:
    supplied = _clean(product.get("product_fingerprint_sha256")).lower()
    if not _valid_hash(supplied):
        return False
    payload = _clone(product)
    payload.pop("product_fingerprint_sha256", None)
    return supplied == _digest(payload)


def expected_catalog_path(channel: dict[str, Any]) -> str:
    """Derive a channel-local catalog path from publication_state.state_path."""
    if not isinstance(channel, dict):
        raise TypeError("channel must be a mapping")
    publication_state = channel.get("publication_state") if isinstance(channel.get("publication_state"), dict) else {}
    raw = _clean(publication_state.get("state_path"))
    if not raw:
        raise ValueError("channel publication_state.state_path is required")
    path = PurePosixPath(raw.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or path.name in {"", "."}:
        raise ValueError("unsafe channel publication state path")
    name = path.name
    stem = name[:-5] if name.endswith(".json") else name
    return str(path.with_name(f"{stem}_metrics_publications.json"))


def _catalog_fingerprint(catalog: dict[str, Any]) -> str:
    payload = _clone(catalog)
    payload.pop("catalog_fingerprint_sha256", None)
    return _digest(payload)


def _descriptor_fingerprint(descriptor: dict[str, Any]) -> str:
    payload = _clone(descriptor)
    payload.pop("descriptor_fingerprint_sha256", None)
    return _digest(payload)


def empty_catalog(channel: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(channel, dict):
        raise TypeError("channel must be a mapping")
    catalog = {
        "schema_version": SCHEMA_VERSION,
        "catalog_id": CATALOG_ID,
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "storage_path": expected_catalog_path(channel),
        "records": {},
        "guards": {
            "remote_publication_proof_required": True,
            "authoritative_fact_kernel_required": True,
            "native_product_identity_required": True,
            "legacy_descriptor_fabrication_allowed": False,
            "predictive_or_estimated_analytics_used": False,
            "credential_values_persisted": False,
            "publication_blocked_by_metrics_catalog": False,
            "cross_channel_catalog_sharing": False,
            "zero_paid_dependency": True,
        },
    }
    catalog["catalog_fingerprint_sha256"] = _catalog_fingerprint(catalog)
    return catalog


def validate_catalog(channel: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(channel, dict) or not isinstance(catalog, dict):
        raise TypeError("channel and catalog must be mappings")
    blocks: list[str] = []
    if _clean(catalog.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("CATALOG_SCHEMA_VERSION")
    if _clean(catalog.get("catalog_id")) != CATALOG_ID:
        blocks.append("CATALOG_ID_MISMATCH")
    if _clean(catalog.get("instance_id")) != _clean(channel.get("instance_id")):
        blocks.append("CATALOG_INSTANCE_MISMATCH")
    if _clean(catalog.get("channel_id")) != _clean(channel.get("channel_id")):
        blocks.append("CATALOG_CHANNEL_MISMATCH")
    if _clean(catalog.get("platform")).lower() != _clean(channel.get("platform")).lower():
        blocks.append("CATALOG_PLATFORM_MISMATCH")
    try:
        expected_path = expected_catalog_path(channel)
    except (TypeError, ValueError):
        expected_path = ""
        blocks.append("CATALOG_PATH_POLICY_INVALID")
    if expected_path and _clean(catalog.get("storage_path")) != expected_path:
        blocks.append("CATALOG_PATH_MISMATCH")
    records = catalog.get("records")
    if not isinstance(records, dict):
        blocks.append("CATALOG_RECORDS_INVALID")
        records = {}
    supplied_fp = _clean(catalog.get("catalog_fingerprint_sha256")).lower()
    if not _valid_hash(supplied_fp) or supplied_fp != _catalog_fingerprint(catalog):
        blocks.append("CATALOG_FINGERPRINT_INVALID")
    guards = catalog.get("guards") if isinstance(catalog.get("guards"), dict) else {}
    if guards.get("zero_paid_dependency") is not True:
        blocks.append("CATALOG_ZERO_PAID_GUARD")
    if guards.get("credential_values_persisted") is not False:
        blocks.append("CATALOG_CREDENTIAL_GUARD")
    if guards.get("predictive_or_estimated_analytics_used") is not False:
        blocks.append("CATALOG_PREDICTIVE_GUARD")
    if guards.get("publication_blocked_by_metrics_catalog") is not False:
        blocks.append("CATALOG_PUBLICATION_GATE_VIOLATION")
    for key, descriptor in records.items():
        if not isinstance(descriptor, dict):
            blocks.append("CATALOG_DESCRIPTOR_INVALID:" + _clean(key))
            continue
        if _clean(descriptor.get("publication_id")) != _clean(key):
            blocks.append("CATALOG_DESCRIPTOR_KEY_MISMATCH:" + _clean(key))
        supplied = _clean(descriptor.get("descriptor_fingerprint_sha256")).lower()
        if not _valid_hash(supplied) or supplied != _descriptor_fingerprint(descriptor):
            blocks.append("DESCRIPTOR_FINGERPRINT_INVALID:" + _clean(key))
    return {"valid": not blocks, "hard_blocks": sorted(set(blocks))}


def _channel_blocks(channel: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    if not _clean(channel.get("instance_id")):
        blocks.append("MISSING_INSTANCE_ID")
    if not _clean(channel.get("channel_id")):
        blocks.append("MISSING_CHANNEL_ID")
    if not _clean(channel.get("platform")):
        blocks.append("MISSING_PLATFORM")
    if channel.get("zero_paid_dependency") is not True:
        blocks.append("ZERO_PAID_DEPENDENCY_VIOLATION")
    metrics = channel.get("metrics") if isinstance(channel.get("metrics"), dict) else {}
    if metrics.get("observed_only") is not True:
        blocks.append("OBSERVED_ONLY_REQUIRED")
    try:
        expected_catalog_path(channel)
    except (TypeError, ValueError):
        blocks.append("CATALOG_PATH_POLICY_INVALID")
    return sorted(set(blocks))


def _series_id(runtime_result: dict[str, Any], story_id: str) -> str | None:
    artifacts = runtime_result.get("artifacts") if isinstance(runtime_result.get("artifacts"), dict) else {}
    decision = artifacts.get("series_decision") if isinstance(artifacts.get("series_decision"), dict) else {}
    if decision.get("eligible") is not True or _clean(decision.get("decision")) != "SERIES_READY":
        return None
    occurrence = decision.get("occurrence") if isinstance(decision.get("occurrence"), dict) else {}
    selected = occurrence.get("selected_story_ids") if isinstance(occurrence.get("selected_story_ids"), list) else []
    if story_id not in {_clean(value) for value in selected if _clean(value)}:
        return None
    return _clean(occurrence.get("series_id")) or None


def _topics(story: dict[str, Any]) -> list[str]:
    raw = story.get("topics")
    if not isinstance(raw, list):
        return []
    return sorted({_clean(value) for value in raw if isinstance(value, str) and _clean(value)})


def _binding_blocks(
    channel: dict[str, Any],
    story: dict[str, Any],
    runtime_result: dict[str, Any],
    published_record: dict[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    blocks = _channel_blocks(channel)
    components: dict[str, Any] = {}
    instance_id = _clean(channel.get("instance_id"))
    channel_id = _clean(channel.get("channel_id"))
    platform = _clean(channel.get("platform")).lower()
    story_id = _clean(story.get("story_id") or story.get("id"))

    if not story_id:
        blocks.append("MISSING_STORY_ID")
    if _clean(story.get("instance_id")) != instance_id:
        blocks.append("STORY_INSTANCE_MISMATCH")
    if runtime_result.get("blocked") is True:
        blocks.append("RUNTIME_RESULT_BLOCKED")
    for key, expected, code in (
        ("instance_id", instance_id, "RUNTIME_INSTANCE_MISMATCH"),
        ("channel_id", channel_id, "RUNTIME_CHANNEL_MISMATCH"),
        ("story_id", story_id, "RUNTIME_STORY_MISMATCH"),
    ):
        if _clean(runtime_result.get(key)) != expected:
            blocks.append(code)
    if _clean(runtime_result.get("platform")).lower() != platform:
        blocks.append("RUNTIME_PLATFORM_MISMATCH")
    runtime_guards = runtime_result.get("guards") if isinstance(runtime_result.get("guards"), dict) else {}
    if runtime_guards.get("zero_paid_dependency") is not True:
        blocks.append("RUNTIME_ZERO_PAID_GUARD")
    if runtime_guards.get("predictive_analytics_used") is not False:
        blocks.append("RUNTIME_PREDICTIVE_ANALYTICS_GUARD")
    if runtime_guards.get("credential_values_read") is not False or runtime_guards.get("credential_values_exposed") is not False:
        blocks.append("RUNTIME_CREDENTIAL_BOUNDARY_VIOLATION")

    artifacts = runtime_result.get("artifacts") if isinstance(runtime_result.get("artifacts"), dict) else {}
    atom_bundle = artifacts.get("atom_bundle") if isinstance(artifacts.get("atom_bundle"), dict) else {}
    formatted = artifacts.get("format") if isinstance(artifacts.get("format"), dict) else {}
    product = formatted.get("product") if isinstance(formatted.get("product"), dict) else {}
    publication = artifacts.get("publication") if isinstance(artifacts.get("publication"), dict) else {}
    prepared_record = publication.get("record") if isinstance(publication.get("record"), dict) else {}
    components.update({"atom_bundle": atom_bundle, "format_result": formatted, "product": product, "prepared_record": prepared_record})

    if not atom_bundle or not product or not prepared_record:
        blocks.append("MISSING_AUTHORITATIVE_RUNTIME_ARTIFACTS")
    if formatted:
        if _clean(formatted.get("instance_id")) != instance_id:
            blocks.append("FORMAT_INSTANCE_MISMATCH")
        if _clean(formatted.get("channel_id")) != channel_id:
            blocks.append("FORMAT_CHANNEL_MISMATCH")
        if _clean(formatted.get("platform")).lower() != platform:
            blocks.append("FORMAT_PLATFORM_MISMATCH")
        if _clean(formatted.get("story_id")) != story_id:
            blocks.append("FORMAT_STORY_MISMATCH")
    if product:
        if not _product_fingerprint_valid(product):
            blocks.append("PRODUCT_FINGERPRINT_INVALID")
        if not _clean(product.get("product_id")):
            blocks.append("MISSING_PRODUCT_ID")
        if not _clean(product.get("native_format")):
            blocks.append("MISSING_NATIVE_FORMAT")
        if _clean(product.get("cross_post_policy")) != "NATIVE_PRODUCT_ONLY":
            blocks.append("INVALID_CROSS_POST_POLICY")
        if product.get("verbatim_cross_platform_reuse_allowed") is not False:
            blocks.append("VERBATIM_CROSS_PLATFORM_REUSE")
        if product.get("analytics_used") is not False:
            blocks.append("PRODUCT_ANALYTICS_POLICY")

    reatomized = content_atomizer.atomize_story(story)
    components["reatomized"] = reatomized
    if reatomized.get("blocked") is True:
        blocks.append("FACT_KERNEL_NOT_ELIGIBLE")
    source_fp = _clean(reatomized.get("source_fingerprint_sha256")).lower()
    if not _valid_hash(source_fp):
        blocks.append("FACT_KERNEL_FINGERPRINT_MISSING")
    elif _clean(atom_bundle.get("source_fingerprint_sha256")).lower() != source_fp:
        blocks.append("FACT_KERNEL_FINGERPRINT_MISMATCH")

    product_id = _clean(product.get("product_id"))
    product_fp = _clean(product.get("product_fingerprint_sha256")).lower()
    publication_id = _clean(prepared_record.get("publication_id"))
    if not publication_id:
        blocks.append("MISSING_PREPARED_PUBLICATION_ID")
    if _clean(prepared_record.get("instance_id")) != instance_id:
        blocks.append("PREPARED_INSTANCE_MISMATCH")
    if _clean(prepared_record.get("channel_id")) != channel_id:
        blocks.append("PREPARED_CHANNEL_MISMATCH")
    if _clean(prepared_record.get("platform")).lower() != platform:
        blocks.append("PREPARED_PLATFORM_MISMATCH")
    if _clean(prepared_record.get("story_id")) != story_id:
        blocks.append("PREPARED_STORY_MISMATCH")
    if _clean(prepared_record.get("product_id")) != product_id:
        blocks.append("PREPARED_PRODUCT_MISMATCH")
    if _clean(prepared_record.get("product_fingerprint_sha256")).lower() != product_fp:
        blocks.append("PREPARED_PRODUCT_FINGERPRINT_MISMATCH")

    if _clean(published_record.get("status")).upper() != "PUBLISHED":
        blocks.append("REMOTE_PUBLICATION_NOT_CONFIRMED")
    for key, expected, code in (
        ("instance_id", instance_id, "PUBLISHED_INSTANCE_MISMATCH"),
        ("channel_id", channel_id, "PUBLISHED_CHANNEL_MISMATCH"),
        ("story_id", story_id, "PUBLISHED_STORY_MISMATCH"),
        ("publication_id", publication_id, "PUBLISHED_PUBLICATION_ID_MISMATCH"),
        ("product_id", product_id, "PUBLISHED_PRODUCT_MISMATCH"),
    ):
        if _clean(published_record.get(key)) != expected:
            blocks.append(code)
    if _clean(published_record.get("platform")).lower() != platform:
        blocks.append("PUBLISHED_PLATFORM_MISMATCH")
    published_product_fp = _clean(published_record.get("product_fingerprint_sha256")).lower()
    if published_product_fp and published_product_fp != product_fp:
        blocks.append("PUBLISHED_PRODUCT_FINGERPRINT_MISMATCH")
    if not _clean(published_record.get("remote_publication_id")):
        blocks.append("MISSING_REMOTE_PUBLICATION_ID")
    if not _valid_timestamp(published_record.get("published_at")):
        blocks.append("INVALID_PUBLISHED_AT")

    components.update({
        "story_id": story_id,
        "product_id": product_id,
        "product_fingerprint_sha256": product_fp,
        "publication_id": publication_id,
        "source_fingerprint_sha256": source_fp,
    })
    return sorted(set(blocks)), components


def _blocked_result(channel: dict[str, Any], catalog: dict[str, Any], blocks: list[str]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_id": CATALOG_ID,
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "blocked": True,
        "publication_blocked": False,
        "hard_blocks": sorted(set(blocks)),
        "decision": "HOLD_DESCRIPTOR_BINDING",
        "descriptor": None,
        "catalog": _clone(catalog),
        "materialization": None,
        "guards": {
            "publication_state_mutated": False,
            "network_calls_performed": False,
            "credential_values_read": False,
            "credential_values_persisted": False,
            "predictive_or_estimated_analytics_used": False,
            "zero_paid_dependency": True,
        },
    }


def bind_published_publication(
    channel: dict[str, Any],
    story: dict[str, Any],
    runtime_result: dict[str, Any],
    published_record: dict[str, Any],
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind one confirmed publication to an immutable metrics descriptor.

    ``published_record`` is the generic durable publication record after adapter
    confirmation/reconciliation. The function never changes that record. It only
    creates or advances a separate metrics-publication catalog.
    """
    if not all(isinstance(value, dict) for value in (channel, story, runtime_result, published_record)):
        raise TypeError("channel, story, runtime_result and published_record must be mappings")
    if catalog is not None and not isinstance(catalog, dict):
        raise TypeError("catalog must be a mapping when provided")

    current = _clone(catalog) if catalog is not None else empty_catalog(channel)
    if catalog is not None:
        checked = validate_catalog(channel, current)
        if checked.get("valid") is not True:
            return _blocked_result(channel, current, list(checked.get("hard_blocks", [])))
    previous_fp = _clean(current.get("catalog_fingerprint_sha256")) or None

    blocks, components = _binding_blocks(channel, story, runtime_result, published_record)
    if blocks:
        return _blocked_result(channel, current, blocks)

    product = components["product"]
    descriptor = {
        "schema_version": SCHEMA_VERSION,
        "instance_id": _clean(channel.get("instance_id")),
        "channel_id": _clean(channel.get("channel_id")),
        "platform": _clean(channel.get("platform")).lower(),
        "status": "PUBLISHED",
        "publication_id": components["publication_id"],
        "remote_publication_id": _clean(published_record.get("remote_publication_id")),
        "story_id": components["story_id"],
        "product_id": components["product_id"],
        "published_at": _clean(published_record.get("published_at")),
        "native_format": _clean(product.get("native_format")).lower(),
        "topic_keys": _topics(story),
        "series_id": _series_id(runtime_result, components["story_id"]),
        "binding_provenance": {
            "fact_kernel_sha256": components["source_fingerprint_sha256"],
            "product_fingerprint_sha256": components["product_fingerprint_sha256"],
            "publication_dedupe_key": _clean(published_record.get("dedupe_key")) or None,
            "binding_method": "verified_fact_kernel_plus_native_product_plus_remote_proof",
        },
        "guards": {
            "observed_metrics_context_only": True,
            "native_product_only": True,
            "verbatim_cross_platform_reuse_allowed": False,
            "predictive_or_estimated_analytics_used": False,
            "credential_values_persisted": False,
            "legacy_descriptor_fabricated": False,
            "publication_blocked_by_descriptor": False,
            "zero_paid_dependency": True,
        },
    }
    descriptor["descriptor_fingerprint_sha256"] = _descriptor_fingerprint(descriptor)

    validation = observed_metrics_collector.validate_publication_descriptor(channel, descriptor)
    if validation.get("valid") is not True:
        return _blocked_result(channel, current, list(validation.get("hard_blocks", [])))

    records = current["records"]
    publication_id = descriptor["publication_id"]
    existing = records.get(publication_id)
    if isinstance(existing, dict):
        if _clean(existing.get("descriptor_fingerprint_sha256")) == descriptor["descriptor_fingerprint_sha256"]:
            decision = "DEDUPE_EXISTING_DESCRIPTOR"
            result_catalog = current
            descriptor = _clone(existing)
        else:
            return _blocked_result(channel, current, ["PUBLICATION_DESCRIPTOR_CONFLICT"])
    else:
        records[publication_id] = _clone(descriptor)
        current["catalog_fingerprint_sha256"] = _catalog_fingerprint(current)
        result_catalog = current
        decision = "BOUND_PUBLISHED_DESCRIPTOR"

    materialization = {
        "path": expected_catalog_path(channel),
        "compare_and_swap_required": True,
        "expected_previous_catalog_fingerprint_sha256": previous_fp,
        "result_catalog_fingerprint_sha256": result_catalog["catalog_fingerprint_sha256"],
        "publication_state_mutated": False,
        "persist_before_harvest_required": True,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_id": CATALOG_ID,
        "instance_id": _clean(channel.get("instance_id")),
        "channel_id": _clean(channel.get("channel_id")),
        "platform": _clean(channel.get("platform")).lower(),
        "blocked": False,
        "publication_blocked": False,
        "hard_blocks": [],
        "decision": decision,
        "descriptor": descriptor,
        "catalog": result_catalog,
        "materialization": materialization,
        "guards": {
            "publication_state_mutated": False,
            "network_calls_performed": False,
            "credential_values_read": False,
            "credential_values_persisted": False,
            "predictive_or_estimated_analytics_used": False,
            "zero_paid_dependency": True,
        },
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("channel", type=Path)
    parser.add_argument("story", type=Path)
    parser.add_argument("runtime_result", type=Path)
    parser.add_argument("published_record", type=Path)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = bind_published_publication(
        _load(args.channel),
        _load(args.story),
        _load(args.runtime_result),
        _load(args.published_record),
        _load(args.catalog) if args.catalog else None,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 2 if result["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
