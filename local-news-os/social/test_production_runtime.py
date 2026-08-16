#!/usr/bin/env python3
"""Acceptance tests for the LOCAL NEWS OS production social runtime orchestrator."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest

import production_runtime


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
CHANNEL_PATHS = {
    "facebook": REPO_ROOT / "valcea-clar/social/channels/facebook.json",
    "instagram": REPO_ROOT / "valcea-clar/social/channels/instagram.json",
    "tiktok": REPO_ROOT / "valcea-clar/social/channels/tiktok.json",
}
READY_NOW = "2026-08-16T09:00:00Z"
QUIET_NOW = "2026-08-15T22:30:00Z"
CANONICAL_URL = "https://valceaclar.ro/stiri/runtime-acceptance"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_channel(platform: str) -> dict:
    return json.loads(CHANNEL_PATHS[platform].read_text(encoding="utf-8"))


def _story() -> dict:
    return {
        "instance_id": "valcea",
        "story_id": "runtime-acceptance-traffic-20260816",
        "material_fact_gate": "PASS",
        "headline": "Trafic restricționat temporar pe un tronson din Râmnicu Vâlcea",
        "dek": "Restricția este programată între 08:00 și 18:00, iar șoferii vor fi deviați pe ruta semnalizată.",
        "paragraphs": [
            "Măsura este temporară și vizează intervalul anunțat în notificarea verificată.",
            "Semnalizarea din teren indică ruta alternativă pentru traficul local.",
        ],
        "facts": [
            {"fact_id": "f1", "text": "Intervalul anunțat este 08:00–18:00."},
            {"fact_id": "f2", "text": "Traficul este deviat pe ruta semnalizată."},
        ],
        "quotes": [
            {"quote_id": "q1", "text": "Respectați semnalizarea temporară din zonă."},
        ],
        "topics": ["service_journalism", "local_events", "infrastructure", "civic_updates"],
        "risk_flags": [],
        "available_formats": ["text", "single_photo", "carousel", "short"],
        "confidence": 99,
        "locality": 1.0,
        "proximity": 1.0,
        "utility": 0.95,
        "share_value": 0.82,
        "save_value": 0.72,
        "conversation_value": 0.55,
        "urgency": 0.35,
        "lifecycle_stage": "baseline",
    }


def _inventory(story_id: str) -> dict:
    common = {
        "instance_id": "valcea",
        "synthetic": False,
        "subject_match": True,
        "editor_approved": True,
        "story_ids": [story_id],
        "source_type": "staff",
        "rights_basis": "owned",
    }
    return {
        "instance_id": "valcea",
        "assets": [
            {
                **common,
                "asset_id": "runtime-photo-a",
                "kind": "photo",
                "sha256": _digest("runtime-real-photo-a"),
                "credit": "VÂLCEA CLAR / runtime fixture",
                "alt_text": "Semnalizare temporară de trafic într-o zonă urbană din Râmnicu Vâlcea.",
            },
            {
                **common,
                "asset_id": "runtime-photo-b",
                "kind": "photo",
                "sha256": _digest("runtime-real-photo-b"),
                "credit": "VÂLCEA CLAR / runtime fixture",
                "alt_text": "Rută alternativă marcată pentru traficul local în timpul restricției.",
            },
            {
                **common,
                "asset_id": "runtime-video-a",
                "kind": "video",
                "sha256": _digest("runtime-real-video-a"),
                "credit": "VÂLCEA CLAR / runtime fixture",
                "alt_text": "Secvență video reală cu semnalizarea temporară și traseul de deviere.",
            },
        ],
    }


def _history(channel: dict, records: list | None = None) -> dict:
    return {
        "instance_id": channel["instance_id"],
        "channel_id": channel["channel_id"],
        "records": copy.deepcopy(records or []),
    }


def _run(platform: str, *, story: dict | None = None, inventory: dict | None = None, now: str = READY_NOW,
         ledger: dict | None = None, human_approved: bool = True, canonical_url: str | None = CANONICAL_URL,
         series_decision: dict | None = None) -> dict:
    channel = _load_channel(platform)
    item = copy.deepcopy(story or _story())
    media = copy.deepcopy(inventory or _inventory(item["story_id"]))
    return production_runtime.orchestrate_channel(
        item,
        channel,
        media,
        _history(channel),
        now=now,
        ledger=ledger,
        human_approved=human_approved,
        canonical_url=canonical_url,
        series_decision=series_decision,
    )


class ProductionRuntimeAcceptance(unittest.TestCase):
    def test_three_sibling_publications_are_native_and_distinct(self) -> None:
        reports = {platform: _run(platform) for platform in ("facebook", "instagram", "tiktok")}
        for platform, report in reports.items():
            self.assertFalse(report["blocked"], platform)
            self.assertEqual("READY", report["disposition"], platform)
            self.assertTrue(report["handoff"]["adapter_dispatch_eligible"], platform)
            self.assertFalse(report["guards"]["network_calls_performed"], platform)
            self.assertTrue(report["guards"]["zero_paid_dependency"], platform)

        products = {platform: report["artifacts"]["format"]["product"] for platform, report in reports.items()}
        self.assertEqual("single_photo", products["facebook"]["native_format"])
        self.assertEqual("carousel", products["instagram"]["native_format"])
        self.assertEqual("short", products["tiktok"]["native_format"])
        self.assertEqual(3, len({product["product_id"] for product in products.values()}))
        self.assertEqual(3, len({product["hook"]["text"] for product in products.values()}))
        self.assertTrue(all(product["verbatim_cross_platform_reuse_allowed"] is False for product in products.values()))

    def test_visual_provenance_is_bound_before_publication_state(self) -> None:
        report = _run("instagram")
        binding = report["artifacts"]["visual"]["binding"]
        self.assertEqual("VISUAL_READY", binding["status"])
        self.assertTrue(binding["provenance_complete"])
        self.assertTrue(binding["reuse_rights_complete"])
        self.assertFalse(binding["synthetic_media_used"])
        self.assertEqual(2, len(binding["selected_asset_ids"]))

    def test_required_link_is_a_hold_not_an_invented_url(self) -> None:
        report = _run("facebook", canonical_url=None)
        self.assertFalse(report["blocked"])
        self.assertEqual("HOLD_LINK_BINDING", report["disposition"])
        self.assertTrue(report["handoff"]["link_hold"])
        self.assertNotIn("publication", report["artifacts"])
        self.assertIsNone(report["artifacts"]["link_binding"]["bound_url"])

    def test_wrong_canonical_host_fails_closed(self) -> None:
        report = _run("facebook", canonical_url="https://example.invalid/story")
        self.assertTrue(report["blocked"])
        self.assertEqual("BLOCKED_LINK_POLICY", report["disposition"])
        self.assertIn("LINK_HOST_NOT_ALLOWED", report["hard_blocks"])

    def test_native_complete_channel_can_run_without_site_link(self) -> None:
        report = _run("instagram", canonical_url=None)
        self.assertFalse(report["blocked"])
        self.assertEqual("READY", report["disposition"])
        self.assertEqual("OPTIONAL_UNBOUND", report["artifacts"]["link_binding"]["status"])

    def test_quiet_hours_become_durable_timing_hold(self) -> None:
        report = _run("facebook", now=QUIET_NOW)
        self.assertFalse(report["blocked"])
        self.assertEqual("HOLD_TIMING", report["disposition"])
        self.assertTrue(report["handoff"]["timing_hold"])
        self.assertFalse(report["handoff"]["adapter_dispatch_eligible"])
        self.assertIn("QUIET_HOURS", report["artifacts"]["cadence"]["cadence_blocks"])
        self.assertEqual("HOLD_TIMING", report["artifacts"]["publication"]["record"]["status"])

    def test_tiktok_human_gate_is_preserved(self) -> None:
        report = _run("tiktok", human_approved=False)
        self.assertFalse(report["blocked"])
        self.assertEqual("AWAITING_APPROVAL", report["disposition"])
        self.assertTrue(report["handoff"]["requires_human_approval"])
        self.assertFalse(report["handoff"]["adapter_dispatch_eligible"])

    def test_missing_required_real_video_blocks_tiktok(self) -> None:
        story = _story()
        inventory = _inventory(story["story_id"])
        inventory["assets"] = [asset for asset in inventory["assets"] if asset["kind"] == "photo"]
        report = _run("tiktok", story=story, inventory=inventory)
        self.assertTrue(report["blocked"])
        self.assertEqual("BLOCKED_VISUAL", report["disposition"])
        self.assertIn("INSUFFICIENT_APPROVED_REAL_MEDIA", report["hard_blocks"])
        self.assertNotIn("publication", report["artifacts"])

    def test_instance_mismatch_blocks_at_preflight(self) -> None:
        story = _story()
        story["instance_id"] = "shadow"
        inventory = _inventory(story["story_id"])
        report = _run("facebook", story=story, inventory=inventory)
        self.assertTrue(report["blocked"])
        self.assertEqual("BLOCKED_PREFLIGHT", report["disposition"])
        self.assertIn("INSTANCE_MISMATCH", report["hard_blocks"])

    def test_repeated_run_with_ledger_is_idempotent(self) -> None:
        first = _run("facebook")
        ledger = first["artifacts"]["publication"]["ledger"]
        second = _run("facebook", ledger=ledger)
        self.assertFalse(second["blocked"])
        self.assertEqual(
            first["artifacts"]["publication"]["record"]["publication_id"],
            second["artifacts"]["publication"]["record"]["publication_id"],
        )
        self.assertEqual("DEDUPE_EXISTING", second["artifacts"]["publication"]["decision"])
        self.assertEqual(first["pipeline_fingerprint_sha256"], second["pipeline_fingerprint_sha256"])

    def test_predictive_analytics_do_not_change_virality_score(self) -> None:
        baseline = _run("instagram")
        injected_story = _story()
        injected_story.update({"predicted_views": 999999999, "predicted_engagement": 1.0, "virality_probability": 1.0})
        injected = _run("instagram", story=injected_story)
        self.assertEqual(baseline["artifacts"]["virality"]["score"], injected["artifacts"]["virality"]["score"])
        self.assertFalse(injected["guards"]["predictive_analytics_used"])
        reasons = injected["artifacts"]["virality"].get("reasons", [])
        self.assertTrue(any(str(reason).startswith("PREDICTIVE_ANALYTICS_IGNORED:") for reason in reasons))

    def test_series_decision_can_inform_ranking_without_weakening_gates(self) -> None:
        story = _story()
        channel = _load_channel("facebook")
        series = {
            "instance_id": "valcea",
            "channel_id": channel["channel_id"],
            "story_id": story["story_id"],
            "eligible": True,
            "decision": "SERIES_READY",
            "hard_blocks": [],
            "occurrence": {"selected_story_ids": [story["story_id"]]},
        }
        without = _run("facebook", story=story)
        with_series = _run("facebook", story=story, series_decision=series)
        self.assertFalse(with_series["blocked"])
        self.assertEqual(without["artifacts"]["virality"]["score"] + 3.0, with_series["artifacts"]["virality"]["score"])
        self.assertFalse(with_series["artifacts"]["virality"]["guards"]["editorial_gates_weakened"])

    def test_zero_paid_dependency_is_fail_closed(self) -> None:
        story = _story()
        channel = _load_channel("facebook")
        channel["zero_paid_dependency"] = False
        report = production_runtime.orchestrate_channel(
            story,
            channel,
            _inventory(story["story_id"]),
            _history(channel),
            now=READY_NOW,
            human_approved=True,
            canonical_url=CANONICAL_URL,
        )
        self.assertTrue(report["blocked"])
        self.assertEqual("BLOCKED_PREFLIGHT", report["disposition"])
        self.assertIn("ZERO_PAID_DEPENDENCY_VIOLATION", report["hard_blocks"])

    def test_identical_inputs_are_deterministic(self) -> None:
        first = _run("facebook")
        second = _run("facebook")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
