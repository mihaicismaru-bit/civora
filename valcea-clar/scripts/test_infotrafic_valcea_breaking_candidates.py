#!/usr/bin/env python3
from __future__ import annotations

import copy
import unittest
from datetime import datetime, timedelta

from infotrafic_valcea_breaking_candidates import build_candidates


BASE_EVENT = {
    "event_id": "traffic-event-" + "a" * 24,
    "thread_key": "traffic-thread-" + "b" * 24,
    "source_signal_id": "infotrafic-valcea-test",
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

EVENT_POLICY = {
    "reader_facing_eligible": False,
    "publication_authority": "NONE",
    "public_projection": False,
    "auto_publication": False,
    "persistence_authority": "NONE",
    "source_recheck_required_before_current_status_claim": True,
}


def make_event(index: int, *, minutes: int = 0, state: str = "TRAFFIC_STOPPED") -> dict:
    event = copy.deepcopy(BASE_EVENT)
    event["event_id"] = "traffic-event-" + f"{index:024x}"
    event["thread_key"] = "traffic-thread-" + "1" * 24
    source_time = datetime.fromisoformat(BASE_EVENT["source_timestamp"]) + timedelta(minutes=minutes)
    event["source_timestamp"] = source_time.isoformat()
    event["refresh_recheck_after"] = (source_time + timedelta(hours=6)).isoformat()
    event["source_content_sha256"] = f"{index:064x}"
    event["article_url"] = (
        f"https://politiaromana.ro/ro/info-trafic/judetul-valcea-test-{index}"
    )
    event["state"] = state
    return event


def normalized_document(*events: dict) -> dict:
    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR internal traffic-event intelligence",
        "event_count": len(events),
        "events": list(events),
        "policy": copy.deepcopy(EVENT_POLICY),
    }


def thread_document(events: tuple[dict, ...], as_of: str) -> dict:
    latest = events[-1]
    as_of_dt = datetime.fromisoformat(as_of)
    recheck_due = datetime.fromisoformat(latest["refresh_recheck_after"])
    if latest["state"] == "RESUMED":
        recheck_status = "CLOSED_BY_EXPLICIT_RESUMED_UPDATE"
    elif as_of_dt >= recheck_due:
        recheck_status = "RECHECK_OVERDUE"
    else:
        recheck_status = "RECHECK_NOT_YET_DUE"
    transitions = []
    previous = None
    for event in events:
        if event["state"] != previous:
            transitions.append(
                {
                    "event_id": event["event_id"],
                    "source_timestamp": event["source_timestamp"],
                    "reported_state": event["state"],
                }
            )
            previous = event["state"]
    thread = {
        "logical_thread_id": "traffic-logical-thread-" + "d" * 24,
        "road": latest["road"],
        "latest_segment": copy.deepcopy(latest["segment"]),
        "latest_locality": latest["locality"],
        "latest_direction": latest["direction"],
        "geography_basis": (
            "SEGMENT"
            if latest["segment"]
            else "LOCALITY"
            if latest["locality"]
            else "ROAD_ONLY_NO_FALLBACK_LINKING"
        ),
        "thread_key_aliases": sorted({event["thread_key"] for event in events}),
        "event_ids": [event["event_id"] for event in events],
        "source_update_count": len(events),
        "first_source_update_at": events[0]["source_timestamp"],
        "last_source_update_at": latest["source_timestamp"],
        "latest_event_id": latest["event_id"],
        "latest_reported_state": latest["state"],
        "state_transitions": transitions,
        "recheck_due_at": latest["refresh_recheck_after"],
        "recheck_status": recheck_status,
        "current_status_claim_allowed": False,
        "reader_facing_eligible": False,
        "lifecycle": "INTERNAL_TRAFFIC_THREAD_NEEDS_SOURCE_RECHECK",
    }
    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR internal INFOTRAFIC thread state",
        "as_of": as_of,
        "event_count": len(events),
        "duplicate_event_count": 0,
        "thread_count": 1,
        "threads": [thread],
        "policy": {
            "reader_facing_eligible": False,
            "publication_authority": "NONE",
            "public_projection": False,
            "auto_publication": False,
            "persistence_authority": "NONE",
            "current_status_claim_allowed": False,
            "source_recheck_required_before_current_status_claim": True,
            "matching_window_hours": 12,
            "matching_semantics": "EXACT_THREAD_KEY_OR_UNAMBIGUOUS_SAME_EXPLICIT_GEOGRAPHY_WITH_COMPATIBLE_DIRECTION",
            "expiry_semantics": "RECHECK_DEADLINE_ONLY_NEVER_AUTOMATIC_CURRENT_STATUS",
        },
    }


class InfotraficValceaBreakingCandidateTests(unittest.TestCase):
    def test_new_stopped_candidate_preserves_evidence(self) -> None:
        event = make_event(1)
        threads = thread_document((event,), "2026-08-28T18:00:00+03:00")
        result = build_candidates(threads, normalized_document(event))
        self.assertEqual(result["breaking_candidate_count"], 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["candidate_kind"], "NEW")
        self.assertTrue(candidate["breaking_candidate_eligible"])
        self.assertEqual(candidate["scores"]["reported_state_severity"], 100)
        self.assertEqual(candidate["scores"]["local_specificity"], 100)
        self.assertEqual(candidate["evidence_chain"][0]["article_url"], event["article_url"])
        self.assertEqual(
            candidate["evidence_chain"][0]["source_content_sha256"],
            event["source_content_sha256"],
        )
        self.assertFalse(candidate["current_status_claim_allowed"])

    def test_update_candidate_keeps_thread_dedupe_key(self) -> None:
        first = make_event(1)
        second = make_event(2, minutes=30, state="ALTERNATE")
        threads = thread_document((first, second), "2026-08-28T18:00:00+03:00")
        result = build_candidates(threads, normalized_document(first, second))
        candidate = result["candidates"][0]
        self.assertEqual(candidate["candidate_kind"], "UPDATE")
        self.assertEqual(candidate["source_update_count"], 2)
        self.assertEqual(len(candidate["evidence_chain"]), 2)
        self.assertEqual(candidate["dedupe_key"], threads["threads"][0]["logical_thread_id"])

    def test_resumed_is_resolved_candidate_not_current_claim(self) -> None:
        first = make_event(1)
        resumed = make_event(2, minutes=30, state="RESUMED")
        threads = thread_document((first, resumed), "2026-08-29T01:00:00+03:00")
        result = build_candidates(threads, normalized_document(first, resumed))
        candidate = result["candidates"][0]
        self.assertEqual(candidate["candidate_kind"], "RESOLVED")
        self.assertTrue(candidate["breaking_candidate_eligible"])
        self.assertFalse(candidate["current_status_claim_allowed"])

    def test_overdue_candidate_requires_recheck_and_is_not_breaking_eligible(self) -> None:
        event = make_event(1)
        threads = thread_document((event,), "2026-08-29T01:00:00+03:00")
        result = build_candidates(threads, normalized_document(event))
        candidate = result["candidates"][0]
        self.assertEqual(candidate["candidate_kind"], "RECHECK_REQUIRED")
        self.assertFalse(candidate["breaking_candidate_eligible"])
        self.assertEqual(
            candidate["hold_reason"],
            "OFFICIAL_SOURCE_RECHECK_REQUIRED_BEFORE_BREAKING_CANDIDATE",
        )
        self.assertEqual(result["recheck_required_count"], 1)

    def test_unknown_impact_is_held(self) -> None:
        event = make_event(1, state="UNKNOWN")
        threads = thread_document((event,), "2026-08-28T18:00:00+03:00")
        result = build_candidates(threads, normalized_document(event))
        candidate = result["candidates"][0]
        self.assertEqual(candidate["candidate_kind"], "NEW")
        self.assertFalse(candidate["breaking_candidate_eligible"])
        self.assertEqual(candidate["hold_reason"], "NO_EXPLICIT_TRAFFIC_IMPACT_STATE")

    def test_missing_event_evidence_fails_closed(self) -> None:
        event = make_event(1)
        threads = thread_document((event,), "2026-08-28T18:00:00+03:00")
        with self.assertRaises(ValueError):
            build_candidates(threads, normalized_document())

    def test_nonofficial_evidence_url_fails_closed(self) -> None:
        event = make_event(1)
        threads = thread_document((event,), "2026-08-28T18:00:00+03:00")
        bad = copy.deepcopy(event)
        bad["article_url"] = "https://example.com/ro/info-trafic/test"
        with self.assertRaises(ValueError):
            build_candidates(threads, normalized_document(bad))

    def test_thread_evidence_mismatch_fails_closed(self) -> None:
        event = make_event(1)
        threads = thread_document((event,), "2026-08-28T18:00:00+03:00")
        threads["threads"][0]["latest_reported_state"] = "HEAVY"
        with self.assertRaises(ValueError):
            build_candidates(threads, normalized_document(event))

    def test_policy_drift_fails_closed(self) -> None:
        event = make_event(1)
        threads = thread_document((event,), "2026-08-28T18:00:00+03:00")
        threads["policy"]["publication_authority"] = "ALLOW"
        with self.assertRaises(ValueError):
            build_candidates(threads, normalized_document(event))

    def test_recheck_status_drift_fails_closed(self) -> None:
        event = make_event(1)
        threads = thread_document((event,), "2026-08-29T01:00:00+03:00")
        threads["threads"][0]["recheck_status"] = "RECHECK_NOT_YET_DUE"
        with self.assertRaises(ValueError):
            build_candidates(threads, normalized_document(event))

    def test_candidate_id_is_deterministic(self) -> None:
        event = make_event(1)
        threads = thread_document((event,), "2026-08-28T18:00:00+03:00")
        first = build_candidates(threads, normalized_document(event))["candidates"][0]
        second = build_candidates(
            copy.deepcopy(threads), normalized_document(copy.deepcopy(event))
        )["candidates"][0]
        self.assertEqual(first["candidate_id"], second["candidate_id"])


if __name__ == "__main__":
    unittest.main()
