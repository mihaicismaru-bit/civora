#!/usr/bin/env python3
# Semantic-neutral replay marker: verify same-identity history restoration from the canonical Call 7 lane.
from __future__ import annotations

import copy
from urllib.error import URLError

from eea_civil_society_fund_call7_exact import EXACT_URL, INDEX_URL, collect_exact, sha256_json
from eea_civil_society_fund_call7_reconcile import reconcile

INDEX_HTML = f"""
<html><body><h1>Calls</h1>
<h2>Apel #7 Dezvoltare organizațională pentru OSC-uri cu experiență și federații</h2>
<a href="{EXACT_URL}">Detalii apel #7</a>
</body></html>
""".encode("utf-8")

DETAIL_HTML = """
<html><body>
<h1>Apel #7 Dezvoltare organizationala pentru OSC-uri cu experienta si federatii</h1>
<p>EEA Civil Society Fund in Romania</p>
<p>Apeluri de proiecte</p><p>Deschis</p>
<p>Numarul Apelului de proiecte</p><p>7</p>
<p>Data publicarii</p><p>08/07/2026</p>
<p>Data limita pentru adresarea de intrebari</p><p>29/09/2026</p>
<p>Data limita de depunere a Cererilor de finantare</p><p>08/10/2026</p>
<p>Suma disponibila</p><p>€3,000,000</p>
<p>Valoarea minima a grantului</p><p>€200,001</p>
<p>Valoarea maxima a grantului</p><p>€350,000</p>
</body></html>
""".encode("utf-8")


def healthy_fetch(url: str, *, timeout: float):
    del timeout
    if url == INDEX_URL:
        return INDEX_HTML, 200, url, "text/html; charset=UTF-8"
    if url == EXACT_URL:
        return DETAIL_HTML, 200, url, "text/html; charset=UTF-8"
    raise AssertionError(url)


def degraded_fetch(url: str, *, timeout: float):
    if url == EXACT_URL:
        raise URLError("synthetic exact authority outage")
    return healthy_fetch(url, timeout=timeout)


def exact(at: str, *, fetcher=healthy_fetch):
    return collect_exact(run_id=f"synthetic-{at}", fetched_at=at, fetcher=fetcher)


def main() -> int:
    previous = exact("2026-09-07T03:00:00+00:00")
    current = exact("2026-09-07T03:05:00+00:00")

    baseline = reconcile(previous)
    assert baseline["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
    assert baseline["semantic_reconciliation_passed"] is True
    assert baseline["material_admission_ready_for_downstream_review"] is False
    assert baseline["lkg_reference_required"] is False

    same = reconcile(current, previous)
    assert same["reconciliation_state"] == "NO_CHANGE"
    assert same["semantic_change_count"] == 0
    assert same["semantic_reconciliation_passed"] is True
    assert same["material_admission_ready_for_downstream_review"] is True
    assert same["lkg_reference_required"] is False
    assert same["lkg_reference_is_current_truth"] is False

    changed = copy.deepcopy(current)
    changed["fetched_at"] = "2026-09-07T03:06:00+00:00"
    changed["exact_semantics"]["budget_candidate"] = "EUR 3,100,000"
    changed["budget_candidate"] = "EUR 3,100,000"
    changed["exact_semantic_fingerprint"] = sha256_json(changed["exact_semantics"])
    changed_rec = reconcile(changed, previous)
    assert changed_rec["reconciliation_state"] == "EEA_CSF_CALL7_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
    assert changed_rec["semantic_change_count"] == 1
    assert changed_rec["semantic_changes"][0]["field"] == "budget_candidate"
    assert changed_rec["open_call_authorized"] is False
    assert changed_rec["budget_authorized"] is False

    degraded = exact("2026-09-07T03:07:00+00:00", fetcher=degraded_fetch)
    degraded_rec = reconcile(degraded, previous)
    assert degraded_rec["reconciliation_state"] == "CURRENT_EXACT_AUTHORITY_UNRESOLVED_LKG_REQUIRED"
    assert degraded_rec["semantic_reconciliation_passed"] is False
    assert degraded_rec["semantic_change_count"] == 0
    assert degraded_rec["semantic_changes"] == []
    assert degraded_rec["lkg_reference_required"] is True
    assert degraded_rec["lkg_reference_available"] is True
    assert degraded_rec["lkg_reference_is_current_truth"] is False
    assert degraded_rec["material_admission_ready_for_downstream_review"] is False

    recovered = exact("2026-09-07T03:08:00+00:00")
    degraded_previous = exact("2026-09-07T03:07:30+00:00", fetcher=degraded_fetch)
    recovered_rec = reconcile(recovered, degraded_previous)
    assert recovered_rec["reconciliation_state"] == "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING"
    assert recovered_rec["semantic_reconciliation_passed"] is True
    assert recovered_rec["material_admission_ready_for_downstream_review"] is False

    equal_time = copy.deepcopy(previous)
    equal_time["fetched_at"] = current["fetched_at"]
    try:
        reconcile(current, equal_time)
    except ValueError as exc:
        assert "strictly older" in str(exc)
    else:
        raise AssertionError("EEA CSF Call 7 reconciliation accepted equal-time previous evidence")

    identity_drift = copy.deepcopy(previous)
    identity_drift["identity_key"] = "0" * 64
    try:
        reconcile(current, identity_drift)
    except ValueError:
        pass
    else:
        raise AssertionError("EEA CSF Call 7 reconciliation accepted identity drift")

    widened = copy.deepcopy(current)
    widened["open_call_authorized"] = True
    try:
        reconcile(widened, previous)
    except ValueError:
        pass
    else:
        raise AssertionError("EEA CSF Call 7 reconciliation accepted authorization widening")

    print({
        "status": "PASS",
        "reconciler": "EEA_CSF_RO_CALL7_RECONCILIATION",
        "same_identity": same["reconciliation_state"],
        "semantic_change_guarded": True,
        "degraded_uses_lkg_reference_only": True,
        "strictly_older_previous_required": True,
        "material_authorization": False,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
