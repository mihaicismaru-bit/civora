#!/usr/bin/env python3
"""Deepen MIPE canonical call facts from grouped official pages and documents.

This pass runs after call identity/precision gating and before public dossier
rendering. It never invents facts: each structured field is derived from text
already captured from canonical MIPE pages or attached official documents.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "partener-eu/ingest/state/mipe_canonical_calls.json"
CORPUS = ROOT / "partener-eu/ingest/state/mipe_ro_corpus.json"
OUT_JS = ROOT / "partener-eu/web/mipe-canonical-calls.js"
CRITICAL = ("status", "deadline", "beneficiaries", "eligibility", "grant", "budget", "scoring")


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: Any) -> str:
    text = "".join(ch for ch in unicodedata.normalize("NFKD", clean(value)) if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9%]+", " ", text.lower()).strip()


def unique(values: Iterable[str], limit: int = 30) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = clean(raw)
        key = fold(value)
        if not value or not key or key in seen:
            continue
        seen.add(key)
        out.append(value)
        if len(out) >= limit:
            break
    return out


def sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or " ")
    parts = re.split(r"(?<=[.!?;:])\s+(?=[A-ZĂÂÎȘȚ0-9])", text)
    return [clean(x) for x in parts if 28 <= len(clean(x)) <= 1200]


def select(text: str, keywords: tuple[str, ...], limit: int = 20, require: tuple[str, ...] = ()) -> list[str]:
    out = []
    for sentence in sentences(text):
        normalized = fold(sentence)
        if not any(fold(k) in normalized for k in keywords):
            continue
        if require and not any(fold(k) in normalized for k in require):
            continue
        out.append(sentence)
    return unique(out, limit)


def money_evidence(text: str) -> list[str]:
    patterns = (
        r"(?:grant(?:ul)?|valoarea(?: maxim[aă]| minim[aă])?|finan[țt]are(?:a)? nerambursabil[aă]?)[^.;]{0,120}?\b\d[\d .]*(?:,\d+)?\s*(?:milioane\s+)?(?:EUR|euro|lei|RON)\b",
        r"(?:buget(?:ul)?|alocare(?:a)?(?: financiar[aă])?)[^.;]{0,120}?\b\d[\d .]*(?:,\d+)?\s*(?:milioane\s+)?(?:EUR|euro|lei|RON)\b",
    )
    hits: list[str] = []
    for pattern in patterns:
        hits.extend(re.findall(pattern, text, flags=re.I))
    return unique(hits, 16)


def dated_submission_evidence(text: str) -> list[str]:
    result = []
    date_pattern = re.compile(
        r"(?:\b\d{1,2}[./-]\d{1,2}[./-]20\d{2}\b|\b\d{1,2}\s+(?:ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)\s+20\d{2}\b)",
        re.I,
    )
    for sentence in sentences(text):
        f = fold(sentence)
        if not date_pattern.search(sentence):
            continue
        if any(token in f for token in ("depun", "mysmis", "termen", "inchid", "deschid", "sesiun", "pana la")):
            result.append(sentence)
    return unique(result, 8)


def caen_evidence(text: str) -> list[str]:
    out = []
    for sentence in sentences(text):
        if re.search(r"\bCAEN\b", sentence, re.I) and re.search(r"\b\d{2,4}\b", sentence):
            out.append(sentence)
    return unique(out, 16)


def merge_list(existing: Any, incoming: list[str], limit: int = 30) -> list[str]:
    base = existing if isinstance(existing, list) else ([] if existing in (None, "") else [str(existing)])
    return unique([*base, *incoming], limit)


def main() -> int:
    canonical = json.loads(CANONICAL.read_text(encoding="utf-8"))
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    pages = {p.get("url"): p for p in corpus.get("pages") or [] if p.get("url")}
    docs = {d.get("url"): d for d in corpus.get("documents") or [] if d.get("url")}

    deep_count = 0
    high_depth = 0
    for call in canonical.get("calls") or []:
        group = call.get("canonicalGroup") or {}
        page_rows = [pages[u] for u in group.get("pageUrls") or [] if u in pages]
        doc_rows = [docs[u] for u in group.get("documentUrls") or [] if u in docs]
        text = "\n".join(
            [clean(p.get("textPreview") or p.get("summary")) for p in page_rows]
            + [clean(d.get("textPreview")) for d in doc_rows if d.get("textPreview")]
        )
        if not text:
            continue

        facts = call.setdefault("materialFacts", {})
        eligibility = facts.get("eligibility") if isinstance(facts.get("eligibility"), dict) else {}
        beneficiaries = select(text, ("solicitanti eligibili", "solicitanți eligibili", "beneficiari eligibili", "pot depune", "pot solicita", "categorii de solicitanti"), 18)
        partners = select(text, ("partener eligibil", "parteneri eligibili", "parteneriat", "lider de parteneriat", "liderul parteneriatului"), 16)
        geography = select(text, ("locul de implementare", "teritoriul eligibil", "regiunea", "regiuni mai putin dezvoltate", "regiuni mai puțin dezvoltate", "iti delta", "iti valea", "tara fagarasului", "țara făgărașului", "motii", "moții"), 16)
        conditions = select(text, ("conditie de eligibilitate", "condiție de eligibilitate", "trebuie sa indeplineasca", "trebuie să îndeplinească", "nu sunt eligibile", "nu este eligibil", "criteriu de eligibilitate"), 24)
        caen = caen_evidence(text)
        activities = select(text, ("activitati eligibile", "activități eligibile", "actiuni eligibile", "acțiuni eligibile", "se finanteaza", "se finanțează", "investitii eligibile", "investiții eligibile"), 22)
        costs = select(text, ("cheltuieli eligibile", "cheltuieli neeligibile", "costuri eligibile", "costuri neeligibile"), 22)
        state_aid = select(text, ("ajutor de stat", "de minimis", "regulamentul (ue) nr. 651", "regulamentul 651"), 16)
        cofinancing = select(text, ("cofinant", "cofinanț", "contributie proprie", "contribuție proprie", "intensitatea ajutorului", "rata de finantare", "rata de finanțare"), 16)
        scoring = select(text, ("punctaj", "grila de evaluare", "grilă de evaluare", "prag minim", "criterii de evaluare", "criteriu de evaluare", "prag de calitate"), 24)
        indicators = select(text, ("indicator de realizare", "indicator de rezultat", "indicatori de realizare", "indicatori de rezultat", "tinta indicator", "ținta indicator"), 20)
        implementation = select(text, ("durata de implementare", "perioada de implementare", "finalizarea proiectului", "termen de implementare", "durabilitate", "sustenabilitate"), 18)
        deadlines = dated_submission_evidence(text)
        money = money_evidence(text)
        grants = [x for x in money if any(k in fold(x) for k in ("grant", "valoarea maxima", "valoarea minima", "finantare nerambursabila"))]
        budgets = [x for x in money if any(k in fold(x) for k in ("buget", "alocare"))]
        doc_names = unique([d.get("name") or d.get("url") for d in doc_rows if d.get("url")], 60)

        if beneficiaries:
            facts["beneficiaries"] = merge_list(facts.get("beneficiaries"), beneficiaries, 22)
        eligibility["conditions"] = merge_list(eligibility.get("conditions"), conditions, 30)
        if partners: eligibility["partners"] = merge_list(eligibility.get("partners"), partners, 20)
        if geography: eligibility["geographic_scope"] = merge_list(eligibility.get("geographic_scope"), geography, 20)
        if caen: eligibility["caen"] = merge_list(eligibility.get("caen"), caen, 20)
        if any(eligibility.values()): facts["eligibility"] = eligibility
        if activities: facts["activities"] = merge_list(facts.get("activities"), activities, 28)
        if costs: facts["costs"] = merge_list(facts.get("costs"), costs, 28)
        if state_aid: facts["state_aid_and_cost_rules"] = merge_list(facts.get("state_aid_and_cost_rules"), state_aid, 20)
        if cofinancing: facts["cofinancing"] = merge_list(facts.get("cofinancing"), cofinancing, 20)
        if scoring: facts["scoring"] = merge_list(facts.get("scoring"), scoring, 30)
        if indicators: facts["indicators"] = merge_list(facts.get("indicators"), indicators, 24)
        if implementation: facts["implementation"] = merge_list(facts.get("implementation"), implementation, 22)
        if deadlines: facts["deadline"] = {"evidence": merge_list((facts.get("deadline") or {}).get("evidence") if isinstance(facts.get("deadline"), dict) else None, deadlines, 10)}
        if grants: facts["grant"] = {"evidence": merge_list((facts.get("grant") or {}).get("evidence") if isinstance(facts.get("grant"), dict) else None, grants, 12)}
        if budgets: facts["budget"] = {"evidence": merge_list((facts.get("budget") or {}).get("evidence") if isinstance(facts.get("budget"), dict) else None, budgets, 12)}
        if doc_names: facts["documents"] = merge_list(facts.get("documents"), doc_names, 60)

        verified = set(call.get("verifiedFactClasses") or [])
        if facts.get("beneficiaries"): verified.add("beneficiaries")
        if facts.get("eligibility"): verified.add("eligibility")
        if facts.get("deadline"): verified.add("deadline")
        if facts.get("grant"): verified.add("grant")
        if facts.get("budget"): verified.add("budget")
        if facts.get("scoring"): verified.add("scoring")
        call["verifiedFactClasses"] = sorted(verified)
        blocked = [x for x in CRITICAL if x not in verified]
        call.setdefault("publicationDecision", {})["blockedFactClasses"] = blocked

        depth_dimensions = {
            "status": "status" in verified,
            "deadline": bool(facts.get("deadline")),
            "beneficiaries": bool(facts.get("beneficiaries")),
            "eligibility": bool(facts.get("eligibility")),
            "activities": bool(facts.get("activities")),
            "financing": bool(facts.get("grant") or facts.get("budget") or facts.get("cofinancing")),
            "costsAid": bool(facts.get("costs") or facts.get("state_aid_and_cost_rules")),
            "documents": bool(facts.get("documents")),
            "scoring": bool(facts.get("scoring")),
            "indicators": bool(facts.get("indicators")),
            "implementation": bool(facts.get("implementation")),
            "provenance": bool(call.get("verificationEvidence")),
        }
        depth_score = round(100 * sum(depth_dimensions.values()) / len(depth_dimensions))
        call.setdefault("quality", {})["completeness"] = round(100 * len(set(CRITICAL) & verified) / len(CRITICAL))
        call["quality"]["depthCompleteness"] = depth_score
        call["quality"]["depthDimensions"] = depth_dimensions
        call["quality"]["missingDepthClasses"] = [k for k, ok in depth_dimensions.items() if not ok]
        call["quality"]["failClosed"] = True
        call["dossierConstruction"] = {
            "engine": "MIPE_CANONICAL_DEEP_FACTS_V1",
            "pageEvidenceCount": len(page_rows),
            "documentEvidenceCount": len(doc_rows),
            "depthCompleteness": depth_score,
            "autonomous": True,
        }
        deep_count += 1
        if depth_score >= 70:
            high_depth += 1

    summary = canonical.setdefault("summary", {})
    summary["deepStructured"] = deep_count
    summary["highDepth"] = high_depth
    canonical.setdefault("policy", {})["deepDossierFactExtraction"] = True
    canonical["policy"]["documentTextFeedsDossiers"] = True
    CANONICAL.write_text(json.dumps(canonical, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text("window.PARTENER_MIPE_CANONICAL_CALLS=" + json.dumps(canonical, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(json.dumps({"canonicalCalls": len(canonical.get("calls") or []), "deepStructured": deep_count, "highDepth": high_depth}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
