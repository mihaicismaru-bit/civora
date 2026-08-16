#!/usr/bin/env python3
"""Acceptance tests for Telegram as an independent durable-outbox publication.

Telegram publishing access is deliberately not assumed. The target is a rapid,
compact sister publication with its own selection, cadence, native formats,
series, state, dedupe and outbox handoff. Normal updates must never be mislabeled
as alerts merely because the channel supports an alert format.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

import adapter_dispatch_bridge
import content_atomizer
import format_engine
import hook_engine
import production_runtime
import recurring_series


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
TELEGRAM_CONFIG = REPO_ROOT / "valcea-clar/social/channels/telegram.json"
THREADS_CONFIG = REPO_ROOT / "valcea-clar/social/channels/threads.json"
REGISTRY_PATH = REPO_ROOT / "valcea-clar/social/channel_registry.json"
SERIES_PATH = REPO_ROOT / "valcea-clar/social/series_registry.json"
NOW = "2026-08-16T09:30:00Z"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _story() -> dict:
    return {
        "instance_id": "valcea",
        "story_id": "telegram-service-update-20260816",
        "material_fact_gate": "PASS",
        "headline": "Traficul va fi dirijat temporar pe o arteră din Râmnicu Vâlcea",
        "dek": "Lucrările sunt programate între 09:00 și 16:00, iar accesul riveranilor rămâne deschis.",
        "paragraphs": [
            "Semnalizarea temporară va fi mutată pe măsură ce frontul de lucru avansează.",
            "Șoferii sunt îndrumați să reducă viteza în zona intervenției.",
        ],
        "facts": [
            {"fact_id": "f1", "text": "Intervalul anunțat pentru lucrări este 09:00–16:00."},
            {"fact_id": "f2", "text": "Accesul riveranilor rămâne deschis pe durata intervenției."},
        ],
        "quotes": [],
        "topics": ["service_journalism", "civic_updates", "infrastructure"],
        "risk_flags": [],
        "available_formats": ["text", "digest", "alert", "single_photo", "thread"],
        "confidence": 99,
        "locality": 1.0,
        "proximity": 1.0,
        "utility": 0.97,
        "share_value": 0.78,
        "save_value": 0.76,
        "conversation_value": 0.55,
        "urgency": 0.35,
        "lifecycle_stage": "baseline",
    }


def _inventory(story_id: str) -> dict:
    return {
        "instance_id": "valcea",
        "assets": [
            {
                "instance_id": "valcea",
                "asset_id": "telegram-real-photo-a",
                "kind": "photo",
                "sha256": _digest("telegram-real-photo-a"),
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


class TelegramOutboxAcceptance(unittest.TestCase):
    def setUp(self) -> None:
        self.telegram = _load(TELEGRAM_CONFIG)
        self.threads = _load(THREADS_CONFIG)
        self.registry = _load(REGISTRY_PATH)
        self.series = _load(SERIES_PATH)

    def test_channel_is_independent_outbox_only_publication(self) -> None:
        self.assertEqual("telegram", self.telegram["platform"])
        self.assertEqual("valcea-telegram", self.telegram["channel_id"])
        self.assertEqual("outbox_only", self.telegram["status"])
        self.assertEqual({"text", "digest", "alert", "single_photo"}, set(self.telegram["native_formats"]))
        self.assertEqual("none:telegram-publishing-access-not-verified", self.telegram["credentials_ref"])
        self.assertEqual("valcea-clar/social/telegram_outbox.json", self.telegram["publication_state"]["outbox_path"])
        self.assertEqual("valcea-clar/social/telegram_state.json", self.telegram["publication_state"]["state_path"])
        self.assertTrue(self.telegram["metrics"]["observed_only"])
        self.assertEqual([], self.telegram["metrics"]["sources"])
        self.assertTrue(self.telegram["zero_paid_dependency"])

    def test_normal_runtime_builds_compact_text_not_fake_alert(self) -> None:
        report = _run(self.telegram)
        self.assertFalse(report["blocked"])
        self.assertEqual("OUTBOX_READY", report["disposition"])
        product = report["artifacts"]["format"]["product"]
        self.assertEqual("text", product["native_format"])
        self.assertEqual("channel_update", product["format_family"])
        self.assertEqual("message", product["native_structure"]["surface"])
        self.assertEqual("compact_verified_update", product["native_structure"]["composition"])
        self.assertTrue(product["hook"]["text"].startswith("De știut — "))
        self.assertNotEqual("alert", product["native_format"])
        self.assertEqual("NATIVE_PRODUCT_ONLY", product["cross_post_policy"])
        self.assertFalse(product["verbatim_cross_platform_reuse_allowed"])
        self.assertFalse(product["analytics_used"])

    def test_verified_correction_uses_alert_format_without_invented_copy(self) -> None:
        story = _story()
        story["correction"] = True
        atoms = content_atomizer.atomize_story(story)
        hook = hook_engine.build_hook(atoms, self.telegram)
        formatted = format_engine.build_native_product(atoms, hook, self.telegram)
        self.assertFalse(formatted["blocked"])
        product = formatted["product"]
        self.assertEqual("alert", product["native_format"])
        self.assertTrue(product["correction"])
        self.assertTrue(product["hook"]["text"].startswith("Corecție — "))
        self.assertFalse(product["invented_claims_allowed"])

    def test_telegram_and_threads_are_distinct_sibling_products(self) -> None:
        telegram_report = _run(self.telegram)
        threads_report = _run(self.threads)
        telegram_product = telegram_report["artifacts"]["format"]["product"]
        threads_product = threads_report["artifacts"]["format"]["product"]
        self.assertEqual("text", telegram_product["native_format"])
        self.assertEqual("thread", threads_product["native_format"])
        self.assertNotEqual(telegram_product["product_id"], threads_product["product_id"])
        self.assertNotEqual(telegram_product["native_structure"], threads_product["native_structure"])
        self.assertNotEqual(telegram_product["hook"]["text"], threads_product["hook"]["text"])

    def test_complete_telegram_text_is_standalone_and_requires_no_visual(self) -> None:
        report = _run(self.telegram)
        product = report["artifacts"]["format"]["product"]
        self.assertFalse(product["visual_requirement"]["required"])
        self.assertEqual("none", product["visual_requirement"]["media_kind"])
        self.assertEqual("NATIVE_STANDALONE", report["artifacts"]["link_binding"]["status"])
        self.assertEqual("OUTBOX_READY", report["disposition"])

    def test_bridge_persists_native_outbox_and_cannot_claim_publish(self) -> None:
        report = _run(self.telegram)
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
        self.assertEqual("valcea-clar/social/telegram_outbox.json", item["physical_outbox_path"])
        self.assertEqual("valcea-clar/social/telegram_state.json", item["physical_state_path"])
        self.assertEqual(report["artifacts"]["format"]["product"], item["adapter_payload"]["native_product"])

    def test_bridge_registration_is_idempotent(self) -> None:
        report = _run(self.telegram)
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

    def test_registry_never_invents_unverified_telegram_adapter_or_credentials(self) -> None:
        entries = [row for row in self.registry["channels"] if row.get("channel_id") == "telegram"]
        self.assertEqual(1, len(entries))
        entry = entries[0]
        self.assertEqual("outbox_only", entry["status"])
        self.assertFalse(entry["direct_publication_enabled"])
        self.assertEqual("durable_outbox_only", entry["publication_mode"])
        self.assertIsNone(entry["adapter"])
        self.assertIsNone(entry["credentials"])
        self.assertFalse(entry["requirements"]["verified_publishing_access"])

    def test_telegram_has_channel_specific_recurring_series(self) -> None:
        policies, errors = recurring_series.channel_policies(self.telegram, self.series)
        self.assertEqual([], errors)
        self.assertEqual(2, len(policies))
        self.assertEqual({"valcea-acum", "ce-trebuie-sa-stii"}, {row["series_id"] for row in policies})
        self.assertTrue(all("digest" in row["preferred_formats"] for row in policies))

    def test_instance_mismatch_fails_closed_before_outbox(self) -> None:
        story = _story()
        story["instance_id"] = "other-city"
        report = _run(self.telegram, story)
        self.assertTrue(report["blocked"])
        self.assertIn("INSTANCE_MISMATCH", report["hard_blocks"])
        self.assertNotEqual("OUTBOX_READY", report["disposition"])

    def test_predictive_analytics_cannot_change_native_product(self) -> None:
        baseline = _run(self.telegram)
        injected_story = _story()
        injected_story["predicted_views"] = 99999999
        injected_story["virality_probability"] = 0.999
        injected_story["predicted_engagement"] = 123456
        injected = _run(self.telegram, injected_story)
        baseline_product = baseline["artifacts"]["format"]["product"]
        injected_product = injected["artifacts"]["format"]["product"]
        self.assertEqual(baseline_product["product_id"], injected_product["product_id"])
        self.assertEqual(
            baseline_product["product_fingerprint_sha256"],
            injected_product["product_fingerprint_sha256"],
        )
        self.assertFalse(injected["artifacts"]["virality"]["analytics"]["predictive_analytics_used"])

    def test_channel_config_copy_does_not_create_direct_access(self) -> None:
        changed = copy.deepcopy(self.telegram)
        changed["status"] = "active"
        registry_entry = next(row for row in self.registry["channels"] if row.get("channel_id") == "telegram")
        self.assertFalse(registry_entry["direct_publication_enabled"])
        self.assertIsNone(registry_entry["adapter"])
        self.assertIsNone(registry_entry["credentials"])


class GitHubAnnotationResult(unittest.TextTestResult):
    def _annotate(self, test: unittest.TestCase) -> None:
        name = self.getDescription(test).replace("\n", " ")
        print(f"::error title=Telegram acceptance failure::{name}")

    def addFailure(self, test, err):  # type: ignore[override]
        self._annotate(test)
        super().addFailure(test, err)

    def addError(self, test, err):  # type: ignore[override]
        self._annotate(test)
        super().addError(test, err)


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TelegramOutboxAcceptance)
    result = unittest.TextTestRunner(verbosity=2, resultclass=GitHubAnnotationResult).run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors) - len(result.skipped)
    print(f"Telegram durable outbox acceptance: {'PASS' if result.wasSuccessful() else 'FAIL'} ({passed}/{total})")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
