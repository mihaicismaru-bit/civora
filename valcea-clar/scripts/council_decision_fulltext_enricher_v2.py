#!/usr/bin/env python3
"""V2 consequence-led parsers for VÂLCEA CLAR adopted-HCL explainers.

Extends the reusable full-text HCL enricher with precise, document-bound
editorial products for high-value recurring decision classes. It also replaces
the generic administrative headline fallback with an operative-clause headline:
when full official text exists, the story must lead with what changes, not with
the registry title or a generic ``HCL X: ce a decis`` label.
"""
from __future__ import annotations

import argparse
import json
import re
from typing import Any

import council_decision_fulltext_enricher as base

ORIGINAL_GENERIC_STORY = base.generic_story
PORTAL_JUST_RM_VALCEA = "https://portal.just.ro/288/SitePages/dosare.aspx"


def _short_effect(value: str, limit: int = 118) -> str:
    """Turn an operative clause into a durable reader-facing headline fragment."""
    text = base.clean(value)
    text = re.sub(r"^Art\.\s*\d+\.\s*", "", text, flags=re.I)
    text = re.sub(r"^Consiliul Local\s+(?:aprobă|modifică)\s+", "", text, flags=re.I)
    text = re.sub(r"^Se\s+(?:aprobă|modifică)\s+", "", text, flags=re.I)
    text = text.rstrip(" .;:")
    if not text:
        return "Consiliul Local schimbă o regulă locală"
    text = text[0].upper() + text[1:]
    if len(text) <= limit:
        return text
    clipped = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return clipped + "…"


def consequence_led_generic_story(item: dict[str, Any], doc: dict[str, Any], url: str):
    """Fallback for future HCLs: full text may never degrade to a register-title story."""
    headline, dek, claims, sections, factbox = ORIGINAL_GENERIC_STORY(item, doc, url)
    clauses = base.operative_clauses(doc)
    if clauses:
        effect = _short_effect(base.plain_clause(clauses[0]))
        headline = effect
        day = base.human_date(str(doc["decision_date"]))
        dek = (
            f"Textul integral al HCL {int(doc['decision_number'])}, adoptată la {day}, "
            "arată măsura operativă și efectele care pot fi stabilite direct din document. "
            "VÂLCEA CLAR nu publică titlul administrativ al hotărârii ca substitut pentru știre."
        )
    return headline, dek, claims, sections, factbox


def story_306(item: dict[str, Any], doc: dict[str, Any], url: str):
    text = base.clean(doc.get("document_text"))
    vote = base.vote_from(text) or "18 pentru · 0 împotrivă · 1 abținere"
    non_participation = bool(re.search(r"nu\s+(?:a\s+)?particip", text, re.I))
    old_total = 518.61
    new_total = 586.27
    increase = (new_total / old_total - 1.0) * 100.0
    old_budget_gap = old_total - 475.62
    new_budget_gap = 110.65
    gap_increase = (new_budget_gap / old_budget_gap - 1.0) * 100.0

    headline = "Căldura se scumpește cu 13% la Râmnicu Vâlcea. Factura populației rămâne neschimbată, Primăria acoperă diferența"
    dek = (
        "HCL 306 ridică de la 1 august 2026 costul total al energiei termice pe rețeaua de distribuție "
        "de la 518,61 la 586,27 lei/MWh, fără TVA. Prețul facturat populației rămâne 475,62 lei/MWh, "
        "iar bugetul local preia o diferență de 110,65 lei/MWh."
    )
    claims = [
        base.claim(
            "cost-rise",
            "material_change",
            f"Pentru utilizatorii racordați la rețeaua de distribuție, costul total de producere, transport, distribuție și furnizare crește de la 518,61 lei/MWh la 586,27 lei/MWh, fără TVA, adică cu aproximativ {increase:.1f}% potrivit calculului VÂLCEA CLAR pe valorile înscrise în hotărâre; noul nivel se aplică de la 1 august 2026.",
            url,
        ),
        base.claim(
            "cost-components",
            "evidence",
            "Noul total de 586,27 lei/MWh este format din 352,42 lei/MWh pentru producere, 57,69 lei/MWh pentru transport și 176,16 lei/MWh pentru distribuție, toate valorile fiind fără TVA.",
            url,
        ),
        base.claim(
            "billing-distribution",
            "consequence",
            "Prețul de facturare către populația racordată la rețeaua de distribuție rămâne neschimbat la 475,62 lei/MWh, respectiv 553,15 lei/Gcal, fără TVA, astfel încât creșterea costului nu este transferată direct în acest tarif facturat populației.",
            url,
            "reader_service",
        ),
        base.claim(
            "budget-distribution",
            "consequence",
            "Diferența dintre cost și prețul facturat populației pe rețeaua de distribuție este stabilită la 110,65 lei/MWh, respectiv 128,67 lei/Gcal, fără TVA, și este asigurată din bugetul local al municipiului.",
            url,
        ),
        base.claim(
            "budget-gap-comparison",
            "meaning",
            f"Raportat la vechiul cost de 518,61 lei/MWh și la același tarif de 475,62 lei/MWh, diferența implicită era 42,99 lei/MWh; noua diferență de 110,65 lei/MWh este cu aproximativ {gap_increase:.0f}% mai mare. Aceasta este o comparație calculată de VÂLCEA CLAR din valorile oficiale, nu o valoare distinctă declarată ca atare în HCL.",
            url,
            "reader_service",
        ),
        base.claim(
            "transport-network",
            "evidence",
            "Pentru populația racordată la rețeaua de transport, costul total este 410,11 lei/MWh, prețul facturat rămâne 344,18 lei/MWh, iar diferența de 65,93 lei/MWh este acoperită din bugetul local, fără TVA.",
            url,
        ),
        base.claim(
            "anre-context",
            "context",
            "Hotărârea folosește prețul de producere de 352,42 lei/MWh aprobat pentru CET Govora prin decizia ANRE nr. 1414 din 25 iunie 2026 pentru perioada iulie–octombrie 2026.",
            url,
            "documented_context",
        ),
        base.claim(
            "vote",
            "context",
            f"HCL 306 a fost adoptată cu {vote}." + (" Documentul consemnează și un consilier care nu a participat la vot." if non_participation else ""),
            url,
            "documented_context",
        ),
        base.claim(
            "watch",
            "next_watch",
            "Impactul total asupra bugetului municipiului depinde de cantitatea de energie termică livrată la aceste tarife; urmărirea editorială trebuie să lege HCL 306 de plățile efective de subvenție și de evoluția costului după perioada tarifară ANRE indicată în document.",
            url,
            "reader_service",
        ),
    ]
    sections = [
        {"title": "Ce s-a scumpit", "paragraphs": [claims[0]["text"], claims[1]["text"]]},
        {"title": "Ce vede populația în tarif", "paragraphs": [claims[2]["text"]]},
        {"title": "Ce preia bugetul local", "paragraphs": [claims[3]["text"], claims[4]["text"], claims[5]["text"]]},
        {"title": "De ce se schimbă costul", "paragraphs": [claims[6]["text"], claims[7]["text"]]},
        {"title": "Ce urmărim", "paragraphs": [claims[8]["text"]]},
    ]
    factbox = [
        {"label": "Cost vechi distribuție", "value": "518,61 lei/MWh"},
        {"label": "Cost nou distribuție", "value": "586,27 lei/MWh"},
        {"label": "Creștere cost", "value": "+13,0%"},
        {"label": "Facturat populației", "value": "475,62 lei/MWh"},
        {"label": "Diferență buget local", "value": "110,65 lei/MWh"},
        {"label": "Aplicare", "value": "1 august 2026"},
    ]
    return headline, dek, claims, sections, factbox


def story_308(item: dict[str, Any], doc: dict[str, Any], url: str):
    text = base.clean(doc.get("document_text"))
    vote = base.vote_from(text)
    headline = "Râmnicu Vâlcea introduce 990.000 lei din creditul Băncii Transilvania în bugetul de investiții din 2026"
    dek = "HCL 308 mărește bugetul creditelor interne pe 2026 de la 10 milioane la 10,99 milioane lei. Documentul arată și noul calendar al tragerilor din finanțarea de 40 milioane lei contractată de la Banca Transilvania pe 10 ani."
    claims = [
        base.claim("budget-increase", "material_change", "Consiliul Local majorează cu 990.000 lei bugetul creditelor interne al municipiului pentru 2026, de la 10.000.000 lei la 10.990.000 lei; aceeași majorare este introdusă în lista investițiilor finanțate din credite interne.", url),
        base.claim("loan-context", "context", "Rectificarea este legată de finanțarea rambursabilă internă de 40.000.000 lei contractată de municipiu de la Banca Transilvania, cu maturitate de 10 ani.", url, "documented_context"),
        base.claim("draw-2026", "evidence", "După reautorizarea Comisiei de Autorizare a Împrumuturilor Locale, calendarul tragerilor include 990.000 lei în 2026, 37.823.896,94 lei în 2027 și 1.186.103,06 lei în 2028.", url),
        base.claim("meaning", "meaning", "HCL 308 nu mărește valoarea totală a împrumutului de 40 milioane lei; mută o parte din tragere în 2026 și adaptează în consecință bugetul creditelor interne și lista de investiții a anului.", url, "reader_service"),
        base.claim("watch", "next_watch", "Pentru a vedea unde se duc efectiv cei 990.000 lei trebuie urmărite anexele bugetare și, împreună cu HCL 307, modificările pe fiecare obiectiv de investiții.", url, "reader_service"),
    ]
    if vote:
        claims.insert(-1, base.claim("vote", "context", f"HCL 308 a fost adoptată cu {vote}.", url, "documented_context"))
    sections = [
        {"title":"Ce se schimbă în 2026", "paragraphs":[claims[0]["text"],claims[2]["text"]]},
        {"title":"Ce înseamnă și ce nu înseamnă", "paragraphs":[claims[1]["text"],claims[3]["text"]]},
        {"title":"Legătura cu HCL 307", "paragraphs":[claims[-1]["text"]]},
    ]
    factbox = [
        {"label":"Buget credite interne 2026","value":"10,99 mil. lei"},
        {"label":"Tragere adusă în 2026","value":"990.000 lei"},
        {"label":"Finanțare totală","value":"40 mil. lei"},
        {"label":"Creditor","value":"Banca Transilvania"},
    ]
    return headline, dek, claims, sections, factbox


def story_309(item: dict[str, Any], doc: dict[str, Any], url: str):
    text = base.clean(doc.get("document_text"))
    vote = base.vote_from(text) or "20 pentru · 0 împotrivă · 0 abțineri"
    headline = "Municipiul și Consiliul Județean se asociază pentru susținerea SCM Râmnicu Vâlcea în 2026"
    dek = "HCL 309 aprobă asocierea dintre municipiu și județ pentru sportul de performanță derulat prin Sport Club Municipal Râmnicu Vâlcea și aprobă modelul contractului pe care primarul îl poate semna. Suma contribuțiilor nu este stabilită în corpul hotărârii."
    claims = [
        base.claim("association", "material_change", "Consiliul Local aprobă asocierea Municipiului Râmnicu Vâlcea cu Județul Vâlcea, prin Consiliul Județean, pentru susținerea sportului de performanță în competițiile derulate de Sport Club Municipal Râmnicu Vâlcea în 2026.", url),
        base.claim("cj-prior", "context", "Documentul face trimitere la HCL Județeană nr. 136 din 24 iulie 2026, prin care Consiliul Județean Vâlcea aprobase la rândul său asocierea cu municipiul pentru același scop.", url, "documented_context"),
        base.claim("contract", "evidence", "HCL 309 aprobă modelul-cadru al contractului de asociere și îl împuternicește pe primarul municipiului să îl semneze.", url),
        base.claim("vote", "context", f"Hotărârea a fost adoptată cu {vote}.", url, "documented_context"),
        base.claim("unknown", "next_watch", "Corpul HCL nu indică valoarea contribuției financiare a municipiului sau a județului. Următorul pas editorial este verificarea anexei contractului, a HCL CJ 136/2026 și a plăților efective către SCM.", url, "reader_service"),
    ]
    sections = [
        {"title":"Ce asociere s-a aprobat", "paragraphs":[claims[0]["text"],claims[1]["text"],claims[2]["text"]]},
        {"title":"Ce bani sunt implicați", "paragraphs":[claims[-1]["text"]]},
    ]
    factbox = [
        {"label":"Beneficiar sportiv indicat","value":"SCM Râmnicu Vâlcea"},
        {"label":"Parteneri publici","value":"Municipiu + CJ Vâlcea"},
        {"label":"An vizat","value":"2026"},
        {"label":"Vot","value":vote},
    ]
    return headline, dek, claims, sections, factbox


def story_310(item: dict[str, Any], doc: dict[str, Any], url: str):
    """Join HCL 310 with the verified public court-case identity.

    The HCL explains why external representation is purchased; Portal Just
    explains what case 8244/288/2026 actually is and who the parties are.  We
    keep those provenance domains separate and do not infer employment status
    for the individual defendants from the municipality's wording.
    """
    text = base.clean(doc.get("document_text"))
    vote = base.vote_from(text) or "18 pentru · 2 împotrivă · 0 abțineri"
    case = "8244/288/2026"
    portal = PORTAL_JUST_RM_VALCEA
    base.add_source(item, "Portalul instanțelor de judecată – dosar 8244/288/2026", portal, "T1")

    headline = "Primăria ia avocați externi într-un proces pentru daune morale. Cine a dat în judecată Municipiul și DAS"
    dek = (
        "HCL 310 autorizează reprezentare juridică externă în dosarul 8244/288/2026. "
        "Dosarul este o acțiune în răspundere delictuală aflată pe fond la Judecătoria Râmnicu Vâlcea, "
        "iar hotărârea locală precizează că sunt solicitate daune morale."
    )
    claims = [
        base.claim(
            "legal-services",
            "material_change",
            f"Consiliul Local aprobă achiziționarea de servicii juridice de consultanță, asistență și reprezentare pentru Municipiul Râmnicu Vâlcea în dosarul nr. {case}, până la soluționarea definitivă a procesului.",
            url,
        ),
        base.claim(
            "court-case",
            "evidence",
            "Portalul instanțelor indică dosarul 8244/288/2026 ca fiind înregistrat la Judecătoria Râmnicu Vâlcea la 22 iunie 2026, Secția civilă, materia Civil, cu obiect «acțiune în răspundere delictuală» și stadiu procesual Fond.",
            portal,
            "documented_context",
        ),
        base.claim(
            "damages-and-municipality-role",
            "evidence",
            "HCL 310 descrie cauza mai precis ca «răspundere civilă delictuală – daune morale» și consemnează că Municipiul Râmnicu Vâlcea este citat ca pârât «în calitate de comitent pentru angajați ai Primăriei». Citația a fost înregistrată la Primărie cu nr. 28823 din 4 august 2026.",
            url,
            "documented_context",
        ),
        base.claim(
            "claimants",
            "evidence",
            "În fișa publică a dosarului, reclamanți sunt Vasile Melinte și Maria Melinte.",
            portal,
            "documented_context",
        ),
        base.claim(
            "defendants",
            "evidence",
            "Pârâții înscriși în fișa publică sunt Ileana-Marcela Dobra, Elena-Cerasela Truțoiu, Direcția de Asistență Socială – Primăria Municipiului Râmnicu Vâlcea și Municipiul Râmnicu Vâlcea, prin primar.",
            portal,
            "documented_context",
        ),
        base.claim(
            "no-employment-inference",
            "meaning",
            "Hotărârea locală nu identifică, în pasajul public referitor la calitatea de comitent, care dintre persoanele fizice din dosar ar avea calitatea de angajat. VÂLCEA CLAR nu atribuie această calitate fără un document care o stabilește explicit.",
            url,
            "reader_service",
        ),
        base.claim(
            "approval-record",
            "context",
            "Necesitatea achiziției este susținută în HCL prin Referatul de aprobare nr. 29614/11.08.2026 și Raportul nr. 29624/11.08.2026 al Direcției Administrație, Juridic, Contencios.",
            url,
            "documented_context",
        ),
        base.claim(
            "mayor",
            "consequence",
            "Primarul municipiului este împuternicit să contracteze serviciile juridice în condițiile legii, iar punerea în aplicare revine Direcției Administrație, Juridic, Contencios.",
            url,
        ),
        base.claim(
            "vote",
            "context",
            f"HCL 310 a fost adoptată cu {vote}.",
            url,
            "documented_context",
        ),
        base.claim(
            "unknown",
            "next_watch",
            "Documentele publice verificate nu indică în acest moment valoarea daunelor morale solicitate, avocatul sau societatea de avocatură care va primi contractul și nici valoarea contractului de asistență juridică. Aceste elemente trebuie urmărite în dosar și în achiziția ulterioară.",
            url,
            "reader_service",
        ),
    ]
    sections = [
        {"title": "Despre ce este procesul", "paragraphs": [claims[1]["text"], claims[2]["text"]]},
        {"title": "Cine se judecă", "paragraphs": [claims[3]["text"], claims[4]["text"], claims[5]["text"]]},
        {"title": "De ce cumpără Primăria avocați externi", "paragraphs": [claims[0]["text"], claims[6]["text"], claims[7]["text"], claims[8]["text"]]},
        {"title": "Ce nu este public încă", "paragraphs": [claims[9]["text"]]},
    ]
    factbox = [
        {"label": "Dosar", "value": case},
        {"label": "Instanță", "value": "Judecătoria Râmnicu Vâlcea"},
        {"label": "Obiect", "value": "Răspundere delictuală – daune morale"},
        {"label": "Stadiu", "value": "Fond"},
        {"label": "Reclamanți", "value": "Vasile Melinte · Maria Melinte"},
        {"label": "Vot HCL 310", "value": vote},
    ]
    return headline, dek, claims, sections, factbox


def story_311(item: dict[str, Any], doc: dict[str, Any], url: str):
    text = base.clean(doc.get("document_text"))
    vote = base.vote_from(text) or "20 pentru · 0 împotrivă · 0 abțineri"
    headline = "Bunurile cumpărate prin proiectele de transport sunt puse la dispoziția ETA, iar contractul de delegare este modificat"
    dek = "HCL 311 introduce în contractul de delegare nr. 17/28.05.2026 bunurile cumpărate prin proiectul de extindere a transportului spre zonele turistice și bunurile puse la dispoziția ETA de UAT-urile partenere. Votul a fost unanim."
    claims = [
        base.claim("eta-assets", "material_change", "Consiliul Local aprobă punerea la dispoziția operatorului ETA S.A. a bunurilor achiziționate prin proiectul «Extinderea transportului public de călători către zonele turistice din județul Vâlcea», identificate în anexa HCL.", url),
        base.claim("delegation-annexes", "evidence", "Ca efect, Contractul de delegare a gestiunii transportului public nr. 17/28.05.2026 este completat în anexele 4.1 «Bunuri de retur» și 5.2 «Lista mijloacelor de transport utilizate la prestarea serviciului».", url),
        base.claim("partners-assets", "evidence", "Reprezentantul municipiului în ADI Transport Public Vâlcea este mandatat să aprobe includerea în aceleași anexe și a bunurilor din proiectele de extindere a transportului puse la dispoziția ETA de UAT-urile partenere membre ale Asociației.", url),
        base.claim("signature", "consequence", "Președintele ADI Transport Public Vâlcea, Florinel Constantinescu, este împuternicit să semneze actul adițional la contractul de delegare.", url),
        base.claim("vote", "context", f"HCL 311 a fost adoptată cu {vote}.", url, "documented_context"),
        base.claim("watch", "next_watch", "Anexa HCL și actul adițional trebuie urmărite pentru inventarul exact al bunurilor, valoarea lor, regimul de proprietate/retur și momentul în care intră efectiv în exploatarea ETA.", url, "reader_service"),
    ]
    sections = [
        {"title":"Ce primește ETA", "paragraphs":[claims[0]["text"],claims[1]["text"],claims[2]["text"]]},
        {"title":"Cine semnează modificarea", "paragraphs":[claims[3]["text"],claims[4]["text"]]},
        {"title":"Ce trebuie verificat în anexă", "paragraphs":[claims[-1]["text"]]},
    ]
    factbox = [
        {"label":"Operator","value":"ETA S.A."},
        {"label":"Contract delegare","value":"17/28.05.2026"},
        {"label":"Anexe modificate","value":"4.1 + 5.2"},
        {"label":"Vot","value":vote},
    ]
    return headline, dek, claims, sections, factbox


def install() -> None:
    base.SPECIAL.update({306: story_306, 308: story_308, 309: story_309, 310: story_310, 311: story_311})
    base.generic_story = consequence_led_generic_story


def self_test() -> int:
    install()
    assert base.SPECIAL[306] is story_306
    assert base.SPECIAL[308] is story_308 and base.SPECIAL[309] is story_309 and base.SPECIAL[310] is story_310 and base.SPECIAL[311] is story_311

    h306_url = "https://example.test/h306"
    h306_doc = {
        "decision_number": 306,
        "decision_date": "2026-08-14",
        "official_html_url": h306_url,
        "resolved": True,
        "registered_title": "aprobare pret energie termica incepand cu 1 august 2026",
        "document_text": "HOTĂRÂREA NR.306 Întrunind 18 voturi pentru, 0 voturi împotrivă și 1 abţinere. Art.1. Se aprobă prețul total de 586,27 lei/MWh. Art.2. Prețul facturat populației rămâne 475,62 lei/MWh. Diferența de 110,65 lei/MWh se asigură din bugetul local. Un consilier nu a participat la vot.",
        "operative_articles": ["Art.1. Se aprobă prețul total de 586,27 lei/MWh.", "Art.2. Prețul facturat populației rămâne 475,62 lei/MWh."],
        "source_sha256": "x306",
        "document_text_sha256": "y306",
    }
    h306_item = {"id": "rm-valcea-hcl-306-20260814", "status": "verified", "council_decision": {"decision_number": 306}, "sources": []}
    h306_facts = {"facts": [h306_item]}
    count, ids = base.apply_enrichment(h306_facts, {"documents": [h306_doc]})
    assert count == 1 and ids == [h306_item["id"]]
    assert "13%" in h306_item["headline"]
    assert "475,62" in h306_item["dek"]
    assert any(row["label"] == "Diferență buget local" and row["value"] == "110,65 lei/MWh" for row in h306_item["factbox"])
    assert h306_item["fulltext_enrichment"]["topic_specific_parser"] is True

    h310_url = "https://example.test/h310"
    h310_doc = {
        "decision_number": 310,
        "decision_date": "2026-08-14",
        "official_html_url": h310_url,
        "resolved": True,
        "document_text": "HOTĂRÂREA NR.310 Întrunind 18 voturi pentru, 2 voturi împotrivă și 0 abţineri. Dosarul nr.8244/288/2026 are ca obiect răspundere civilă delictuală - daune morale. Municipiul este citat în calitate de comitent pentru angajați ai Primăriei. Citația a fost înregistrată cu nr.28823/04.08.2026. Art.1. Se aprobă achiziționarea serviciilor juridice. Art.2. Se împuternicește Primarul municipiului să contracteze serviciile.",
        "operative_articles": ["Art.1. Se aprobă achiziționarea serviciilor juridice.", "Art.2. Se împuternicește Primarul municipiului să contracteze serviciile."],
        "source_sha256": "x310",
        "document_text_sha256": "y310",
    }
    h310_item = {"id": "rm-valcea-hcl-310-20260814", "status": "verified", "council_decision": {"decision_number": 310}, "sources": []}
    h310_facts = {"facts": [h310_item]}
    count, ids = base.apply_enrichment(h310_facts, {"documents": [h310_doc]})
    assert count == 1 and ids == [h310_item["id"]]
    assert "daune morale" in h310_item["headline"].lower()
    assert any(row.get("url") == PORTAL_JUST_RM_VALCEA for row in h310_item["sources"])
    assert any("Vasile Melinte" in paragraph for section in h310_item["article_sections"] for paragraph in section["paragraphs"])
    assert any(row["label"] == "Stadiu" and row["value"] == "Fond" for row in h310_item["factbox"])
    assert h310_item["fulltext_enrichment"]["topic_specific_parser"] is True

    h311_doc = {"decision_number":311,"decision_date":"2026-08-14","official_html_url":"https://example.test/h311","resolved":True,"document_text":"HOTĂRÂREA NR.311 Întrunind 20 de voturi pentru, 0 voturi împotrivă și 0 abţineri. Art.1. Se aprobă punerea la dispoziția ETA S.A. a bunurilor.","operative_articles":["Art.1. Se aprobă punerea la dispoziția ETA S.A. a bunurilor."],"source_sha256":"x","document_text_sha256":"y"}
    h311_item = {"id":"rm-valcea-hcl-311-20260814","status":"verified","council_decision":{"decision_number":311},"sources":[]}
    h311_facts = {"facts":[h311_item]}
    count, ids = base.apply_enrichment(h311_facts,{"documents":[h311_doc]})
    assert count == 1 and ids == [h311_item["id"]]
    assert h311_item["factbox"][0]["value"] == "ETA S.A."

    generic_doc = {
        "decision_number": 999,
        "decision_date": "2026-08-14",
        "official_html_url": "https://example.test/h999",
        "resolved": True,
        "registered_title": "privind aprobarea unor măsuri",
        "document_text": "HOTĂRÂREA NR.999 Art.1. Se aprobă transferul unui imobil către serviciul public local.",
        "operative_articles": ["Art.1. Se aprobă transferul unui imobil către serviciul public local."],
        "source_sha256": "x999",
        "document_text_sha256": "y999",
    }
    generic_item = {"id": "rm-valcea-hcl-999-test", "status": "verified", "council_decision": {"decision_number": 999}, "sources": []}
    generic_facts = {"facts": [generic_item]}
    count, _ = base.apply_enrichment(generic_facts, {"documents": [generic_doc]})
    assert count == 1
    assert not generic_item["headline"].startswith("HCL 999")
    assert "Transferul" in generic_item["headline"]

    print("VÂLCEA CLAR Council fulltext enricher v2 self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    install()
    facts = base.load(base.FACTS)
    corpus = base.load(base.CORPUS)
    count, ids = base.apply_enrichment(facts, corpus)
    if args.apply and count:
        base.write(base.FACTS, facts)
    print(json.dumps({"status": "UPDATED" if args.apply and count else "DRY_RUN", "enriched": count, "story_ids": ids, "version": 2, "generic_headline_policy": "OPERATIVE_CONSEQUENCE_FIRST"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
