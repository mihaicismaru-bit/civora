#!/usr/bin/env python3
"""DR-14 partial closure must be explicit in every generated dossier surface."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "partener-eu" / "ingest" / "apply_afir_current_authoritative_dossiers.py"


def main() -> int:
    spec = importlib.util.spec_from_file_location("afir_current_dossiers", GENERATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    dossier = module.open_dossier(
        dossier_id="afir-dr14-2026", title="DR-14 — Investiții în ferme mici",
        code="DR-14", applicants=["Fermieri"], activities=["Investiții."],
        budget="108.000.000 EUR", project_value="maximum 50.000 EUR",
        cofinancing="minimum 15%", scoring=["Prag 40"], documents=["Ghid DR-14"],
        risks=["Epuizare fonduri"], sources=[], standfirst="DR-14 deschis.",
    )

    # Before applying the repair, the canonical generator lacks this fact.
    before = json.dumps(dossier, ensure_ascii=False).lower()
    assert "achiziții simple — închisă" not in before

    module.apply_dr14_partial_closure(dossier)
    after = json.dumps(dossier, ensure_ascii=False).lower()
    assert dossier["status"] == "OPEN"  # Three other components continue.
    assert dossier["publicationState"] == "PUBLISHABLE"
    assert "achiziții simple" in dossier["standfirst"].lower()
    assert "închis" in dossier["standfirst"].lower()
    assert "zootehnic" in dossier["standfirst"].lower()
    assert "legumicultură" in dossier["standfirst"].lower()
    assert "alte sectoare" in dossier["standfirst"].lower()
    assert "achiziții simple — închisă" in after
    assert any(s.get("url") == module.DR14_CLOSURE for s in dossier["sources"])
    assert any(s.get("url") == module.DR14_CLOSURE and s.get("tier") == "T1" for s in dossier["sources"])
    assert module.DR14_CLOSURE in dossier["canonicalLinks"]
    assert dossier["quality"]["evidenceCount"] == len(dossier["sources"])
    assert any(t.get("kind") == "COMPONENT_CLOSED" for t in dossier["timeline"])
    assert dossier["executiveSummary"]["componentStatus"]["achizitiiSimple"] == "CLOSED"
    assert dossier["executiveSummary"]["componentStatus"]["zootehnic"] == "OPEN"
    assert dossier["executiveSummary"]["componentStatus"]["legumicultura"] == "OPEN"
    assert dossier["executiveSummary"]["componentStatus"]["alteSectoare"] == "OPEN"
    for title in ("Rezumat executiv", "Decizia rapidă", "Ce trebuie făcut acum"):
        section = next(s for s in dossier["sections"] if s["title"] == title)
        assert "achiziții simple" in json.dumps(section, ensure_ascii=False).lower()
    print(json.dumps({"ok": True, "case": "DR14_PARTIAL_CLOSURE", "sources": len(dossier["sources"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
