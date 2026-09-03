#!/usr/bin/env python3
from __future__ import annotations

import copy

from eea_civil_society_fund_call5_exact import EXACT_URL, INDEX_URL, collect_exact, sha256_json
from eea_civil_society_fund_call5_reconcile import reconcile

INDEX_HTML = f"""
<html><body>
<h1>Calls</h1>
<article>
<h2>Apel #5 Incluziunea și creșterea capacității romilor prin dezvoltarea comunităților interetnice</h2>
<p>Apeluri de proiecte</p><p>Deschis</p>
<a href="{EXACT_URL}">Detalii apel #5</a>
</article>
</body></html>
""".encode("utf-8")

DETAIL_HTML = """
<html><body>
<h1>Apel #5 Incluziunea si cresterea capacitatii romilor prin dezvoltarea comunitatilor interetnice</h1>
<p>EEA Civil Society Fund in Romania</p>
<p>Apeluri de proiecte</p><p>Deschis</p>
<section><h2>Call details</h2>
<p>Numarul Apelului de proiecte</p><p>5</p>
<p>Data publicarii</p><p>08/07/2026</p>
<p>Data limita pentru adresarea de intrebari</p><p>29/09/2026</p>
<p>Data limita de depunere a Cererilor de finantare</p><p>08/10/2026</p>
<p>Suma disponibila</p><p>€6,500,000</p>
<p>Valoarea minima a grantului</p><p>€15,000</p>
<p>Valoarea maxima a grantului</p><p>€350,000</p>
</section>
</body></html>
""".encode("utf-8")


def fake_fetch(url: str, *, timeout: float):
    del timeout
    if url == INDEX_URL:
        return INDEX_HTML, 200, url, "text/html; charset=UTF-8"
    if url == EXACT_URL:
        return DETAIL_HTML, 200, url, "text/html; charset=UTF-8"
    raise AssertionError(url)


def make(at: str):
    return collect_exact(run_id="reconcile-test", fetched_at=at, fetcher=fake_fetch)


def main() -> int:
    previous = make("2026-09-03T03:40:00+00:00")
    current = make("2026-09-03T03:41:00+00:00")

    baseline = reconcile(previous)
    assert baseline["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
    assert baseline["material_admission_ready_for_downstream_review"] is False
    assert "previous_same_identity_exact_receipt_or_reviewed_baseline_exception" in baseline["missing_for_material_admission"]
    assert baseline["open_call_authorized"] is False

    same = reconcile(current, previous)
    assert same["reconciliation_state"] == "NO_CHANGE"
    assert same["semantic_change_count"] == 0
    assert same["material_admission_ready_for_downstream_review"] is True
    assert same["open_call_authorized"] is False
    assert "field_scoped_material_admission" in same["missing_for_material_admission"]

    changed = copy.deepcopy(current)
    changed["fetched_at"] = "2026-09-03T03:42:00+00:00"
    changed["exact_semantics"] = dict(changed["exact_semantics"])
    changed["exact_semantics"]["budget_candidate"] = "EUR 6,600,000"
    changed["budget_candidate"] = "EUR 6,600,000"
    changed["exact_semantic_fingerprint"] = sha256_json(changed["exact_semantics"])
    diff = reconcile(changed, current)
    assert diff["reconciliation_state"] == "EEA_CSF_CALL5_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
    assert diff["semantic_change_count"] == 1
    assert diff["budget_authorized"] is False
    assert diff["publication_effect"] == "NONE"

    try:
        reconcile(previous, current)
    except ValueError as exc:
        assert "newer than current" in str(exc)
    else:
        raise AssertionError("EEA CSF reconciliation accepted inverted history")

    wrong_identity = copy.deepcopy(previous)
    wrong_identity["identity_key"] = "0" * 64
    try:
        reconcile(current, wrong_identity)
    except Exception:
        pass
    else:
        raise AssertionError("EEA CSF reconciliation accepted identity drift")

    print({
        "status": "PASS",
        "reconciler": "EEA_CSF_RO_CALL5",
        "same_identity": "NO_CHANGE",
        "baseline_review_ready": False,
        "same_identity_review_ready": True,
        "material_authorization": False,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
