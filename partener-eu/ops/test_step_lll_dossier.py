#!/usr/bin/env python3
from __future__ import annotations

import json
import copy
import importlib.util
import tempfile
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"


def get_section(d, title):
    return next((s for s in d.get("sections") or [] if s.get("title") == title), None)


def get_fact(d, label):
    return next((f for f in d.get("quickFacts") or [] if f.get("label") == label), None)


def joined(section):
    return " ".join(section.get("items") or []).lower() if section else ""


def test_status_admission():
    path = ROOT / "partener-eu" / "ingest" / "apply_step_lll_authoritative_dossier.py"
    spec = importlib.util.spec_from_file_location("step_lll_dossier", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    row = {"callCode": module.MYSMIS_CALL_CODE, "status": "FINALIZAT"}
    good = {
        "schema": "CIVORA_MYSMIS_EXACT_CALL_INVENTORY_V1",
        "status": "PASS_CANDIDATE_ONLY",
        "canonicalUrl": "https://reporting.mysmis2021.gov.ro/ords/repo_bo/r/mysmis-2021/finantari-programe-2021-2027",
        "authorityClass": "T1_OFFICIAL_MYSMIS_REPORTING",
        "sourceFamily": "ROMANIA_MIPE_MYSMIS",
        "parserVersion": "MYSMIS_EXACT_CALL_INVENTORY_V2",
        "observedAt": "2026-11-27T02:56:59+00:00",
        "runId": "fixture",
        "rawSha256": "a" * 64,
        **dict.fromkeys(("materialFactUse", "publishAuthorized", "openCallAuthorized",
                         "deadlineAuthorized", "budgetAuthorized", "eligibilityAuthorized"), False),
        "candidateInventory": {
            "exactIdentityCompleteForVisiblePage": True,
            "identityFailures": [], "duplicateCallCodes": [],
            "pageComplete": False, "rows": [row],
        },
    }
    with tempfile.TemporaryDirectory() as tmp:
        file = Path(tmp) / "inventory.json"
        with patch.object(module, "MYSMIS_INVENTORY", file):
            def observe(value):
                file.write_text(json.dumps(value), encoding="utf-8")
                return module.exact_mysmis_status()

            assert module.exact_mysmis_status() is None
            valid = observe(good)
            assert valid and valid["materialFactUse"] == "STATUS_ONLY_DEMOTION"
            assert valid["pageComplete"] is False
            assert valid["observationState"] == "PASS_CANDIDATE_ONLY"
            for field, value in (
                ("status", "SOURCE_UNAVAILABLE_FAIL_CLOSED"),
                ("status", "PROVISIONAL_FAIL_CLOSED"),
                ("canonicalUrl", "https://reporting.mysmis2021.gov.ro.example.invalid/"),
                ("authorityClass", "DISCOVERY_ONLY"),
                ("sourceFamily", "UNKNOWN"),
                ("parserVersion", "UNKNOWN"),
                ("observedAt", "2026-11-27T02:56:59"),
                ("observedAt", "2026-11-27T02:56:59+02:00"),
                ("runId", ""),
                ("rawSha256", "missing"),
                ("openCallAuthorized", True),
                ("publishAuthorized", 0),
            ):
                candidate = copy.deepcopy(good)
                candidate[field] = value
                assert observe(candidate) is None, field
            for field in ("observedAt", "rawSha256", "runId", "authorityClass"):
                candidate = copy.deepcopy(good)
                del candidate[field]
                assert observe(candidate) is None, field
            other = {**row, "status": "DESCHIS"}
            for rows in ([row, other], [other, row], [row, row], [other],
                         [{**row, "callCode": "PEO/OTHER"}], [None], []):
                candidate = copy.deepcopy(good)
                candidate["candidateInventory"]["rows"] = rows
                assert observe(candidate) is None, rows
            for key, value in (("exactIdentityCompleteForVisiblePage", False),
                               ("identityFailures", ["missing"]),
                               ("duplicateCallCodes", [module.MYSMIS_CALL_CODE])):
                candidate = copy.deepcopy(good)
                candidate["candidateInventory"][key] = value
                assert observe(candidate) is None, key
            file.write_text("{broken", encoding="utf-8")
            assert module.exact_mysmis_status() is None
            assert observe([]) is None
    # Exercise the entire projection in memory, including transition from an
    # earlier verified status to REVIEW after a failed acquisition.
    for evidence in (None, valid):
        dossier = {"id": module.TARGET_ID, "quality": {
            "verifiedFactClasses": ["status"], "blockedFactClasses": ["status"]},
            "quickFacts": [{"label": "Status", "value": "FINALIZAT", "confidence": "CONFIRMED"}]}
        products = {"dossiers": [dossier]}
        canonical = {"calls": [{"id": module.TARGET_ID}]}
        with patch.object(module, "read", side_effect=[products, canonical]), \
             patch.object(module, "exact_mysmis_status", return_value=evidence), \
             patch.object(module, "write") as output:
            assert module.main() == 0
            output.assert_called_once_with(products)
        quality = dossier["quality"]
        assert quality["failClosed"] is True
        assert dossier["status"] == ("CLOSED" if evidence else "REVIEW")
        assert ("status" in quality["verifiedFactClasses"]) is bool(evidence)
        assert ("status" in quality["blockedFactClasses"]) is (not bool(evidence))
        assert get_fact(dossier, "Status")["confidence"] == ("CONFIRMED" if evidence else "UNRESOLVED")
        assert dossier["publicationState"] == ("PUBLISHABLE" if evidence else "PROVISIONAL_FAIL_CLOSED")
        assert dossier["executiveSummary"]["status"] == dossier["status"]
    print("PASS STEP-LLL isolated status-admission fixtures")


def main() -> int:
    test_status_admission()
    payload = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    d = next(
        (
            x for x in payload.get("dossiers") or []
            if x.get("id") == "step-lll-adulti-4.3"
            or ("STEP-LLL" in str(x.get("title") or "") and "Adulți" in str(x.get("title") or ""))
        ),
        None,
    )
    assert d, "STEP-LLL Adults dossier missing"
    assert d.get("status") == "CLOSED"
    assert d.get("statusLabel") == "FINALIZAT"
    assert get_fact(d, "Status")["value"] == "FINALIZAT"
    assert d.get("region") == "Național; minimum 2 regiuni de dezvoltare"
    assert get_fact(d, "Deschidere")["value"] == "29 mai 2026, 16:00"
    assert get_fact(d, "Termen")["value"] == "30 septembrie 2026, 16:00"
    assert get_fact(d, "Buget")["value"] == "92.000.000 EUR"
    assert get_fact(d, "Contribuție proprie")["value"] == "0%"
    assert get_fact(d, "Durată maximă")["value"] == "36 luni"
    assert "7.974 EUR" in get_fact(d, "Grant")["value"]
    assert d.get("quality", {}).get("completeness") == 100
    assert d.get("quality", {}).get("depthCompleteness") == 100
    assert d.get("quality", {}).get("stepLllAuthoritativeBundle") is True
    status_provenance = d.get("quality", {}).get("statusProvenance") or {}
    assert status_provenance.get("callCode") == "PEO/1160/PEO_P11/OP4/ESO4.7/PEO_A66"
    assert status_provenance.get("status") == "FINALIZAT"
    assert status_provenance.get("materialFactUse") == "STATUS_ONLY_DEMOTION"
    assert status_provenance.get("observedAt")
    assert status_provenance.get("runId")
    assert status_provenance.get("parserVersion") == "MYSMIS_EXACT_CALL_INVENTORY_V2"
    assert status_provenance.get("rawSha256")
    assert not d.get("quality", {}).get("blockedFactClasses")

    applicants = get_section(d, "Cine poate aplica")
    eligibility = get_section(d, "Condiții esențiale de eligibilitate")
    activities = get_section(d, "Ce finanțează și în ce condiții")
    costs = get_section(d, "Costuri, cofinanțare și ajutor de stat")
    docs = get_section(d, "Documente de pregătit")
    scoring = get_section(d, "Cum se punctează")
    indicators = get_section(d, "Indicatori și obligații")
    corr = get_section(d, "Corrigendum nr. 1 — rezumat")
    qa = get_section(d, "Q&A AM — clarificări esențiale")
    implementation = get_section(d, "Implementare")
    executive = get_section(d, "Rezumat executiv")
    quick = get_section(d, "Decizia rapidă")
    actions = get_section(d, "Ce trebuie făcut acum")

    assert applicants and len(applicants["items"]) >= 6
    assert "fpc" in joined(applicants)
    assert "confederații sindicale" in joined(applicants)
    assert "asociații profesionale sectoriale" in joined(applicants)
    assert eligibility and "angajate și/sau șomeri" in joined(eligibility)
    assert "minimum 25" in joined(eligibility)
    assert "minimum două regiuni" in joined(eligibility)
    assert "pensionar" not in joined(eligibility)
    assert activities and "a1" in joined(activities) and "exclusiv șomerilor" in joined(activities)
    assert "a2.1" in joined(activities) and "a2.2" in joined(activities)
    assert costs and "nu este un cost unitar" in joined(costs)
    assert docs and len(docs["items"]) >= 8
    assert scoring and "eeco01" in joined(scoring)
    assert indicators and "11.538" in joined(indicators)
    assert corr and "30 septembrie 2026" in joined(corr)
    assert "12 august" not in joined(corr)
    assert qa and "minimum 25" in joined(qa)
    assert "7.974 eur" in joined(qa)
    assert "minimum două regiuni" in joined(qa)
    assert "36 de luni" in joined(qa)
    assert "a1" in joined(qa) and "a2.2" in joined(qa)
    assert implementation and "36 de luni" in joined(implementation)
    assert executive and "stare apel: finalizat" in joined(executive)
    public_action_text = " ".join([str(d.get("decisionAction") or ""), joined(executive), joined(quick), joined(actions)]).lower()
    assert "depunerea este deschisă" not in public_action_text
    assert "acționează" not in public_action_text
    assert "planifică depunerea înainte" not in public_action_text
    assert "nu mai planifica o depunere" in public_action_text
    assert (d.get("executiveSummary") or {}).get("status") == "CLOSED"

    summaries = d.get("documentSummaries") or []
    by_kind = {x.get("kind"): x for x in summaries}
    assert {"CORRIGENDUM", "QA_AM"} <= set(by_kind)
    assert "mfe.gov.ro" in str(by_kind["CORRIGENDUM"].get("sourceUrl") or "")
    assert "mfe.gov.ro" in str(by_kind["QA_AM"].get("sourceUrl") or "")
    assert payload.get("policy", {}).get("stepLllSourceBoundDossier") is True

    print(json.dumps({
        "ok": True,
        "dossierId": d.get("id"),
        "quality": d.get("quality", {}).get("completeness"),
        "depth": d.get("quality", {}).get("depthCompleteness"),
        "sections": len(d.get("sections") or []),
        "sources": len(d.get("sources") or []),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
