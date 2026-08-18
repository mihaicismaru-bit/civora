#!/usr/bin/env python3
"""Acceptance tests for durable corrected-native-product binding."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from pathlib import Path

import correction_native_product_binding as binding


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_document(channel: str = "facebook", *, platform: str | None = None) -> dict:
    platform = platform or channel
    route_binding = {
        "route_id": f"route:{channel}:correction-1:publication-1",
        "action_id": f"action:{channel}:correction-1:publication-1",
        "instance_id": "valcea",
        "channel_id": channel,
        "platform": platform,
        "correction_story_id": "correction-1",
        "affected_story_id": "story-1",
        "affected_publication_id": "publication-1",
        "remote_publication_id": "remote-1",
        "fact_kernel_sha256": sha("corrected fact kernel"),
        "declared_publication_outbox": f"valcea-clar/social/{channel}_outbox.json",
    }
    item = {
        "item_id": "correction-outbox:" + binding._digest(route_binding)[:24],
        "status": "READY_FOR_NATIVE_REGENERATION",
        "instance_id": "valcea",
        "channel_id": channel,
        "platform": platform,
        "correction_story_id": "correction-1",
        "affected_story_id": "story-1",
        "affected_publication_id": "publication-1",
        "remote_publication_id": "remote-1",
        "source_route_id": route_binding["route_id"],
        "source_action_id": route_binding["action_id"],
        "source_dispatch_plan_fingerprint_sha256": sha("plan"),
        "corrected_fact_kernel_sha256": sha("corrected fact kernel"),
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
            "route_binding_sha256": binding._digest(route_binding),
            "declared_publication_outbox": route_binding["declared_publication_outbox"],
        },
        "guards": {
            "credential_values_present": False,
            "editorial_copy_present": False,
            "network_calls_performed": False,
            "zero_paid_dependency": True,
        },
    }
    item["item_fingerprint_sha256"] = binding._digest(item)
    document = {
        "schema_version": "1.0",
        "instance_id": "valcea",
        "channel_id": channel,
        "platform": platform,
        "declared_publication_outbox": route_binding["declared_publication_outbox"],
        "correction_outbox_path": f"valcea-clar/social/corrections/{channel}.json",
        "items": [item],
        "guards": {
            "channel_local_state": True,
            "normal_publication_outbox_overwritten": False,
            "credential_values_present": False,
            "editorial_copy_present": False,
            "network_calls_performed": False,
            "zero_paid_dependency": True,
        },
    }
    document["outbox_fingerprint_sha256"] = binding._digest(document)
    return document


def manifest(channel: str = "facebook", *, platform: str | None = None, native_format: str = "text") -> dict:
    platform = platform or channel
    row = {
        "instance_id": "valcea",
        "channel_id": channel,
        "platform": platform,
        "correction_story_id": "correction-1",
        "affected_publication_id": "publication-1",
        "source_fact_kernel_sha256": sha("corrected fact kernel"),
        "product_path": f"valcea-clar/social/generated/corrections/{channel}/correction-1.json",
        "product_fingerprint_sha256": sha(f"new native product:{channel}:{native_format}"),
        "original_publication_product_fingerprint_sha256": sha("original native product"),
        "native_format": native_format,
        "generator_version": "correction-native-v1",
        "regeneration_source": "VERIFIED_CORRECTED_FACT_KERNEL",
        "reuse_prior_copy": False,
        "verbatim_cross_platform_reuse_allowed": False,
        "network_calls_performed": False,
        "credential_values_read": False,
        "zero_paid_dependency": True,
    }
    if native_format in binding.VISUAL_FORMATS:
        row["visual_provenance_sha256"] = sha("real visual provenance")
    return row


def item_id(document: dict) -> str:
    return document["items"][0]["item_id"]


def test_binds_exact_native_product_without_authorizing_network_dispatch() -> None:
    source = source_document()
    result = binding.bind_native_correction_product(source, item_id(source), manifest())
    assert result["status"] == "PASS", result
    assert result["changed"] is True
    item = result["document"]["items"][0]
    assert item["status"] == "READY_FOR_CORRECTION_DISPATCH_ROUTING"
    assert item["native_product"]["source_fact_kernel_sha256"] == sha("corrected fact kernel")
    assert item["dispatch"]["network_dispatch_allowed"] is False
    assert item["dispatch"]["requires_adapter_capability_recheck"] is True


def test_visual_product_requires_real_visual_provenance_fingerprint() -> None:
    source = source_document("instagram")
    bad = manifest("instagram", native_format="image_plus_text")
    bad.pop("visual_provenance_sha256")
    result = binding.bind_native_correction_product(source, item_id(source), bad)
    assert result["status"] == "BLOCKED", result
    assert "CORRECTION_VISUAL_PROVENANCE_REQUIRED" in result["holds"]

    good = manifest("instagram", native_format="image_plus_text")
    result = binding.bind_native_correction_product(source, item_id(source), good)
    assert result["status"] == "PASS", result
    assert result["binding"]["visual_provenance_sha256"] == sha("real visual provenance")


def test_fact_kernel_identity_and_channel_mismatch_fail_closed() -> None:
    source = source_document()
    bad_kernel = manifest()
    bad_kernel["source_fact_kernel_sha256"] = sha("wrong kernel")
    result = binding.bind_native_correction_product(source, item_id(source), bad_kernel)
    assert "CORRECTION_PRODUCT_FACT_KERNEL_MISMATCH" in result["holds"]

    bad_channel = manifest()
    bad_channel["channel_id"] = "threads"
    result = binding.bind_native_correction_product(source, item_id(source), bad_channel)
    assert "CORRECTION_PRODUCT_CHANNEL_MISMATCH" in result["holds"]


def test_editorial_copy_and_secret_fields_are_rejected_from_manifest() -> None:
    source = source_document()
    with_copy = manifest()
    with_copy["caption"] = "do not store this"
    result = binding.bind_native_correction_product(source, item_id(source), with_copy)
    assert "CORRECTION_PRODUCT_MANIFEST_CONTAINS_EDITORIAL_COPY" in result["holds"]

    with_secret = manifest()
    with_secret["access_token"] = "never"
    result = binding.bind_native_correction_product(source, item_id(source), with_secret)
    assert "CORRECTION_PRODUCT_MANIFEST_CONTAINS_SECRET_FIELD" in result["holds"]


def test_original_product_fingerprint_cannot_be_reused_when_known() -> None:
    source = source_document()
    same = manifest()
    same["original_publication_product_fingerprint_sha256"] = same["product_fingerprint_sha256"]
    result = binding.bind_native_correction_product(source, item_id(source), same)
    assert result["status"] == "BLOCKED", result
    assert "CORRECTION_PRODUCT_REUSES_ORIGINAL_PRODUCT_FINGERPRINT" in result["holds"]


def test_binding_is_idempotent_but_conflicting_rebind_fails_closed() -> None:
    source = source_document()
    first_manifest = manifest()
    first = binding.bind_native_correction_product(source, item_id(source), first_manifest)
    assert first["status"] == "PASS", first
    second = binding.bind_native_correction_product(first["document"], item_id(source), first_manifest)
    assert second["status"] == "PASS", second
    assert second["changed"] is False

    conflicting = manifest()
    conflicting["product_fingerprint_sha256"] = sha("different regenerated product")
    third = binding.bind_native_correction_product(first["document"], item_id(source), conflicting)
    assert third["status"] == "BLOCKED", third
    assert "CORRECTION_PRODUCT_BINDING_CONFLICT" in third["holds"]


def test_tampered_source_outbox_never_binds() -> None:
    source = source_document()
    source["items"][0]["remote_publication_id"] = "tampered"
    result = binding.bind_native_correction_product(source, item_id(source), manifest())
    assert result["status"] == "BLOCKED", result
    assert "CORRECTION_OUTBOX_FINGERPRINT_INVALID" in result["holds"] or "CORRECTION_OUTBOX_ITEM_FINGERPRINT_INVALID" in result["holds"]


def test_persistence_is_conflict_safe_and_does_not_overwrite_concurrent_state() -> None:
    source = source_document()
    result = binding.bind_native_correction_product(source, item_id(source), manifest())
    assert result["status"] == "PASS", result
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        path = root / source["correction_outbox_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        concurrent = copy.deepcopy(source)
        concurrent["items"][0]["status"] = "CONCURRENT_UPDATE"
        concurrent["items"][0].pop("item_fingerprint_sha256", None)
        concurrent["items"][0]["item_fingerprint_sha256"] = binding._digest(concurrent["items"][0])
        concurrent.pop("outbox_fingerprint_sha256", None)
        concurrent["outbox_fingerprint_sha256"] = binding._digest(concurrent)
        path.write_text(json.dumps(concurrent, ensure_ascii=False), encoding="utf-8")
        try:
            binding.persist_bound_correction_outbox(result, root)
        except ValueError as exc:
            assert "PERSIST_CONFLICT" in str(exc)
        else:
            raise AssertionError("concurrent correction outbox was overwritten")
        assert json.loads(path.read_text(encoding="utf-8")) == concurrent


def test_persistence_uses_exact_source_fingerprint_then_readback() -> None:
    source = source_document()
    result = binding.bind_native_correction_product(source, item_id(source), manifest())
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        path = root / source["correction_outbox_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
        receipt = binding.persist_bound_correction_outbox(result, root)
        assert receipt["status"] == "PASS", receipt
        assert receipt["persisted"] is True
        assert json.loads(path.read_text(encoding="utf-8")) == result["document"]


def test_guards_remain_zero_paid_network_free_and_copy_free() -> None:
    source = source_document()
    result = binding.bind_native_correction_product(source, item_id(source), manifest())
    assert result["guards"] == {
        "network_calls_performed": False,
        "credential_values_read": False,
        "editorial_copy_materialized": False,
        "remote_edit_claimed": False,
        "adapter_dispatch_authorized": False,
        "zero_paid_dependency": True,
    }
    serialized = json.dumps(result["document"], ensure_ascii=False).lower()
    assert "do not store this" not in serialized
    assert "never" not in serialized


def main() -> int:
    tests = [
        test_binds_exact_native_product_without_authorizing_network_dispatch,
        test_visual_product_requires_real_visual_provenance_fingerprint,
        test_fact_kernel_identity_and_channel_mismatch_fail_closed,
        test_editorial_copy_and_secret_fields_are_rejected_from_manifest,
        test_original_product_fingerprint_cannot_be_reused_when_known,
        test_binding_is_idempotent_but_conflicting_rebind_fails_closed,
        test_tampered_source_outbox_never_binds,
        test_persistence_is_conflict_safe_and_does_not_overwrite_concurrent_state,
        test_persistence_uses_exact_source_fingerprint_then_readback,
        test_guards_remain_zero_paid_network_free_and_copy_free,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"Correction Native Product Binding acceptance: PASS ({len(tests)}/{len(tests)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
