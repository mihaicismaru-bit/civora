#!/usr/bin/env python3
from __future__ import annotations

import copy
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ingest"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[0]))

from eu_direct_innovation_fund_ft_exact import collect_exact
from eu_direct_innovation_fund_ft_reconcile import reconcile, validate_receipt
from test_eu_direct_innovation_fund_ft_exact import CALL, DISCOVERY, REF, facet_payload, make_post, search_payload, topic


def evidence(fetched_at: str, deadline="2026-04-23T17:00:00Z"):
    return collect_exact(
        REF,
        run_id="synthetic",
        fetched_at=fetched_at,
        expected_call_identifier=CALL,
        discovery_source_url=DISCOVERY,
        post_func=make_post(search=search_payload(deadline), facet=facet_payload()),
        topic_func=topic,
    )


def main():
    current = evidence("2026-09-02T22:00:00+00:00")
    baseline = reconcile(current)
    validate_receipt(baseline, current=current)
    assert baseline["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
    assert baseline["material_admission_ready_for_downstream_review"] is True
    assert baseline["candidate_state"] == "CLOSED_CALL"
    assert baseline["status_label"] == "Closed"
    assert baseline["open_call_authorized"] is False
    assert baseline["closed_call_authorized"] is False
    assert baseline["missing_for_material_admission"] == ["field_scoped_material_admission"]

    same = evidence("2026-09-02T23:00:00+00:00")
    no_change = reconcile(same, previous=current)
    validate_receipt(no_change, current=same, previous=current)
    assert no_change["reconciliation_state"] == "NO_CHANGE"
    assert no_change["semantic_change_count"] == 0

    changed = evidence("2026-09-03T00:00:00+00:00", deadline="2026-04-24T17:00:00Z")
    diff = reconcile(changed, previous=same)
    assert diff["reconciliation_state"] == "INNOVATION_FUND_EXACT_TOPIC_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
    assert diff["semantic_change_count"] == 1
    assert diff["semantic_changes"][0]["field"] == "deadline_candidate"
    assert diff["deadline_authorized"] is False
    assert diff["closed_call_authorized"] is False

    bad = copy.deepcopy(no_change)
    bad["publish_authorized"] = True
    try:
        validate_receipt(bad, current=same, previous=current)
        raise AssertionError("reconciliation self-authorization was accepted")
    except ValueError as exc:
        assert "attempted authorization" in str(exc)

    print("eu_direct_innovation_fund_ft_reconcile regression: PASS")


if __name__ == "__main__":
    main()
