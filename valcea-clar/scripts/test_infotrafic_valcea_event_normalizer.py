#!/usr/bin/env python3
from __future__ import annotations

import copy
import unittest

from infotrafic_valcea_event_normalizer import normalize_signal


BASE_SIGNAL = {
    "signal_id": "infotrafic-valcea-test",
    "source_id": "signal-infotrafic-valcea",
    "source_kind": "ROAD_TRAFFIC_ALERTS",
    "article_url": "https://politiaromana.ro/ro/info-trafic/judetul-valcea-test",
    "source_timestamp": "2026-08-28T16:35:00+03:00",
    "source_content_sha256": "a" * 64,
    "title": "JUDEȚUL VÂLCEA: INFORMARE PE DN 7",
    "excerpt": "Traficul este oprit pe DN 7, între Călimănești și Câineni, pe sensul Râmnicu Vâlcea - Sibiu. Se estimează reluarea traficului în jurul orei 18:00.",
    "lifecycle": "SIGNAL_ONLY_NEEDS_EDITORIAL_VERIFICATION",
    "publication_authority": "NONE",
    "public_projection": False,
    "auto_publication": False,
}


class InfotraficValceaEventNormalizerTests(unittest.TestCase):
    def make(self, excerpt: str) -> dict:
        signal = copy.deepcopy(BASE_SIGNAL)
        signal["excerpt"] = excerpt
        return signal

    def test_stopped_event_extracts_explicit_fields(self) -> None:
        event = normalize_signal(BASE_SIGNAL)
        self.assertEqual(event["road"], "DN7")
        self.assertEqual(event["state"], "TRAFFIC_STOPPED")
        self.assertEqual(event["segment"], {"start": "Călimănești", "end": "Câineni"})
        self.assertEqual(event["direction"], "Râmnicu Vâlcea - Sibiu")
        self.assertEqual(event["estimated_reopen_at"], "2026-08-28T18:00:00+03:00")
        self.assertEqual(event["refresh_recheck_after"], "2026-08-28T22:35:00+03:00")
        self.assertFalse(event["public_projection"])
        self.assertFalse(event["auto_publication"])

    def test_alternate_state(self) -> None:
        event = normalize_signal(self.make("Circulația se desfășoară alternativ pe DN7."))
        self.assertEqual(event["state"], "ALTERNATE")

    def test_heavy_state(self) -> None:
        event = normalize_signal(self.make("Sunt valori ridicate de trafic pe DN 7."))
        self.assertEqual(event["state"], "HEAVY")

    def test_resumed_state(self) -> None:
        event = normalize_signal(self.make("Traficul a fost reluat pe DN7."))
        self.assertEqual(event["state"], "RESUMED")

    def test_estimate_does_not_claim_resumed(self) -> None:
        event = normalize_signal(
            self.make("Se estimează reluarea traficului pe DN7 în jurul orei 19:00.")
        )
        self.assertEqual(event["state"], "UNKNOWN")
        self.assertEqual(event["estimated_reopen_at"], "2026-08-28T19:00:00+03:00")

    def test_past_clock_estimate_is_not_rolled_into_tomorrow(self) -> None:
        event = normalize_signal(
            self.make("Se estimează reluarea traficului pe DN7 în jurul orei 15:00.")
        )
        self.assertIsNone(event["estimated_reopen_at"])

    def test_missing_direction_stays_null(self) -> None:
        event = normalize_signal(self.make("Trafic intens pe DN7 în localitatea Bujoreni."))
        self.assertIsNone(event["direction"])
        self.assertEqual(event["locality"], "Bujoreni")

    def test_thread_key_is_stable_for_same_explicit_corridor(self) -> None:
        first = normalize_signal(BASE_SIGNAL)
        second_signal = copy.deepcopy(BASE_SIGNAL)
        second_signal["article_url"] += "-update"
        second_signal["source_timestamp"] = "2026-08-28T16:50:00+03:00"
        second_signal["source_content_sha256"] = "b" * 64
        second_signal["excerpt"] = "Pe DN7, între Călimănești și Câineni, pe sensul Râmnicu Vâlcea - Sibiu, traficul este oprit."
        second = normalize_signal(second_signal)
        self.assertEqual(first["thread_key"], second["thread_key"])
        self.assertNotEqual(first["event_id"], second["event_id"])

    def test_wrong_host_fails_closed(self) -> None:
        signal = copy.deepcopy(BASE_SIGNAL)
        signal["article_url"] = "https://example.com/ro/info-trafic/fake"
        with self.assertRaises(ValueError):
            normalize_signal(signal)

    def test_missing_road_fails_closed(self) -> None:
        signal = self.make("Trafic intens în zonă.")
        signal["title"] = "JUDEȚUL VÂLCEA: INFORMARE RUTIERĂ"
        with self.assertRaises(ValueError):
            normalize_signal(signal)


if __name__ == "__main__":
    unittest.main()
