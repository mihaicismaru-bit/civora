#!/usr/bin/env python3
"""Materialize verified administrative stories from multiple official primary sources.

These kernels are for reader-facing straight news where the fact is independently
recoverable from official institutional surfaces and every material claim carries
claim-level provenance. Administrative register titles are never published as the
story itself; the kernel must explain the concrete consequence or discrepancy.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "editorial" / "facts_registry.json"

HCJ_2026_URL = "https://cjvalcea.ro/monitorul-oficial-local/hotararile-autoritatii-deliberative/2026-hotararile-autoritatii-deliberative/"
CJ_SESSION_URL = "https://cjvalcea.ro/avn_sedinte_cj/24-07-2026/"
CJ_GOV_URL = "https://cjvalcea.ro/alte-informatii-publice/guvernanta-corporativa/"
STORY_ID = "cj-valcea-cocos-rajdp-mandat-guvernanta-20260818"


def story() -> dict:
    headline = "Vasile Cocoș nu mai are mandat de administrator la RAJDP. Pagina de guvernanță a CJ îl afișează încă în Consiliul de Administrație"
    dek = (
        "HCJ 137 din 24 iulie 2026 aprobă încetarea mandatului lui Vasile Cocoș la Drumurile Județene Vâlcea. "
        "În schimb, pagina oficială de guvernanță corporativă a CJ îl menționează încă drept membru CA, o neconcordanță pe care instituția trebuie să o actualizeze sau să o explice."
    )
    claims = [
        {
            "id": "mandate-ended",
            "role": "material_change",
            "kind": "fact",
            "text": (
                "Consiliul Județean Vâlcea a adoptat la 24 iulie 2026 HCJ nr. 137, prin care aprobă încetarea mandatului de administrator "
                "al lui Vasile Cocoș, membru în Consiliul de Administrație al Regiei Autonome Județene de Drumuri și Poduri Vâlcea."
            ),
            "source_urls": [HCJ_2026_URL, CJ_SESSION_URL],
        },
        {
            "id": "appointment-context",
            "role": "who_what_when_where",
            "kind": "documented_context",
            "text": (
                "Titlul actului adoptat arată că Vasile Cocoș fusese numit în această calitate prin HCJ nr. 62 din 25 martie 2025."
            ),
            "source_urls": [HCJ_2026_URL],
        },
        {
            "id": "governance-list",
            "role": "context",
            "kind": "fact",
            "text": (
                "Pe pagina oficială de guvernanță corporativă, Consiliul Județean publică încă o «Listă a administratorilor și directorilor în funcțiune la RAJDP Vâlcea» "
                "în care Vasile Cocoș apare ca membru CA, alături de Dragoș-Aurelian Bitu și Laura-Ștefania Florica."
            ),
            "source_urls": [CJ_GOV_URL],
        },
        {
            "id": "discrepancy",
            "role": "consequence",
            "kind": "reader_service",
            "text": (
                "Cele două suprafețe oficiale ale aceleiași instituții sunt astfel nealiniate: registrul hotărârilor consemnează încetarea mandatului, "
                "iar pagina de guvernanță îl afișează încă în lista persoanelor în funcțiune. Cea mai prudentă explicație este că pagina de prezentare poate fi neactualizată; "
                "documentele consultate nu justifică o altă concluzie."
            ),
            "source_urls": [HCJ_2026_URL, CJ_GOV_URL],
        },
        {
            "id": "reason-unknown",
            "role": "context",
            "kind": "reader_service",
            "text": (
                "Denumirea publică a HCJ 137 confirmă încetarea mandatului, dar nu explică motivul încetării. VÂLCEA CLAR nu atribuie un motiv în lipsa raportului sau a altui document oficial care îl precizează."
            ),
            "source_urls": [HCJ_2026_URL, CJ_SESSION_URL],
        },
        {
            "id": "watch",
            "role": "next_watch",
            "kind": "reader_service",
            "text": (
                "De urmărit sunt actualizarea listei de guvernanță corporativă și orice act ulterior prin care este ocupat locul rămas în Consiliul de Administrație al RAJDP."
            ),
            "source_urls": [HCJ_2026_URL, CJ_GOV_URL],
        },
    ]
    return {
        "id": STORY_ID,
        "status": "verified",
        "section": "ADMINISTRAȚIE",
        "priority": 90,
        "confidence": 98,
        "material_fact_gate": "PASS",
        "editorial_type": "straight_news",
        "valid_from": "2026-08-18T00:00:00+03:00",
        "valid_until": "2026-12-31T23:59:59+02:00",
        "slots": ["morning", "evening"],
        "headline": headline,
        "dek": dek,
        "paragraphs": [],
        "sources": [
            {"name": "Consiliul Județean Vâlcea — registrul HCJ 2026, HCJ 137/24.07.2026", "url": HCJ_2026_URL, "tier": "T1"},
            {"name": "Consiliul Județean Vâlcea — ședința din 24.07.2026", "url": CJ_SESSION_URL, "tier": "T1"},
            {"name": "Consiliul Județean Vâlcea — Guvernanța corporativă", "url": CJ_GOV_URL, "tier": "T1"},
        ],
        "fact_kernel": {
            "format_hint": "straight_news",
            "headline": {"text": headline, "source_urls": [HCJ_2026_URL, CJ_GOV_URL]},
            "dek": {"text": dek, "source_urls": [HCJ_2026_URL, CJ_GOV_URL]},
            "claims": claims,
        },
        "primary_source_verification": {
            "verified_at": "2026-08-18T20:34:00+03:00",
            "source_class": "official_county_council",
            "non_hcl_source_allowed": True,
            "title_date_only": False,
            "cross_surface_discrepancy": True,
            "full_structured_fact_kernel": True,
        },
    }


def upsert(document: dict, item: dict) -> tuple[dict, bool]:
    out = copy.deepcopy(document)
    facts = list(out.get("facts") or [])
    changed = True
    for i, row in enumerate(facts):
        if row.get("id") == item["id"]:
            changed = row != item
            facts[i] = item
            break
    else:
        facts.append(item)
    out["facts"] = facts
    return out, changed


def self_test() -> None:
    item = story()
    assert item["status"] == "verified"
    assert item["material_fact_gate"] == "PASS"
    assert item["fact_kernel"]["format_hint"] == "straight_news"
    assert len(item["sources"]) == 3
    assert all(claim.get("source_urls") for claim in item["fact_kernel"]["claims"])
    assert any(claim["id"] == "reason-unknown" for claim in item["fact_kernel"]["claims"])
    doc, changed = upsert({"facts": []}, item)
    assert changed and doc["facts"][0]["id"] == STORY_ID
    doc2, changed2 = upsert(doc, item)
    assert not changed2 and doc2 == doc
    print("VÂLCEA CLAR primary-source admin kernels self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    document = json.loads(FACTS.read_text(encoding="utf-8"))
    updated, changed = upsert(document, story())
    if args.apply and changed:
        FACTS.write_text(json.dumps(updated, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({"status": "UPDATED" if args.apply and changed else "UNCHANGED" if not changed else "DRY_RUN", "story_id": STORY_ID, "changed": changed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
