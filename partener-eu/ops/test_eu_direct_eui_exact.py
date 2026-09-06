#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
INGEST = ROOT / "partener-eu" / "ingest"
sys.path.insert(0, str(INGEST))
SPEC = importlib.util.spec_from_file_location("eu_direct_eui_exact", INGEST / "eu_direct_eui_exact.py")
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

REGISTRY = mod.load_registry(INGEST / "eu_direct_eui_exact_registry.json")
CALL_ID = "EUI-IA-CALL-4-2026"
URL = "https://www.urban-initiative.eu/calls-proposals/fourth-call-proposals-innovative-actions"

HEALTHY_HTML = b"""<!doctype html><html><body>
<h1>Fourth Call for Proposals EUI - Innovative Actions</h1>
<div>Closed</div><p>The Call for Proposals is closed.</p>
<p>The fourth EUI-Innovative Actions (EUI-IA) Call for Proposals was launched on 25 February 2026 and closed on 15 June 2026 at 14.00 CEST with an allocated indicative budget of EUR 60 million ERDF.</p>
<h2>Fourth EUI-IA Call for Proposals</h2>
<p>For the fourth EUI - Innovative Actions (EUI-IA) Call for Proposals, a provisional budget of EUR 60 million ERDF is allocated.</p>
<p>Each project can receive up to a maximum of EUR 2 million ERDF co-financing.</p>
<p>Applications are open to cities above 25 000 inhabitants.</p>
<h3>Terms of Reference</h3>
<p>EUI-IA Guidance for Call 4</p>
<p>EUI-IA Call 4 Terms of Reference (in all EU languages)</p>
<p>The submission is through EUI.Connect.</p>
</body></html>"""


def fake_healthy(url: str, *, timeout: float):
    assert url == URL and timeout == 30.0
    return HEALTHY_HTML, 200, URL, "text/html; charset=UTF-8"


def test_healthy_exact_non_authorizing() -> None:
    evidence = mod.collect_exact(
        REGISTRY,
        call_id=CALL_ID,
        run_id="test-healthy",
        fetched_at="2026-09-06T20:00:00+00:00",
        fetcher=fake_healthy,
    )
    assert evidence["source_health_state"] == "HEALTHY"
    assert evidence["candidate_state"] == "CLOSED_CALL"
    assert evidence["status_label"] == "Closed"
    assert evidence["deadline_candidate"].casefold().startswith("15 june 2026")
    assert "60 million ERDF" in evidence["budget_candidate"]
    assert "2 million ERDF" in evidence["max_erdf_contribution_candidate"]
    assert "25 000 inhabitants" in evidence["urban_authority_population_threshold_candidate"]
    assert evidence["evidence_usable_for_reconciliation"] is True
    assert evidence["current_material_truth_available"] is False
    assert evidence["material_admission_ready_for_downstream_review"] is False
    for key in mod.MATERIAL_FLAGS:
        assert evidence[key] is False
    mod.validate_evidence(evidence, REGISTRY)


def test_lexical_open_does_not_override_explicit_closed() -> None:
    raw = HEALTHY_HTML.replace(b"</body>", b"<p>Open data and open innovation support cities.</p></body>")
    def fetcher(url: str, *, timeout: float):
        return raw, 200, URL, "text/html"
    evidence = mod.collect_exact(REGISTRY, call_id=CALL_ID, run_id="test-open-word", fetcher=fetcher)
    assert evidence["candidate_state"] == "CLOSED_CALL"
    assert evidence["open_call_authorized"] is False
    assert evidence["closed_call_authorized"] is False


def test_marker_drift_degrades_and_suppresses_candidates() -> None:
    raw = b"<html><body><h1>European Urban Initiative</h1><p>Terms of Reference</p></body></html>"
    def fetcher(url: str, *, timeout: float):
        return raw, 200, URL, "text/html"
    evidence = mod.collect_exact(REGISTRY, call_id=CALL_ID, run_id="test-marker", fetcher=fetcher)
    assert evidence["source_health_state"] == "DEGRADED_MARKER_MISMATCH"
    assert evidence["lkg_required"] is True
    assert evidence["evidence_usable_for_reconciliation"] is False
    assert evidence["candidate_state"] == "UNKNOWN"
    assert evidence["status_label"] is None
    assert evidence["deadline_candidate"] is None
    assert evidence["budget_candidate"] is None
    assert evidence["exact_semantic_fingerprint"] is None


def test_redirect_off_authority_degrades() -> None:
    def fetcher(url: str, *, timeout: float):
        return HEALTHY_HTML, 200, "https://example.com/calls-proposals/fourth-call-proposals-innovative-actions", "text/html"
    evidence = mod.collect_exact(REGISTRY, call_id=CALL_ID, run_id="test-redirect", fetcher=fetcher)
    assert evidence["source_health_state"] == "DEGRADED_TRANSPORT"
    assert evidence["candidate_state"] == "UNKNOWN"
    assert evidence["lkg_required"] is True


def test_transport_failure_degrades_without_fabrication() -> None:
    def fetcher(url: str, *, timeout: float):
        raise TimeoutError("bounded timeout")
    evidence = mod.collect_exact(REGISTRY, call_id=CALL_ID, run_id="test-timeout", fetcher=fetcher)
    assert evidence["source_health_state"] == "DEGRADED_TRANSPORT"
    assert evidence["candidate_state"] == "UNKNOWN"
    assert evidence["receipt"]["raw_sha256"] is None
    assert evidence["exact_semantics"] is None
    assert evidence["current_material_truth_available"] is False


def test_authorization_widening_rejected() -> None:
    evidence = mod.collect_exact(REGISTRY, call_id=CALL_ID, run_id="test-auth", fetcher=fake_healthy)
    bad = copy.deepcopy(evidence)
    bad["closed_call_authorized"] = True
    try:
        mod.validate_evidence(bad, REGISTRY)
    except ValueError as exc:
        assert "attempted material authorization" in str(exc)
    else:
        raise AssertionError("authorization widening was accepted")


def test_semantic_fingerprint_tamper_rejected() -> None:
    evidence = mod.collect_exact(REGISTRY, call_id=CALL_ID, run_id="test-hash", fetcher=fake_healthy)
    bad = copy.deepcopy(evidence)
    bad["exact_semantics"]["status_label"] = "Open"
    try:
        mod.validate_evidence(bad, REGISTRY)
    except ValueError as exc:
        assert "semantic fingerprint mismatch" in str(exc)
    else:
        raise AssertionError("semantic fingerprint tamper was accepted")


def test_registry_policy_remains_non_authorizing() -> None:
    policy = REGISTRY["policy"]
    assert policy["acquisition_only"] is True
    assert policy["semantic_reconciliation_required"] is True
    assert policy["field_scoped_material_admission_required"] is True
    assert policy["publication_effect"] == "NONE"
    for key in mod.MATERIAL_FLAGS:
        assert policy[key] is False
    assert policy["canonical_corpus_mutation"] is False


def main() -> int:
    tests = [
        test_healthy_exact_non_authorizing,
        test_lexical_open_does_not_override_explicit_closed,
        test_marker_drift_degrades_and_suppresses_candidates,
        test_redirect_off_authority_degrades,
        test_transport_failure_degrades_without_fabrication,
        test_authorization_widening_rejected,
        test_semantic_fingerprint_tamper_rejected,
        test_registry_policy_remains_non_authorizing,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS {len(tests)} EUI exact fail-closed regressions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
