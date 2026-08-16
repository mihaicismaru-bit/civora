#!/usr/bin/env python3
"""Acceptance tests for Threads as an independent VÂLCEA CLAR publication.

Threads now has verified direct-access configuration, but the generic social core
must remain network-free: it can build a complete native thread and a durable
DIRECT_READY handoff using credential reference names only. Actual Threads API
calls remain owned by the dedicated site-engine adapter/workflow.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

import adapter_dispatch_bridge
import production_runtime
import recurring_series


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
THREADS_CONFIG = REPO_ROOT / "valcea-clar/social/channels/threads.json"
YOUTUBE_CONFIG = REPO_ROOT / "valcea-clar/social/channels/youtube.json"
REGISTRY_PATH = REPO_ROOT / "valcea-clar/social/channel_registry.json"
SERIES_PATH = REPO_ROOT / "valcea-clar/social/series_registry.json"
NOW = "2026-08-16T10:00:00Z"
THREADS_REFS = {"VALCEA_THREADS_ACCESS_TOKEN"}


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _story() -> dict:
    return {
        "instance_id": "valcea",
        "story_id": "threads-roadworks-20260816",
        "material_fact_gate": "PASS",
        "headline": "Lucrări programate luni pe o stradă din Râmnicu Vâlcea",
        "dek": "Intervenția este anunțată între 09:00 și 16:00, iar circulația va fi dirijată local.",
        "paragraphs": [
            "Echipele vor lucra etapizat pentru a păstra accesul local pe durata intervenției.",
            "Șoferii sunt rugați să urmărească semnalizarea temporară din zonă.",
        ],
        "facts": [
            {"fact_id": "f1", "text": "Intervalul anunțat pentru lucrări este 09:00–16:00."},
            {"fact_id": "f2", "text": "Circulația va fi dirijată local pe durata intervenției."},
        ],
        "quotes": [
            {"quote_id": "q1", "text": "Semnalizarea temporară va fi adaptată etapelor de lucru."},
        ],
        "topics": ["service_journalism", "civic_updates", "infrastructure"],
        "risk_flags": [],
        "available_formats": ["thread", "text", "single_photo", "short"],
        "confidence": 99,
        "locality": 1.0,
        "proximity": 1.0,
        "utility": 0.95,
        "share_value": 0.76,
        "save_value": 0.74,
        "conversation_value": 0.58,
        "urgency": 0.25,
        "lifecycle_stage": "baseline",
    }


def _inventory(story_id: str) -> dict:
    return {
        "instance_id": "valcea",
        "assets": [
            {
                "instance_id": "valcea",
                "asset_id": "threads-real-photo-a",
                "kind": "photo",
                "sha256": _digest("threads-real-photo-a"),
                "synthetic": False,
                "subject_match": True,
                "editor_approved": True,
                "story_ids": [story_id],
                "source_type": "staff",
                "rights_basis": "owned",
                "credit": "VÂLCEA CLAR / acceptance fixture",
                "alt_text": "Semnalizare temporară în zona unor lucrări stradale din Râmnicu Vâlcea.",
            },
            {
                "instance_id": "valcea",
                "asset_id": "threads-real-video-a",
                "kind": "video",
                "sha256": _digest("threads-real-video-a"),
                "synthetic": False,
                "subject_match": True,
                "editor_approved": True,
                "story_ids": [story_id],
                "source_type": "staff",
                "rights_basis": "owned",
                "credit": "VÂLCEA CLAR / acceptance fixture",
                "alt_text": "Secvență video reală cu zona lucrărilor și semnalizarea temporară.",
            },
        ],
    }


def _history(channel: dict) -> dict:
    return {
        "instance_id": channel["instance_id"],
        "channel_id": channel["channel_id"],
        "records": [],
    }


def _run(channel: dict, story: dict | None = None) -> dict:
    value = copy.deepcopy(story or _story())
    return production_runtime.orchestrate_channel(
        value,
        channel,
        _inventory(value["story_id"]),
        _history(channel),
        now=NOW,
        human_approved=True,
        canonical_url=None,
    )


class ThreadsDirectAcceptance(unittest.TestCase):
    def setUp(self) -> None:
        self.threads = _load(THREADS_CONFIG)
        self.youtube = _load(YOUTUBE_CONFIG)
        self.registry = _load(REGISTRY_PATH)
        self.series = _load(SERIES_PATH)

    def test_channel_is_independent_verified_direct_publication(self) -> None:
        self.assertEqual("threads", self.threads["platform"])
        self.assertEqual("valcea-threads", self.threads["channel_id"])
        self.assertEqual("active", self.threads["status"])
        self.assertEqual(["thread", "text", "single_photo"], self.threads["native_formats"])
        self.assertEqual("github-actions-secret:VALCEA_THREADS_ACCESS_TOKEN", self.threads["credentials_ref"])
        self.assertEqual("valcea-clar/social/threads_outbox.json", self.threads["publication_state"]["outbox_path"])
        self.assertEqual("valcea-clar/social/threads_state.json", self.threads["publication_state"]["state_path"])
        self.assertTrue(self.threads["publication_state"]["activation_baseline_required"])
        self.assertTrue(self.threads["publication_state"]["partial_publish_requires_manual_reconciliation"])
        self.assertTrue(self.threads["metrics"]["observed_only"])
        self.assertEqual(["threads_api"], self.threads["metrics"]["sources"])
        self.assertTrue(self.threads["zero_paid_dependency"])

    def test_runtime_builds_native_thread_from_verified_fact_kernel(self) -> None:
        report = _run(self.threads)
        self.assertFalse(report["blocked"])
        self.assertEqual("READY", report["disposition"])
        product = report["artifacts"]["format"]["product"]
        self.assertEqual("thread", product["native_format"])
        self.assertEqual("thread_sequence", product["format_family"])
        self.assertEqual("thread", product["native_structure"]["surface"])
        self.assertGreaterEqual(len(product["native_structure"]["post_atom_ids"]), 2)
        self.assertEqual("NATIVE_PRODUCT_ONLY", product["cross_post_policy"])
        self.assertFalse(product["verbatim_cross_platform_reuse_allowed"])
        self.assertFalse(product["analytics_used"])
        self.assertFalse(report["guards"]["network_calls_performed"])
        self.assertFalse(report["guards"]["credential_values_read"])

    def test_threads_and_youtube_are_distinct_sibling_products(self) -> None:
        threads_report = _run(self.threads)
        youtube_report = _run(self.youtube)
        threads_product = threads_report["artifacts"]["format"]["product"]
        youtube_product = youtube_report["artifacts"]["format"]["product"]
        self.assertEqual("thread", threads_product["native_format"])
        self.assertEqual("short", youtube_product["native_format"])
        self.assertNotEqual(threads_product["product_id"], youtube_product["product_id"])
        self.assertNotEqual(
            threads_product["product_fingerprint_sha256"],
            youtube_product["product_fingerprint_sha256"],
        )
        self.assertNotEqual(threads_product["native_structure"], youtube_product["native_structure"])
        self.assertNotEqual(threads_product["hook"]["text"], youtube_product["hook"]["text"])

    def test_complete_thread_is_standalone_and_requires_no_visual(self) -> None:
        report = _run(self.threads)
        product = report["artifacts"]["format"]["product"]
        self.assertFalse(product["visual_requirement"]["required"])
        self.assertEqual("none", product["visual_requirement"]["media_kind"])
        self.assertEqual("NATIVE_STANDALONE", report["artifacts"]["link_binding"]["status"])
        self.assertEqual("READY", report["disposition"])

    def test_bridge_builds_direct_ready_handoff_without_network_or_secret_values(self) -> None:
        report = _run(self.threads)
        bridged = adapter_dispatch_bridge.bridge_runtime_handoff(
            report, self.registry, present_refs=THREADS_REFS
        )
        self.assertFalse(bridged["blocked"])
        self.assertEqual("DIRECT_READY", bridged["dispatch_disposition"])
        self.assertEqual("READY", bridged["publication_status_after_bridge"])
        self.assertEqual("DIRECT_READY", bridged["runtime_gate"]["decision"])
        self.assertTrue(bridged["adapter_handoff"]["dispatch_allowed"])
        self.assertFalse(bridged["adapter_handoff"]["durable_outbox_only"])
        self.assertEqual("valcea-clar/social/threads_publish.py", bridged["adapter_handoff"]["adapter"])
        self.assertEqual(["VALCEA_THREADS_ACCESS_TOKEN"], bridged["adapter_handoff"]["credential_reference_names"])
        self.assertFalse(bridged["guards"]["credential_values_read"])
        self.assertFalse(bridged["guards"]["network_dispatch_performed"])
        item = next(iter(bridged["commit_bundle"]["outbox"]["items"].values()))
        self.assertEqual("valcea-clar/social/threads_outbox.json", item["physical_outbox_path"])
        self.assertEqual("valcea-clar/social/threads_state.json", item["physical_state_path"])
        self.assertEqual(report["artifacts"]["format"]["product"], item["adapter_payload"]["native_product"])

    def test_bridge_registration_is_idempotent(self) -> None:
        report = _run(self.threads)
        first = adapter_dispatch_bridge.bridge_runtime_handoff(
            report, self.registry, present_refs=THREADS_REFS
        )
        second = adapter_dispatch_bridge.bridge_runtime_handoff(
            report,
            self.registry,
            present_refs=THREADS_REFS,
            outbox=first["commit_bundle"]["outbox"],
        )
        self.assertFalse(second["blocked"])
        self.assertEqual("DEDUPE_EXISTING_HANDOFF", second["decision"])
        self.assertEqual("DIRECT_READY", second["dispatch_disposition"])
        self.assertEqual(1, len(second["commit_bundle"]["outbox"]["items"]))

    def test_missing_threads_credential_reference_fails_closed_without_fake_publish(self) -> None:
        report = _run(self.threads)
        bridged = adapter_dispatch_bridge.bridge_runtime_handoff(
            report, self.registry, present_refs=set()
        )
        self.assertFalse(bridged["blocked"])
        self.assertEqual("BLOCKED_MISSING_CREDENTIALS", bridged["dispatch_disposition"])
        self.assertEqual("BLOCKED_AUTH", bridged["publication_status_after_bridge"])
        self.assertFalse(bridged["adapter_handoff"]["dispatch_allowed"])
        self.assertIn("VALCEA_THREADS_ACCESS_TOKEN", bridged["adapter_handoff"]["missing_reference_names"])
        self.assertFalse(bridged["guards"]["network_dispatch_performed"])

    def test_registry_declares_verified_threads_adapter_and_credential_reference(self) -> None:
        entries = [row for row in self.registry["channels"] if row.get("channel_id") == "threads"]
        self.assertEqual(1, len(entries))
        entry = entries[0]
        self.assertTrue(entry["direct_publication_enabled"])
        self.assertEqual("native_api_fail_closed", entry["publication_mode"])
        self.assertEqual("valcea-clar/social/threads_publish.py", entry["adapter"])
        self.assertEqual(
            {"access_token_secret": "VALCEA_THREADS_ACCESS_TOKEN"},
            entry["credentials"],
        )
        self.assertTrue(entry["requirements"]["verified_publishing_access"])
        self.assertTrue(entry["requirements"]["activation_baseline_required"])
        self.assertTrue(entry["requirements"]["historical_backlog_replay_forbidden"])

    def test_threads_has_channel_specific_recurring_series(self) -> None:
        policies, errors = recurring_series.channel_policies(self.threads, self.series)
        self.assertEqual([], errors)
        self.assertEqual(2, len(policies))
        self.assertEqual({"valcea-in-3-idei", "ce-se-schimba"}, {row["series_id"] for row in policies})
        self.assertTrue(all("thread" in row["preferred_formats"] for row in policies))

    def test_instance_mismatch_fails_closed_before_handoff(self) -> None:
        story = _story()
        story["instance_id"] = "other-city"
        report = _run(self.threads, story)
        self.assertTrue(report["blocked"])
        self.assertIn("INSTANCE_MISMATCH", report["hard_blocks"])
        self.assertNotEqual("READY", report["disposition"])

    def test_predictive_analytics_cannot_change_native_product(self) -> None:
        baseline = _run(self.threads)
        injected_story = _story()
        injected_story["predicted_views"] = 99999999
        injected_story["virality_probability"] = 0.999
        injected_story["predicted_engagement"] = 123456
        injected = _run(self.threads, injected_story)
        baseline_product = baseline["artifacts"]["format"]["product"]
        injected_product = injected["artifacts"]["format"]["product"]
        self.assertEqual(baseline_product["product_id"], injected_product["product_id"])
        self.assertEqual(
            baseline_product["product_fingerprint_sha256"],
            injected_product["product_fingerprint_sha256"],
        )
        self.assertFalse(
            injected["artifacts"]["virality"]["analytics"]["predictive_analytics_used"]
        )


class GitHubAnnotationResult(unittest.TextTestResult):
    def _annotate(self, test: unittest.TestCase) -> None:
        name = test.id().replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::error title=Threads acceptance failure::{name}", file=sys.stderr)

    def addFailure(self, test: unittest.TestCase, err) -> None:
        self._annotate(test)
        super().addFailure(test, err)

    def addError(self, test: unittest.TestCase, err) -> None:
        self._annotate(test)
        super().addError(test, err)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ThreadsDirectAcceptance)
    result = unittest.TextTestRunner(verbosity=2, resultclass=GitHubAnnotationResult).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
