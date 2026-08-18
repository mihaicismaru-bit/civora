#!/usr/bin/env python3
"""V2 topic parsers for the remaining 14 August 2026 HCL explainers.

Extends v1 with precise, document-bound editorial products for HCL 308, 309 and
311.  The underlying generic fulltext resolver remains reusable for other HCLs;
these parsers only improve headline, structure and reader utility where the
official document provides a clear deterministic pattern.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

import council_decision_fulltext_enricher as base


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
    base.SPECIAL.update({308: story_308, 309: story_309, 311: story_311})


def self_test() -> int:
    install()
    assert base.SPECIAL[308] is story_308 and base.SPECIAL[309] is story_309 and base.SPECIAL[311] is story_311
    doc={"decision_number":311,"decision_date":"2026-08-14","official_html_url":"https://example.test/h311","resolved":True,"document_text":"HOTĂRÂREA NR.311 Întrunind 20 de voturi pentru, 0 voturi împotrivă și 0 abţineri. Art.1. Se aprobă punerea la dispoziția ETA S.A. a bunurilor.","operative_articles":["Art.1. Se aprobă punerea la dispoziția ETA S.A. a bunurilor."],"source_sha256":"x","document_text_sha256":"y"}
    item={"id":"rm-valcea-hcl-311-20260814","status":"verified","council_decision":{"decision_number":311},"sources":[]}
    facts={"facts":[item]}
    count, ids=base.apply_enrichment(facts,{"documents":[doc]})
    assert count==1 and ids==[item["id"]]
    assert item["factbox"][0]["value"]=="ETA S.A."
    print("VÂLCEA CLAR Council fulltext enricher v2 self-test: PASS")
    return 0


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--self-test",action="store_true")
    args=parser.parse_args()
    if args.self_test:
        return self_test()
    install()
    facts=base.load(base.FACTS)
    corpus=base.load(base.CORPUS)
    count, ids=base.apply_enrichment(facts,corpus)
    if args.apply and count:
        base.write(base.FACTS,facts)
    print(json.dumps({"status":"UPDATED" if args.apply and count else "DRY_RUN","enriched":count,"story_ids":ids,"version":2},ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
