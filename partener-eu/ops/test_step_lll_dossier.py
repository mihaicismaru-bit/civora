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
    assert d.get("status") == "OPEN"
    assert d.get("region") == "7 regiuni mai puțin dezvoltate (fără București–Ilfov)"
    assert get_fact(d, "Termen")["value"] == "30 septembrie 2026, 16:00"
    assert get_fact(d, "Buget")["value"] == "92.000.000 EUR"
    assert get_fact(d, "Contribuție proprie")["value"] == "0%"
    assert "7.974 EUR" in get_fact(d, "Grant")["value"]
    assert d.get("quality", {}).get("completeness") == 100
    assert d.get("quality", {}).get("stepLllAuthoritativeBundle") is True
    assert not d.get("quality", {}).get("blockedFactClasses")
    assert get_section(d, "Cine poate aplica") and len(get_section(d, "Cine poate aplica")["items"]) >= 7
    assert get_section(d, "Ce finanțează și în ce condiții") and not get_section(d, "Ce finanțează și în ce condiții").get("empty")
    assert get_section(d, "Costuri, cofinanțare și ajutor de stat") and not get_section(d, "Costuri, cofinanțare și ajutor de stat").get("empty")
    assert get_section(d, "Documente de pregătit") and len(get_section(d, "Documente de pregătit")["items"]) >= 6
    assert get_section(d, "Indicatori și obligații") and any("EECO01" in x for x in get_section(d, "Indicatori și obligații")["items"])
    corr = get_section(d, "Corrigendum nr. 1 — rezumat")
    qa = get_section(d, "Q&A AM — clarificări esențiale")
    assert corr and any("30 septembrie 2026" in x for x in corr["items"])
    assert qa and any("minimum 25" in x.lower() for x in qa["items"])
    assert qa and any("7.974 EUR" in x for x in qa["items"])
    summaries = d.get("documentSummaries") or []
    assert {x.get("kind") for x in summaries} >= {"CORRIGENDUM", "QA_AM"}
    assert all(str(x.get("sourceUrl") or "").startswith("http") for x in summaries)
    assert all("mfe.gov.ro" in str(x.get("sourceUrl") or "") for x in summaries)
    assert payload.get("policy", {}).get("stepLllSourceBoundDossier") is True
    print(json.dumps({
        "ok": True,
        "dossierId": d.get("id"),
        "quality": d.get("quality", {}).get("completeness"),
        "sections": len(d.get("sections") or []),
        "sources": len(d.get("sources") or []),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
