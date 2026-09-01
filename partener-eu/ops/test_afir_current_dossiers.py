#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"


def by_title(dossier: dict, title: str) -> dict | None:
    return next((row for row in dossier.get("sections") or [] if row.get("title") == title), None)


def fact(dossier: dict, label: str) -> dict | None:
    return next((row for row in dossier.get("quickFacts") or [] if row.get("label") == label), None)


def main() -> int:
    payload = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    dossiers = {row["id"]: row for row in payload.get("dossiers") or []}
    assert {"afir-dr14-2026", "afir-dr18-2026", "afir-dr31-2026-2027"} <= set(dossiers)

    dr14, dr18, dr31 = (dossiers[key] for key in ("afir-dr14-2026", "afir-dr18-2026", "afir-dr31-2026-2027"))
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

    assert dr31["status"] == "PUBLIC_CONSULTATION"
    assert dr31["publicationState"] == "PUBLISHABLE"
    assert dr31["audience"] == []
    assert "iunie 2026" in dr31["standfirst"]
    assert "10 zile calendaristice" in fact(dr31, "Termen")["value"]
    assert "beneficiaries" in dr31["quality"]["blockedFactClasses"]

    codes = [str(row.get("code") or "").replace("-", "").replace(" ", "").upper() for row in payload["dossiers"]]
    assert codes.count("DR14") == 1
    assert codes.count("DR18") == 1
    assert codes.count("DR31") == 1
    assert payload["policy"]["afirCurrentSessionsSourceBound"] is True
    assert payload["policy"]["afirConsultationsNeverPresentedAsOpen"] is True
    assert payload["policy"]["derivedProjectionSynchronized"] is True

    assert {"afir-dr14-2026", "afir-dr18-2026"} <= set(payload["home"]["openDossierIds"])
    assert "afir-dr31-2026-2027" in payload["home"]["prepareDossierIds"]
    assert payload["summary"]["openCount"] == len(payload["home"]["openDossierIds"])
    step = dossiers["PEO-STEP-LLL-ADULTI-2026"]
    assert fact(step, "Completitudine critică")["value"] == f"{step['quality']['completeness']}%"

    news_ids = {row["id"] for row in payload.get("news") or []}
    assert {"news-afir-dr14-dr18-open-2026-09-01", "news-afir-dr31-consultation-2026-08-28"} <= news_ids
    print(json.dumps({"ok": True, "open": payload["home"]["openDossierIds"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
