#!/usr/bin/env python3
from __future__ import annotations

import copy
import unittest
from datetime import datetime, timedelta

from infotrafic_valcea_newsroom_review_envelope import build_review_envelope

INPUT_POLICY = {
    "reader_facing_eligible": False,
    "publication_authority": "NONE",
    "public_projection": False,
    "auto_publication": False,
    "persistence_authority": "NONE",
    "current_status_claim_allowed": False,
    "requires_editorial_verification": True,
    "source_recheck_required_before_current_status_claim": True,
    "recheck_required_candidates_are_breaking_eligible": False,
    "ranking_semantics": "INTERNAL_TRIAGE_ONLY_NO_PUBLICATION_OR_CURRENT_STATUS_AUTHORITY",
}


def make_candidate(
    index: int,
    *,
    kind: str = "NEW",
    state: str = "TRAFFIC_STOPPED",
    score: int = 95,
    road: str = "DN7",
) -> dict:
    source_time = datetime.fromisoformat("2026-08-28T16:35:00+03:00") + timedelta(minutes=index)
    recheck_due = source_time + timedelta(hours=6)
    update_count = 1 if kind in {"NEW", "RECHECK_REQUIRED"} else 2
    if kind == "RESOLVED":
        state = "RESUMED"
        recheck_status = "CLOSED_BY_EXPLICIT_RESUMED_UPDATE"
        eligible = True
        hold_reason = None
    elif kind == "RECHECK_REQUIRED":
        recheck_status = "RECHECK_OVERDUE"
        eligible = False
        hold_reason = "OFFICIAL_SOURCE_RECHECK_REQUIRED_BEFORE_BREAKING_CANDIDATE"
    elif state == "UNKNOWN":
        recheck_status = "RECHECK_NOT_YET_DUE"
        eligible = False
        hold_reason = "NO_EXPLICIT_TRAFFIC_IMPACT_STATE"
    else:
        recheck_status = "RECHECK_NOT_YET_DUE"
        eligible = True
        hold_reason = None

    evidence = []
    for evidence_index in range(update_count):
        ts = source_time - timedelta(minutes=10 * (update_count - 1 - evidence_index))
        evidence.append(
            {
                "event_id": "traffic-event-" + f"{index * 10 + evidence_index:024x}",
                "source_signal_id": f"infotrafic-valcea-test-{index}-{evidence_index}",
                "article_url": (
                    "https://politiaromana.ro/ro/info-trafic/"
                    f"judetul-valcea-test-{index}-{evidence_index}"
                ),
                "source_timestamp": ts.isoformat(),
                "source_content_sha256": f"{index * 10 + evidence_index + 1:064x}",
                "normalization": "DETERMINISTIC_INTERNAL_EVENT_V1",
            }
        )

    return {
        "candidate_id": "traffic-candidate-" + f"{index:024x}",
        "dedupe_key": "traffic-logical-thread-" + f"{index:024x}",
        "candidate_kind": kind,
        "breaking_candidate_eligible": eligible,
        "hold_reason": hold_reason,
        "road": road,
        "road_family": "DN" if road.startswith("DN") else "DJ",
        "segment": {"start": "Călimănești", "end": "Câineni"},
        "locality": None,
        "direction": "Râmnicu Vâlcea - Sibiu",
        "latest_reported_state": state,
        "last_source_update_at": source_time.isoformat(),
        "source_update_count": update_count,
        "recheck_due_at": recheck_due.isoformat(),
        "recheck_status": recheck_status,
        "scores": {
            "reported_state_severity": 100 if state == "TRAFFIC_STOPPED" else 20,
            "road_network_relevance": 90,
            "local_specificity": 100,
            "internal_triage": score,
            "semantics": "INTERNAL_REVIEW_HEURISTIC_NOT_A_CURRENT_IMPACT_OR_PUBLICATION_SCORE",
            "local_specificity_basis": "EXPLICIT_SEGMENT",
        },
        "evidence_chain": evidence,
        "requires_editorial_verification": True,
        "requires_official_source_recheck_before_reader_current_status_claim": True,
        "current_status_claim_allowed": False,
        "reader_facing_eligible": False,
        "publication_authority": "NONE",
        "public_projection": False,
        "auto_publication": False,
        "persistence_authority": "NONE",
        "lifecycle": "INTERNAL_BREAKING_CANDIDATE_REVIEW_REQUIRED",
    }


def document(*candidates: dict, as_of: str = "2026-08-28T20:00:00+03:00") -> dict:
    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR internal INFOTRAFIC breaking candidates",
        "as_of": as_of,
        "candidate_count": len(candidates),
        "breaking_candidate_count": sum(
            1 for item in candidates if item["breaking_candidate_eligible"]
        ),
        "recheck_required_count": sum(
            1 for item in candidates if item["candidate_kind"] == "RECHECK_REQUIRED"
        ),
        "candidates": list(candidates),
        "policy": copy.deepcopy(INPUT_POLICY),
    }


class NewsroomReviewEnvelopeTests(unittest.TestCase):
    def test_urgent_candidate_enters_human_breaking_review(self) -> None:
        result = build_review_envelope(document(make_candidate(1, score=95)))
        item = result["items"][0]
        self.assertEqual(item["review_lane"], "URGENT_BREAKING_REVIEW")
        self.assertEqual(item["editorial_decision_state"], "UNREVIEWED")
        self.assertFalse(item["reader_facing_eligible"])
        self.assertEqual(item["publication_authority"], "NONE")
        self.assertEqual(len(item["evidence_chain"]), 1)

    def test_standard_candidate_is_not_promoted_to_urgent(self) -> None:
        item = build_review_envelope(document(make_candidate(2, score=72)))["items"][0]
        self.assertEqual(item["review_lane"], "STANDARD_BREAKING_REVIEW")

    def test_resolved_candidate_gets_resolution_lane(self) -> None:
        item = build_review_envelope(
            document(make_candidate(3, kind="RESOLVED", score=70))
        )["items"][0]
        self.assertEqual(item["review_lane"], "RESOLUTION_REVIEW")
        self.assertFalse(item["current_status_claim_allowed"])

    def test_overdue_candidate_gets_source_recheck_lane(self) -> None:
        candidate = make_candidate(4, kind="RECHECK_REQUIRED", score=100)
        result = build_review_envelope(
            document(candidate, as_of="2026-08-29T01:00:00+03:00")
        )
        item = result["items"][0]
        self.assertEqual(item["review_lane"], "SOURCE_RECHECK")
        self.assertFalse(item["breaking_candidate_eligible"])

    def test_unknown_candidate_gets_evidence_hold(self) -> None:
        item = build_review_envelope(
            document(make_candidate(5, state="UNKNOWN", score=90))
        )["items"][0]
        self.assertEqual(item["review_lane"], "EVIDENCE_HOLD")

    def test_lane_priority_precedes_raw_score(self) -> None:
        standard = make_candidate(6, score=79)
        resolution = make_candidate(7, kind="RESOLVED", score=40)
        urgent = make_candidate(8, score=80)
        recheck = make_candidate(9, kind="RECHECK_REQUIRED", score=100)
        result = build_review_envelope(
            document(standard, resolution, urgent, recheck, as_of="2026-08-29T01:00:00+03:00")
        )
        self.assertEqual(
            [item["review_lane"] for item in result["items"]],
            [
                "URGENT_BREAKING_REVIEW",
                "RESOLUTION_REVIEW",
                "STANDARD_BREAKING_REVIEW",
                "SOURCE_RECHECK",
            ],
        )

    def test_duplicate_logical_thread_fails_closed(self) -> None:
        first = make_candidate(10)
        second = make_candidate(11)
        second["dedupe_key"] = first["dedupe_key"]
        with self.assertRaises(ValueError):
            build_review_envelope(document(first, second))

    def test_candidate_count_drift_fails_closed(self) -> None:
        payload = document(make_candidate(12))
        payload["candidate_count"] = 2
        with self.assertRaises(ValueError):
            build_review_envelope(payload)

    def test_policy_drift_fails_closed(self) -> None:
        payload = document(make_candidate(13))
        payload["policy"]["publication_authority"] = "ALLOW"
        with self.assertRaises(ValueError):
            build_review_envelope(payload)

    def test_nonofficial_evidence_fails_closed(self) -> None:
        candidate = make_candidate(14)
        candidate["evidence_chain"][0]["article_url"] = "https://example.com/ro/info-trafic/test"
        with self.assertRaises(ValueError):
            build_review_envelope(document(candidate))

    def test_evidence_timestamp_must_match_candidate(self) -> None:
        candidate = make_candidate(15)
        candidate["evidence_chain"][-1]["source_timestamp"] = "2026-08-28T15:00:00+03:00"
        with self.assertRaises(ValueError):
            build_review_envelope(document(candidate))

    def test_candidate_boundary_drift_fails_closed(self) -> None:
        candidate = make_candidate(16)
        candidate["reader_facing_eligible"] = True
        with self.assertRaises(ValueError):
            build_review_envelope(document(candidate))

    def test_review_item_id_is_deterministic(self) -> None:
        payload = document(make_candidate(17))
        first = build_review_envelope(payload)["items"][0]["review_item_id"]
        second = build_review_envelope(copy.deepcopy(payload))["items"][0]["review_item_id"]
        self.assertEqual(first, second)

    def test_output_policy_has_no_runtime_authority(self) -> None:
        policy = build_review_envelope(document(make_candidate(18)))["policy"]
        self.assertEqual(policy["fact_kernel_authority"], "NONE")
        self.assertEqual(policy["writer_authority"], "NONE")
        self.assertEqual(policy["publication_authority"], "NONE")
        self.assertEqual(policy["persistence_authority"], "NONE")
        self.assertFalse(policy["stateful_queue"])


if __name__ == "__main__":
    unittest.main()
