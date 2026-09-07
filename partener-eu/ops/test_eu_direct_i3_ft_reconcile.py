#!/usr/bin/env python3
from __future__ import annotations

import copy
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ingest"))

import test_eu_direct_i3_ft_exact as exact_test
from eu_direct_i3_ft_exact import collect_exact
from eu_direct_i3_ft_reconcile import reconcile, validate_receipt


def make_healthy(*, fetched_at: str, deadline: str = "2026-11-12T17:00:00+01:00"):
    return collect_exact(
        exact_test.REF,
        eismea_url=exact_test.EISMEA_URL,
        run_id="reconcile-synthetic",
        fetched_at=fetched_at,
        post_func=exact_test.make_post(search=exact_test.search_payload(deadline)),
        topic_func=exact_test.topic,
        eismea_fetcher=exact_test.eismea_open,
    )


def make_degraded(*, fetched_at: str):
    return collect_exact(
        exact_test.REF,
        eismea_url=exact_test.EISMEA_URL,
        run_id="reconcile-degraded",
        fetched_at=fetched_at,
        post_func=exact_test.make_post(),
        topic_func=exact_test.degraded_topic,
        eismea_fetcher=exact_test.eismea_open,
    )


def expect_value_error(fn, contains: str | None = None):
    try:
        fn()
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        if contains is not None:
            assert contains in str(exc), (contains, str(exc))


def main():
    previous = make_healthy(fetched_at="2026-09-06T07:30:00+00:00")
    current = make_healthy(fetched_at="2026-09-06T07:31:00+00:00")

    baseline = reconcile(previous)
    assert baseline["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
    assert baseline["semantic_reconciliation_passed"] is True
    assert baseline["material_admission_ready_for_downstream_review"] is True
    assert baseline["previous_evidence_sha256"] is None

    no_change = reconcile(current, previous)
    assert no_change["reconciliation_state"] == "NO_CHANGE"
    assert no_change["semantic_change_count"] == 0
    assert no_change["semantic_changes"] == []
    assert no_change["previous_identity_match"] is True
    assert no_change["lkg_reference_available"] is True
    assert no_change["lkg_reference_is_current_truth"] is False
    assert no_change["material_admission_ready_for_downstream_review"] is True
    assert "field_scoped_material_admission" in no_change["missing_for_material_admission"]
    assert no_change["open_call_authorized"] is False
    assert no_change["deadline_authorized"] is False
    assert no_change["budget_authorized"] is False
    assert no_change["eligibility_authorized"] is False
    assert no_change["publish_authorized"] is False
    assert no_change["distribution_authorized"] is False
    assert no_change["call_alert_authorized"] is False
    assert no_change["publication_effect"] == "NONE"
    assert no_change["canonical_corpus_mutation"] is False

    changed = make_healthy(
        fetched_at="2026-09-06T07:32:00+00:00",
        deadline="2026-12-12T17:00:00+01:00",
    )
    semantic_change = reconcile(changed, previous)
    assert semantic_change["reconciliation_state"] == "I3_EXACT_CALL_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
    assert semantic_change["semantic_change_count"] >= 1
    assert any(row["field"] == "deadline_candidate" for row in semantic_change["semantic_changes"])
    assert semantic_change["open_call_authorized"] is False
    assert semantic_change["publication_effect"] == "NONE"

    degraded = make_degraded(fetched_at="2026-09-06T07:33:00+00:00")
    degraded_rec = reconcile(degraded, previous)
    assert degraded_rec["reconciliation_state"] == "CURRENT_EXACT_AUTHORITY_UNRESOLVED_LKG_REQUIRED"
    assert degraded_rec["semantic_reconciliation_passed"] is False
    assert degraded_rec["lkg_reference_required"] is True
    assert degraded_rec["lkg_reference_available"] is True
    assert degraded_rec["lkg_reference_is_current_truth"] is False
    assert degraded_rec["material_admission_ready_for_downstream_review"] is False
    assert "current_exact_authority_unresolved" in degraded_rec["missing_for_material_admission"]

    degraded_previous = make_degraded(fetched_at="2026-09-06T07:28:00+00:00")
    recovered = reconcile(current, degraded_previous)
    assert recovered["reconciliation_state"] == "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING"
    assert recovered["semantic_change_count"] == 0
    assert recovered["lkg_reference_available"] is False
    assert recovered["material_admission_ready_for_downstream_review"] is True

    expect_value_error(lambda: reconcile(previous, current), "strictly older")

    tampered_previous = copy.deepcopy(previous)
    tampered_previous["eismea_authority_url"] = exact_test.EISMEA_URL + "?other=1"
    expect_value_error(lambda: reconcile(current, tampered_previous))

    tampered_receipt = copy.deepcopy(no_change)
    tampered_receipt["open_call_authorized"] = True
    expect_value_error(lambda: validate_receipt(tampered_receipt, current=current, previous=previous))

    assert current["candidate_state"] == "OPEN_CALL"
    assert current["status_label"] == "Open"
    assert current["open_call_authorized"] is False
    print("eu_direct_i3_ft_reconcile regression: PASS")


if __name__ == "__main__":
    main()
