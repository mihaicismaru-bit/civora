#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
LIVE_FUNDS = ROOT / "partener-eu" / "ingest" / "state" / "afir_live_funds.json"


def by_title(dossier: dict, title: str) -> dict | None:
    return next((row for row in dossier.get("sections") or [] if row.get("title") == title), None)


def fact(dossier: dict, label: str) -> dict | None:
    return next((row for row in dossier.get("quickFacts") or [] if row.get("label") == label), None)


def main() -> int:
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
    for dossier in (dr14, dr18):
        assert dossier["status"] == "OPEN"
        assert dossier["publicationState"] == "PUBLISHABLE"
        assert fact(dossier, "Deschidere")["value"] == "1 septembrie 2026, 09:00"
        assert fact(dossier, "Termen")["value"] == "31 octombrie 2026, 16:00"
        assert dossier["quality"]["afirCurrentSessionBundle"] is True
        assert dossier["quality"]["blockedFactClasses"] == []
        assert all(str(row.get("url") or "").startswith("https://www.afir.ro/") for row in dossier["sources"])
        assert by_title(dossier, "Cine poate aplica")["items"] == dossier["audience"]
        assert dossier["executiveSummary"]["applicants"] == dossier["audience"]

    assert fact(dr14, "Buget")["value"] == "108.000.000 EUR"
    assert "50.000 EUR" in fact(dr14, "Grant")["value"]
    assert "80 puncte" in " ".join(by_title(dr14, "Cum se punctează")["items"])
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
    assert {"afir-dr14-2026", "afir-dr18-2026"} <= set(home_open)
    assert "afir-dr31-2026-2027" in payload["home"]["prepareDossierIds"]
    # The homepage is intentionally a bounded editorial shortlist (max 8),
    # while summary.openCount is the total verified OPEN catalog count.
    assert len(home_open) == min(payload["summary"]["openCount"], 8)
    step = dossiers["PEO-STEP-LLL-ADULTI-2026"]
    assert fact(step, "Completitudine critică")["value"] == f"{step['quality']['completeness']}%"

    news_ids = {row["id"] for row in payload.get("news") or []}
    assert {"news-afir-dr14-dr18-open-2026-09-01", "news-afir-dr31-consultation-2026-08-28"} <= news_ids
    print(json.dumps({"ok": True, "open": home_open, "catalogOpenCount": payload["summary"]["openCount"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())