#!/usr/bin/env python3
from __future__ import annotations

import copy
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ingest"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[0]))

from eu_direct_eic_ft_exact import collect_exact
from eu_direct_eic_ft_reconcile import reconcile, validate_receipt
from test_eu_direct_eic_ft_exact import REF, facet_payload, make_post, search_payload, topic


def evidence(fetched_at: str, deadline="2026-10-28T17:00:00Z"):
    return collect_exact(
        REF,
        run_id="synthetic",
        fetched_at=fetched_at,
        discovery_source_url="https://eic.ec.europa.eu/eic-funding-opportunities/eic-pathfinder/eic-pathfinder-challenges-2026_en",
        post_func=make_post(search=search_payload(deadline), facet=facet_payload()),
        topic_func=topic,
    )


def main():
    current = evidence("2026-09-02T17:00:00+00:00")
    baseline = reconcile(current)
    validate_receipt(baseline, current=current)
    assert baseline["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
    assert baseline["material_admission_ready_for_downstream_review"] is True
    assert baseline["open_call_authorized"] is False
    assert baseline["missing_for_material_admission"] == ["field_scoped_material_admission"]

    same = evidence("2026-09-02T18:00:00+00:00")
    no_change = reconcile(same, previous=current)
    validate_receipt(no_change, current=same, previous=current)
    assert no_change["reconciliation_state"] == "NO_CHANGE"
    assert no_change["semantic_change_count"] == 0

    changed = evidence("2026-09-02T19:00:00+00:00", deadline="2026-11-01T17:00:00Z")
    diff = reconcile(changed, previous=same)
    assert diff["reconciliation_state"] == "EIC_EXACT_TOPIC_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
    assert diff["semantic_change_count"] == 1
    assert diff["semantic_changes"][0]["field"] == "deadline_candidate"
    assert diff["deadline_authorized"] is False

    bad = copy.deepcopy(no_change)
    bad["publish_authorized"] = True
    try:
        validate_receipt(bad, current=same, previous=current)
        raise AssertionError("reconciliation self-authorization was accepted")
    except ValueError as exc:
        assert "attempted authorization" in str(exc)

    print("eu_direct_eic_ft_reconcile regression: PASS")


if __name__ == "__main__":
    main()
