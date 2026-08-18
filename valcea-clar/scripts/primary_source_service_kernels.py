#!/usr/bin/env python3
"""Materialize verified non-HCL primary-source service stories for VÂLCEA CLAR.

This bridge is for fully verified primary-source facts that are already specific
enough to publish (AJOFM/ANOFM job offers, utility notices, official service
announcements) and therefore must not wait for a council-decision pipeline.
Every new story uses the canonical claim-level fact-kernel contract and durable
absolute-date copy.
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
BUJORENI_ZIDAR_URL = "https://mediere.anofm.ro/app/module/mediere/job/3301248"

APAVIL_STORY_ID = "apavil-joburi-fara-experienta-20260818"
BUJORENI_STORY_ID = "bujoreni-11-zidari-4582-6000-20260818"


def apavil_story() -> dict:
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
        "id": APAVIL_STORY_ID,
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


def bujoreni_story() -> dict:
    headline = "11 locuri de muncă la Bujoreni pentru zidari: 4.582–6.000 lei brut și bonuri de masă"
    dek = (
        "CAROLIN SRL declară în oferta oficială ANOFM 11 posturi nou create de zidar roșar-tencuitor în Olteni, Bujoreni. "
        "Contractele sunt pe perioadă nedeterminată, iar oferta este valabilă până la 18 decembrie 2026."
    )
    claims = [
        {
            "id": "eleven-jobs",
            "role": "material_change",
            "kind": "fact",
            "text": (
                "Oferta ANOFM cu ID 3301248, publicată de CAROLIN SRL, indică 11 locuri de muncă nou create pentru ocupația "
                "zidar roșar-tencuitor în localitatea Olteni, comuna Bujoreni, județul Vâlcea."
            ),
            "source_urls": [BUJORENI_ZIDAR_URL],
        },
        {
            "id": "apply",
            "role": "reader_action",
            "kind": "reader_service",
            "text": (
                "Oferta este valabilă până la 18 decembrie 2026, selecția este prin interviu, iar ANOFM publică drept contact "
                "Statica Ion, adresa office.carolin@yahoo.ro și numărul de telefon 0744 589 735."
            ),
            "source_urls": [BUJORENI_ZIDAR_URL],
        },
        {
            "id": "salary-contract-location",
            "role": "who_what_when_where",
            "kind": "fact",
            "text": (
                "Salariul declarat este între 4.582 și 6.000 lei brut, cu bonuri de masă. Contractul este pe durată nedeterminată, "
                "cu normă întreagă și muncă la sediu, la Bujoreni – Olteni."
            ),
            "source_urls": [BUJORENI_ZIDAR_URL],
        },
        {
            "id": "requirements",
            "role": "context",
            "kind": "documented_context",
            "text": (
                "Cerința minimă de educație este școala generală, iar oferta solicită experiență medie, între 3 și 5 ani. "
                "Condițiile de muncă menționate sunt lucrul la înălțime și deplasările în țară."
            ),
            "source_urls": [BUJORENI_ZIDAR_URL],
        },
        {
            "id": "watch",
            "role": "next_watch",
            "kind": "reader_service",
            "text": (
                "ANOFM indică 11 poziții disponibile în oferta consultată. VÂLCEA CLAR va actualiza materialul dacă angajatorul sau "
                "platforma oficială modifică numărul de locuri, nivelul salarial ori termenul de valabilitate."
            ),
            "source_urls": [BUJORENI_ZIDAR_URL],
        },
    ]
    return {
        "id": BUJORENI_STORY_ID,
        "status": "verified",
        "section": "LOCURI DE MUNCĂ",
        "priority": 88,
        "confidence": 99,
        "material_fact_gate": "PASS",
        "editorial_type": "service",
        "valid_from": "2026-08-18T00:00:00+03:00",
        "valid_until": "2026-12-18T23:59:59+02:00",
        "slots": ["morning", "evening"],
        "headline": headline,
        "dek": dek,
        "paragraphs": [],
        "sources": [
            {"name": "ANOFM — oferta CAROLIN SRL pentru zidar roșar-tencuitor, ID 3301248", "url": BUJORENI_ZIDAR_URL, "tier": "T1"}
        ],
        "fact_kernel": {
            "format_hint": "service_news",
            "headline": {"text": headline, "source_urls": [BUJORENI_ZIDAR_URL]},
            "dek": {"text": dek, "source_urls": [BUJORENI_ZIDAR_URL]},
            "claims": claims,
        },
        "primary_source_verification": {
            "verified_at": "2026-08-18T20:30:00+03:00",
            "source_class": "official_employment_service",
            "non_hcl_source_allowed": True,
            "title_date_only": False,
            "full_structured_fact_kernel": True,
        },
    }


def stories() -> list[dict]:
    return [apavil_story(), bujoreni_story()]


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


def upsert_all(document: dict, items: list[dict]) -> tuple[dict, list[str]]:
    out = document
    changed_ids: list[str] = []
    for item in items:
        out, changed = upsert(out, item)
        if changed:
            changed_ids.append(item["id"])
    return out, changed_ids


def self_test() -> None:
    items = stories()
    assert {item["id"] for item in items} == {APAVIL_STORY_ID, BUJORENI_STORY_ID}
    for item in items:
        assert item["status"] == "verified"
        assert item["material_fact_gate"] == "PASS"
        assert item["editorial_type"] == "service"
        assert len(item["fact_kernel"]["claims"]) >= 2
        assert all(claim.get("source_urls") for claim in item["fact_kernel"]["claims"])
    assert {src["url"] for src in items[0]["sources"]} == {LAB_URL, ELEC_URL}
    assert items[1]["sources"][0]["url"] == BUJORENI_ZIDAR_URL
    doc, changed_ids = upsert_all({"facts": []}, items)
    assert set(changed_ids) == {APAVIL_STORY_ID, BUJORENI_STORY_ID}
    doc2, changed_ids2 = upsert_all(doc, items)
    assert not changed_ids2 and doc2 == doc
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
    updated, changed_ids = upsert_all(document, stories())
    if args.apply and changed_ids:
        FACTS.write_text(json.dumps(updated, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    status = "UPDATED" if args.apply and changed_ids else "UNCHANGED" if not changed_ids else "DRY_RUN"
    print(json.dumps({"status": status, "story_ids": changed_ids, "changed": bool(changed_ids)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
