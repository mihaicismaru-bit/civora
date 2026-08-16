#!/usr/bin/env python3
"""Acceptance tests for LinkedIn as an independent durable-outbox publication.

LinkedIn publishing access is deliberately not assumed. The target is a complete
professional-context product with its own selection, cadence, series, state,
dedupe and outbox handoff while direct publication remains impossible.
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
LINKEDIN_CONFIG = REPO_ROOT / "valcea-clar/social/channels/linkedin.json"
THREADS_CONFIG = REPO_ROOT / "valcea-clar/social/channels/threads.json"
REGISTRY_PATH = REPO_ROOT / "valcea-clar/social/channel_registry.json"
SERIES_PATH = REPO_ROOT / "valcea-clar/social/series_registry.json"
NOW = "2026-08-16T10:00:00Z"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _story() -> dict:
    return {
        "instance_id": "valcea",
        "story_id": "linkedin-public-investment-20260816",
        "material_fact_gate": "PASS",
        "headline": "Primăria anunță lucrări etapizate pe o arteră din Râmnicu Vâlcea",
        "dek": "Intervenția este programată între 09:00 și 16:00, cu circulație dirijată local și acces păstrat pentru riverani.",
        "paragraphs": [
            "Programarea etapizată urmărește menținerea accesului local pe durata intervenției.",
            "Semnalizarea temporară va fi adaptată pe măsură ce frontul de lucru avansează.",
        ],
        "facts": [
            {"fact_id": "f1", "text": "Intervalul anunțat pentru lucrări este 09:00–16:00."},
            {"fact_id": "f2", "text": "Circulația va fi dirijată local pe durata intervenției."},
        ],
        "quotes": [
            {"quote_id": "q1", "text": "Accesul local va fi păstrat pe durata lucrărilor."},
        ],
        "topics": ["service_journalism", "civic_updates", "infrastructure", "public_money"],
        "risk_flags": [],
        "available_formats": ["text", "single_photo", "carousel", "thread"],
        "confidence": 99,
        "locality": 1.0,
        "proximity": 1.0,
        "utility": 0.95,
        "share_value": 0.70,
        "save_value": 0.79,
        "conversation_value": 0.62,
        "urgency": 0.20,
        "lifecycle_stage": "baseline",
    }


def _inventory(story_id: str) -> dict:
    return {
        "instance_id": "valcea",
        "assets": [
            {
                "instance_id": "valcea",
                "asset_id": "linkedin-real-photo-a",
                "kind": "photo",
                "sha256": _digest("linkedin-real-photo-a"),
                "synthetic": False,
                "subject_match": True,
                "editor_approved": True,
                "story_ids": [story_id],
                "source_type": "staff",
                "rights_basis": "owned",
                "credit": "VÂLCEA CLAR / acceptance fixture",
                "alt_text": "Semnalizare temporară într-o zonă de lucrări stradale din Râmnicu Vâlcea.",
            }
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


class LinkedInOutboxAcceptance(unittest.TestCase):
    def setUp(self) -> None:
        self.linkedin = _load(LINKEDIN_CONFIG)
        self.threads = _load(THREADS_CONFIG)
        self.registry = _load(REGISTRY_PATH)
        self.series = _load(SERIES_PATH)

    def test_channel_is_independent_outbox_only_publication(self) -> None:
        self.assertEqual("linkedin", self.linkedin["platform"])
        self.assertEqual("valcea-linkedin", self.linkedin["channel_id"])
        self.assertEqual("outbox_only", self.linkedin["status"])
        self.assertEqual(["text", "single_photo", "carousel"], self.linkedin["native_formats"])
        self.assertEqual("none:linkedin-publishing-access-not-verified", self.linkedin["credentials_ref"])
        self.assertEqual("valcea-clar/social/linkedin_outbox.json", self.linkedin["publication_state"]["outbox_path"])
        self.assertEqual("valcea-clar/social/linkedin_state.json", self.linkedin["publication_state"]["state_path"])
        self.assertTrue(self.linkedin["metrics"]["observed_only"])
        self.assertEqual([], self.linkedin["metrics"]["sources"])
        self.assertTrue(self.linkedin["zero_paid_dependency"])

    def test_runtime_builds_professional_context_product(self) -> None:
        report = _run(self.linkedin)
        self.assertFalse(report["blocked"])
        self.assertEqual("OUTBOX_READY", report["disposition"])
        product = report["artifacts"]["format"]["product"]
        self.assertEqual("text", product["native_format"])
        self.assertEqual("professional_context_post", product["format_family"])
        self.assertEqual("feed", product["native_structure"]["surface"])
        self.assertEqual("context_then_evidence", product["native_structure"]["composition"])
        self.assertEqual("NATIVE_PRODUCT_ONLY", product["cross_post_policy"])
        self.assertFalse(product["verbatim_cross_platform_reuse_allowed"])
        self.assertFalse(product["analytics_used"])

    def test_linkedin_and_threads_are_distinct_sibling_products(self) -> None:
        linkedin_report = _run(self.linkedin)
        threads_report = _run(self.threads)
        linkedin_product = linkedin_report["artifacts"]["format"]["product"]
        threads_product = threads_report["artifacts"]["format"]["product"]
        self.assertEqual("text", linkedin_product["native_format"])
        self.assertEqual("thread", threads_product["native_format"])
        self.assertNotEqual(linkedin_product["product_id"], threads_product["product_id"])
        self.assertNotEqual(linkedin_product["native_structure"], threads_product["native_structure"])
        self.assertNotEqual(linkedin_product["hook"]["text"], threads_product["hook"]["text"])
        self.assertTrue(linkedin_product["hook"]["text"].startswith("Context local — "))

    def test_complete_linkedin_text_is_standalone_and_requires_no_visual(self) -> None:
        report = _run(self.linkedin)
        product = report["artifacts"]["format"]["product"]
        self.assertFalse(product["visual_requirement"]["required"])
        self.assertEqual("none", product["visual_requirement"]["media_kind"])
        self.assertEqual("NATIVE_STANDALONE", report["artifacts"]["link_binding"]["status"])
        self.assertEqual("OUTBOX_READY", report["disposition"])

    def test_bridge_persists_native_outbox_and_cannot_claim_publish(self) -> None:
        report = _run(self.linkedin)
        bridged = adapter_dispatch_bridge.bridge_runtime_handoff(report, self.registry, present_refs=set())
        self.assertFalse(bridged["blocked"])
        self.assertEqual("OUTBOX_ONLY", bridged["dispatch_disposition"])
        self.assertEqual("OUTBOX_READY", bridged["publication_status_after_bridge"])
        self.assertEqual("OUTBOX_ONLY", bridged["runtime_gate"]["decision"])
        self.assertTrue(bridged["adapter_handoff"]["durable_outbox_only"])
        self.assertFalse(bridged["adapter_handoff"]["dispatch_allowed"])
        self.assertIsNone(bridged["adapter_handoff"]["adapter"])
        self.assertEqual([], bridged["adapter_handoff"]["credential_reference_names"])
        self.assertFalse(bridged["guards"]["network_dispatch_performed"])
        item = next(iter(bridged["commit_bundle"]["outbox"]["items"].values()))
        self.assertEqual("valcea-clar/social/linkedin_outbox.json", item["physical_outbox_path"])
        self.assertEqual("valcea-clar/social/linkedin_state.json", item["physical_state_path"])
        self.assertEqual(report["artifacts"]["format"]["product"], item["adapter_payload"]["native_product"])

    def test_bridge_registration_is_idempotent(self) -> None:
        report = _run(self.linkedin)
        first = adapter_dispatch_bridge.bridge_runtime_handoff(report, self.registry, present_refs=set())
        second = adapter_dispatch_bridge.bridge_runtime_handoff(
            report,
            self.registry,
            present_refs=set(),
            outbox=first["commit_bundle"]["outbox"],
        )
        self.assertFalse(second["blocked"])
        self.assertEqual("DEDUPE_EXISTING_HANDOFF", second["decision"])
        self.assertEqual("OUTBOX_ONLY", second["dispatch_disposition"])
        self.assertEqual(1, len(second["commit_bundle"]["outbox"]["items"]))

    def test_registry_never_invents_unverified_linkedin_adapter_or_credentials(self) -> None:
        entries = [row for row in self.registry["channels"] if row.get("channel_id") == "linkedin"]
        self.assertEqual(1, len(entries))
        entry = entries[0]
        self.assertFalse(entry["direct_publication_enabled"])
        self.assertEqual("durable_outbox_only", entry["publication_mode"])
        self.assertIsNone(entry["adapter"])
        self.assertIsNone(entry["credentials"])
        self.assertFalse(entry["requirements"]["verified_publishing_access"])

    def test_linkedin_has_channel_specific_recurring_series(self) -> None:
        policies, errors = recurring_series.channel_policies(self.linkedin, self.series)
        self.assertEqual([], errors)
        self.assertEqual(2, len(policies))
        self.assertEqual({"valcea-pentru-decidenti", "banii-publici-explicati"}, {row["series_id"] for row in policies})
        self.assertTrue(all("text" in row["preferred_formats"] for row in policies))

    def test_instance_mismatch_fails_closed_before_outbox(self) -> None:
        story = _story()
        story["instance_id"] = "other-city"
        report = _run(self.linkedin, story)
        self.assertTrue(report["blocked"])
        self.assertIn("INSTANCE_MISMATCH", report["hard_blocks"])
        self.assertNotEqual("OUTBOX_READY", report["disposition"])

    def test_predictive_analytics_cannot_change_native_product(self) -> None:
        baseline = _run(self.linkedin)
        injected_story = _story()
        injected_story["predicted_views"] = 99999999
        injected_story["virality_probability"] = 0.999
        injected_story["predicted_engagement"] = 123456
        injected = _run(self.linkedin, injected_story)
        baseline_product = baseline["artifacts"]["format"]["product"]
        injected_product = injected["artifacts"]["format"]["product"]
        self.assertEqual(baseline_product["product_id"], injected_product["product_id"])
        self.assertEqual(
            baseline_product["product_fingerprint_sha256"],
            injected_product["product_fingerprint_sha256"],
        )
        self.assertFalse(injected["artifacts"]["virality"]["analytics"]["predictive_analytics_used"])


class GitHubAnnotationResult(unittest.TextTestResult):
    def _annotate(self, test: unittest.TestCase) -> None:
        name = test.id().replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::error title=LinkedIn acceptance failure::{name}", file=sys.stderr)

    def addFailure(self, test: unittest.TestCase, err) -> None:
        self._annotate(test)
        super().addFailure(test, err)

    def addError(self, test: unittest.TestCase, err) -> None:
        self._annotate(test)
        super().addError(test, err)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(LinkedInOutboxAcceptance)
    result = unittest.TextTestRunner(verbosity=2, resultclass=GitHubAnnotationResult).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
