#!/usr/bin/env python3
"""Materialize one reader-facing explainer per adopted Râmnicu Vâlcea HCL.

The official adopted-decision register is enough to establish decision number,
date and registered subject.  When the full attachment is not yet resolved the
article stays deliberately scoped to that documentary baseline: it explains the
registered subject in plain language and states what the register title alone
does NOT establish.  No amounts, beneficiaries, contract terms or implementation
results are invented.

Each article is evergreen.  A later document resolver may enrich the same stable
story id with the operative articles, annexes, values, entities and follow-up
status.  Cross-decision entity/topic intersections are materialized separately as
investigation leads; those leads never auto-publish as allegations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "editorial" / "council_watch_rm_valcea_state.json"
FACTS = ROOT / "editorial" / "facts_registry.json"
GRAPH = ROOT / "editorial" / "council_decision_graph.json"
LEADS = ROOT / "editorial" / "council_investigation_leads.json"
ENGINE_ID = "council_decision_article_engine_v1"
EVERGREEN_UNTIL = "2099-12-31T23:59:59+03:00"


def load(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def human_date(value: str) -> str:
    y, m, d = value.split("-")
    months = {
        "01": "ianuarie", "02": "februarie", "03": "martie", "04": "aprilie",
        "05": "mai", "06": "iunie", "07": "iulie", "08": "august",
        "09": "septembrie", "10": "octombrie", "11": "noiembrie", "12": "decembrie",
    }
    return f"{int(d)} {months[m]} {y}"


def normalize_title(value: str) -> str:
    text = " ".join(str(value or "").replace("-incheiere", " - incheiere").split())
    replacements = {
        "statii incarcare": "stații de încărcare",
        "achizitionare": "achiziționare",
        "consultanta": "consultanță",
        "reprezentare": "reprezentare",
        "sustinere": "susținere",
        "performanta": "performanță",
        "rectificare": "rectificare",
        "imprumut": "împrumut",
        "aprobare pret": "aprobare preț",
        "energie termica": "energie termică",
        "incepand": "începând",
        "modificare": "modificare",
        "incheiere": "încheiere",
        "concesiune": "concesiune",
        "incheiat": "încheiat",
        "Consiliul Judetean": "Consiliul Județean",
        "contractul de delegare": "contractul de delegare",
        "catre": "către",
        "si ": "și ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.strip(" .")


TEMPLATES: list[dict[str, Any]] = [
    {
        "match": ("microbuze electrice", "statii incarcare"),
        "section": "MOBILITATE",
        "topic": "mobilitate-electrica",
        "plain": "transferul unor microbuze electrice și al unor stații de încărcare către unități administrativ-teritoriale",
        "unknown": "Titlul registrului nu precizează câte microbuze și stații sunt transferate, către ce UAT-uri, valoarea bunurilor, proiectul din care provin sau condițiile concrete ale transferului.",
        "entities": ["microbuze electrice", "stații de încărcare", "UAT-uri"],
    },
    {
        "match": ("ETA", "contract de delegare"),
        "section": "MOBILITATE",
        "topic": "eta-delegare",
        "plain": "punerea unor bunuri achiziționate prin proiect la dispoziția ETA și mandatarea reprezentantului municipiului pentru modificarea contractului de delegare",
        "unknown": "Titlul registrului nu precizează lista și valoarea bunurilor, proiectul de finanțare, clauzele care se modifică ori impactul financiar și operațional asupra serviciului de transport.",
        "entities": ["ETA", "contract de delegare", "Municipiul Râmnicu Vâlcea"],
    },
    {
        "match": ("servicii juridice",),
        "section": "ADMINISTRAȚIE",
        "topic": "servicii-juridice",
        "plain": "achiziționarea de servicii juridice de consultanță și reprezentare",
        "unknown": "Titlul registrului nu identifică dosarul sau problema juridică, valoarea estimată, procedura de achiziție, prestatorul ori durata contractului.",
        "entities": ["servicii juridice", "Municipiul Râmnicu Vâlcea"],
    },
    {
        "match": ("Consiliul Judetean", "sport"),
        "section": "BANI_PUBLICI",
        "topic": "sport-performanta",
        "plain": "o asociere cu Consiliul Județean Vâlcea pentru susținerea sportului de performanță",
        "unknown": "Titlul registrului nu precizează cluburile sau disciplinele beneficiare, contribuția financiară a fiecărei instituții, durata asocierii ori indicatorii de rezultat.",
        "entities": ["Consiliul Județean Vâlcea", "sport de performanță", "Municipiul Râmnicu Vâlcea"],
    },
    {
        "match": ("rectificare buget", "credite interne"),
        "section": "BANI_PUBLICI",
        "topic": "credite-interne",
        "plain": "rectificarea bugetului creditelor interne al municipiului pentru anul 2026",
        "unknown": "Titlul registrului nu arată sumele majorate sau diminuate, proiectele finanțate, soldul creditelor ori efectul asupra serviciului datoriei.",
        "entities": ["credite interne", "buget 2026", "Municipiul Râmnicu Vâlcea"],
    },
    {
        "match": ("contractare imprumut",),
        "section": "BANI_PUBLICI",
        "topic": "imprumut-municipal",
        "plain": "modificarea unei anexe la o hotărâre din 2024 privind contractarea unui împrumut",
        "unknown": "Titlul registrului nu stabilește valoarea împrumutului afectată de modificare, destinațiile finanțate, creditorul, costurile sau noul calendar de tragere și rambursare.",
        "entities": ["împrumut municipal", "HCL 350-39/2024", "Municipiul Râmnicu Vâlcea"],
    },
    {
        "match": ("pret energie termica",),
        "section": "SERVICII",
        "topic": "energie-termica",
        "plain": "aprobarea prețului energiei termice aplicabil de la 1 august 2026",
        "unknown": "Titlul registrului nu indică valoarea prețului aprobat, componentele sale, eventualele subvenții ori diferența față de nivelul anterior.",
        "entities": ["energie termică", "Municipiul Râmnicu Vâlcea"],
    },
    {
        "match": ("Cet Govora", "concesiune"),
        "section": "SERVICII",
        "topic": "cet-govora-concesiune",
        "plain": "modificarea HCL 226/2026 printr-un act adițional la contractul de concesiune încheiat cu CET Govora",
        "unknown": "Titlul registrului nu arată ce clauze ale concesiunii se modifică, durata, obligațiile economice, tarifele ori efectele asupra serviciului de termoficare.",
        "entities": ["CET Govora", "contract de concesiune", "HCL 226/2026", "Municipiul Râmnicu Vâlcea"],
    },
]


def classify(row: dict[str, Any]) -> dict[str, Any]:
    raw = str(row.get("title") or "")
    folded = raw.casefold()
    for spec in TEMPLATES:
        if all(term.casefold() in folded for term in spec["match"]):
            return spec
    return {
        "section": "ADMINISTRAȚIE",
        "topic": "administratie",
        "plain": normalize_title(raw),
        "unknown": "Titlul registrului stabilește obiectul general al hotărârii, dar nu este suficient pentru valori, beneficiari, obligații, termene sau efecte de implementare care nu sunt scrise explicit în el.",
        "entities": ["Municipiul Râmnicu Vâlcea"],
    }


def article_id(number: int, day: str) -> str:
    return f"rm-valcea-hcl-{number}-{day.replace('-', '')}"


def article(row: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    number = int(row["decision_number"])
    day = str(row["decision_date"])
    spec = classify(row)
    official_title = normalize_title(str(row.get("title") or ""))
    source_url = str(source["url"])
    day_label = human_date(day)

    headline = f"HCL {number}/{2026}: ce înseamnă decizia despre {spec['plain']}"
    if len(headline) > 138:
        headline = f"HCL {number} din {day_label}: {official_title}"
        headline = headline[:138].rstrip(" -,:;")
    dek = (
        f"Hotărârea nr. {number} din {day_label} apare în registrul oficial al Consiliului Local Râmnicu Vâlcea. "
        "Explicăm ce se poate stabili sigur din registru și ce trebuie documentat din textul integral."
    )
    claims = [
        {
            "id": "official-register-row",
            "role": "material_change",
            "kind": "fact",
            "text": (
                f"Registrul oficial al hotărârilor adoptate listează HCL {number} din {day_label} cu obiectul «{official_title}»."
            ),
            "source_urls": [source_url],
        },
        {
            "id": "plain-language-scope",
            "role": "meaning",
            "kind": "reader_service",
            "text": (
                f"În limbaj curent, obiectul înscris în registru privește {spec['plain']}. Această explicație reformulează exclusiv titlul oficial și nu adaugă valori, beneficiari sau efecte care nu apar în registru."
            ),
            "source_urls": [source_url],
        },
        {
            "id": "document-chain-next",
            "role": "next_watch",
            "kind": "reader_service",
            "text": str(spec["unknown"]),
            "source_urls": [source_url],
        },
    ]
    official_doc = str(row.get("official_html_url") or "").strip()
    sources = [
        {
            "name": "Primăria Municipiului Râmnicu Vâlcea — registrul HCL adoptate",
            "url": source_url,
            "tier": "T1",
            **({"sha256": source.get("sha256")} if source.get("sha256") else {}),
        }
    ]
    if official_doc:
        sources.append({
            "name": f"HCL Râmnicu Vâlcea nr. {number}/{day}",
            "url": official_doc,
            "tier": "T1",
        })
    item = {
        "id": article_id(number, day),
        "status": "verified",
        "section": spec["section"],
        "editorial_type": "explainer",
        "priority": 92,
        "confidence": 96 if official_doc else 94,
        "publication_lifecycle": "evergreen",
        "valid_from": f"{day}T00:00:00+03:00",
        "valid_until": EVERGREEN_UNTIL,
        "slots": ["morning", "evening"],
        "headline": headline,
        "dek": dek,
        "paragraphs": [claim["text"] for claim in claims],
        "material_fact_gate": "PASS_EXPLAINER_ONLY",
        "sources": sources,
        "fact_kernel": {
            "format_hint": "explainer",
            "headline": {"text": headline, "source_urls": [source_url]},
            "dek": {"text": dek, "source_urls": [source_url]},
            "claims": claims,
        },
        "council_decision": {
            "decision_number": number,
            "decision_date": day,
            "registered_title": str(row.get("title") or ""),
            "topic": spec["topic"],
            "entities": spec["entities"],
            "document_health": row.get("document_health"),
            "evidence_scope": "OFFICIAL_REGISTER_PLUS_DOCUMENT" if official_doc else "OFFICIAL_ADOPTED_REGISTER_ROW_ONLY",
            "auto_enrich_when_document_resolves": True,
            "result_claims_beyond_register_forbidden": not bool(official_doc),
        },
        "kernel_provenance": {
            "builder_id": ENGINE_ID,
            "source_monitor": "council-watch-rm-valcea",
            "source_register": source_url,
            "stable_story_id": True,
            "evergreen": True,
        },
    }
    return item


def entity_id(label: str) -> str:
    folded = re.sub(r"[^a-z0-9]+", "-", label.lower().replace("ă", "a").replace("â", "a").replace("î", "i").replace("ș", "s").replace("ț", "t"))
    return folded.strip("-") or "entity"


def graph_for(items: list[dict[str, Any]], meeting_date: str) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_entities: set[str] = set()
    for item in items:
        decision = item["council_decision"]
        did = str(item["id"])
        nodes.append({
            "id": did,
            "type": "decision",
            "decision_number": decision["decision_number"],
            "date": decision["decision_date"],
            "topic": decision["topic"],
            "headline": item["headline"],
        })
        for label in decision.get("entities") or []:
            eid = "entity-" + entity_id(str(label))
            if eid not in seen_entities:
                seen_entities.add(eid)
                nodes.append({"id": eid, "type": "entity", "label": label})
            edges.append({"from": did, "to": eid, "type": "mentions"})
    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR Council Decision Graph",
        "generated_at": utc_now(),
        "meeting_date": meeting_date,
        "nodes": nodes,
        "edges": edges,
        "policy": {
            "edge_is_documentary_relation_not_allegation": True,
            "investigation_requires_separate_evidence": True,
        },
    }


def lead_document(items: list[dict[str, Any]], meeting_date: str) -> dict[str, Any]:
    by_number = {int(item["council_decision"]["decision_number"]): item for item in items}
    clusters = [
        {
            "id": f"lead-cet-energie-{meeting_date.replace('-', '')}",
            "title": "CET Govora + prețul energiei termice: ce se schimbă împreună",
            "decision_numbers": [305, 306],
            "questions": [
                "Ce clauze ale concesiunii cu CET Govora au fost modificate?",
                "Care este prețul energiei termice aprobat de la 1 august 2026 și cum se compune?",
                "Există subvenție locală sau diferență de preț suportată din buget?",
            ],
        },
        {
            "id": f"lead-imprumut-buget-{meeting_date.replace('-', '')}",
            "title": "Împrumutul municipiului și rectificarea creditelor interne",
            "decision_numbers": [307, 308],
            "questions": [
                "Ce proiecte și sume sunt mutate prin rectificare?",
                "Cum se leagă modificarea anexei împrumutului de bugetul creditelor interne?",
                "Care este expunerea totală și calendarul serviciului datoriei?",
            ],
        },
        {
            "id": f"lead-eta-mobilitate-{meeting_date.replace('-', '')}",
            "title": "ETA, microbuzele electrice și bunurile transferate prin proiecte",
            "decision_numbers": [311, 312],
            "questions": [
                "Ce bunuri intră în patrimoniul/folosința ETA și în ce condiții?",
                "Câte microbuze electrice și stații sunt transferate și către ce UAT-uri?",
                "Ce proiecte și surse de finanțare au plătit bunurile?",
            ],
        },
        {
            "id": f"lead-sport-public-money-{meeting_date.replace('-', '')}",
            "title": "Asocierea municipiu–CJ pentru sportul de performanță",
            "decision_numbers": [309],
            "questions": [
                "Ce cluburi și discipline beneficiază?",
                "Ce contribuții financiare asumă municipiul și Consiliul Județean?",
                "Care sunt criteriile și rezultatele urmărite?",
            ],
        },
        {
            "id": f"lead-servicii-juridice-{meeting_date.replace('-', '')}",
            "title": "Serviciile juridice externe aprobate prin HCL 310",
            "decision_numbers": [310],
            "questions": [
                "Pentru ce litigiu sau proiect sunt cumpărate serviciile?",
                "Care este valoarea și procedura de achiziție?",
                "Cine este prestatorul și de ce este necesară expertiză externă?",
            ],
        },
    ]
    leads = []
    for cluster in clusters:
        decision_ids = [
            by_number[number]["id"] for number in cluster["decision_numbers"] if number in by_number
        ]
        if not decision_ids:
            continue
        leads.append({
            **cluster,
            "status": "OPEN_REQUIRES_DOCUMENT_CHAIN",
            "public_projection": False,
            "decision_ids": decision_ids,
            "minimum_next_evidence": "official full HCL + annexes; add procurement/contract/budget sources when relevant",
            "reputational_claims_allowed": False,
            "automatic_article_upgrade_allowed_after_primary_evidence": True,
        })
    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR Council Investigation Leads",
        "generated_at": utc_now(),
        "meeting_date": meeting_date,
        "lead_count": len(leads),
        "leads": leads,
        "policy": {
            "lead_is_not_allegation": True,
            "lead_is_not_public_story": True,
            "investigation_requires_document_chain": True,
            "cross_document_pattern_may_raise_priority": True,
        },
    }


def build(*, apply: bool) -> dict[str, Any]:
    state = load(STATE, {}) or {}
    target = state.get("target_meeting") if isinstance(state.get("target_meeting"), dict) else {}
    meeting_date = str(target.get("date") or "").strip()
    if not meeting_date:
        raise SystemExit("missing target meeting date")
    source = dict(state.get("source") or {})
    source["sha256"] = (state.get("register_health") or {}).get("source_sha256")
    rows = [
        row for row in state.get("target_decisions") or []
        if isinstance(row, dict) and str(row.get("decision_date") or "") == meeting_date
    ]
    if not rows:
        raise SystemExit("no adopted decisions for target meeting")

    items = [article(row, source) for row in rows]
    items.sort(key=lambda item: int(item["council_decision"]["decision_number"]), reverse=True)
    graph = graph_for(items, meeting_date)
    leads = lead_document(items, meeting_date)

    facts = load(FACTS, {"schema_version": "1.0", "facts": []}) or {"schema_version": "1.0", "facts": []}
    current = [row for row in facts.get("facts") or [] if isinstance(row, dict)]
    replace_ids = {item["id"] for item in items}
    merged = [row for row in current if str(row.get("id") or "") not in replace_ids]
    merged.extend(items)
    merged.sort(key=lambda row: (-int(row.get("priority") or 0), str(row.get("id") or "")))
    facts["facts"] = merged
    facts.setdefault("policy", {})["adopted_hcl_register_explainers"] = ENGINE_ID
    facts["policy"]["hcl_register_explainers_are_evergreen"] = True
    facts["policy"]["register_only_article_may_not_claim_unseen_operational_terms"] = True

    if apply:
        write(FACTS, facts)
        write(GRAPH, graph)
        write(LEADS, leads)

    return {
        "status": "UPDATED" if apply else "DRY_RUN",
        "engine": ENGINE_ID,
        "meeting_date": meeting_date,
        "article_count": len(items),
        "article_ids": [item["id"] for item in items],
        "investigation_leads": leads["lead_count"],
        "graph_nodes": len(graph["nodes"]),
        "graph_edges": len(graph["edges"]),
        "fingerprint": digest({"items": items, "leads": leads.get("leads")}),
    }


def self_test() -> int:
    sample_source = {"url": "https://example.test/hcl", "publisher": "Primăria", "tier": "T1"}
    sample = {"decision_number": 306, "decision_date": "2026-08-14", "title": "aprobare pret energie termica incepand cu 1 august 2026", "official_html_url": None}
    item = article(sample, sample_source)
    assert item["id"] == "rm-valcea-hcl-306-20260814"
    assert item["publication_lifecycle"] == "evergreen"
    assert item["material_fact_gate"] == "PASS_EXPLAINER_ONLY"
    assert len(item["fact_kernel"]["claims"]) == 3
    assert "1 august 2026" in item["council_decision"]["registered_title"]
    assert item["council_decision"]["result_claims_beyond_register_forbidden"] is True
    print("VÂLCEA CLAR council decision article engine self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    print(json.dumps(build(apply=args.apply), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
