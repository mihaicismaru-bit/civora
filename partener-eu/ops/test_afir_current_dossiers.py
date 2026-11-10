#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
LIVE_FUNDS = ROOT / "partener-eu" / "ingest" / "state" / "afir_live_funds.json"


def by_title(dossier: dict, title: str) -> dict | None:
    return next((row for row in dossier.get("sections") or [] if row.get("title") == title), None)


def fact(dossier: dict, label: str) -> dict | None:
    return next((row for row in dossier.get("quickFacts") or [] if row.get("label") == label), None)


def test_extension_counter_proof_fail_closed() -> None:
    """Exact positive and negative replay of hashed AFIR extension evidence."""
    import copy
    import importlib.util
    import tempfile
    from unittest.mock import patch

    module_path = ROOT / "partener-eu" / "ingest" / "apply_afir_current_authoritative_dossiers.py"
    spec = importlib.util.spec_from_file_location("afir_extension_overlay", module_path)
    assert spec and spec.loader
    overlay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(overlay)
    original = json.loads(LIVE_FUNDS.read_text(encoding="utf-8"))
    assert overlay.dr14_dr18_extension_counter_proof() == original["sourceObservedAt"]

    def replay(candidate: dict, *, should_pass: bool) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "hashed_official_counter.json"
            fixture.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
            with patch.object(overlay, "LIVE_FUNDS", fixture):
                if should_pass:
                    assert overlay.dr14_dr18_extension_counter_proof() == candidate["sourceObservedAt"]
                else:
                    try:
                        overlay.dr14_dr18_extension_counter_proof()
                    except RuntimeError:
                        pass
                    else:
                        raise AssertionError("unsafe AFIR extension evidence was admitted")

    # AFIR's newer live counter can omit exhausted Achiziții simple entirely.
    omitted = copy.deepcopy(original)
    omitted["rows"] = [
        row for row in omitted["rows"]
        if not (row.get("interventionCode") == "DR-14"
                and "ACHIZI" in str(row.get("sector") or "").upper())
    ]
    replay(omitted, should_pass=True)
    held = copy.deepcopy(original)
    held["status"] = "PROVISIONAL_FAIL_CLOSED"
    replay(held, should_pass=False)
    held = copy.deepcopy(original)
    held["sourceFingerprintMatchesCorpus"] = False
    held["sourceFingerprintReconciledFromCanonicalLiveFetch"] = False
    replay(held, should_pass=False)
    held = copy.deepcopy(original)
    held["rows"] = [row for row in held["rows"] if row.get("interventionCode") != "DR-18"]
    replay(held, should_pass=False)
    held = copy.deepcopy(original)
    for row in held["rows"]:
        if row.get("interventionCode") == "DR-18":
            row["closesAtIso"] = "2026-10-31T16:00:00+02:00"
    replay(held, should_pass=False)


def test_afir_source_scope_guard() -> None:
    """Verify that an AFIR-only candidate cannot change unrelated LKG facts."""
    import copy
    import importlib.util

    module_path = ROOT / "partener-eu" / "ops" / "validate_decision_products_lkg.py"
    spec = importlib.util.spec_from_file_location("afir_lkg_source_scope", module_path)
    assert spec and spec.loader
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    baseline = {
        "dossiers": [
            {"id": "mipe-protected", "status": "REVIEW", "evidence": "original"},
            {"id": "afir-dr14-2026", "status": "OPEN", "deadline": "old"},
        ],
        "news": [{"id": "mipe-protected-news", "headline": "original"}],
    }
    # Unrelated AFIR scope remains writable, while non-AFIR LKG remains fixed.
    allowed = copy.deepcopy(baseline)
    allowed["dossiers"].append({
        "id": "afir-dr12-2026", "sourceType": "AFIR_CANONICAL", "status": "OPEN"
    })
    assert gate.validate_afir_source_scope(baseline, allowed)["afirOnlySourceScope"] == "PASS"

    def denied(candidate: dict, reason: str) -> None:
        try:
            gate.validate_afir_source_scope(baseline, candidate)
        except AssertionError as error:
            assert reason in str(error), str(error)
        else:
            raise AssertionError(f"unsafe AFIR projection admitted: {reason}")

    for section, field in (("dossiers", "status"), ("news", "headline")):
        altered = copy.deepcopy(allowed)
        altered[section][0][field] = "UNAUTHORIZED"
        denied(altered, "outside source scope")
    removed = copy.deepcopy(allowed)
    removed["dossiers"] = [row for row in removed["dossiers"] if row["id"] != "mipe-protected"]
    denied(removed, "outside source scope")

    # The 30 October official extension is verified as a source discovery,
    # but a changed DR14/DR18 material deadline/status or publication news may
    # not pass the product persistence gate until an immutable source receipt
    # and reviewed field-scoped admission exist. No material change = no alert.
    deadline_change = copy.deepcopy(baseline)
    deadline_change["dossiers"][1]["deadline"] = "2026-11-16T16:00:00+02:00"
    denied(deadline_change, "extension material release HELD")
    new_extension_news = copy.deepcopy(baseline)
    new_extension_news["news"].append({
        "id": "news-afir-dr14-dr18-extended-2026-10-30",
        "kind": "DEADLINE_EXTENDED",
    })
    denied(new_extension_news, "extension material release HELD")
    omitted_extension = copy.deepcopy(baseline)
    omitted_extension["dossiers"] = [row for row in omitted_extension["dossiers"] if row["id"] != "afir-dr14-2026"]
    denied(omitted_extension, "extension material release HELD")

def test_projection_clock_and_bucharest_dst() -> None:
    """Current application windows use wall time, not a source build timestamp."""
    import importlib.util

    module_path = ROOT / "partener-eu" / "ingest" / "sync_decision_products_projection.py"
    spec = importlib.util.spec_from_file_location("afir_live_projection", module_path)
    assert spec and spec.loader
    projection = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(projection)

    # DST-aware deadlines are non-negotiable for official Romanian calls.
    assert projection.parse_date("16 noiembrie 2026, 16:00 (componente cu fonduri)") == datetime(
        2026, 11, 16, 14, 0, tzinfo=timezone.utc
    )
    assert projection.parse_date("16 iulie 2026, 16:00") == datetime(
        2026, 7, 16, 13, 0, tzinfo=timezone.utc
    )
    official = {
        "status": "OPEN", "publicationState": "PUBLISHABLE",
        "quickFacts": [
            {"label": "Status", "value": "DESCHIS", "confidence": "CONFIRMED"},
            {"label": "Termen", "value": "16 noiembrie 2026, 16:00 (componente cu fonduri)", "confidence": "CONFIRMED"},
        ],
    }
    assert projection.current_open(official, datetime(2026, 11, 7, 20, tzinfo=timezone.utc))
    assert projection.current_open(official, datetime(2026, 11, 16, 14, tzinfo=timezone.utc))
    assert not projection.current_open(official, datetime(2026, 11, 16, 14, 0, 1, tzinfo=timezone.utc))
    assert not projection.current_open({**official, "publicationState": "REVIEW_REQUIRED"}, datetime(
        2026, 11, 7, 20, tzinfo=timezone.utc
    ))
    # Static lock on the critical clock boundary: source-generatedAt is a
    # version marker only; source timestamps may be stale or future-dated.
    source = module_path.read_text(encoding="utf-8")
    assert 'clock = dt.datetime.now(dt.timezone.utc)' in source
    assert 'clock = parse_date(payload.get("generatedAt"))' not in source


def main() -> int:
    test_afir_source_scope_guard()
    test_extension_counter_proof_fail_closed()
    test_projection_clock_and_bucharest_dst()
    payload = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    dossiers = {row["id"]: row for row in payload.get("dossiers") or []}
    assert {
        "afir-dr12-2026",
        "afir-dr14-2026",
        "afir-dr18-2026",
        "afir-dr31-2026-2027",
        "afir-fm-public-autoconsum-2026",
        "afir-fm-public-storage-2026",
    } <= set(dossiers)

    dr12, dr14, dr18, dr31 = (
        dossiers[key] for key in ("afir-dr12-2026", "afir-dr14-2026", "afir-dr18-2026", "afir-dr31-2026-2027")
    )
    expired = datetime.now(timezone.utc) >= datetime.fromisoformat("2026-11-16T16:00:00+02:00")
    for dossier in (dr14, dr18):
        if expired:
            assert dossier["status"] == "REVIEW"
            assert dossier["publicationState"] == "PROVISIONAL_FAIL_CLOSED"
            assert "status" in dossier["quality"]["blockedFactClasses"]
            assert dossier["executiveSummary"]["status"] == "REVIEW"
            assert fact(dossier, "Status")["value"] == "ÎN VERIFICARE"
            assert "depunere deschisă" in dossier["decisionAction"]
        else:
            assert dossier["status"] == "OPEN"
            assert dossier["publicationState"] == "PUBLISHABLE"
        assert fact(dossier, "Deschidere")["value"] == "1 septembrie 2026, 09:00"
        assert fact(dossier, "Termen")["value"] == "16 noiembrie 2026, 16:00 (componente cu fonduri)"
        assert dossier["executiveSummary"]["closes"] == "2026-11-16T16:00:00+02:00"
        assert any(row.get("url") == "https://www.afir.ro/info-la-zi/prelungire-sesiune-depunere-proiecte-de-investitii-aferente-dr-14-si-dr-18/" and "deadline" in set(row.get("supports") or []) for row in dossier["sources"])
        assert dossier["quality"]["afirCurrentSessionBundle"] is True
        if not expired:
            assert dossier["quality"]["blockedFactClasses"] == []
        assert all(str(row.get("url") or "").startswith("https://www.afir.ro/") for row in dossier["sources"])
        assert by_title(dossier, "Cine poate aplica")["items"] == dossier["audience"]
        assert dossier["executiveSummary"]["applicants"] == dossier["audience"]

    assert fact(dr14, "Buget")["value"] == "108.000.000 EUR"
    assert "50.000 EUR" in fact(dr14, "Grant")["value"]
    assert "80 puncte" in " ".join(by_title(dr14, "Cum se punctează")["items"])
    assert "epuizată" in json.dumps(by_title(dr14, "Riscuri de respingere sau implementare"), ensure_ascii=False).lower()
    assert "achiziții simple este epuizată" in json.dumps(by_title(dr14, "Ce finanțează și în ce condiții"), ensure_ascii=False).lower()
    assert fact(dr18, "Buget")["value"] == "5.000.000 EUR"
    assert "100.000 EUR" in fact(dr18, "Grant")["value"]
    assert "85% sau 65%" in fact(dr18, "Grant")["value"]

    for dossier_id in ("afir-fm-public-autoconsum-2026", "afir-fm-public-storage-2026"):
        energy = dossiers[dossier_id]
        assert energy["status"] == "OPEN"
        assert energy["statusLabel"] == "DESCHIS"
        assert energy["publicationState"] == "PUBLISHABLE"
        assert fact(energy, "Deschidere")["value"] == "28 septembrie 2026, 10:00"
        assert fact(energy, "Termen")["value"] == "20 noiembrie 2026, 23:59"
        assert energy["executiveSummary"]["status"] == "OPEN"
        assert energy["executiveSummary"]["sourceBound"] is True
        assert any(
            row.get("url") == "https://www.afir.ro/comunicate/depunere-in-curs-a-proiectelor-in-energie-a-entitatilor-publice/"
            and "status" in set(row.get("supports") or [])
            for row in energy["sources"]
        )
        public_text = json.dumps(energy, ensure_ascii=False).lower()
        assert "apelul nu este încă open" not in public_text
        assert "apelul nu este inca open" not in public_text

    live = json.loads(LIVE_FUNDS.read_text(encoding="utf-8"))
    dr12_live_rows = [
        row for row in live.get("rows") or []
        if str(row.get("interventionCode") or "").upper() == "DR-12"
    ]
    fingerprint_admissible = (
        live.get("sourceFingerprintMatchesCorpus") is True
        or live.get("sourceFingerprintReconciledFromCanonicalLiveFetch") is True
    )
    dr12_post_launch = (
        live.get("status") == "PASS"
        and fingerprint_admissible
        and (live.get("policy") or {}).get("publishableDedicatedSnapshot") is True
        and any(int(row.get("submittedProjectCount") or 0) > 0 for row in dr12_live_rows)
    )
    expected_dr12_status = "OPEN" if dr12_post_launch else "UPCOMING"
    assert dr12["status"] == expected_dr12_status
    assert dr12["publicationState"] == "PUBLISHABLE"
    assert fact(dr12, "Deschidere")["value"] == "6 octombrie 2026, 09:00"
    assert fact(dr12, "Termen")["value"] == "2 decembrie 2026, 16:00"
    assert fact(dr12, "Buget")["value"] == "169.589.647 EUR"
    assert "200.000 EUR" in fact(dr12, "Grant")["value"]
    assert "80 puncte" in " ".join(by_title(dr12, "Cum se punctează")["items"])
    assert "45 puncte" in " ".join(by_title(dr12, "Cum se punctează")["items"])
    # Historical monthly thresholds are retained, but an applicant must never
    # be instructed to simulate the expired first-stage 80-point threshold.
    current_actions = " ".join(by_title(dr12, "Ce trebuie făcut acum")["items"])
    assert "80 de puncte al primei etape" not in current_actions
    assert "pragul de calitate al etapei curente" in current_actions
    assert "NU ESTE CAZUL" in " ".join(by_title(dr12, "Riscuri de respingere sau implementare")["items"])
    assert dr12["executiveSummary"]["sourceBound"] is True
    assert dr12["executiveSummary"]["status"] == expected_dr12_status
    assert dr12["quality"]["afirCurrentUpcomingBundle"] is (not dr12_post_launch)
    assert dr12["quality"]["afirCurrentOpenBundle"] is dr12_post_launch
    assert dr12["quality"]["afirPostLaunchSubmissionEvidence"] is dr12_post_launch
    if dr12_post_launch:
        assert dr12["statusLabel"] == "DESCHIS"
        assert dr12["decision"] == "ACȚIONEAZĂ"
        assert "este deschisă pentru depunere" in dr12["standfirst"]
        assert "nu depune înainte de deschiderea oficială" not in json.dumps(dr12, ensure_ascii=False).lower()

    assert dr31["status"] == "PUBLIC_CONSULTATION"
    assert dr31["publicationState"] == "PUBLISHABLE"
    assert dr31["audience"] == []
    assert "iunie 2026" in dr31["standfirst"]
    assert "10 zile calendaristice" in fact(dr31, "Termen")["value"]
    assert "beneficiaries" in dr31["quality"]["blockedFactClasses"]

    codes = [str(row.get("code") or "").replace("-", "").replace(" ", "").upper() for row in payload["dossiers"]]
    assert codes.count("DR12") == 1
    assert codes.count("DR14") == 1
    assert codes.count("DR18") == 1
    assert codes.count("DR31") == 1
    assert payload["policy"]["afirCurrentSessionsSourceBound"] is True
    assert payload["policy"]["afirConsultationsNeverPresentedAsOpen"] is True
    assert payload["policy"]["afirEnergyPostLaunchEvidenceSourceBound"] is True
    assert payload["policy"]["afirDr12UpcomingSourceBound"] is (not dr12_post_launch)
    assert payload["policy"]["afirDr12PostLaunchSourceBound"] is dr12_post_launch
    assert payload["policy"]["derivedProjectionSynchronized"] is True

    home_open = payload["home"]["openDossierIds"]
    # AFIR's official 30 Oct notice extends the *funded components* of both
    # interventions to 16 Nov 16:00. The old 31 Oct deadline must not remove
    # these actionable dossiers prematurely; after the new deadline, the
    # homepage freshness filter must exclude them automatically.
    if datetime.now(timezone.utc) < datetime.fromisoformat("2026-11-16T16:00:00+02:00"):
        assert {"afir-dr14-2026", "afir-dr18-2026"} <= set(home_open)
    else:
        assert "afir-dr14-2026" not in home_open
        assert "afir-dr18-2026" not in home_open
    assert {"afir-fm-public-autoconsum-2026", "afir-fm-public-storage-2026"} <= set(home_open)
    if dr12_post_launch:
        assert "afir-dr12-2026" in home_open
    assert "afir-dr31-2026-2027" in payload["home"]["prepareDossierIds"]
    # The homepage is intentionally a bounded editorial shortlist (max 8),
    # while summary.openCount is the total verified OPEN catalog count.
    assert len(home_open) == min(payload["summary"]["openCount"], 8)
    # PEO STEP dossier validation is owned by PARTENER.EU Decision Products.
    # AFIR-only preflight cannot rewrite PEO LKG just to fix unrelated fields.

    news_ids = {row["id"] for row in payload.get("news") or []}
    assert {"news-afir-dr14-dr18-open-2026-09-01", "news-afir-dr14-dr18-extended-2026-10-30", "news-afir-dr31-consultation-2026-08-28"} <= news_ids
    print(json.dumps({"ok": True, "open": home_open, "catalogOpenCount": payload["summary"]["openCount"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())