#!/usr/bin/env python3
"""Enrich the canonical Râmnicu Vâlcea gambling explainer from a durable dossier.

The Council Fact Kernel remains the authority for the July HCL cluster. This
module runs *after* verified Council kernels are promoted and adds documentary
context that has its own sources: the local 2026 regulation, operator profiles
and ONJN cross-checks. It never converts an annual local authorization into a
claim that a new venue opened, that the annual tax was paid, or that the mayor
issued the final authorization document.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "editorial" / "facts_registry.json"
DOSSIER = ROOT / "editorial" / "gambling_ramnicu_2026_dossier.json"
TARGET_ID = "rm-valcea-gambling-authorizations-20260723"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def add_source(sources: list[dict[str, Any]], name: str, url: str, tier: str) -> None:
    if not url:
        return
    if any(str(row.get("url") or "") == url for row in sources):
        return
    sources.append({"name": name, "url": url, "tier": tier})


def enrich(doc: dict[str, Any], dossier: dict[str, Any]) -> bool:
    target = next((row for row in doc.get("facts") or [] if row.get("id") == TARGET_ID), None)
    if not isinstance(target, dict) or target.get("status") != "verified":
        return False

    sources = [dict(row) for row in target.get("sources") or [] if isinstance(row, dict)]
    regulation = dossier["regulation"]
    add_source(sources, "HCL Râmnicu Vâlcea nr. 142/2026 — regulament jocuri de noroc", regulation["official_pdf"], "T1")
    add_source(sources, "HCL 142/2026 — transcriere documentară", regulation["documentary_mirror"], "T2")

    profile_by_name = {row["legal_name"]: row for row in dossier.get("operator_profiles") or []}
    for profile in profile_by_name.values():
        for source in profile.get("sources") or []:
            add_source(sources, source["name"], source["url"], source["tier"])

    onjn_urls = {
        "superbet-feb": "https://registru.onjn.gov.ro/mijloace-de-joc/1?in_use=1&page=97",
        "superbet-sep": "https://registru.onjn.gov.ro/mijloace-de-joc/1?in_use=1&page=385",
        "cellada": "https://registru.onjn.gov.ro/mijloace-de-joc/1?in_use=1&page=379",
        "cellada-exact": "https://registru.onjn.gov.ro/e/fb6c627f-6940-4f0c-9d44-007e890560e8",
        "baum": "https://registru.onjn.gov.ro/mijloace-de-joc/1?in_use=1&page=102",
        "caradune-historic": "https://registru.onjn.gov.ro/e/9c85be71-ee7e-4fdf-a697-22dad9771d57",
    }
    for key, url in onjn_urls.items():
        add_source(sources, f"ONJN — registrul public al mijloacelor de joc ({key})", url, "T1")

    hcl_urls = [
        str(row.get("url")) for row in sources
        if isinstance(row, dict) and str(row.get("name") or "").startswith("HCL Râmnicu Vâlcea nr.")
        and "142/2026" not in str(row.get("name") or "")
    ]
    if len(hcl_urls) < 11:
        # The original verified Council kernel requires full coverage. If that
        # invariant is no longer true, do not construct richer copy from it.
        return False

    regulation_url = regulation["official_pdf"]
    termene_caradune = "https://termene.ro/firma/43551020-CARADUNE-GAMES-SRL"
    termene_cellada = "https://termene.ro/firma/6627786-CELLADA-SRL"
    termene_baum = "https://termene.ro/firma/4101083-BAUM-SRL"
    baum_official = "https://baumgames.ro/"
    superbet_about = "https://superbet.ro/wiki/despre-noi"
    superbet_group = "https://www.globenewswire.com/news-release/2025/02/11/3024543/0/en/superbet-group-secures-1-3-billion-refinancing.html"

    locations = [row for row in dossier["july_23_cluster"]["known_locations"]]
    location_text = "; ".join(f"HCL {row['decision']}: {row['operator']} — {row['address']}" for row in locations)

    headline = "Jocurile de noroc din Râmnicu Vâlcea: 11 autorizații într-o zi și rețeaua din spatele adreselor"
    dek = (
        "Pe 23 iulie 2026, Consiliul Local a acordat 11 autorizații anuale pentru patru operatori. "
        "VÂLCEA CLAR pune hotărârile în contextul noului regulament local, al taxei de 1.000 lei/mp/an și al registrului ONJN."
    )

    claims = [
        {
            "id": "july-cluster",
            "role": "material_change",
            "kind": "fact",
            "text": (
                "În 23 iulie 2026, 11 hotărâri adoptate de Consiliul Local Râmnicu Vâlcea au acordat autorizații anuale de funcționare pentru activități de jocuri de noroc. "
                "Operatorii nominalizați în această serie sunt CARADUNE GAMES SRL, SUPERBET RETAIL SA, CELLADA SRL și BAUM SRL."
            ),
            "source_urls": hcl_urls,
        },
        {
            "id": "new-local-regime",
            "role": "meaning",
            "kind": "documented_context",
            "text": (
                "Seria din iulie trebuie citită în contextul unui regim local nou. HCL 142 din 19 mai 2026 stabilește că activitatea fizică de jocuri de noroc în municipiu are nevoie de autorizație anuală acordată prin hotărâre a Consiliului Local, distinct de licențierea și autorizarea națională administrate de ONJN."
            ),
            "source_urls": [regulation_url],
        },
        {
            "id": "local-tax",
            "role": "consequence",
            "kind": "reader_service",
            "text": (
                "Regulamentul local fixează taxa anuală la 1.000 lei pentru fiecare metru pătrat de suprafață utilă folosită pentru jocuri de noroc, inclusiv părțile comune utilizate. Plata trebuie făcută în 30 de zile de la hotărârea de acordare, iar neplata atrage retragerea autorizației; documentul emis ulterior de primar este valabil un an de la emitere."
            ),
            "source_urls": [regulation_url],
        },
        {
            "id": "locations",
            "role": "evidence",
            "kind": "fact",
            "text": (
                "Din titlurile și documentele oficiale ale seriei pot fi stabilite, fără a deduce deschiderea unor locații noi, următoarele puncte: "
                + location_text
                + ". Adresa completă aferentă HCL 301 rămâne în dosarul VÂLCEA CLAR pentru extragere deterministă și nu este completată din presupuneri."
            ),
            "source_urls": hcl_urls,
        },
        {
            "id": "onjn-footprint",
            "role": "evidence",
            "kind": "documented_context",
            "text": (
                "Registrul public ONJN arată o amprentă locală mai largă decât cele 11 hotărâri: pentru SUPERBET RETAIL SA apar aparate slot marcate «În exploatare» la Maior V. Popescu 1, I.C. Brătianu 16 și Mihai Eminescu 31; pentru CELLADA/PLAYER apar, între altele, Tineretului 6–8, Nicolae Iorga 1 și Nicolae Bălcescu 1; pentru BAUM apar Republicii 33 și Toamnei 2. Aceste înregistrări ONJN nu sunt confundate cu obiectul fiecărei autorizații locale din 23 iulie."
            ),
            "source_urls": [onjn_urls["superbet-feb"], onjn_urls["superbet-sep"], onjn_urls["cellada"], onjn_urls["cellada-exact"], onjn_urls["baum"]],
        },
        {
            "id": "operator-scale",
            "role": "context",
            "kind": "documented_context",
            "text": (
                "Operatorii nu sunt firme locale mici. Conform bilanțurilor agregate de Termene.ro pentru 2025, CARADUNE GAMES SRL a raportat 57,4 milioane lei cifră de afaceri și 211 angajați, CELLADA SRL 117,5 milioane lei și 236 angajați, iar BAUM SRL 165,3 milioane lei și 281 angajați. BAUM afirmă pe propriul site că deservește peste 750 de locații în România."
            ),
            "source_urls": [termene_caradune, termene_cellada, termene_baum, baum_official],
        },
        {
            "id": "ownership-context",
            "role": "context",
            "kind": "documented_context",
            "text": (
                "Pentru Superbet există un tablou public mai clar la nivel de grup: compania a fost fondată în 2008 de Sacha Dragic, iar Blackstone a făcut în 2019 o investiție strategică minoritară de 175 milioane euro; în 2025 grupul a anunțat o refinanțare de 1,3 miliarde euro cu Blackstone și HPS Investment Partners. Această informație descrie grupul Superbet și nu este prezentată drept extrasul actual al acționariatului juridic al SUPERBET RETAIL SA."
            ),
            "source_urls": [superbet_about, superbet_group],
        },
        {
            "id": "ownership-unknowns",
            "role": "next_watch",
            "kind": "reader_service",
            "text": (
                "Pentru CARADUNE GAMES, CELLADA și BAUM, sursele publice gratuite consultate indică structuri cu unul, opt, respectiv doi asociați, dar nu oferă un suport suficient de solid pentru ca VÂLCEA CLAR să publice acum numele complete ale beneficiarilor sau asociaților. Dosarul rămâne deschis pentru documente ONRC și legături între operatori, proprietarii spațiilor și alte firme."
            ),
            "source_urls": [termene_caradune, termene_cellada, termene_baum],
        },
        {
            "id": "what-hcl-does-not-prove",
            "role": "meaning",
            "kind": "reader_service",
            "text": (
                "O hotărâre de acordare nu dovedește singură că s-a deschis o sală nouă, că taxa locală a fost efectiv plătită sau că primarul a emis deja documentul final al autorizației. Următoarea etapă de verificare este legarea fiecărei adrese de plata taxei, autorizația emisă, istoricul ONJN, proprietarul spațiului și eventualele controale ori sancțiuni."
            ),
            "source_urls": [regulation_url] + hcl_urls,
        },
    ]

    target["section"] = "ADMINISTRAȚIE"
    target["editorial_type"] = "explainer"
    target["priority"] = 97
    target["headline"] = headline
    target["dek"] = dek
    target["paragraphs"] = [row["text"] for row in claims]
    target["sources"] = sources
    target["fact_kernel"] = {
        "format_hint": "explainer",
        "headline": {"text": headline, "source_urls": hcl_urls + [regulation_url]},
        "dek": {"text": dek, "source_urls": hcl_urls + [regulation_url]},
        "claims": claims,
    }
    target["dossier_enrichment"] = {
        "dossier": "editorial/gambling_ramnicu_2026_dossier.json",
        "status": dossier.get("status"),
        "image_status": (dossier.get("image") or {}).get("status"),
        "guards": dossier.get("editorial_guards"),
    }
    return True


def self_test() -> int:
    dossier = load(DOSSIER)
    assert dossier["target_story_id"] == TARGET_ID
    assert dossier["editorial_guards"]["annual_authorization_is_not_new_venue"] is True
    assert len(dossier["july_23_cluster"]["known_locations"]) == 10
    print("VÂLCEA CLAR gambling dossier enricher self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    doc = load(FACTS)
    dossier = load(DOSSIER)
    changed = enrich(doc, dossier)
    if not changed:
        if args.check:
            raise SystemExit("canonical gambling fact unavailable or incomplete")
        print(json.dumps({"status": "NO_CHANGE", "reason": "target_not_verified"}))
        return 0
    if args.check:
        target = next(row for row in doc["facts"] if row.get("id") == TARGET_ID)
        assert len(target["fact_kernel"]["claims"]) >= 9
        assert target["dossier_enrichment"]["guards"]["annual_authorization_is_not_new_venue"] is True
        print(json.dumps({"status": "PASS", "claims": len(target["fact_kernel"]["claims"])}))
        return 0
    FACTS.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "UPDATED", "story_id": TARGET_ID, "claims": 9}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
