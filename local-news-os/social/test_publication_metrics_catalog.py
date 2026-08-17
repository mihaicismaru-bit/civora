#!/usr/bin/env python3
"""Acceptance tests for publication metrics descriptor binding and runtime catalog."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

import metrics_harvest_scheduler
import observed_metrics_collector
import publication_metrics_catalog as catalog
import publication_state
import test_production_runtime as runtime_fixture


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
PUBLISHED_AT = "2026-08-16T10:00:00Z"


def _channel(platform: str) -> dict:
    return json.loads((REPO_ROOT / f"valcea-clar/social/channels/{platform}.json").read_text(encoding="utf-8"))


def _published_fixture(platform: str = "facebook", *, story: dict | None = None, series_decision: dict | None = None):
    source_story = copy.deepcopy(story or runtime_fixture._story())
    runtime = runtime_fixture._run(platform, story=source_story, series_decision=series_decision)
    assert runtime["blocked"] is False, runtime
    prepared = runtime["artifacts"]["publication"]
    publication_id = prepared["record"]["publication_id"]
    proof = publication_state.apply_attempt(
        prepared["ledger"],
        publication_id,
        PUBLISHED_AT,
        success=True,
        remote_publication_id=f"remote-{platform}-proof",
    )
    assert proof["blocked"] is False, proof
    return _channel(platform), source_story, runtime, proof["record"]


def _bind(platform: str = "facebook", *, story: dict | None = None, series_decision: dict | None = None, existing: dict | None = None):
    ch, source_story, runtime, published = _published_fixture(platform, story=story, series_decision=series_decision)
    return catalog.bind_published_publication(ch, source_story, runtime, published, existing)


class PublicationMetricsCatalogAcceptance(unittest.TestCase):
    def test_facebook_remote_proof_binds_descriptor_complete_for_collector(self) -> None:
        ch, story, runtime, published = _published_fixture("facebook")
        result = catalog.bind_published_publication(ch, story, runtime, published)
        self.assertFalse(result["blocked"], result)
        self.assertEqual("BOUND_PUBLISHED_DESCRIPTOR", result["decision"])
        descriptor = result["descriptor"]
        self.assertEqual("PUBLISHED", descriptor["status"])
        self.assertEqual(published["remote_publication_id"], descriptor["remote_publication_id"])
        self.assertEqual("single_photo", descriptor["native_format"])
        self.assertTrue(observed_metrics_collector.validate_publication_descriptor(ch, descriptor)["valid"])
        self.assertFalse(result["publication_blocked"])

    def test_instagram_keeps_its_native_carousel_identity(self) -> None:
        result = _bind("instagram")
        self.assertFalse(result["blocked"], result)
        self.assertEqual("carousel", result["descriptor"]["native_format"])
        self.assertEqual("valcea-instagram", result["descriptor"]["channel_id"])
        self.assertNotEqual("single_photo", result["descriptor"]["native_format"])

    def test_topics_are_authoritative_sorted_and_deduplicated_from_verified_story(self) -> None:
        story = runtime_fixture._story()
        story["topics"] = ["infrastructure", "service_journalism", "infrastructure", "civic_updates"]
        result = _bind("facebook", story=story)
        self.assertEqual(
            ["civic_updates", "infrastructure", "service_journalism"],
            result["descriptor"]["topic_keys"],
        )

    def test_series_identity_is_bound_only_when_story_is_selected(self) -> None:
        story = runtime_fixture._story()
        series = {
            "instance_id": "valcea",
            "channel_id": "valcea-facebook",
            "story_id": story["story_id"],
            "eligible": True,
            "decision": "SERIES_READY",
            "hard_blocks": [],
            "occurrence": {
                "series_id": "banii-publici",
                "selected_story_ids": [story["story_id"]],
            },
        }
        selected = _bind("facebook", story=story, series_decision=series)
        self.assertEqual("banii-publici", selected["descriptor"]["series_id"])

        not_selected = copy.deepcopy(series)
        not_selected["occurrence"]["selected_story_ids"] = ["different-story"]
        other = _bind("facebook", story=story, series_decision=not_selected)
        self.assertIsNone(other["descriptor"]["series_id"])

    def test_remote_publication_proof_is_mandatory_but_publication_is_not_rolled_back(self) -> None:
        ch, story, runtime, published = _published_fixture("facebook")
        published["remote_publication_id"] = None
        result = catalog.bind_published_publication(ch, story, runtime, published)
        self.assertTrue(result["blocked"])
        self.assertIn("MISSING_REMOTE_PUBLICATION_ID", result["hard_blocks"])
        self.assertFalse(result["publication_blocked"])
        self.assertFalse(result["guards"]["publication_state_mutated"])

    def test_published_identity_mismatch_fails_closed(self) -> None:
        ch, story, runtime, published = _published_fixture("facebook")
        published["story_id"] = "other-story"
        result = catalog.bind_published_publication(ch, story, runtime, published)
        self.assertTrue(result["blocked"])
        self.assertIn("PUBLISHED_STORY_MISMATCH", result["hard_blocks"])

    def test_tampered_native_product_fingerprint_fails_closed(self) -> None:
        ch, story, runtime, published = _published_fixture("facebook")
        runtime["artifacts"]["format"]["product"]["native_format"] = "text"
        result = catalog.bind_published_publication(ch, story, runtime, published)
        self.assertTrue(result["blocked"])
        self.assertIn("PRODUCT_FINGERPRINT_INVALID", result["hard_blocks"])

    def test_fact_kernel_tampering_between_runtime_and_binding_fails_closed(self) -> None:
        ch, story, runtime, published = _published_fixture("facebook")
        story["headline"] = "Titlu modificat după producerea produsului nativ"
        result = catalog.bind_published_publication(ch, story, runtime, published)
        self.assertTrue(result["blocked"])
        self.assertIn("FACT_KERNEL_FINGERPRINT_MISMATCH", result["hard_blocks"])

    def test_predictive_fields_have_zero_effect_on_descriptor_identity(self) -> None:
        clean_story = runtime_fixture._story()
        clean = _bind("facebook", story=clean_story)
        noisy_story = runtime_fixture._story()
        noisy_story.update({
            "predicted_views": 999999999,
            "expected_reach": 999999999,
            "virality_probability": 1.0,
        })
        noisy = _bind("facebook", story=noisy_story)
        self.assertEqual(
            clean["descriptor"]["descriptor_fingerprint_sha256"],
            noisy["descriptor"]["descriptor_fingerprint_sha256"],
        )
        encoded = json.dumps(noisy["descriptor"], ensure_ascii=False)
        self.assertNotIn("predicted_views", encoded)
        self.assertNotIn("expected_reach", encoded)
        self.assertNotIn("virality_probability", encoded)

    def test_secret_like_story_metadata_is_not_persisted(self) -> None:
        story = runtime_fixture._story()
        story["access_token"] = "must-never-survive"
        story["client_secret"] = "also-must-never-survive"
        result = _bind("facebook", story=story)
        self.assertFalse(result["blocked"], result)
        encoded = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("must-never-survive", encoded)
        self.assertNotIn("also-must-never-survive", encoded)
        self.assertFalse(result["guards"]["credential_values_persisted"])

    def test_same_binding_is_idempotent(self) -> None:
        ch, story, runtime, published = _published_fixture("facebook")
        first = catalog.bind_published_publication(ch, story, runtime, published)
        second = catalog.bind_published_publication(ch, story, runtime, published, first["catalog"])
        self.assertFalse(second["blocked"], second)
        self.assertEqual("DEDUPE_EXISTING_DESCRIPTOR", second["decision"])
        self.assertEqual(first["catalog"], second["catalog"])
        self.assertEqual(
            first["descriptor"]["descriptor_fingerprint_sha256"],
            second["descriptor"]["descriptor_fingerprint_sha256"],
        )

    def test_conflicting_remote_proof_cannot_rewrite_existing_descriptor(self) -> None:
        ch, story, runtime, published = _published_fixture("facebook")
        first = catalog.bind_published_publication(ch, story, runtime, published)
        conflicting = copy.deepcopy(published)
        conflicting["remote_publication_id"] = "different-remote-proof"
        second = catalog.bind_published_publication(ch, story, runtime, conflicting, first["catalog"])
        self.assertTrue(second["blocked"])
        self.assertIn("PUBLICATION_DESCRIPTOR_CONFLICT", second["hard_blocks"])
        self.assertEqual(first["catalog"], second["catalog"])

    def test_catalog_tampering_is_detected_before_append(self) -> None:
        ch, story, runtime, published = _published_fixture("facebook")
        first = catalog.bind_published_publication(ch, story, runtime, published)
        tampered = copy.deepcopy(first["catalog"])
        tampered["records"][published["publication_id"]]["topic_keys"] = ["tampered"]
        second = catalog.bind_published_publication(ch, story, runtime, published, tampered)
        self.assertTrue(second["blocked"])
        self.assertTrue(
            any(code.startswith("DESCRIPTOR_FINGERPRINT_INVALID") for code in second["hard_blocks"])
            or "CATALOG_FINGERPRINT_INVALID" in second["hard_blocks"]
        )

    def test_cross_instance_catalog_cannot_be_shared(self) -> None:
        first = _bind("facebook")
        foreign = copy.deepcopy(first["catalog"])
        foreign["instance_id"] = "cluj"
        ch, story, runtime, published = _published_fixture("facebook")
        second = catalog.bind_published_publication(ch, story, runtime, published, foreign)
        self.assertTrue(second["blocked"])
        self.assertIn("CATALOG_INSTANCE_MISMATCH", second["hard_blocks"])

    def test_legacy_adapter_map_is_not_reverse_engineered(self) -> None:
        ch = _channel("facebook")
        story = runtime_fixture._story()
        legacy_runtime = {
            "instance_id": "valcea",
            "channel_id": "valcea-facebook",
            "platform": "facebook",
            "story_id": story["story_id"],
            "published": {
                story["story_id"]: {
                    "facebook_post_id": "page_post",
                    "published_at": PUBLISHED_AT,
                }
            },
            "guards": {"zero_paid_dependency": True, "predictive_analytics_used": False, "credential_values_read": False, "credential_values_exposed": False},
        }
        legacy_record = {
            "status": "PUBLISHED",
            "instance_id": "valcea",
            "channel_id": "valcea-facebook",
            "platform": "facebook",
            "story_id": story["story_id"],
            "remote_publication_id": "page_post",
            "published_at": PUBLISHED_AT,
        }
        result = catalog.bind_published_publication(ch, story, legacy_runtime, legacy_record)
        self.assertTrue(result["blocked"])
        self.assertIn("MISSING_AUTHORITATIVE_RUNTIME_ARTIFACTS", result["hard_blocks"])
        self.assertEqual({}, result["catalog"]["records"])

    def test_catalog_is_directly_consumable_by_existing_harvest_scheduler(self) -> None:
        result = _bind("facebook")
        ch = _channel("facebook")
        enumerated = metrics_harvest_scheduler.enumerate_publications(ch, result["catalog"])
        self.assertTrue(enumerated["valid"], enumerated)
        self.assertEqual(1, len(enumerated["publications"]))
        self.assertEqual(result["descriptor"]["publication_id"], enumerated["publications"][0]["publication_id"])

        plan = metrics_harvest_scheduler.plan_harvest(
            ch,
            result["catalog"],
            {
                "status": "VALID",
                "facebook_ready": True,
                "instagram_ready": True,
                "secret_material_persisted": False,
            },
            now="2026-08-16T16:30:00Z",
        )
        self.assertEqual("HARVEST_READY", plan["status"], plan)
        self.assertEqual(6, plan["jobs"][0]["checkpoint"]["checkpoint_hours"])
        self.assertFalse(plan["publication_blocked"])

    def test_storage_path_is_channel_local_and_zero_paid_policy_is_fail_closed_for_catalog_only(self) -> None:
        ch = _channel("facebook")
        self.assertEqual(
            "valcea-clar/social/facebook_state_metrics_publications.json",
            catalog.expected_catalog_path(ch),
        )
        ch["zero_paid_dependency"] = False
        story = runtime_fixture._story()
        runtime = runtime_fixture._run("facebook", story=story)
        prepared = runtime["artifacts"]["publication"]
        proof = publication_state.apply_attempt(
            prepared["ledger"],
            prepared["record"]["publication_id"],
            PUBLISHED_AT,
            success=True,
            remote_publication_id="remote-facebook-proof",
        )
        result = catalog.bind_published_publication(ch, story, runtime, proof["record"])
        self.assertTrue(result["blocked"])
        self.assertIn("ZERO_PAID_DEPENDENCY_VIOLATION", result["hard_blocks"])
        self.assertFalse(result["publication_blocked"])

    def test_identical_inputs_are_deterministic(self) -> None:
        ch, story, runtime, published = _published_fixture("facebook")
        first = catalog.bind_published_publication(ch, story, runtime, published)
        second = catalog.bind_published_publication(ch, story, runtime, published)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
