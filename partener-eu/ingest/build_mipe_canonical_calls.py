#!/usr/bin/env python3
"""Canonicalize the direct Romanian MIPE corpus into one object per funding call.

Input is the evidence-rich Windows v3 crawl. This stage deliberately sits
between transport/crawl and publishing: pages, corrigenda, result notices and
documents belonging to the same financing call are grouped before any dossier
is rendered. Material facts are extracted conservatively and remain unknown
when the official corpus does not support them.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = ROOT / "partener-eu/ingest/state/mipe_ro_corpus.json"
OUT_PATH = ROOT / "partener-eu/ingest/state/mipe_canonical_calls.json"
OUT_JS = ROOT / "partener-eu/web/mipe-canonical-calls.js"

CALL_EVENTS = {
    "CONSULTATION_OPENED", "GUIDE_PUBLISHED", "GUIDE_MODIFIED", "CALL_OPENED",
    "DEADLINE_EXTENDED", "CALL_CLOSED", "EVALUATION_UPDATE", "RESULTS_PUBLISHED",
    "CONTRACTING_UPDATE",
}
STATUS_FROM_EVENT = {
    "CONSULTATION_OPENED": "PUBLIC_CONSULTATION",
    "GUIDE_PUBLISHED": "EXPECTED",
    "GUIDE_MODIFIED": "EXPECTED",
    "CALL_OPENED": "OPEN",
    "DEADLINE_EXTENDED": "OPEN",
    "CALL_CLOSED": "CLOSED",
    "EVALUATION_UPDATE": "CLOSED",
    "RESULTS_PUBLISHED": "CLOSED",
    "CONTRACTING_UPDATE": "CLOSED",
}
EVENT_RANK = {
    "CONSULTATION_OPENED": 1,
    "GUIDE_PUBLISHED": 2,
    "GUIDE_MODIFIED": 3,
    "CALL_OPENED": 4,
    "DEADLINE_EXTENDED": 5,
    "CALL_CLOSED": 6,
    "EVALUATION_UPDATE": 7,
    "RESULTS_PUBLISHED": 8,
    "CONTRACTING_UPDATE": 9,
}
PROGRAMME_LABELS = {
    "PEO": "Programul Educație și Ocupare",
    "PoIDS": "Programul Incluziune și Demnitate Socială",
    "PIDS": "Programul Incluziune și Demnitate Socială",
    "PDDTJ": "Programul Dezvoltare Durabilă și Tranziție Justă",
    "PDDS": "Programul Dezvoltare Durabilă",
    "PS": "Programul Sănătate",
    "PNRR": "PNRR",
    "PCIDIF": "Programul Creștere Inteligentă, Digitalizare și Instrumente Financiare",
    "PoAT": "Programul Asistență Tehnică",
    "MIPE": "MIPE",
}
STOPWORDS = {
    "ghidul", "ghid", "solicitantului", "conditii", "condiții", "specifice",
    "actualizeaza", "actualizează", "varianta", "consolidata", "consolidată",
    "consultare", "publica", "publică", "apel", "apelul", "proiecte", "proiectelor",
    "programul", "program", "pentru", "privind", "aferent", "aferenta", "aferentă",
    "lanseaza", "lansează", "lansarea", "lista", "proiectelor", "intermediara",
    "intermediară", "finala", "finală", "2021", "2027", "peo", "pids", "poids",
}
GENERIC_TITLES = {
    "ministerul investitiilor si proiectelor europene", "programul educatie si ocupare",
    "programul incluziune si demnitate sociala", "programul sanatate", "pnrr",
}
CODE_PATTERNS = [
    re.compile(r"\bPEO/\d+(?:/[A-Z0-9_.-]+){3,8}\b", re.I),
    re.compile(r"\b(?:PIDS|POIDS)/\d+(?:/[A-Z0-9_.-]+){2,8}\b", re.I),
    re.compile(r"\bPS/\d+(?:/[A-Z0-9_.-]+){2,8}\b", re.I),
    re.compile(r"\b(?:PDDTJ|PTJ)/\d+(?:/[A-Z0-9_.-]+){1,8}\b", re.I),
    re.compile(r"\b(?:PCIDIF|POAT|POT)/\d+(?:/[A-Z0-9_.-]+){1,8}\b", re.I),
]


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: Any) -> str:
    s = "".join(ch for ch in unicodedata.normalize("NFKD", clean(value)) if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def tokens(value: Any) -> set[str]:
    return {x for x in fold(value).split() if len(x) >= 3 and x not in STOPWORDS}


def unique(seq: Iterable[str], limit: int = 50) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in seq:
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
    parts = re.split(r"(?<=[.!?;])\s+(?=[A-ZĂÂÎȘȚ0-9])", text)
    return [clean(x) for x in parts if 25 <= len(clean(x)) <= 900]


def extract_code(text: str) -> str | None:
    for pattern in CODE_PATTERNS:
        m = pattern.search(text or "")
        if m:
            return re.sub(r"\s+", "", m.group(0)).upper().rstrip(".,;:")
    return None


def quoted_call_name(text: str) -> str | None:
    candidates = []
    for pattern in (r"[„“\"]([^„”\"]{18,260})[”\"]", r"'([^']{18,260})'"):
        candidates.extend(re.findall(pattern, text or ""))
    candidates = [clean(x) for x in candidates if not re.search(r"prioritat|obiectiv specific", x, re.I)]
    if not candidates:
        return None
    candidates.sort(key=lambda x: (len(tokens(x)), len(x)), reverse=True)
    return candidates[0]


def canonical_name(page: dict[str, Any]) -> str:
    title = clean(page.get("title"))
    summary = clean(page.get("summary"))
    quoted = quoted_call_name(f"{title} {summary[:1800]}")
    if quoted:
        return quoted
    value = title
    value = re.sub(r"^(?:consultare publică\s*,?\s*)", "", value, flags=re.I)
    value = re.sub(r"^(?:PEO|PoIDS|PIDS|PDDTJ|Programul Sănătate)\s*:\s*", "", value, flags=re.I)
    value = re.sub(r"^(?:Actualizează\s+)?Ghidul Solicitantului(?:\s*[-–—:]\s*)?", "", value, flags=re.I)
    value = re.sub(r"^Varianta consolidată a Ghidului Solicitantului\s*", "", value, flags=re.I)
    value = re.sub(r"^Lansarea apelului(?:\s+(?:competitiv|non-competitiv))?\s*", "", value, flags=re.I)
    value = re.sub(r"^Lansează apelul(?:\s+de tip\s+(?:competitiv|necompetitiv))?\s*", "", value, flags=re.I)
    value = re.sub(r"^Lista (?:finală|intermediară)(?: nr\. ?\d+)? (?:a )?(?:proiectelor|cererilor de finanțare) (?:aprobate|selectate|respinse|de rezervă).*? pentru apelul(?: de proiecte)?\s*", "", value, flags=re.I)
    value = clean(value.strip(" -–—:,.\"„”"))
    return value or title or "Apel MIPE identificat"


def programme(page: dict[str, Any], text: str) -> str:
    tag = clean(page.get("programme") or "")
    hay = f"{tag} {page.get('title','')} {text[:3000]}"
    if re.search(r"\bPEO\b|Educație și Ocupare|Educatie si Ocupare", hay, re.I): return "PEO"
    if re.search(r"\bPoIDS\b|\bPIDS\b|Incluziune și Demnitate|Incluziune si Demnitate", hay, re.I): return "PoIDS"
    if re.search(r"\bPDDTJ\b|Tranziție Justă|Tranzitie Justa", hay, re.I): return "PDDTJ"
    if re.search(r"Programul Sănătate|Programul Sanatate|\bPS/\d+", hay, re.I): return "PS"
    if re.search(r"\bPNRR\b", hay, re.I): return "PNRR"
    if re.search(r"PCIDIF|Creștere Inteligentă|Crestere Inteligenta", hay, re.I): return "PCIDIF"
    if re.search(r"\bPoAT\b|Asistență Tehnică|Asistenta Tehnica", hay, re.I): return "PoAT"
    return tag if tag in PROGRAMME_LABELS else "MIPE"


def is_generic_page(page: dict[str, Any]) -> bool:
    title = fold(page.get("title"))
    url = clean(page.get("url"))
    if not title and url.rstrip("/") == "https://mfe.gov.ro":
        return True
    if title in GENERIC_TITLES:
        return True
    path = urlparse(url).path.rstrip("/")
    if path in {"", "/ghiduri_peos", "/ghiduri_pids", "/pnrr", "/pdds/despre-program-programare"}:
        return True
    return False


def event_kind(page: dict[str, Any]) -> str:
    kind = str(page.get("kind") or "OFFICIAL_UPDATE").upper()
    if kind in CALL_EVENTS:
        return kind
    text = fold(f"{page.get('title')} {page.get('summary')}")
    if "consultare publica" in text: return "CONSULTATION_OPENED"
    if "corrigendum" in text or "actualizeaza ghidul" in text: return "GUIDE_MODIFIED"
    if "lansarea apelului" in text or "lanseaza apelul" in text: return "CALL_OPENED"
    if "lista finala" in text and ("selectate" in text or "aprobate" in text): return "RESULTS_PUBLISHED"
    if "lista intermediara" in text and ("aprobate" in text or "respinse" in text): return "EVALUATION_UPDATE"
    if "proiectelor contractate" in text: return "CONTRACTING_UPDATE"
    if "ghidul solicitantului" in text: return "GUIDE_PUBLISHED"
    return kind


def title_similarity(a: str, b: str) -> float:
    aa, bb = tokens(a), tokens(b)
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / len(aa | bb)


def money_candidates(text: str) -> list[str]:
    patterns = [
        r"(?:buget(?:ul)?|alocare(?:a)?|valoare(?:a)?|grant(?:ul)?)[^.;]{0,90}?\b\d[\d .]*(?:,\d+)?\s*(?:milioane\s+)?(?:EUR|euro|lei|RON)\b",
        r"\b\d[\d .]*(?:,\d+)?\s*(?:milioane\s+)?(?:EUR|euro)\b",
    ]
    hits: list[str] = []
    for p in patterns:
        hits.extend(re.findall(p, text, flags=re.I))
    return unique(hits, 12)


def extract_deadlines(text: str) -> list[str]:
    candidates = []
    for s in sentences(text):
        f = fold(s)
        if not any(k in f for k in ("termen", "pana la", "până la", "mysmis", "depunere", "inchidere", "închidere")):
            continue
        if re.search(r"\b\d{1,2}[./-]\d{1,2}[./-]20\d{2}\b", s) or re.search(r"\b\d{1,2}\s+(?:ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)\s+20\d{2}\b", s, re.I):
            candidates.append(s)
    return unique(candidates, 6)


def select_sentences(text: str, keywords: tuple[str, ...], limit: int) -> list[str]:
    out = []
    for s in sentences(text):
        f = fold(s)
        if any(fold(k) in f for k in keywords):
            out.append(s)
    return unique(out, limit)


def infer_material_facts(text: str, docs: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    beneficiaries = select_sentences(text, ("solicitanti eligibili", "solicitanți eligibili", "beneficiari eligibili", "pot solicita", "pot depune", "parteneri eligibili"), 14)
    eligibility = select_sentences(text, ("eligibil", "conditie", "condiție", "nu sunt eligibile", "trebuie sa", "trebuie să"), 24)
    activities = select_sentences(text, ("activitati eligibile", "activități eligibile", "finanteaza", "finanțează", "actiunea", "acțiunea", "investitii", "investiții"), 20)
    costs = select_sentences(text, ("cheltuieli eligibile", "costuri eligibile", "ajutor de stat", "de minimis", "cofinant", "cofinanț", "contributie proprie", "contribuție proprie"), 20)
    scoring = select_sentences(text, ("punctaj", "grila", "grilă", "prag minim", "criteriu de evaluare", "criterii de evaluare"), 20)
    indicators = select_sentences(text, ("indicator", "rezultat", "realizare", "tinta", "ținta"), 16)
    deadlines = extract_deadlines(text)
    monies = money_candidates(text)
    grant_lines = [x for x in monies if re.search(r"grant|valoare|maxim|minim|finant", fold(x), re.I)]
    budget_lines = [x for x in monies if re.search(r"buget|alocare", fold(x), re.I)]
    doc_names = unique([d.get("name") or d.get("url") for d in docs if d.get("url")], 50)
    facts: dict[str, Any] = {}
    verified: list[str] = []
    if beneficiaries:
        facts["beneficiaries"] = beneficiaries; verified.append("beneficiaries")
    if eligibility:
        facts["eligibility"] = {"conditions": eligibility}; verified.append("eligibility")
    if activities:
        facts["activities"] = activities
    if costs:
        facts["costs"] = costs
    if scoring:
        facts["scoring"] = scoring; verified.append("scoring")
    if indicators:
        facts["indicators"] = indicators
    if deadlines:
        facts["deadline"] = {"evidence": deadlines}; verified.append("deadline")
    if grant_lines:
        facts["grant"] = {"evidence": grant_lines}; verified.append("grant")
    if budget_lines:
        facts["budget"] = {"evidence": budget_lines}; verified.append("budget")
    if doc_names:
        facts["documents"] = doc_names
    return facts, sorted(set(verified))


def main() -> int:
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    pages = [p for p in corpus.get("pages") or [] if p.get("verification") == "CANONICAL_OFFICIAL_FETCH"]
    documents = {d.get("url"): d for d in corpus.get("documents") or [] if d.get("url")}

    candidates: list[dict[str, Any]] = []
    for page in pages:
        if is_generic_page(page):
            continue
        text = clean(page.get("textPreview") or page.get("summary"))
        title = canonical_name(page)
        if len(tokens(title)) < 2:
            continue
        kind = event_kind(page)
        if kind not in CALL_EVENTS and str(page.get("pageClass") or "").upper() not in {"CALL_OR_GUIDE", "CALL_LIFECYCLE_EVENT"}:
            continue
        code = extract_code(f"{page.get('title','')} {page.get('summary','')} {text[:5000]}")
        prog = programme(page, text)
        candidates.append({"page": page, "name": title, "code": code, "programme": prog, "kind": kind})

    groups: list[dict[str, Any]] = []
    by_code: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        code = candidate["code"]
        if code:
            key = fold(code)
            group = by_code.get(key)
            if group is None:
                group = {"programme": candidate["programme"], "code": code, "name": candidate["name"], "members": []}
                by_code[key] = group; groups.append(group)
            group["members"].append(candidate)
            if len(tokens(candidate["name"])) > len(tokens(group["name"])):
                group["name"] = candidate["name"]
            continue
        best = None; best_score = 0.0
        for group in groups:
            if group["programme"] != candidate["programme"]:
                continue
            score = title_similarity(candidate["name"], group["name"])
            if score > best_score:
                best, best_score = group, score
        if best is not None and best_score >= 0.62:
            best["members"].append(candidate)
            if len(tokens(candidate["name"])) > len(tokens(best["name"])):
                best["name"] = candidate["name"]
        else:
            groups.append({"programme": candidate["programme"], "code": None, "name": candidate["name"], "members": [candidate]})

    calls: list[dict[str, Any]] = []
    for group in groups:
        members = group["members"]
        page_rows = [m["page"] for m in members]
        event_rows = sorted(members, key=lambda m: EVENT_RANK.get(m["kind"], 0))
        latest_kind = event_rows[-1]["kind"] if event_rows else "OFFICIAL_UPDATE"
        status = STATUS_FROM_EVENT.get(latest_kind, "REVIEW")
        doc_refs: list[dict[str, Any]] = []
        for page in page_rows:
            for ref in page.get("documents") or []:
                if not isinstance(ref, dict) or not ref.get("url"):
                    continue
                full = documents.get(ref["url"], {})
                doc_refs.append({
                    "name": ref.get("name") or full.get("name") or "Document oficial",
                    "url": ref["url"],
                    "sha256": full.get("sha256"),
                    "bytes": full.get("bytes"),
                    "contentType": full.get("contentType"),
                    "extraction": full.get("extraction"),
                    "textPreview": full.get("textPreview") or "",
                    "observedAt": full.get("observedAt") or page.get("observedAt"),
                })
        dedup_docs: dict[str, dict[str, Any]] = {d["url"]: d for d in doc_refs}
        doc_refs = list(dedup_docs.values())
        combined_text = "\n".join([clean(p.get("textPreview") or p.get("summary")) for p in page_rows] + [clean(d.get("textPreview")) for d in doc_refs if d.get("textPreview")])
        facts, verified = infer_material_facts(combined_text, doc_refs)
        verified = sorted(set(verified + (["status"] if latest_kind in STATUS_FROM_EVENT else [])))
        blocked = [x for x in ("status", "deadline", "beneficiaries", "eligibility", "grant", "budget", "scoring") if x not in verified]
        completeness = round(100 * (7 - len(blocked)) / 7)
        canonical_seed = group["code"] or f"{group['programme']}|{fold(group['name'])}"
        call_id = "mipe-" + hashlib.sha256(canonical_seed.encode()).hexdigest()[:18]
        sources = []
        for page in page_rows:
            supports = ["source_event"]
            if page.get("kind") in CALL_EVENTS: supports.append("status")
            sources.append({
                "sourceUrl": page.get("url"), "sourceTier": "T1",
                "observedAt": page.get("observedAt"), "supportedFactClasses": supports,
                "label": page.get("title") or group["name"], "kind": event_kind(page),
            })
        for d in doc_refs:
            supports = [x for x in verified if x != "status"] or ["document"]
            sources.append({
                "sourceUrl": d.get("url"), "sourceTier": "T1",
                "observedAt": d.get("observedAt"), "supportedFactClasses": supports,
                "label": d.get("name") or "Document oficial", "kind": "OFFICIAL_DOCUMENT",
            })
        calls.append({
            "id": call_id,
            "title": group["name"],
            "programme": PROGRAMME_LABELS.get(group["programme"], group["programme"]),
            "programmeCode": group["programme"],
            "code": group["code"] or "—",
            "region": "România",
            "status": status,
            "publicationState": "PUBLISHABLE" if completeness >= 43 else "PROVISIONAL_FAIL_CLOSED",
            "asOf": corpus.get("generatedAt"),
            "materialFacts": facts,
            "verifiedFactClasses": verified,
            "publicationDecision": {"blockedFactClasses": blocked},
            "verificationEvidence": sources,
            "canonicalGroup": {
                "pageCount": len(page_rows), "documentCount": len(doc_refs),
                "latestEvent": latest_kind,
                "pageUrls": unique([p.get("url") for p in page_rows], 60),
                "documentUrls": unique([d.get("url") for d in doc_refs], 100),
            },
            "timeline": sorted([
                {"date": p.get("observedAt"), "kind": event_kind(p), "title": p.get("title"), "url": p.get("url")}
                for p in page_rows
            ], key=lambda x: str(x.get("date") or "")),
            "quality": {"completeness": completeness, "blocked": blocked, "failClosed": True},
        })

    calls.sort(key=lambda x: (x["programme"], x["title"]))
    payload = {
        "schemaVersion": 1,
        "generatedAt": corpus.get("generatedAt"),
        "source": "MIPE Romanian direct corpus v3",
        "policy": {
            "oneCanonicalObjectPerCall": True,
            "groupPagesCorrigendaAndDocuments": True,
            "openOnlyFromExplicitOfficialEvent": True,
            "unknownFactsRemainUnknown": True,
            "failClosed": True,
        },
        "summary": {
            "corpusPages": len(pages), "candidatePages": len(candidates),
            "canonicalCalls": len(calls),
            "withExplicitCode": sum(1 for c in calls if c.get("code") not in {None, "—"}),
            "withDocuments": sum(1 for c in calls if c.get("canonicalGroup", {}).get("documentCount")),
            "publishable": sum(1 for c in calls if c.get("publicationState") == "PUBLISHABLE"),
        },
        "calls": calls,
    }
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text("window.PARTENER_MIPE_CANONICAL_CALLS=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
