#!/usr/bin/env python3
"""Acceptance tests for WhatsApp as an independent durable-outbox publication.

Verified WhatsApp publishing access is deliberately not assumed. The channel is
modeled as a low-frequency sister publication with its own promise, voice,
cadence, fatigue, series, state and dedupe. A normal story must never be turned
into an alert merely because messaging surfaces can feel urgent.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest

import adapter_dispatch_bridge
import content_atomizer
import format_engine
import hook_engine
import production_runtime


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
WHATSAPP_CONFIG = REPO_ROOT / "valcea-clar/social/channels/whatsapp.json"
TELEGRAM_CONFIG = REPO_ROOT / "valcea-clar/social/channels/telegram.json"
REGISTRY_PATH = REPO_ROOT / "valcea-clar/social/channel_registry.json"
NOW = "2026-08-16T10:15:00Z"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _story() -> dict:
    return {
        "instance_id": "valcea",
        "story_id": "whatsapp-service-update-20260816",
        "material_fact_gate": "PASS",
        "headline": "Programul unei linii locale se modifică temporar luni dimineață",
        "dek": "Două plecări vor avea ore diferite, iar restul programului rămâne neschimbat.",
        "paragraphs": [
            "Operatorul recomandă verificarea orei de plecare înainte de deplasare.",
            "Programul obișnuit revine după intervalul anunțat.",
        ],
        "facts": [
            {"fact_id": "f1", "text": "Modificarea vizează două plecări de luni dimineață."},
            {"fact_id": "f2", "text": "Restul programului rămâne neschimbat."},
        ],
        "quotes": [],
        "topics": ["service_journalism", "civic_updates", "infrastructure"],
        "risk_flags": [],
        "available_formats": ["text", "single_photo"],
        "confidence": 99,
        "locality": 1.0,
        "proximity": 1.0,
        "utility": 0.98,
        "share_value": 0.72,
        "save_value": 0.82,
        "conversation_value": 0.42,
        "urgency": 0.28,
        "lifecycle_stage": "baseline",
    }


def _inventory(story_id: str) -> dict:
    return {
        "instance_id": "valcea",
        "assets": [
            {
                "instance_id": "valcea",
                "asset_id": "whatsapp-real-photo-a",
                "kind": "photo",
                "sha256": _digest("whatsapp-real-photo-a"),
                "synthetic": False,
                "subject_match": True,
                "editor_approved": True,
                "story_ids": [story_id],
                "source_type": "staff",
                "rights_basis": "owned",
                "credit": "VÂLCEA CLAR / acceptance fixture",
                "alt_text": "Stație de transport public din Râmnicu Vâlcea.",
            }
        ],
    }


def _history(channel: dict) -> dict:
    return {"instance_id": channel["instance_id"], "channel_id": channel["channel_id"], "records": []}


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


class WhatsAppOutboxAcceptance(unittest.TestCase):
    def setUp(self) -> None:
        self.whatsapp = _load(WHATSAPP_CONFIG)
        self.telegram = _load(TELEGRAM_CONFIG)
        self.registry = _load(REGISTRY_PATH)

    def test_channel_is_independent_outbox_only_publication(self) -> None:
        self.assertEqual("whatsapp", self.whatsapp["platform"])
        self.assertEqual("valcea-whatsapp", self.whatsapp["channel_id"])
        self.assertEqual("outbox_only", self.whatsapp["status"])
        self.assertEqual({"text", "single_photo"}, set(self.whatsapp["native_formats"]))
        self.assertEqual("none:whatsapp-publishing-access-not-verified", self.whatsapp["credentials_ref"])
        self.assertEqual("valcea-clar/social/whatsapp_outbox.json", self.whatsapp["publication_state"]["outbox_path"])
        self.assertEqual("valcea-clar/social/whatsapp_state.json", self.whatsapp["publication_state"]["state_path"])
        self.assertTrue(self.whatsapp["metrics"]["observed_only"])
        self.assertEqual([], self.whatsapp["metrics"]["sources"])
        self.assertTrue(self.whatsapp["zero_paid_dependency"])

    def test_normal_runtime_is_low_noise_text_not_fake_alert(self) -> None:
        report = _run(self.whatsapp)
        self.assertFalse(report["blocked"])
        self.assertEqual("OUTBOX_READY", report["disposition"])
        product = report["artifacts"]["format"]["product"]
        self.assertEqual("text", product["native_format"])
        self.assertEqual("message_update", product["format_family"])
        self.assertEqual("message", product["native_structure"]["surface"])
        self.assertTrue(product["hook"]["text"].startswith("Vâlcea — "))
        self.assertNotIn("URGENT", product["hook"]["text"].upper())
        self.assertEqual("NATIVE_PRODUCT_ONLY", product["cross_post_policy"])
        self.assertFalse(product["verbatim_cross_platform_reuse_allowed"])
        self.assertFalse(product["analytics_used"])

    def test_verified_correction_is_explicit_without_inventing_alert_semantics(self) -> None:
        story = _story()
        story["correction"] = True
        atoms = content_atomizer.atomize_story(story)
        hook = hook_engine.build_hook(atoms, self.whatsapp)
        formatted = format_engine.build_native_product(atoms, hook, self.whatsapp)
        self.assertFalse(formatted["blocked"])
        product = formatted["product"]
        self.assertEqual("text", product["native_format"])
        self.assertTrue(product["correction"])
        self.assertTrue(product["hook"]["text"].startswith("Corecție — "))
        self.assertFalse(product["invented_claims_allowed"])

    def test_whatsapp_and_telegram_are_distinct_sibling_products(self) -> None:
        whatsapp_report = _run(self.whatsapp)
        telegram_report = _run(self.telegram)
        whatsapp_product = whatsapp_report["artifacts"]["format"]["product"]
        telegram_product = telegram_report["artifacts"]["format"]["product"]
        self.assertEqual("text", whatsapp_product["native_format"])
        self.assertEqual("text", telegram_product["native_format"])
        self.assertNotEqual(whatsapp_product["format_family"], telegram_product["format_family"])
        self.assertNotEqual(whatsapp_product["product_id"], telegram_product["product_id"])
        self.assertNotEqual(whatsapp_product["hook"]["text"], telegram_product["hook"]["text"])

    def test_complete_whatsapp_text_is_standalone_and_requires_no_visual(self) -> None:
        report = _run(self.whatsapp)
        product = report["artifacts"]["format"]["product"]
        self.assertFalse(product["visual_requirement"]["required"])
        self.assertEqual("none", product["visual_requirement"]["media_kind"])
        self.assertEqual("NATIVE_STANDALONE", report["artifacts"]["link_binding"]["status"])
        self.assertEqual("OUTBOX_READY", report["disposition"])

    def test_bridge_targets_independent_durable_outbox_and_cannot_claim_publish(self) -> None:
        report = _run(self.whatsapp)
        bridged = adapter_dispatch_bridge.bridge_runtime_handoff(report, self.registry, present_refs=set())
        self.assertFalse(bridged["blocked"])
        self.assertEqual("OUTBOX_ONLY", bridged["dispatch_disposition"])
        self.assertEqual("OUTBOX_READY", bridged["publication_status_after_bridge"])
        self.assertTrue(bridged["adapter_handoff"]["durable_outbox_only"])
        self.assertFalse(bridged["adapter_handoff"]["dispatch_allowed"])
        self.assertIsNone(bridged["adapter_handoff"]["adapter"])
        self.assertEqual([], bridged["adapter_handoff"]["credential_reference_names"])
        self.assertFalse(bridged["guards"]["network_dispatch_performed"])
        item = next(iter(bridged["commit_bundle"]["outbox"]["items"].values()))
        self.assertEqual("valcea-clar/social/whatsapp_outbox.json", item["physical_outbox_path"])
        self.assertEqual("valcea-clar/social/whatsapp_state.json", item["physical_state_path"])

    def test_bridge_registration_is_idempotent(self) -> None:
        report = _run(self.whatsapp)
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

    def test_registry_never_invents_unverified_whatsapp_adapter_or_credentials(self) -> None:
        entries = [row for row in self.registry["channels"] if row.get("channel_id") == "whatsapp"]
        self.assertEqual(1, len(entries))
        entry = entries[0]
        self.assertEqual("outbox_only", entry["status"])
        self.assertFalse(entry["direct_publication_enabled"])
        self.assertEqual("durable_outbox_only", entry["publication_mode"])
        self.assertIsNone(entry["adapter"])
        self.assertIsNone(entry["credentials"])
        self.assertFalse(entry["requirements"]["verified_publishing_access"])
        self.assertTrue(entry["requirements"]["recipient_scope_policy_before_dispatch"])

    def test_whatsapp_has_own_low_frequency_cadence_fatigue_and_series(self) -> None:
        self.assertEqual(6, self.whatsapp["cadence"]["max_posts_per_day"])
        self.assertEqual(60, self.whatsapp["cadence"]["min_spacing_minutes"])
        self.assertEqual(8, self.whatsapp["fatigue"]["same_story_cooldown_hours"])
        self.assertEqual(2, self.whatsapp["fatigue"]["max_related_posts_24h"])
        self.assertEqual(
            {"valcea-esential", "weekend-in-valcea"},
            {row["series_id"] for row in self.whatsapp["series"]},
        )

    def test_instance_mismatch_fails_closed_before_outbox(self) -> None:
        story = _story()
        story["instance_id"] = "other-city"
        report = _run(self.whatsapp, story)
        self.assertTrue(report["blocked"])
        self.assertIn("INSTANCE_MISMATCH", report["hard_blocks"])
        self.assertNotEqual("OUTBOX_READY", report["disposition"])

    def test_predictive_analytics_cannot_change_native_product(self) -> None:
        baseline = _run(self.whatsapp)
        injected_story = _story()
        injected_story["predicted_views"] = 99999999
        injected_story["virality_probability"] = 0.999
        injected_story["predicted_engagement"] = 123456
        injected = _run(self.whatsapp, injected_story)
        baseline_product = baseline["artifacts"]["format"]["product"]
        injected_product = injected["artifacts"]["format"]["product"]
        self.assertEqual(baseline_product["product_id"], injected_product["product_id"])
        self.assertEqual(
            baseline_product["product_fingerprint_sha256"],
            injected_product["product_fingerprint_sha256"],
        )
        self.assertFalse(injected["artifacts"]["virality"]["analytics"]["predictive_analytics_used"])

    def test_channel_config_copy_does_not_create_direct_access(self) -> None:
        changed = copy.deepcopy(self.whatsapp)
        changed["status"] = "active"
        registry_entry = next(row for row in self.registry["channels"] if row.get("channel_id") == "whatsapp")
        self.assertEqual("active", changed["status"])
        self.assertFalse(registry_entry["direct_publication_enabled"])
        self.assertIsNone(registry_entry["adapter"])
        self.assertIsNone(registry_entry["credentials"])


class GitHubAnnotationResult(unittest.TextTestResult):
    def _annotate(self, test: unittest.TestCase) -> None:
        name = self.getDescription(test).replace("\n", " ")
        print(f"::error title=WhatsApp acceptance failure::{name}")

    def addFailure(self, test, err):  # type: ignore[override]
        self._annotate(test)
        super().addFailure(test, err)

    def addError(self, test, err):  # type: ignore[override]
        self._annotate(test)
        super().addError(test, err)


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(WhatsAppOutboxAcceptance)
    result = unittest.TextTestRunner(verbosity=2, resultclass=GitHubAnnotationResult).run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors) - len(result.skipped)
    print(f"WhatsApp durable outbox acceptance: {'PASS' if result.wasSuccessful() else 'FAIL'} ({passed}/{total})")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
