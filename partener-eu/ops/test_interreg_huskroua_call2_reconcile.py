#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INGEST = ROOT / "partener-eu" / "ingest"
sys.path.insert(0, str(INGEST))

import interreg_huskroua_call2_exact as exact  # noqa: E402
import interreg_huskroua_call2_reconcile as rec  # noqa: E402


EXACT_HTML = b"""<html><body>
<h1>2nd Call for Proposals</h1>
<p>Second call for proposals</p>
<p>2nd Call for Proposals</p>
</body></html>"""

CLOSURE_HTML = b"""<html><body>
<h1>Closure of the 2nd Call for Proposals</h1>
<p>2nd Call for Proposals</p>
<p>The 2nd Call for Proposals has been officially closed.</p>
</body></html>"""


def registry() -> dict:
    return {
        "schema": exact.REGISTRY_SCHEMA,
        "source_family": "INTERREG",
        "programme_family": "INTERREG_HUSKROUA_2021_2027",
        "programme_id": "HUSKROUA",
        "programme": "Interreg VI-A NEXT Hungary-Slovakia-Romania-Ukraine Programme",
        "authority_class": "T1_OFFICIAL_PROGRAMME_EXACT_CALL",
        "official_call_identifier": "2",
        "official_call_identifier_kind": "OFFICIAL_CALL_NUMBER",
        "exact_call_url": "https://next.huskroua-cbc.eu/calls/2nd-call-for-proposals",
        "closure_url": "https://next.huskroua-cbc.eu/news/closure-of-the-2nd-call-for-proposals",
        "required_exact_markers": ["2nd Call for Proposals"],
        "required_closure_markers": ["Closure of the 2nd Call for Proposals", "2nd Call for Proposals"],
        "policy": {
            "semantic_reconciliation_required": True,
            "field_scoped_material_admission_required": True,
            "previous_or_lkg_is_current_truth": False,
            **{flag: False for flag in exact.MATERIAL_FLAGS},
        },
    }


def fetcher(url: str):
    raw = EXACT_HTML if "/calls/" in url else CLOSURE_HTML
    return raw, {
        "requested_url": url,
        "final_url": url,
        "http_status": 200,
        "content_type": "text/html; charset=utf-8",
    }


def assert_non_authorizing(obj: dict) -> None:
    for flag in exact.MATERIAL_FLAGS:
        assert obj[flag] is False, (flag, obj[flag])
    assert obj["publication_effect"] == "NONE"


def main() -> None:
    current, _ = exact.collect(
        registry=registry(),
        run_id="current",
        fetched_at="2026-09-04T04:30:00+00:00",
        fetcher=fetcher,
    )
    baseline = rec.reconcile(current)
    assert baseline["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
    assert baseline["semantic_change_count"] == 0
    assert baseline["material_admission_ready_for_downstream_review"] is False
    assert baseline["lkg_reference_available"] is False
    assert_non_authorizing(baseline)

    previous = copy.deepcopy(current)
    previous["run_id"] = "previous"
    previous["fetched_at"] = "2026-09-04T04:00:00+00:00"
    same = rec.reconcile(current, previous)
    assert same["reconciliation_state"] == "NO_CHANGE"
    assert same["semantic_change_count"] == 0
    assert same["semantic_reconciliation_passed"] is True
    assert same["material_admission_ready_for_downstream_review"] is True
    assert same["lkg_reference_available"] is True
    assert same["previous_or_lkg_is_current_truth"] is False
    assert_non_authorizing(same)

    changed = copy.deepcopy(current)
    exact_row = next(row for row in changed["sources"] if row["kind"] == "exact_call")
    exact_row["normalized_visible_text_sha256"] = "1" * 64
    changed["exact_semantics"]["source_visible_text_sha256"]["exact_call"] = "1" * 64
    changed["exact_semantic_fingerprint"] = exact.sha256_json(changed["exact_semantics"])
    exact.validate_evidence(changed)
    semantic_change = rec.reconcile(changed, previous)
    assert semantic_change["reconciliation_state"] == "HUSKROUA_CALL2_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
    assert semantic_change["semantic_change_count"] == 1
    assert semantic_change["semantic_changes"][0]["field"] == "source_visible_text_sha256"
    assert semantic_change["material_admission_ready_for_downstream_review"] is True
    assert_non_authorizing(semantic_change)

    def degraded_fetcher(url: str):
        if "/calls/" in url:
            raise OSError("synthetic transport failure")
        return fetcher(url)

    degraded, _ = exact.collect(
        registry=registry(),
        run_id="degraded",
        fetched_at="2026-09-04T04:45:00+00:00",
        fetcher=degraded_fetcher,
    )
    degraded_rec = rec.reconcile(degraded, previous)
    assert degraded_rec["reconciliation_state"] == "CURRENT_SOURCE_HEALTH_DEGRADED_LKG_REQUIRED"
    assert degraded_rec["semantic_reconciliation_passed"] is False
    assert degraded_rec["lkg_reference_required"] is True
    assert degraded_rec["lkg_reference_available"] is True
    assert degraded_rec["material_admission_ready_for_downstream_review"] is False
    assert degraded_rec["previous_or_lkg_is_current_truth"] is False
    assert_non_authorizing(degraded_rec)

    previous_degraded = copy.deepcopy(degraded)
    previous_degraded["run_id"] = "previous-degraded"
    previous_degraded["fetched_at"] = "2026-09-04T03:45:00+00:00"
    recovered = rec.reconcile(current, previous_degraded)
    assert recovered["reconciliation_state"] == "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING"
    assert recovered["source_health_watch_candidate"] is True
    assert recovered["material_admission_ready_for_downstream_review"] is False
    assert_non_authorizing(recovered)

    future_previous = copy.deepcopy(previous)
    future_previous["fetched_at"] = "2026-09-04T05:00:00+00:00"
    try:
        rec.reconcile(current, future_previous)
    except ValueError:
        pass
    else:
        raise AssertionError("newer previous HUSKROUA evidence must fail closed")

    identity_drift = copy.deepcopy(previous)
    identity_drift["official_call_identifier"] = "3"
    try:
        rec.reconcile(current, identity_drift)
    except ValueError:
        pass
    else:
        raise AssertionError("HUSKROUA previous identity drift must fail closed")

    widened = dict(same)
    widened["closed_call_authorized"] = True
    try:
        rec.validate_reconciliation(widened, current=current, previous=previous)
    except ValueError:
        pass
    else:
        raise AssertionError("HUSKROUA reconciliation authorization widening must fail closed")

    print("PASS HUSKROUA Call 2 reconciliation: baseline, same-identity NO_CHANGE, semantic drift, degraded/LKG and history ordering fail closed")


if __name__ == "__main__":
    main()
