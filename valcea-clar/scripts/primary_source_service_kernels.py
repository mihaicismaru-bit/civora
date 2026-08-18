#!/usr/bin/env python3
"""Materialize verified non-HCL primary-source service stories for VÂLCEA CLAR.

This bridge exists for fully verified primary-source facts that are already
specific enough to publish (AJOFM/ANOFM job offers, utility notices, official
service announcements) and therefore must not wait for a council-decision
pipeline. New stories use the canonical claim-level fact-kernel contract.

The current seed is built only from the two official ANOFM job-offer pages for
APAVIL SA verified on 18 August 2026. Durable copy uses absolute dates.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "editorial" / "facts_registry.json"

LAB_URL = "https://mediere.anofm.ro/app/module/mediere/job/3315405"
ELEC_URL = "https://mediere.anofm.ro/app/module/mediere/job/3318496"
STORY_ID = "apavil-joburi-fara-experienta-20260818"


def story() -> dict:
    headline = "APAVIL scoate la concurs două posturi fără experiență: laborant în Râmnicu Vâlcea și electrician în Călimănești"
    dek = (
        "Cele două oferte oficiale ANOFM sunt pentru contracte pe perioadă nedeterminată și normă întreagă. "
        "Termenele de valabilitate sunt 20 august 2026 pentru laborant și 21 august 2026 pentru electrician."
    )
    claims = [
        {
            "id": "two-jobs",
            "role": "material_change",
            "kind": "fact",
            "text": (
                "APAVIL SA are două oferte distincte publicate în platforma oficială de mediere ANOFM: un post de laborant chimist "
                "în municipiul Râmnicu Vâlcea și un post de electrician de întreținere și reparații în orașul Călimănești."
            ),
            "source_urls": [LAB_URL, ELEC_URL],
        },
        {
            "id": "lab-action",
            "role": "reader_action",
            "kind": "reader_service",
            "text": (
                "Oferta pentru laborant chimist este valabilă până la 20 august 2026, iar selecția este prin concurs; ANOFM indică "
                "drept contact resurse.umane@apavil.ro și numărul 0350 802 161."
            ),
            "source_urls": [LAB_URL],
        },
        {
            "id": "electrician-action",
            "role": "reader_action",
            "kind": "reader_service",
            "text": (
                "Oferta pentru electrician este valabilă până la 21 august 2026 și prevede tot selecție prin concurs; pagina ANOFM "
                "indică aceeași adresă de resurse umane și același număr de telefon al angajatorului."
            ),
            "source_urls": [ELEC_URL],
        },
        {
            "id": "lab-details",
            "role": "who_what_when_where",
            "kind": "fact",
            "text": (
                "Pentru laborant chimist, locul de muncă este la Râmnicu Vâlcea, Strada Câmpului nr. 17. Oferta cere studii liceale "
                "de specialitate, nu cere experiență profesională și prevede contract cu durată nedeterminată, cu normă întreagă."
            ),
            "source_urls": [LAB_URL],
        },
        {
            "id": "electrician-details",
            "role": "who_what_when_where",
            "kind": "fact",
            "text": (
                "Pentru electrician de întreținere și reparații, locul de muncă este în Călimănești, Calea lui Traian nr. 288A. Oferta "
                "cere școală profesională, nu cere experiență și prevede contract cu durată nedeterminată, normă întreagă și muncă la sediu."
            ),
            "source_urls": [ELEC_URL],
        },
        {
            "id": "publication-dates",
            "role": "context",
            "kind": "documented_context",
            "text": (
                "Oferta pentru laborant a fost publicată de ANOFM la 2 iulie 2026, iar cea pentru electrician la 6 iulie 2026. "
                "Fiecare ofertă indică un singur loc vacant și zero locuri nou create."
            ),
            "source_urls": [LAB_URL, ELEC_URL],
        },
        {
            "id": "salary-unknown",
            "role": "next_watch",
            "kind": "reader_service",
            "text": (
                "Paginile publice ANOFM consultate nu afișează în câmpurile vizibile o valoare salarială; VÂLCEA CLAR nu completează "
                "salariul din presupuneri și va actualiza materialul numai dacă apare o sursă oficială verificabilă."
            ),
            "source_urls": [LAB_URL, ELEC_URL],
        },
    ]
    return {
        "id": STORY_ID,
        "status": "verified",
        "section": "LOCURI DE MUNCĂ",
        "priority": 91,
        "confidence": 99,
        "material_fact_gate": "PASS",
        "editorial_type": "service",
        "valid_from": "2026-08-18T00:00:00+03:00",
        "valid_until": "2026-12-31T23:59:59+02:00",
        "slots": ["morning", "evening"],
        "headline": headline,
        "dek": dek,
        "paragraphs": [],
        "sources": [
            {"name": "ANOFM — oferta APAVIL SA pentru laborant chimist, ID 3315405", "url": LAB_URL, "tier": "T1"},
            {"name": "ANOFM — oferta APAVIL SA pentru electrician, ID 3318496", "url": ELEC_URL, "tier": "T1"},
        ],
        "fact_kernel": {
            "format_hint": "service_news",
            "headline": {"text": headline, "source_urls": [LAB_URL, ELEC_URL]},
            "dek": {"text": dek, "source_urls": [LAB_URL, ELEC_URL]},
            "claims": claims,
        },
        "primary_source_verification": {
            "verified_at": "2026-08-18T20:20:00+03:00",
            "source_class": "official_employment_service",
            "non_hcl_source_allowed": True,
            "title_date_only": False,
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
    assert item["editorial_type"] == "service"
    assert len(item["fact_kernel"]["claims"]) >= 2
    assert {src["url"] for src in item["sources"]} == {LAB_URL, ELEC_URL}
    assert all(claim.get("source_urls") for claim in item["fact_kernel"]["claims"])
    doc, changed = upsert({"facts": []}, item)
    assert changed and doc["facts"][0]["id"] == STORY_ID
    doc2, changed2 = upsert(doc, item)
    assert not changed2 and doc2 == doc
    print("VÂLCEA CLAR primary-source service kernels self-test: PASS")


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
