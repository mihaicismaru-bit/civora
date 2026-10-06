#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"


def get_section(d, title):
    return next((s for s in d.get("sections") or [] if s.get("title") == title), None)


def get_fact(d, label):
    return next((f for f in d.get("quickFacts") or [] if f.get("label") == label), None)


def joined(section):
    return " ".join(section.get("items") or []).lower() if section else ""


def main() -> int:
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
