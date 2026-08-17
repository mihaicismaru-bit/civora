#!/usr/bin/env python3
"""Acceptance tests for operational publication-metrics catalog materialization."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import publication_metrics_catalog as catalog
import publication_metrics_handoff as handoff
import test_production_runtime as runtime_fixture
import test_publication_metrics_catalog as catalog_fixture


ACCESS = {
    "status": "VALID",
    "facebook_ready": True,
    "instagram_ready": True,
    "secret_material_persisted": False,
}


def _dispatch(record: dict) -> dict:
    return {
        "schema_version": "1.0",
        "blocked": False,
        "hard_blocks": [],
        "decision": "PUBLISHED",
        "publication_status": "PUBLISHED",
        "record": copy.deepcopy(record),
        "adapter_invoked": True,
    }


def _run(platform: str, root: Path, *, now: str = "2026-08-16T16:30:00Z", story: dict | None = None, access: dict | None = None):
    channel, source_story, runtime, published = catalog_fixture._published_fixture(platform, story=story)
    result = handoff.materialize_after_remote_publication(
        channel,
        source_story,
        runtime,
        _dispatch(published),
        copy.deepcopy(access or ACCESS),
        repo_root=root,
        now=now,
    )
    return channel, source_story, runtime, published, result


class PublicationMetricsOperationalHandoffAcceptance(unittest.TestCase):
    def test_facebook_remote_proof_is_persisted_before_6h_harvest_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            channel, _story, _runtime, published, result = _run("facebook", root)
            self.assertEqual("CATALOG_PERSISTED_HARVEST_READY", result["status"], result)
            self.assertFalse(result["publication_blocked"])
            self.assertTrue(result["guards"]["catalog_persisted_before_scheduler"])
            self.assertEqual(6, result["harvest_plan"]["jobs"][0]["checkpoint"]["checkpoint_hours"])
            self.assertEqual(published["publication_id"], result["harvest_plan"]["jobs"][0]["publication_id"])
            path = root / catalog.expected_catalog_path(channel)
            self.assertTrue(path.exists())
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(result["catalog_fingerprint_sha256"], persisted["catalog_fingerprint_sha256"])

    def test_immediate_post_publication_materializes_catalog_without_forcing_analytics_call(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _channel, _story, _runtime, _published, result = _run(
                "facebook", Path(temp), now="2026-08-16T10:00:30Z"
            )
            self.assertEqual("CATALOG_PERSISTED_NO_HARVEST_DUE", result["status"], result)
            self.assertEqual("NO_HARVEST_DUE", result["harvest_plan"]["status"])
            self.assertEqual([], result["harvest_plan"]["jobs"])
            self.assertFalse(result["guards"]["network_calls_performed"])

    def test_instagram_keeps_carousel_identity_in_persisted_catalog_and_harvest_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            channel, _story, _runtime, _published, result = _run("instagram", Path(temp))
            self.assertEqual("CATALOG_PERSISTED_HARVEST_READY", result["status"], result)
            publication = result["harvest_plan"]["jobs"][0]["publication"]
            self.assertEqual("carousel", publication["native_format"])
            self.assertEqual("valcea-instagram", publication["channel_id"])
            persisted = json.loads((Path(temp) / catalog.expected_catalog_path(channel)).read_text(encoding="utf-8"))
            only = next(iter(persisted["records"].values()))
            self.assertEqual("carousel", only["native_format"])

    def test_identical_post_publication_replay_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            channel, story, runtime, published = catalog_fixture._published_fixture("facebook")
            first = handoff.materialize_after_remote_publication(
                channel, story, runtime, _dispatch(published), ACCESS, repo_root=root, now="2026-08-16T16:30:00Z"
            )
            before = (root / catalog.expected_catalog_path(channel)).read_text(encoding="utf-8")
            second = handoff.materialize_after_remote_publication(
                channel, story, runtime, _dispatch(published), ACCESS, repo_root=root, now="2026-08-16T16:30:00Z"
            )
            after = (root / catalog.expected_catalog_path(channel)).read_text(encoding="utf-8")
            self.assertEqual("IDEMPOTENT_CATALOG", second["catalog_persistence"]["status"])
            self.assertFalse(second["catalog_persistence"]["written"])
            self.assertEqual(first["catalog_fingerprint_sha256"], second["catalog_fingerprint_sha256"])
            self.assertEqual(before, after)

    def test_unconfirmed_dispatch_result_never_creates_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            channel, story, runtime, published = catalog_fixture._published_fixture("facebook")
            dispatch = _dispatch(published)
            dispatch["publication_status"] = "PUBLISHING"
            dispatch["record"]["status"] = "PUBLISHING"
            dispatch["record"]["remote_publication_id"] = None
            result = handoff.materialize_after_remote_publication(
                channel, story, runtime, dispatch, ACCESS, repo_root=root, now="2026-08-16T16:30:00Z"
            )
            self.assertEqual("HOLD_REMOTE_PUBLICATION_PROOF", result["status"])
            self.assertFalse(result["publication_blocked"])
            self.assertFalse((root / catalog.expected_catalog_path(channel)).exists())
            self.assertIsNone(result["harvest_plan"])

    def test_catalog_compare_and_swap_conflict_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            channel, story, runtime, published = catalog_fixture._published_fixture("facebook")
            first = catalog.bind_published_publication(channel, story, runtime, published)
            persisted = handoff.persist_catalog_cas(
                root,
                channel,
                first["catalog"],
                expected_previous_catalog_fingerprint_sha256=None,
            )
            self.assertTrue(persisted["persisted"], persisted)

            story2 = runtime_fixture._story()
            story2["story_id"] = "story-second-publication"
            story2["headline"] = "A doua știre verificată pentru testul de catalog"
            ch2, source2, runtime2, published2 = catalog_fixture._published_fixture("facebook", story=story2)
            second = catalog.bind_published_publication(ch2, source2, runtime2, published2, first["catalog"])
            conflict = handoff.persist_catalog_cas(
                root,
                channel,
                second["catalog"],
                expected_previous_catalog_fingerprint_sha256="0" * 64,
            )
            self.assertFalse(conflict["persisted"])
            self.assertEqual("HOLD_CATALOG_CAS_CONFLICT", conflict["status"])
            self.assertIn("CATALOG_COMPARE_AND_SWAP_CONFLICT", conflict["hard_blocks"])
            on_disk = json.loads((root / catalog.expected_catalog_path(channel)).read_text(encoding="utf-8"))
            self.assertEqual(first["catalog"]["catalog_fingerprint_sha256"], on_disk["catalog_fingerprint_sha256"])

    def test_tampered_existing_catalog_is_not_overwritten_and_scheduler_is_not_called(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            channel, story, runtime, published = catalog_fixture._published_fixture("facebook")
            target = root / catalog.expected_catalog_path(channel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('{"tampered": true}\n', encoding="utf-8")
            with mock.patch.object(handoff.metrics_harvest_scheduler, "plan_harvest", side_effect=AssertionError("scheduler must not run")) as planner:
                result = handoff.materialize_after_remote_publication(
                    channel, story, runtime, _dispatch(published), ACCESS, repo_root=root, now="2026-08-16T16:30:00Z"
                )
            self.assertEqual("HOLD_METRICS_CATALOG", result["status"])
            planner.assert_not_called()
            self.assertEqual('{"tampered": true}\n', target.read_text(encoding="utf-8"))

    def test_conflicting_remote_proof_cannot_rewrite_persisted_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            channel, story, runtime, published = catalog_fixture._published_fixture("facebook")
            first = handoff.materialize_after_remote_publication(
                channel, story, runtime, _dispatch(published), ACCESS, repo_root=root, now="2026-08-16T16:30:00Z"
            )
            conflicting = copy.deepcopy(published)
            conflicting["remote_publication_id"] = "remote-conflicting-proof"
            second = handoff.materialize_after_remote_publication(
                channel, story, runtime, _dispatch(conflicting), ACCESS, repo_root=root, now="2026-08-16T16:30:00Z"
            )
            self.assertEqual("HOLD_DESCRIPTOR_BINDING", second["status"])
            self.assertIn("PUBLICATION_DESCRIPTOR_CONFLICT", second["hard_blocks"])
            on_disk = json.loads((root / catalog.expected_catalog_path(channel)).read_text(encoding="utf-8"))
            self.assertEqual(first["catalog_fingerprint_sha256"], on_disk["catalog_fingerprint_sha256"])

    def test_secret_like_access_attestation_value_is_never_returned_or_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            secret = "EAA-super-secret-value-that-must-not-survive"
            access = copy.deepcopy(ACCESS)
            access["access_token"] = secret
            channel, _story, _runtime, _published, result = _run("facebook", Path(temp), access=access)
            encoded = json.dumps(result, ensure_ascii=False)
            persisted = (Path(temp) / catalog.expected_catalog_path(channel)).read_text(encoding="utf-8")
            self.assertNotIn(secret, encoded)
            self.assertNotIn(secret, persisted)
            self.assertFalse(result["guards"]["credential_values_read"])
            self.assertFalse(result["guards"]["credential_values_persisted"])

    def test_predictive_story_fields_have_no_effect_on_persisted_descriptor(self) -> None:
        clean_story = runtime_fixture._story()
        noisy_story = runtime_fixture._story()
        noisy_story.update({"predicted_views": 99999999, "expected_reach": 99999999, "virality_probability": 0.999})
        with tempfile.TemporaryDirectory() as clean_temp, tempfile.TemporaryDirectory() as noisy_temp:
            _ch1, _s1, _r1, _p1, clean = _run("facebook", Path(clean_temp), story=clean_story)
            _ch2, _s2, _r2, _p2, noisy = _run("facebook", Path(noisy_temp), story=noisy_story)
            self.assertEqual(clean["descriptor_fingerprint_sha256"], noisy["descriptor_fingerprint_sha256"])
            encoded = json.dumps(noisy, ensure_ascii=False)
            self.assertNotIn("predicted_views", encoded)
            self.assertNotIn("expected_reach", encoded)
            self.assertNotIn("virality_probability", encoded)

    def test_cross_instance_story_cannot_materialize_into_channel_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            channel, story, runtime, published = catalog_fixture._published_fixture("facebook")
            foreign = copy.deepcopy(story)
            foreign["instance_id"] = "other-instance"
            result = handoff.materialize_after_remote_publication(
                channel, foreign, runtime, _dispatch(published), ACCESS, repo_root=root, now="2026-08-16T16:30:00Z"
            )
            self.assertEqual("HOLD_DESCRIPTOR_BINDING", result["status"])
            self.assertIn("STORY_INSTANCE_MISMATCH", result["hard_blocks"])
            self.assertFalse((root / catalog.expected_catalog_path(channel)).exists())

    def test_zero_paid_dependency_is_fail_closed_for_metrics_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            channel, story, runtime, published = catalog_fixture._published_fixture("facebook")
            channel["zero_paid_dependency"] = False
            result = handoff.materialize_after_remote_publication(
                channel, story, runtime, _dispatch(published), ACCESS, repo_root=root, now="2026-08-16T16:30:00Z"
            )
            self.assertEqual("HOLD_METRICS_CATALOG", result["status"])
            self.assertIn("ZERO_PAID_DEPENDENCY_VIOLATION", result["hard_blocks"])
            self.assertFalse(result["publication_blocked"])
            self.assertFalse(result["publication_rolled_back"])

    def test_facebook_and_instagram_catalogs_are_physically_independent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            facebook, *_rest_fb, result_fb = _run("facebook", root)
            instagram, *_rest_ig, result_ig = _run("instagram", root)
            fb_path = root / catalog.expected_catalog_path(facebook)
            ig_path = root / catalog.expected_catalog_path(instagram)
            self.assertNotEqual(fb_path, ig_path)
            self.assertTrue(fb_path.exists())
            self.assertTrue(ig_path.exists())
            self.assertNotEqual(result_fb["catalog_fingerprint_sha256"], result_ig["catalog_fingerprint_sha256"])

    def test_binding_does_not_mutate_confirmed_publication_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            channel, story, runtime, published = catalog_fixture._published_fixture("facebook")
            before = copy.deepcopy(published)
            result = handoff.materialize_after_remote_publication(
                channel, story, runtime, _dispatch(published), ACCESS, repo_root=Path(temp), now="2026-08-16T16:30:00Z"
            )
            self.assertFalse(result["publication_blocked"])
            self.assertEqual(before, published)
            self.assertFalse(result["guards"]["publication_state_mutated"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
