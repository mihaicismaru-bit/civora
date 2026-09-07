#!/usr/bin/env python3
import copy

import interreg_ro_rs_calls_planning as src
import interreg_ro_rs_calls_planning_reconcile as rec


def healthy(fetched_at: str, fingerprint: str = "a" * 64):
    data = {
        "schema": src.SCHEMA,
        "parser_version": src.PARSER_VERSION,
        "source_family": src.SOURCE_FAMILY,
        "programme_family": src.PROGRAMME_FAMILY,
        "programme": "Interreg IPA Romania-Serbia Programme 2021-2027",
        "authority_class": src.AUTHORITY_CLASS,
        "authority_url": src.INDEX_URL,
        "run_id": "fixture",
        "fetched_at": fetched_at,
        "observation_state": "PLANNED",
        "market_intelligence_only": True,
        "planning_evidence_non_authorizing": True,
        "material_admission_ready_for_downstream_review": False,
        "publication_effect": "NONE",
        "source_health_state": "HEALTHY",
        "lkg_required": False,
        "semantic_fingerprint": fingerprint,
        "latest_calendar": {"calendar_date": "2026-06-09", "calendar_url": "https://romania-serbia.net/x.xlsx"},
    }
    data.update({flag: False for flag in src.MATERIAL_FLAGS})
    return data


def degraded(fetched_at: str):
    data = healthy(fetched_at)
    data.update({
        "source_health_state": "DEGRADED",
        "lkg_required": True,
        "semantic_fingerprint": None,
        "latest_calendar": None,
    })
    return data


def must_fail(fn, needle: str):
    try:
        fn()
    except ValueError as exc:
        assert needle in str(exc), (needle, str(exc))
    else:
        raise AssertionError(f"expected ValueError containing {needle!r}")


def main():
    previous = healthy("2026-09-08T00:00:00+00:00")
    current = healthy("2026-09-08T01:00:00+00:00")

    same = rec.reconcile(current, previous)
    rec.validate_reconciliation(same)
    assert same["reconciliation_state"] == "NO_CHANGE"
    assert same["semantic_change_count"] == 0
    assert same["history_state"] == "CURRENT_HEALTHY"
    assert same["lkg_is_current_truth"] is False

    changed = healthy("2026-09-08T01:00:00+00:00", "b" * 64)
    diff = rec.reconcile(changed, previous)
    rec.validate_reconciliation(diff)
    assert diff["reconciliation_state"] == "SEMANTIC_CHANGE_REVIEW_REQUIRED"
    assert diff["semantic_change_fields"] == ["planned_calls_calendar"]
    assert diff["semantic_change_count"] == 1

    down = rec.reconcile(degraded("2026-09-08T01:00:00+00:00"), previous)
    rec.validate_reconciliation(down)
    assert down["reconciliation_state"] == "CURRENT_DEGRADED_LKG_REQUIRED_NON_AUTHORIZING"
    assert down["lkg_reference_available"] is True
    assert down["lkg_is_current_truth"] is False

    baseline = rec.reconcile(current, None)
    rec.validate_reconciliation(baseline)
    assert baseline["reconciliation_state"] == "BASELINE_HEALTHY"

    must_fail(lambda: rec.reconcile(current, healthy("2026-09-08T01:00:00+00:00")), "strictly older")

    widened = copy.deepcopy(previous)
    widened["open_call_authorized"] = True
    must_fail(lambda: rec.reconcile(current, widened), "widened material authorization")

    drift = copy.deepcopy(previous)
    drift["authority_url"] = "https://example.com/not-authority"
    must_fail(lambda: rec.reconcile(current, drift), "authority identity mismatch")

    naive = copy.deepcopy(previous)
    naive["fetched_at"] = "2026-09-08T00:00:00"
    must_fail(lambda: rec.reconcile(current, naive), "timezone-aware")

    for receipt in (same, diff, down, baseline):
        assert receipt["publication_effect"] == "NONE"
        assert receipt["material_admission_ready_for_downstream_review"] is False
        for flag in src.MATERIAL_FLAGS:
            assert receipt[flag] is False, (receipt["reconciliation_state"], flag)

    print("PASS RO-RS planned-calls reconciliation: same-identity history, semantic drift review, LKG reference-only, no authorization widening")


if __name__ == "__main__":
    main()
