#!/usr/bin/env python3
from __future__ import annotations

import copy

from eea_norway_romania_programme_watch import CIVIL_SOCIETY_CALLS_URL, ROMANIA_COOPERATION_URL, collect
from eea_norway_romania_programme_watch_reconcile import (
    MATERIAL_FLAGS,
    build_degraded_snapshot,
    prepare_healthy_snapshot,
    reconcile,
    validate_reconciliation,
    validate_snapshot,
)
from test_eea_norway_romania_programme_watch import CALLS, COOPERATION, fake_fetch


def fail(fn, needle: str) -> None:
    try:
        fn()
    except ValueError as exc:
        assert needle.casefold() in str(exc).casefold(), (needle, str(exc))
    else:
        raise AssertionError(f"expected ValueError containing {needle!r}")


def healthy(*, fetched_at: str, run_id: str, calls_body: bytes = CALLS, cooperation_body: bytes = COOPERATION):
    def fetch(url: str):
        raw, meta = fake_fetch(url)
        if url == CIVIL_SOCIETY_CALLS_URL:
            raw = calls_body
        elif url == ROMANIA_COOPERATION_URL:
            raw = cooperation_body
        return raw, meta
    receipt, _ = collect(run_id=run_id, fetched_at=fetched_at, fetcher=fetch)
    return prepare_healthy_snapshot(receipt)


def main() -> int:
    previous = healthy(fetched_at="2026-09-07T00:00:00+00:00", run_id="eea-watch-prev")
    current = healthy(fetched_at="2026-09-07T00:10:00+00:00", run_id="eea-watch-current")
    validate_snapshot(current)

    baseline = reconcile(previous)
    assert baseline["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
    assert baseline["semantic_change_count"] == 0

    no_change = reconcile(current, previous)
    assert no_change["reconciliation_state"] == "NO_CHANGE"
    assert no_change["semantic_change_count"] == 0
    assert no_change["programming_watch_candidate"] is False
    assert no_change["call_index_discovery_watch_candidate"] is False
    assert no_change["lkg_reference_is_current_truth"] is False
    assert all(no_change[k] is False for k in MATERIAL_FLAGS)
    validate_reconciliation(no_change, current=current)

    # Raw/source hash drift without semantic programme/discovery change must not alert.
    noisy = healthy(
        fetched_at="2026-09-07T00:20:00+00:00",
        run_id="eea-watch-noise",
        cooperation_body=COOPERATION.replace(b"</body>", b"<p>Page rendering marker only.</p></body>"),
    )
    assert noisy["semantic_fingerprint"] != current["semantic_fingerprint"]
    noise_rec = reconcile(noisy, current)
    assert noise_rec["reconciliation_state"] == "NO_CHANGE"
    assert noise_rec["semantic_change_count"] == 0

    # New numbered official call link is a discovery watch only, never an OPEN fact.
    calls_plus = CALLS.replace(
        b"</body>",
        b'<a href="/en/eea-civil-society-fund-romania/calls/call-3-human-rights">Call #3 Human Rights</a></body>',
    )
    changed = healthy(
        fetched_at="2026-09-07T00:30:00+00:00",
        run_id="eea-watch-changed",
        calls_body=calls_plus,
    )
    changed_rec = reconcile(changed, noisy)
    assert changed_rec["reconciliation_state"] == "EEA_NORWAY_ROMANIA_DISCOVERY_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
    assert changed_rec["call_index_discovery_watch_candidate"] is True
    assert changed_rec["semantic_change_count"] == 1
    assert changed_rec["semantic_changes"][0]["kind"] == "CALL_DISCOVERY_SET_CHANGED"
    assert changed_rec["open_call_authorized"] is False
    assert changed_rec["deadline_authorized"] is False
    assert changed_rec["budget_authorized"] is False
    assert changed_rec["eligibility_authorized"] is False

    degraded = build_degraded_snapshot(
        run_id="eea-watch-degraded",
        fetched_at="2026-09-07T00:40:00+00:00",
        failure_class="HTTP_503",
        failure_detail="synthetic transport failure",
    )
    validate_snapshot(degraded)
    degraded_rec = reconcile(degraded, changed)
    assert degraded_rec["reconciliation_state"] == "CURRENT_EEA_NORWAY_ROMANIA_WATCH_DEGRADED_LKG_REQUIRED"
    assert degraded_rec["semantic_reconciliation_passed"] is False
    assert degraded_rec["lkg_reference_required"] is True
    assert degraded_rec["lkg_reference_available"] is True
    assert degraded_rec["source_health_watch_candidate"] is True
    assert degraded_rec["call_index_discovery_watch_candidate"] is False

    recovered = healthy(fetched_at="2026-09-07T00:50:00+00:00", run_id="eea-watch-recovered")
    recovery_rec = reconcile(recovered, degraded)
    assert recovery_rec["reconciliation_state"] == "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING"
    assert recovery_rec["source_health_watch_candidate"] is True
    assert recovery_rec["call_index_discovery_watch_candidate"] is False

    newer_previous = healthy(fetched_at="2026-09-07T01:00:00+00:00", run_id="eea-watch-newer")
    fail(lambda: reconcile(recovered, newer_previous), "not strictly older")

    drift = copy.deepcopy(previous)
    drift["authority_urls"][0] = "https://example.invalid/not-authority"
    fail(lambda: validate_snapshot(drift), "authority identity drift")

    widening = copy.deepcopy(current)
    widening["open_call_authorized"] = True
    fail(lambda: validate_snapshot(widening), "material authorization")

    discovery_widening = copy.deepcopy(current)
    discovery_widening["call_discovery"][0]["open_call_authorized"] = True
    fail(lambda: validate_snapshot(discovery_widening), "attempted authorization")

    lexical_calls = CALLS.replace(
        b"Call #1 Strengthening Democracy",
        b"Call #1 OPEN deadline budget eligible Strengthening Democracy",
    )
    lexical = healthy(
        fetched_at="2026-09-07T01:10:00+00:00",
        run_id="eea-watch-lexical",
        calls_body=lexical_calls,
    )
    lexical_rec = reconcile(lexical, recovered)
    assert lexical_rec["open_call_authorized"] is False
    assert lexical_rec["deadline_authorized"] is False
    assert lexical_rec["budget_authorized"] is False
    assert lexical_rec["eligibility_authorized"] is False

    print("EEA/Norway Romania programme + call-discovery reconciliation regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
