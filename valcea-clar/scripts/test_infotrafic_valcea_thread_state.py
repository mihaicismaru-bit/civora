#!/usr/bin/env python3
from __future__ import annotations

import copy
import unittest
from datetime import timedelta

from infotrafic_valcea_thread_state import build_threads, parse_timestamp


BASE_EVENT = {
    "event_id": "traffic-event-" + "a" * 24,
    "thread_key": "traffic-thread-" + "b" * 24,
    "source_signal_id": "signal-test",
    "source_id": "signal-infotrafic-valcea",
    "source_kind": "ROAD_TRAFFIC_ALERTS",
    "article_url": "https://politiaromana.ro/ro/info-trafic/judetul-valcea-test",
    "source_timestamp": "2026-08-28T16:35:00+03:00",
    "source_content_sha256": "c" * 64,
    "road": "DN7",
    "segment": {"start": "Călimănești", "end": "Câineni"},
    "locality": None,
    "direction": "Râmnicu Vâlcea - Sibiu",
    "state": "TRAFFIC_STOPPED",
    "estimated_reopen_at": None,
    "refresh_recheck_after": "2026-08-28T22:35:00+03:00",
    "refresh_semantics": "INTERNAL_RECHECK_DEADLINE_NOT_A_CURRENT_STATUS_CLAIM",
    "field_semantics": "EXPLICIT_SOURCE_TEXT_ONLY_NULL_WHEN_NOT_EXPLICIT",
    "lifecycle": "INTERNAL_TRAFFIC_EVENT_NEEDS_SOURCE_RECHECK",
    "publication_authority": "NONE",
    "public_projection": False,
    "auto_publication": False,
    "provenance": {
        "authority": "POLITIA_ROMANA_INFOTRAFIC",
        "source_signal_lifecycle": "SIGNAL_ONLY_NEEDS_EDITORIAL_VERIFICATION",
        "normalization": "DETERMINISTIC_INTERNAL_EVENT_V1",
        "evidence_fields": ["title", "excerpt", "source_timestamp", "source_content_sha256"],
    },
}

POLICY = {
    "reader_facing_eligible": False,
    "publication_authority": "NONE",
    "public_projection": False,
    "auto_publication": False,
    "persistence_authority": "NONE",
    "source_recheck_required_before_current_status_claim": True,
}


def document(*events: dict) -> dict:
    return {"events": list(events), "policy": copy.deepcopy(POLICY)}


def make_event(
    index: int,
    *,
    minutes: int = 0,
    state: str | None = None,
    thread: int | None = None,
    direction: str | None | object = "KEEP",
    segment: dict | None | object = "KEEP",
    locality: str | None | object = "KEEP",
) -> dict:
    event = copy.deepcopy(BASE_EVENT)
    event["event_id"] = "traffic-event-" + f"{index:024d}"
    if thread is not None:
        event["thread_key"] = "traffic-thread-" + f"{thread:024d}"
    source_time = parse_timestamp(BASE_EVENT["source_timestamp"], "test") + timedelta(minutes=minutes)
    event["source_timestamp"] = source_time.isoformat()
    event["refresh_recheck_after"] = (source_time + timedelta(hours=6)).isoformat()
    if state is not None:
        event["state"] = state
    if direction != "KEEP":
        event["direction"] = direction
    if segment != "KEEP":
        event["segment"] = segment
    if locality != "KEEP":
        event["locality"] = locality
    return event


class InfotraficValceaThreadStateTests(unittest.TestCase):
    def test_exact_thread_updates_group_and_transition(self) -> None:
        first = make_event(1, thread=1)
        second = make_event(2, minutes=30, state="ALTERNATE", thread=1)
        result = build_threads(document(first, second), "2026-08-28T18:00:00+03:00")
        self.assertEqual(result["thread_count"], 1)
        thread = result["threads"][0]
        self.assertEqual(thread["source_update_count"], 2)
        self.assertEqual(
            [item["reported_state"] for item in thread["state_transitions"]],
            ["TRAFFIC_STOPPED", "ALTERNATE"],
        )

    def test_same_segment_missing_direction_links_conservatively(self) -> None:
        first = make_event(1, thread=1)
        second = make_event(2, minutes=30, thread=2, direction=None)
        result = build_threads(document(first, second), "2026-08-28T18:00:00+03:00")
        self.assertEqual(result["thread_count"], 1)
        self.assertEqual(len(result["threads"][0]["thread_key_aliases"]), 2)

    def test_opposite_known_direction_does_not_link_fallback(self) -> None:
        first = make_event(1, thread=1)
        second = make_event(
            2,
            minutes=30,
            thread=2,
            direction="Sibiu - Râmnicu Vâlcea",
        )
        result = build_threads(document(first, second), "2026-08-28T18:00:00+03:00")
        self.assertEqual(result["thread_count"], 2)

    def test_recheck_overdue_is_not_current_status_claim(self) -> None:
        result = build_threads(document(make_event(1, thread=1)), "2026-08-29T01:00:00+03:00")
        thread = result["threads"][0]
        self.assertEqual(thread["recheck_status"], "RECHECK_OVERDUE")
        self.assertFalse(thread["current_status_claim_allowed"])

    def test_resumed_closes_thread(self) -> None:
        first = make_event(1, thread=1)
        second = make_event(2, minutes=30, state="RESUMED", thread=1)
        result = build_threads(document(first, second), "2026-08-29T01:00:00+03:00")
        self.assertEqual(
            result["threads"][0]["recheck_status"],
            "CLOSED_BY_EXPLICIT_RESUMED_UPDATE",
        )

    def test_identical_duplicate_is_deduped(self) -> None:
        first = make_event(1, thread=1)
        result = build_threads(
            document(first, copy.deepcopy(first)),
            "2026-08-28T18:00:00+03:00",
        )
        self.assertEqual(result["event_count"], 1)
        self.assertEqual(result["duplicate_event_count"], 1)

    def test_conflicting_duplicate_fails_closed(self) -> None:
        first = make_event(1, thread=1)
        conflicting = copy.deepcopy(first)
        conflicting["state"] = "HEAVY"
        with self.assertRaises(ValueError):
            build_threads(document(first, conflicting), "2026-08-28T18:00:00+03:00")

    def test_same_key_after_window_starts_new_incident(self) -> None:
        first = make_event(1, thread=1)
        second = make_event(2, minutes=13 * 60, thread=1)
        result = build_threads(document(first, second), "2026-08-29T08:00:00+03:00")
        self.assertEqual(result["thread_count"], 2)

    def test_post_resumed_new_stop_starts_new_incident(self) -> None:
        first = make_event(1, thread=1)
        resumed = make_event(2, minutes=30, state="RESUMED", thread=1)
        new_stop = make_event(3, minutes=60, state="TRAFFIC_STOPPED", thread=1)
        result = build_threads(
            document(first, resumed, new_stop),
            "2026-08-28T18:00:00+03:00",
        )
        self.assertEqual(result["thread_count"], 2)

    def test_road_only_different_keys_do_not_fallback_link(self) -> None:
        first = make_event(1, thread=1, segment=None)
        second = make_event(2, minutes=10, thread=2, segment=None)
        result = build_threads(document(first, second), "2026-08-28T18:00:00+03:00")
        self.assertEqual(result["thread_count"], 2)

    def test_policy_drift_fails_closed(self) -> None:
        payload = document(make_event(1, thread=1))
        payload["policy"]["persistence_authority"] = "WRITE"
        with self.assertRaises(ValueError):
            build_threads(payload, "2026-08-28T18:00:00+03:00")

    def test_publication_authority_fails_closed(self) -> None:
        event = make_event(1, thread=1)
        event["publication_authority"] = "ALLOW"
        with self.assertRaises(ValueError):
            build_threads(document(event), "2026-08-28T18:00:00+03:00")


if __name__ == "__main__":
    unittest.main()
