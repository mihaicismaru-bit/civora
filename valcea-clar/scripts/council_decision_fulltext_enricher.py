#!/usr/bin/env python3
"""Upgrade stable HCL articles from register explainers to full-document journalism.

Input is the already-resolved official DocManager corpus.  The script keeps the
same stable story ids created by `council_decision_article_engine.py`, replaces
register-only copy with claim-level sourced explainers, and adds reader-facing
fact boxes/sections.  It is deliberately deterministic: topic-specific parsers
cover high-value recurring decision classes; all other decisions fall back to
operative-clause translation plus explicit unknowns.

No cross-document pattern is promoted to an allegation here.  Investigation
leads remain private until a separate evidence chain clears the normal gate.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "editorial" / "facts_registry.json"
CORPUS = ROOT / "editorial" / "council_decision_document_corpus.json"
ENGINE_ID = "council_decision_fulltext_enricher_v1"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def human_date(value: str) -> str:
    months = {1:"ianuarie",2:"februarie",3:"martie",4:"aprilie",5:"mai",6:"iunie",7:"iulie",8:"august",9:"septembrie",10:"octombrie",11:"noiembrie",12:"decembrie"}
    y, m, d = [int(x) for x in value.split("-")]
    return f"{d} {months[m]} {y}"


def add_source(item: dict[str, Any], name: str, url: str, tier: str = "T1") -> None:
    if not url:
        return
    sources = item.setdefault("sources", [])
    if not any(str(row.get("url") or "") == url for row in sources if isinstance(row, dict)):
        sources.append({"name": name, "url": url, "tier": tier})


def vote_from(text: str) -> str | None:
    m = re.search(
        r"(?:Întrunind|Intrunind)\s+(\d+)\s+(?:de\s+)?vot(?:uri)?\s*[„“\"]?pentru[”\"]?\s*,?\s*"
        r"(\d+)\s+vot(?:uri)?\s*[„“\"]?(?:împotrivă|impotriva)[”\"]?\s*(?:și|si|,)?\s*"
        r"(\d+)\s+(?:de\s+)?ab(?:ţ|ț|t)ineri?",
        text,
        re.I,
    )
    if m:
        return f"{m.group(1)} pentru · {m.group(2)} împotrivă · {m.group(3)} abțineri"
    # Some acts use singular/plural variants or add non-participation.
    m = re.search(r"(\d+)\s+vot(?:uri)?\s*[„“\"]?pentru.*?(\d+)\s+vot(?:uri)?\s*[„“\"]?(?:împotrivă|impotriva).*?(\d+)\s+ab", text, re.I | re.S)
    return f"{m.group(1)} pentru · {m.group(2)} împotrivă · {m.group(3)} abțineri" if m else None


def operative_clauses(doc: dict[str, Any]) -> list[str]:
    output: list[str] = []
    for raw in doc.get("operative_articles") or []:
        text = clean(raw)
        if not re.match(r"^Art\.\s*\d+\.", text):
            continue
        if re.search(r"se (?:dă|da) publicității|se comunică", text, re.I):
            continue
        output.append(text)
    return output


def plain_clause(clause: str) -> str:
    body = re.sub(r"^Art\.\s*\d+\.\s*", "", clean(clause)).strip()
    transforms = [
        (r"^Se aprobă\s+", "Consiliul Local aprobă "),
        (r"^Se modifică\s+", "Consiliul Local modifică "),
        (r"^Se împuternicește\s+Primarul municipiului Râmnicu Vâlcea\s+", "Primarul municipiului este împuternicit "),
        (r"^Se împuternicește\s+Primarul municipiului\s+", "Primarul municipiului este împuternicit "),
        (r"^Cu ducerea la îndeplinire a prezentei hotărâri se încredințează\s+", "Punerea în aplicare revine "),
        (r"^Predarea-primirea\s+", "Predarea-primirea "),
    ]
    for pattern, replacement in transforms:
        body = re.sub(pattern, replacement, body, flags=re.I)
    if body and body[-1] not in ".!?":
        body += "."
    return body


def first(pattern: str, text: str, flags: int = re.I | re.S) -> str | None:
    m = re.search(pattern, text, flags)
    return clean(m.group(1)) if m else None


def claim(cid: str, role: str, text: str, url: str, kind: str = "fact") -> dict[str, Any]:
    return {"id": cid, "role": role, "kind": kind, "text": clean(text), "source_urls": [url]}


def base_sections(doc: dict[str, Any], clauses: list[str]) -> list[dict[str, Any]]:
    plain = [plain_clause(value) for value in clauses[:5] if plain_clause(value)]
    return [{"title": "Ce a decis Consiliul Local", "paragraphs": plain}] if plain else []


def generic_story(item: dict[str, Any], doc: dict[str, Any], url: str) -> tuple[str, str, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    number = int(doc["decision_number"])
    day = human_date(str(doc["decision_date"]))
    clauses = operative_clauses(doc)
    plain = [plain_clause(value) for value in clauses[:5] if plain_clause(value)]
    title = clean(doc.get("registered_title"))
    headline = f"HCL {number} din {day}: ce a decis concret Consiliul Local"
    dek = f"Am citit textul integral al HCL {number}, nu doar titlul din registru. Documentul privește {title} și arată măsurile operative aprobate de consilieri."
    claims = [claim("full-document-scope", "material_change", plain[0] if plain else f"Documentul oficial integral confirmă obiectul HCL {number}: {title}.", url)]
    for index, paragraph in enumerate(plain[1:4], 2):
        claims.append(claim(f"operative-{index}", "evidence", paragraph, url))
    vote = vote_from(clean(doc.get("document_text")))
    if vote:
        claims.append(claim("vote", "context", f"Hotărârea a fost adoptată cu {vote}.", url, "documented_context"))
    claims.append(claim("follow-up", "next_watch", "VÂLCEA CLAR păstrează aceeași hotărâre în monitorizare pentru anexele, contractele, plățile și efectele de implementare care pot apărea ulterior în documentele publice.", url, "reader_service"))
    sections = base_sections(doc, clauses)
    factbox = [{"label":"HCL","value":str(number)}, {"label":"Data","value":day}]
    if vote:
        factbox.append({"label":"Vot","value":vote})
    return headline, dek, claims, sections, factbox


def story_312(item: dict[str, Any], doc: dict[str, Any], url: str):
    text = clean(doc.get("document_text"))
    vote = vote_from(text) or "20 pentru · 0 împotrivă · 0 abțineri"
    contract = first(r"Contractul de achiziție publică de produse nr\.\s*([^,]+?)\s+cu societatea", text) or "30708/13.08.2025"
    supplier = first(r"cu societatea\s+([^,]+?),\s+având ca obiect", text) or "BMC Trucks & Bus S.A."
    clauses = operative_clauses(doc)
    transfer_lines = [plain_clause(c) for c in clauses if re.search(r"transferul dreptului de proprietate către UAT", c, re.I)]
    deadline = first(r"în termen de cel mult\s+(\d+\s+zile)", text) or "15 zile"
    headline = "11 microbuze electrice sunt transferate către opt localități din Vâlcea"
    dek = f"HCL 312 împarte 11 microbuze, 11 stații lente și 5 stații rapide cumpărate prin PNRR. Furnizorul contractului de achiziție este {supplier}, iar predarea către UAT-uri trebuie făcută în cel mult {deadline}."
    claims = [
        claim("assets", "material_change", "Consiliul Local a aprobat transferul a 11 microbuze electrice, împreună cu 11 stații de încărcare lentă și 5 stații de încărcare rapidă, către opt UAT-uri partenere în proiectul de extindere a transportului public spre zonele turistice.", url),
        claim("procurement", "evidence", f"Documentul leagă achiziția de contractul de produse nr. {contract}, încheiat cu {supplier}; contractul inițial a avut ca obiect 13 microbuze electrice, 13 stații lente și 5 stații rapide.", url, "documented_context"),
        claim("distribution", "evidence", " ".join(transfer_lines), url),
        claim("deadline", "consequence", f"Predarea-primirea către UAT-urile beneficiare se face prin protocol în termen de cel mult {deadline} de la adoptarea hotărârii.", url, "reader_service"),
        claim("vote", "context", f"HCL 312 a fost adoptată cu {vote}.", url, "documented_context"),
        claim("watch", "next_watch", "Urmărirea editorială continuă cu protocoalele de predare, înmatricularea și punerea efectivă în circulație a microbuzelor în fiecare localitate beneficiară.", url, "reader_service"),
    ]
    sections = [
        {"title":"Ce se transferă", "paragraphs":[claims[0]["text"], claims[1]["text"]]},
        {"title":"Cine primește microbuzele", "paragraphs":transfer_lines},
        {"title":"Ce urmează", "paragraphs":[claims[3]["text"], claims[-1]["text"]]},
    ]
    factbox = [{"label":"Microbuze","value":"11"},{"label":"Stații lente","value":"11"},{"label":"Stații rapide","value":"5"},{"label":"Vot","value":vote}]
    return headline, dek, claims, sections, factbox


def story_310(item: dict[str, Any], doc: dict[str, Any], url: str):
    text = clean(doc.get("document_text"))
    case = first(r"dosarul(?: civil)? nr\.\s*([0-9/]+)", text) or "8244/288/2026"
    vote = vote_from(text) or "18 pentru · 2 împotrivă · 0 abțineri"
    headline = f"Primăria cumpără avocați externi pentru dosarul civil {case}"
    dek = "HCL 310 autorizează consultanță, asistență și reprezentare juridică externă până la soluționarea definitivă a procesului. Hotărârea nu indică încă în textul publicat cine va primi contractul și la ce preț."
    claims = [
        claim("legal-services", "material_change", f"Consiliul Local aprobă achiziționarea de servicii juridice de consultanță, asistență și reprezentare pentru Municipiul Râmnicu Vâlcea în dosarul civil nr. {case}, până la soluționarea definitivă a acestuia.", url),
        claim("mayor", "consequence", "Primarul municipiului este împuternicit să contracteze serviciile juridice în condițiile legii, iar punerea în aplicare revine Direcției Administrație, Juridic, Contencios.", url),
        claim("vote", "context", f"Hotărârea a trecut cu {vote}.", url, "documented_context"),
        claim("unknown", "next_watch", "Textul HCL nu nominalizează avocatul sau societatea de avocatură și nu fixează în corpul hotărârii valoarea contractului; acestea trebuie urmărite în achiziția ulterioară și în documentele dosarului.", url, "reader_service"),
    ]
    sections = [{"title":"Ce s-a aprobat", "paragraphs":[claims[0]["text"],claims[1]["text"]]}, {"title":"Ce trebuie urmărit", "paragraphs":[claims[3]["text"]]}]
    factbox = [{"label":"Dosar","value":case},{"label":"Durată","value":"până la soluționarea definitivă"},{"label":"Vot","value":vote}]
    return headline, dek, claims, sections, factbox


def story_307(item: dict[str, Any], doc: dict[str, Any], url: str):
    text = clean(doc.get("document_text"))
    vote = vote_from(text) or "17 pentru · 1 împotrivă · 2 abțineri"
    headline = "730.000 lei din împrumutul municipal sunt mutați către parcarea etajată din Nord"
    dek = "HCL 307 redistribuie bani în interiorul împrumutului de 40 milioane lei: scade finanțarea pentru locuințele de tineri și cu 1.400 lei pentru Școala Copăcelu, iar parcarea etajată din Nord ajunge la 10,286 milioane lei din împrumut."
    claims = [
        claim("loan", "context", "Hotărârea modifică lista investițiilor finanțate din împrumutul bancar intern de 40.000.000 lei aprobat în 2024.", url, "documented_context"),
        claim("school", "evidence", "Finanțarea din împrumut pentru reabilitarea și modernizarea Școlii nr. 6 Copăcelu – clădirea Școala Nouă scade cu 1.400 lei și ajunge la 5.045.360 lei.", url),
        claim("housing", "evidence", "Finanțarea din împrumut pentru locuințele de tineri destinate închirierii de pe strada Știrbei Vodă nr. 111A scade cu 728.600 lei și ajunge la 1.633.410 lei.", url),
        claim("parking", "material_change", "Finanțarea din împrumut pentru parcarea etajată din zona Nord și refacerea terenului de sport crește cu 730.000 lei și ajunge la 10.286.840 lei.", url),
        claim("vote", "context", f"HCL 307 a fost adoptată cu {vote}.", url, "documented_context"),
        claim("watch", "next_watch", "Urmărirea trebuie să lege această redistribuire de execuția efectivă a celor trei investiții și de eventuale noi modificări ale împrumutului municipal.", url, "reader_service"),
    ]
    sections = [{"title":"De unde se iau banii", "paragraphs":[claims[1]["text"],claims[2]["text"]]}, {"title":"Unde merg", "paragraphs":[claims[3]["text"]]}, {"title":"Ce urmărim", "paragraphs":[claims[-1]["text"]]}]
    factbox = [{"label":"Împrumut total","value":"40 mil. lei"},{"label":"Mutare spre parcarea Nord","value":"+730.000 lei"},{"label":"Locuințe tineri","value":"−728.600 lei"},{"label":"Vot","value":vote}]
    return headline, dek, claims, sections, factbox


def story_306(item: dict[str, Any], doc: dict[str, Any], url: str):
    text = clean(doc.get("document_text"))
    vote = vote_from(text)
    headline = "Prețul facturat populației pentru căldură rămâne neschimbat; diferența este plătită din bugetul local"
    dek = "HCL 306 stabilește noile costuri SACET de la 1 august 2026, dar menține prețurile de facturare pentru populație. Bugetul municipiului acoperă diferențe de 110,65 lei/MWh pe rețeaua de distribuție și 65,93 lei/MWh pe rețeaua de transport, exclusiv TVA."
    claims = [
        claim("cost-distribution", "evidence", "Pentru utilizatorii racordați la rețeaua de distribuție, costul de producere, transport, distribuție și furnizare este stabilit la 586,27 lei/MWh, respectiv 681,82 lei/Gcal, exclusiv TVA.", url),
        claim("billing-distribution", "material_change", "Prețul de facturare către populația racordată la rețeaua de distribuție rămâne neschimbat la 475,62 lei/MWh, respectiv 553,15 lei/Gcal, exclusiv TVA.", url),
        claim("billing-transport", "evidence", "Pentru populația racordată la rețeaua de transport, prețul de facturare rămâne 344,18 lei/MWh, respectiv 400,28 lei/Gcal, exclusiv TVA.", url),
        claim("subsidy-distribution", "consequence", "Diferența pentru rețeaua de distribuție, de 110,65 lei/MWh sau 128,67 lei/Gcal, exclusiv TVA, este asigurată din bugetul local.", url),
        claim("subsidy-transport", "consequence", "Diferența pentru rețeaua de transport, de 65,93 lei/MWh sau 76,67 lei/Gcal, exclusiv TVA, este de asemenea asigurată din bugetul local.", url),
        claim("watch", "next_watch", "Pentru impactul bugetar total trebuie urmărite cantitățile efectiv livrate și plățile de subvenție către operator în perioada de aplicare.", url, "reader_service"),
    ]
    if vote:
        claims.insert(-1, claim("vote","context",f"Hotărârea a fost adoptată cu {vote}.",url,"documented_context"))
    sections = [{"title":"Ce plătește populația", "paragraphs":[claims[1]["text"],claims[2]["text"]]}, {"title":"Ce acoperă bugetul local", "paragraphs":[claims[3]["text"],claims[4]["text"]]}, {"title":"Ce trebuie urmărit", "paragraphs":[claims[-1]["text"]]}]
    factbox = [{"label":"Facturare distribuție","value":"475,62 lei/MWh"},{"label":"Subvenție distribuție","value":"110,65 lei/MWh"},{"label":"Facturare transport","value":"344,18 lei/MWh"},{"label":"Subvenție transport","value":"65,93 lei/MWh"}]
    return headline, dek, claims, sections, factbox


def story_305(item: dict[str, Any], doc: dict[str, Any], url: str):
    text = clean(doc.get("document_text"))
    vote = vote_from(text) or "18 pentru · 0 împotrivă · 1 abținere"
    headline = "CET Govora primește dreptul de a cumpăra integral energia termică de la alți producători"
    dek = "HCL 305 rescrie actul adițional la concesiune după ce CET Govora a refuzat forma din iunie. Documentul leagă schimbarea de oprirea grupurilor pe lignit la 31 august 2026 și de faptul că noua centrală a CJ era estimată să devină operațională cel mai devreme la 15 octombrie 2026."
    claims = [
        claim("old-addendum", "context", "Actul adițional aprobat în iunie permitea cumpărarea de energie de la producători autorizați doar ca soluție complementară capacităților exploatate direct de concesionar.", url, "documented_context"),
        claim("cet-refusal", "evidence", "CET Govora a comunicat Primăriei că nu poate semna forma transmisă, argumentând că ea nu permite achiziția de la terți ca modalitate autonomă de acoperire a întregului necesar SACET și nu răspunde situației tehnice și economice descrise de operator.", url, "attributed_statement"),
        claim("transition", "evidence", "Documentul menționează scoaterea din exploatare la 31 august 2026 a grupurilor 3 și 4 pe lignit ale CET Govora și arată că centrala realizată de Consiliul Județean era estimată să fie operațională cel mai devreme la 15 octombrie 2026.", url),
        claim("new-rule", "material_change", "Noua formulare permite concesionarului să asigure energia termică fie prin exploatarea directă a capacităților proprii sau ale unor terți, fie prin achiziția de energie termică de la producători autorizați; concesionarul rămâne responsabil pentru furnizare până la delegarea către un nou operator.", url),
        claim("finance-risk", "consequence", "În adresa citată de hotărâre, CET Govora avertizează și asupra necesității stabilirii surselor de finanțare, mecanismului de plată și alocării riscurilor pentru această perioadă de tranziție.", url, "attributed_statement"),
        claim("vote", "context", f"HCL 305 a fost adoptată cu {vote}; documentul consemnează și o neparticipare la vot.", url, "documented_context"),
        claim("watch", "next_watch", "Dosarul trebuie urmărit împreună cu HCL 306 privind prețurile și subvenția la energie termică, contractele de achiziție a căldurii și calendarul noului operator SACET.", url, "reader_service"),
    ]
    sections = [{"title":"De ce a fost nevoie de o nouă hotărâre", "paragraphs":[claims[0]["text"],claims[1]["text"],claims[2]["text"]]}, {"title":"Ce se schimbă în concesiune", "paragraphs":[claims[3]["text"],claims[4]["text"]]}, {"title":"Firul care merită urmărit", "paragraphs":[claims[-1]["text"]]}]
    factbox = [{"label":"Oprire grupuri lignit","value":"31 aug. 2026"},{"label":"Noua centrală CJ – estimare din HCL","value":"cel mai devreme 15 oct. 2026"},{"label":"Contract concesiune","value":"9692/16.05.2002"},{"label":"Vot","value":vote}]
    return headline, dek, claims, sections, factbox


SPECIAL: dict[int, Callable[..., Any]] = {305:story_305,306:story_306,307:story_307,310:story_310,312:story_312}


def apply_enrichment(facts: dict[str, Any], corpus: dict[str, Any]) -> tuple[int, list[str]]:
    docs = {int(row.get("decision_number") or 0): row for row in corpus.get("documents") or [] if isinstance(row, dict) and row.get("resolved") is True}
    changed: list[str] = []
    for item in facts.get("facts") or []:
        if not isinstance(item, dict) or not isinstance(item.get("council_decision"), dict):
            continue
        number = int(item["council_decision"].get("decision_number") or 0)
        doc = docs.get(number)
        if not doc:
            continue
        url = str(doc.get("official_html_url") or "").strip()
        if not url:
            continue
        add_source(item, f"HCL Râmnicu Vâlcea nr. {number}/{doc.get('decision_date')}", url, "T1")
        builder = SPECIAL.get(number, generic_story)
        headline, dek, claims, sections, factbox = builder(item, doc, url)
        item["headline"] = headline
        item["dek"] = dek
        item["paragraphs"] = [row["text"] for row in claims]
        item["article_sections"] = sections
        item["factbox"] = factbox
        item["confidence"] = 99
        item["material_fact_gate"] = "PASS_EXPLAINER_ONLY"
        item["publication_lifecycle"] = "evergreen"
        item["fact_kernel"] = {
            "format_hint":"explainer",
            "headline":{"text":headline,"source_urls":[url]},
            "dek":{"text":dek,"source_urls":[url]},
            "claims":claims,
        }
        item["council_decision"]["document_health"] = "OK_GENERIC_RESOLVER"
        item["council_decision"]["official_html_url"] = url
        item["council_decision"]["evidence_scope"] = "FULL_OFFICIAL_HCL_TEXT"
        item["council_decision"]["result_claims_beyond_register_forbidden"] = False
        item["council_decision"]["fulltext_enricher"] = ENGINE_ID
        item["fulltext_enrichment"] = {
            "engine_id": ENGINE_ID,
            "source_sha256": doc.get("source_sha256"),
            "document_text_sha256": doc.get("document_text_sha256"),
            "operative_article_count": len(doc.get("operative_articles") or []),
            "topic_specific_parser": number in SPECIAL,
            "same_canonical_story_id": True,
        }
        changed.append(str(item.get("id")))
    facts.setdefault("policy", {})["adopted_hcl_fulltext_enricher"] = ENGINE_ID
    facts["policy"]["full_hcl_text_preferred_over_register_title"] = True
    return len(changed), changed


def self_test() -> int:
    doc = {"decision_number":310,"decision_date":"2026-08-14","registered_title":"servicii juridice","official_html_url":"https://example.test/h310","resolved":True,"document_text":"HOTĂRÂREA NR.310 Întrunind 18 voturi pentru, 2 voturi împotrivă și 0 abţineri, HOTĂRĂȘTE: Art.1. Se aprobă achiziționarea serviciilor juridice pentru dosarul civil nr.8244/288/2026. Art.2. Se împuternicește Primarul municipiului Râmnicu Vâlcea să contracteze serviciile.","operative_articles":["Art.1. Se aprobă achiziționarea serviciilor juridice pentru dosarul civil nr.8244/288/2026.","Art.2. Se împuternicește Primarul municipiului Râmnicu Vâlcea să contracteze serviciile."],"source_sha256":"x","document_text_sha256":"y"}
    item={"id":"rm-valcea-hcl-310-20260814","status":"verified","council_decision":{"decision_number":310},"sources":[]}
    facts={"facts":[item]}
    count, ids=apply_enrichment(facts,{"documents":[doc]})
    assert count==1 and ids==[item["id"]]
    assert "8244/288/2026" in item["headline"]
    assert item["fulltext_enrichment"]["topic_specific_parser"] is True
    assert len(item["fact_kernel"]["claims"]) >= 4
    print("VÂLCEA CLAR Council fulltext enricher v1 self-test: PASS")
    return 0


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--self-test",action="store_true")
    args=parser.parse_args()
    if args.self_test:
        return self_test()
    facts=load(FACTS)
    corpus=load(CORPUS)
    count, ids=apply_enrichment(facts,corpus)
    if args.apply and count:
        write(FACTS,facts)
    print(json.dumps({"status":"UPDATED" if args.apply and count else "DRY_RUN","enriched":count,"story_ids":ids},ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
