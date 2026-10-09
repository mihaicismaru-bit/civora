#!/usr/bin/env python3
"""AFIR DR-14 partial closure: authoritatively closed component remains closed.

Run after constructing partener-eu/ingest/state/decision_products.json.
This is intentionally RED against the current public projection.
"""
from __future__ import annotations
import json
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "partener-eu/ingest/state/decision_products.json"
SOURCE = ("https://www.afir.ro/comunicate/"
          "fondurile-alocate-interventiei-dr-14-pentru-componenta-achizitii-simple-au-fost-epuizate/")

def normalized(value: object) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(value).lower())
                   if not unicodedata.combining(c))

def verify(payload: dict) -> None:
    rows = [row for row in payload.get("dossiers", [])
            if row.get("id") == "afir-dr14-2026"]
    assert len(rows) == 1, "DR14_MISSING_OR_DUPLICATED"
    row = rows[0]
    sources = row.get("sources") or []
    assert any(s.get("url") == SOURCE and s.get("tier") == "T1"
               and ("component_status" in s.get("supports", [])
                    or "component_closure" in s.get("supports", []))
               for s in sources), "DR14_OFFICIAL_CLOSURE_PROVENANCE_MISSING"
    parts = row.get("sections") or []
    decision = next((s.get("items") for s in parts if s.get("title") == "Decizia rapidă"), [])
    advice = " ".join([str(row.get("standfirst", "")),
                       str(row.get("decisionAction", "")),
                       *(str(x) for x in decision)])
    normalized_advice = normalized(advice)
    assert "achizitii simple" in normalized_advice, "DR14_COMPONENT_MISSING"
    assert "inchis" in normalized_advice or "inchisa" in normalized_advice, "DR14_CLOSURE_UNDISCLOSED"
    assert "zootehn" in normalized_advice and "legumicultur" in normalized_advice, "DR14_REMAINING_COMPONENTS_UNCLEAR"
    assert any(e.get("kind") == "COMPONENT_CLOSED" and e.get("sourceUrl") == SOURCE
               for e in row.get("timeline") or []), "DR14_EVENT_PROVENANCE_MISSING"

if __name__ == "__main__":
    verify(json.loads(PRODUCTS.read_text(encoding="utf-8")))
    print("PASS: DR-14 component-specific closure is source-bound and clearly disclosed")
