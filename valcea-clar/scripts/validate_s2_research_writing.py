#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RESEARCH=ROOT/"research"

def load(path):
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict):
        raise AssertionError(f"{path} must be object")
    return value

def main():
    sources=load(RESEARCH/"s2_priority_sources.json")
    agenda=load(RESEARCH/"s2_editorial_agenda_2026-09-22.json")
    examples=load(ROOT/"editorial"/"s2_format_examples.json")

    rows=sources.get("sources") or []
    assert 20 <= len(rows) <= 30, len(rows)
    ids=[r["id"] for r in rows]
    assert len(ids)==len(set(ids)), "duplicate source ids"
    assert all(r.get("url") and r.get("tier") in {"T1","T1B","T2","T3"} for r in rows)
    assert sum(1 for r in rows if r.get("tier") in {"T1","T1B"}) >= 20
    assert any(r.get("mode")=="discovery_only" and r.get("tier")=="T2" for r in rows)
    verticals={r.get("vertical") for r in rows}
    required={"ADMINISTRAȚIE","INFRASTRUCTURĂ","MOBILITATE","ECONOMIE","EDUCAȚIE","CULTURĂ","SPORT","SIGURANȚĂ","SĂNĂTATE","JUSTIȚIE","ACHIZIȚII"}
    assert required <= verticals, sorted(required-verticals)
    geography={g for r in rows for g in (r.get("geography") or [])}
    assert {"Brezoi","Lotru","Valea Oltului"} <= geography

    candidates=agenda.get("candidates") or []
    assert len(candidates) >= 6
    assert all(c.get("angle") and c.get("evidence") and c.get("verification_gap") and c.get("next_watch") for c in candidates)
    formats={c.get("format") for c in candidates}
    assert {"straight_news","explainer","service_news"} <= formats

    products=examples.get("examples") or []
    by_format={p.get("format"):p for p in products}
    assert set(by_format)=={"straight_news","explainer","service_news"}, set(by_format)
    assert examples.get("publication_authority")=="none"
    assert examples.get("editorial_review_required") is True
    for fmt,p in by_format.items():
        assert p.get("headline") and p.get("dek")
        assert len(p.get("paragraphs") or []) >= 3
        assert p.get("sources") and all(s.get("url") and s.get("tier") for s in p["sources"])
        assert p.get("editorial_contribution") and p.get("limitations")
    calc=by_format["explainer"].get("calculations") or {}
    expected={"rural_share_percent":65.7,"non_indemnified_share_percent":56.1,"hard_or_very_hard_employability_share_percent":47.0,"age_50_plus_share_percent":44.0}
    assert calc==expected, calc
    text=" ".join(by_format["explainer"]["paragraphs"])
    assert "nu" in text.lower() and "cauz" in text.lower(), "explainer must preserve causal limitation"

    print(json.dumps({
        "status":"PASS",
        "sources":len(rows),
        "t1_or_t1b":sum(1 for r in rows if r.get("tier") in {"T1","T1B"}),
        "agenda_items":len(candidates),
        "formats":sorted(by_format),
        "publication_authority":examples.get("publication_authority")
    },ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
