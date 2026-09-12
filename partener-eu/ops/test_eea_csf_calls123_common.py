#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib
from urllib.error import URLError

from eea_civil_society_fund_exact_common import INDEX_URL, SPECS, sha256_json


def index_html() -> bytes:
    rows = []
    for spec in SPECS.values():
        rows.append(f'<h2>{spec.title_ro}</h2><a href="{spec.exact_url}">Detalii</a>')
    return ("<html><body>" + "".join(rows) + "</body></html>").encode("utf-8")


def detail_html(call_id: str) -> bytes:
    spec = SPECS[call_id]
    budget = spec.budget.removeprefix("EUR ")
    grant_min = spec.grant_min.removeprefix("EUR ")
    grant_max = spec.grant_max.removeprefix("EUR ")
    return f"""
    <html><body>
    <h1>{spec.title_ro}</h1>
    <p>EEA Civil Society Fund in Romania</p>
    <p>Apeluri de proiecte</p><p>Deschis</p>
    <p>Numarul Apelului de proiecte</p><p>{call_id}</p>
    <p>Data publicarii</p><p>08/07/2026</p>
    <p>Data limita pentru adresarea de intrebari</p><p>29/09/2026</p>
    <p>Data limita de depunere a Cererilor de finantare</p><p>08/10/2026</p>
    <p>Suma disponibila</p><p>€{budget}</p>
    <p>Valoarea minima a grantului</p><p>€{grant_min}</p>
    <p>Valoarea maxima a grantului</p><p>€{grant_max}</p>
    </body></html>
    """.encode("utf-8")


def modules(call_id: str):
    exact = importlib.import_module(f"eea_civil_society_fund_call{call_id}_exact")
    reconcile = importlib.import_module(f"eea_civil_society_fund_call{call_id}_reconcile")
    return exact, reconcile


def healthy_fetch(call_id: str):
    spec = SPECS[call_id]
    def fetch(url: str, *, timeout: float):
        del timeout
        if url == INDEX_URL:
            return index_html(), 200, url, "text/html; charset=UTF-8"
        if url == spec.exact_url:
            return detail_html(call_id), 200, url, "text/html; charset=UTF-8"
        raise AssertionError(url)
    return fetch


def degraded_fetch(call_id: str):
    spec = SPECS[call_id]
    base = healthy_fetch(call_id)
    def fetch(url: str, *, timeout: float):
        if url == spec.exact_url:
            raise URLError("synthetic exact authority outage")
        return base(url, timeout=timeout)
    return fetch


def exercise(call_id: str) -> None:
    spec = SPECS[call_id]
    exact, recmod = modules(call_id)
    previous = exact.collect_exact(run_id="test-prev", fetched_at="2026-09-07T08:00:00+00:00", fetcher=healthy_fetch(call_id))
    current = exact.collect_exact(run_id="test-current", fetched_at="2026-09-07T08:05:00+00:00", fetcher=healthy_fetch(call_id))

    exact.validate_evidence(previous)
    exact.validate_evidence(current)
    assert current["source_health_state"] == "HEALTHY"
    assert current["official_call_identifier"] == call_id
    assert current["candidate_state"] == "OPEN_CALL"
    assert current["status_label"] == "Open"
    assert current["deadline_candidate"] == "2026-10-08"
    assert current["budget_candidate"] == spec.budget
    assert current["grant_min_candidate"] == spec.grant_min
    assert current["grant_max_candidate"] == spec.grant_max
    assert current["open_call_authorized"] is False

    baseline = recmod.reconcile(previous)
    assert baseline["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
    assert baseline["material_admission_ready_for_downstream_review"] is False

    same = recmod.reconcile(current, previous)
    assert same["reconciliation_state"] == "NO_CHANGE"
    assert same["semantic_change_count"] == 0
    assert same["material_admission_ready_for_downstream_review"] is True
    assert same["open_call_authorized"] is False

    changed = copy.deepcopy(current)
    changed["fetched_at"] = "2026-09-07T08:06:00+00:00"
    changed["exact_semantics"] = dict(changed["exact_semantics"])
    changed["exact_semantics"]["budget_candidate"] = "EUR 1"
    changed["budget_candidate"] = "EUR 1"
    changed["exact_semantic_fingerprint"] = sha256_json(changed["exact_semantics"])
    diff = recmod.reconcile(changed, current)
    assert diff["semantic_change_count"] == 1
    assert diff["budget_authorized"] is False
    assert diff["publication_effect"] == "NONE"

    degraded = exact.collect_exact(run_id="test-degraded", fetched_at="2026-09-07T08:07:00+00:00", fetcher=degraded_fetch(call_id))
    assert degraded["source_health_state"] == "DEGRADED"
    assert degraded["candidate_state"] == "UNKNOWN"
    assert degraded["lkg_required"] is True
    degraded_rec = recmod.reconcile(degraded, previous)
    assert degraded_rec["reconciliation_state"] == "CURRENT_EXACT_AUTHORITY_UNRESOLVED_LKG_REQUIRED"
    assert degraded_rec["semantic_reconciliation_passed"] is False
    assert degraded_rec["semantic_change_count"] == 0
    assert degraded_rec["lkg_reference_available"] is True
    assert degraded_rec["lkg_reference_is_current_truth"] is False

    equal = copy.deepcopy(previous)
    equal["fetched_at"] = current["fetched_at"]
    try:
        recmod.reconcile(current, equal)
    except ValueError as exc:
        assert "strictly older" in str(exc)
    else:
        raise AssertionError(f"Call {call_id} accepted equal-time previous")

    widened = copy.deepcopy(current)
    widened["open_call_authorized"] = True
    try:
        recmod.reconcile(widened, previous)
    except Exception:
        pass
    else:
        raise AssertionError(f"Call {call_id} accepted authorization widening")

    wrong_url = copy.deepcopy(current)
    wrong_url["authority_url"] = "https://example.org/call"
    try:
        exact.validate_evidence(wrong_url)
    except Exception:
        pass
    else:
        raise AssertionError(f"Call {call_id} accepted authority widening")


def main() -> int:
    for call_id in ("1", "2", "3"):
        exercise(call_id)
    print({
        "status": "PASS",
        "calls": ["1", "2", "3"],
        "same_identity": "NO_CHANGE",
        "degraded_uses_lkg_reference_only": True,
        "strictly_older_previous_required": True,
        "material_authorization": False,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
