#!/usr/bin/env python3
"""Build the canonical PARTENER.EU funding-call lifecycle registry.

The lifecycle registry follows every identified call from first discovery and
public consultation through final guide, launch, submission, evaluation,
results, contracting and completion. It consumes only already-ingested official
sources and preserves unknowns instead of inferring administrative facts.

The Consultant workspace is intentionally not an input. It is a downstream
consumer of this registry.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
DECISION_PATH = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
MIPE_PATH = ROOT / "partener-eu" / "ingest" / "state" / "mipe_state.json"
AFIR_PATH = ROOT / "partener-eu" / "ingest" / "state" / "afir_corpus.json"
MYSMIS_PATH = ROOT / "partener-eu" / "web" / "mysmis-registry.js"
PREVIOUS_PATH = ROOT / "partener-eu" / "ingest" / "state" / "call_lifecycle.json"
OUT_PATH = PREVIOUS_PATH
OUT_JS = ROOT / "partener-eu" / "web" / "call-lifecycle.js"

STAGES = [
    "DISCOVERED",
    "CONSULTATION",
    "FINAL_GUIDE",
    "ANNOUNCED",
    "OPEN",
    "CLOSED",
    "EVALUATION",
    "RESULTS",
    "CONTRACTING",
    "COMPLETED",
]
STAGE_RANK = {stage: idx for idx, stage in enumerate(STAGES)}
STAGE_LABELS = {
    "DISCOVERED": "Identificat",
    "CONSULTATION": "În consultare",
    "FINAL_GUIDE": "Ghid final",
    "ANNOUNCED": "Anunțat",
    "OPEN": "Deschis",
    "CLOSED": "Închis pentru depunere",
    "EVALUATION": "În evaluare",
    "RESULTS": "Rezultate publicate",
    "CONTRACTING": "În contractare",
    "COMPLETED": "Finalizat",
}
EVENT_STAGE = {
    "CONSULTATION_OPENED": "CONSULTATION",
    "GUIDE_PUBLISHED": "FINAL_GUIDE",
    "GUIDE_UPDATED_AFTER_CONSULTATION": "FINAL_GUIDE",
    "GUIDE_MODIFIED": "FINAL_GUIDE",
    "CALL_ANNOUNCED": "ANNOUNCED",
    "CALL_OPENED": "OPEN",
    "CALL_CLOSED": "CLOSED",
    "EVALUATION_STARTED": "EVALUATION",
    "RESULTS_PUBLISHED": "RESULTS",
    "CONTRACTING_STARTED": "CONTRACTING",
    "CONTRACTS_PUBLISHED": "CONTRACTING",
    "CALL_COMPLETED": "COMPLETED",
}
STATUS_STAGE = {
    "PUBLIC_CONSULTATION": "CONSULTATION",
    "EXPECTED": "ANNOUNCED",
    "ANNOUNCED": "ANNOUNCED",
    "OPEN": "OPEN",
    "CLOSED": "CLOSED",
    "CANCELLED": "CLOSED",
    "SUSPENDED": "CLOSED",
    "REVIEW": "DISCOVERED",
    "DISCOVERED": "DISCOVERED",
}
NEXT_EVENTS = {
    "DISCOVERED": ["consultare publică", "ghid al solicitantului", "calendar estimativ"],
    "CONSULTATION": ["închiderea consultării", "ghid final", "ordin de aprobare", "lansarea apelului"],
    "FINAL_GUIDE": ["data lansării", "deschiderea MySMIS", "corrigendum", "clarificări"],
    "ANNOUNCED": ["ghid final", "deschiderea apelului", "MySMIS", "corrigendum"],
    "OPEN": ["corrigendum", "prelungire termen", "clarificări", "închiderea depunerii"],
    "CLOSED": ["începerea evaluării", "liste intermediare", "contestații", "rezultate"],
    "EVALUATION": ["rezultate intermediare", "contestații", "rezultate finale", "contractare"],
    "RESULTS": ["liste finale", "contracte", "beneficiari", "proiecte selectate"],
    "CONTRACTING": ["contracte semnate", "beneficiari contractați", "stadiu implementare"],
    "COMPLETED": ["corecții ale listelor", "rezultate finale consolidate", "indicatori de implementare"],
}
RESULT_WORDS = (
    "rezultat", "selecție", "selectie", "câștigător", "castigator",
    "lista proiectelor", "proiecte aprobate", "proiecte selectate",
    "lista beneficiarilor", "contracte semnate", "contestații", "contestatii",
)
STOPWORDS = {
    "apel", "program", "proiect", "proiecte", "pentru", "privind", "sprijin", "regiunea",
    "regiuni", "finantare", "finanțare", "investitii", "investiții", "actiunea", "acțiunea",
    "masura", "măsura", "componenta", "dezvoltare", "fonduri", "europene", "romania", "românia",
    "prin", "din", "si", "și", "ale", "sau", "unei", "unui", "cadrul",
}


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_mysmis() -> dict[str, Any]:
    try:
        text = MYSMIS_PATH.read_text(encoding="utf-8")
        marker = "window.PARTENER_DATA.mysmisRegistry="
        if marker not in text:
            return {}
        return json.loads(text.split(marker, 1)[1].rsplit(";", 1)[0])
    except Exception:
        return {}


def norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(value: Any) -> set[str]:
    return {t for t in norm(value).split() if len(t) >= 3 and t not in STOPWORDS}


def source_host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def evidence_id(*parts: Any) -> str:
    return hashlib.sha256("\n".join(str(x or "") for x in parts).encode()).hexdigest()[:18]


def stage_from_dossier(dossier: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    status = str(dossier.get("status") or "REVIEW").upper()
    base = STATUS_STAGE.get(status, "DISCOVERED")
    candidates.append((STAGE_RANK[base], base, {"type": "DOSSIER_STATUS", "value": status}))
    for event in dossier.get("timeline") or []:
        kind = str(event.get("kind") or "").upper()
        stage = EVENT_STAGE.get(kind)
        if stage:
            candidates.append((STAGE_RANK[stage], stage, {
                "type": "OFFICIAL_EVENT",
                "kind": kind,
                "date": event.get("date"),
                "text": event.get("text"),
            }))
    rank, stage, evidence = max(candidates, key=lambda row: row[0])
    return stage, [row[2] for row in candidates if row[1] == stage]


def mysmis_match(dossier: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any] | None:
    title = norm(dossier.get("title"))
    if not title:
        return None
    dt = tokens(title)
    if len(dt) < 2:
        return None
    best: tuple[float, dict[str, Any]] | None = None
    for row in registry.get("calls") or []:
        candidate = norm(row.get("call"))
        ct = tokens(candidate)
        if not ct:
            continue
        common = len(dt & ct)
        containment = common / max(1, min(len(dt), len(ct)))
        jaccard = common / max(1, len(dt | ct))
        exactish = len(title) >= 20 and (title in candidate or candidate in title)
        score = 1.0 if exactish else (containment * 0.72 + jaccard * 0.28)
        if common < 3 and not exactish:
            continue
        if score < 0.72:
            continue
        if best is None or score > best[0]:
            best = (score, row)
    if not best:
        return None
    score, row = best
    return {"confidence": round(score, 3), **row}


def advance_with_mysmis(stage: str, match: dict[str, Any] | None) -> tuple[str, list[dict[str, Any]]]:
    if not match:
        return stage, []
    evidence = [{
        "type": "MYSMIS_PUBLIC_REGISTRY",
        "officialStatus": match.get("officialStatus"),
        "submitted": match.get("submitted"),
        "contracts": match.get("contracts"),
        "withdrawn": match.get("withdrawn"),
        "confidence": match.get("confidence"),
    }]
    status = norm(match.get("officialStatus"))
    contracts = int(str(match.get("contracts") or "0").replace(".", "") or 0)
    submitted = int(str(match.get("submitted") or "0").replace(".", "") or 0)
    target = stage
    if "finalizat" in status:
        target = "COMPLETED"
    elif contracts > 0:
        target = "CONTRACTING"
    elif submitted > 0 and STAGE_RANK.get(stage, 0) >= STAGE_RANK["CLOSED"]:
        target = "EVALUATION"
    if STAGE_RANK[target] > STAGE_RANK[stage]:
        return target, evidence
    return stage, evidence


def result_sources(dossier: dict[str, Any], afir: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    # A source supporting the fact-class `beneficiaries` is about eligibility,
    # not about winners. Only explicit result/selection/contract language counts.
    for source in dossier.get("sources") or []:
        label = str(source.get("label") or "")
        if norm(label).startswith("evidenta oficiala"):
            continue
        hay = norm(f"{label} {source.get('url')}")
        if any(norm(word) in hay for word in RESULT_WORDS):
            candidates.append({
                "label": label or "Rezultate / proiecte selectate",
                "url": source.get("url"),
                "tier": source.get("tier") or "T1",
                "observedAt": source.get("observedAt"),
            })

    # AFIR navigation contains generic Beneficiari/Contracte links on almost
    # every page. They are not call-specific. Accept AFIR evidence only when the
    # page itself is explicitly a result/selection page and matches the dossier.
    dtitle = tokens(dossier.get("title"))
    if dossier.get("sourceType") == "AFIR_PROVISIONAL" or "AFIR" in str(dossier.get("programme") or "").upper():
        for item in afir.get("items") or []:
            title = str(item.get("title") or "")
            title_norm = norm(title)
            if not any(norm(word) in title_norm for word in RESULT_WORDS):
                continue
            it = tokens(title)
            if dtitle and it and len(dtitle & it) / max(1, min(len(dtitle), len(it))) < 0.45:
                continue
            url = item.get("url")
            if url:
                candidates.append({
                    "label": title or "Rezultate AFIR",
                    "url": url,
                    "tier": "T1",
                    "observedAt": item.get("observedAt"),
                })
            for link in item.get("documentLinks") or []:
                hay = norm(f"{link.get('name')} {link.get('url')}")
                if any(norm(word) in hay for word in RESULT_WORDS):
                    candidates.append({
                        "label": link.get("name") or "Listă oficială rezultate",
                        "url": link.get("url"),
                        "tier": "T1",
                        "observedAt": item.get("observedAt"),
                    })
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in candidates:
        url = row.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(row)
    return out[:20]


def lifecycle_history(previous: dict[str, Any], dossier_id: str, stage: str, observed_at: str) -> list[dict[str, Any]]:
    prior = next((x for x in previous.get("calls") or [] if x.get("dossierId") == dossier_id), None)
    history = list(prior.get("transitions") or []) if prior else []
    old_stage = prior.get("stage") if prior else None
    if not history:
        history.append({"observedAt": observed_at, "from": None, "to": stage, "reason": "INITIAL_CANONICAL_PROJECTION"})
    elif old_stage != stage:
        history.append({"observedAt": observed_at, "from": old_stage, "to": stage, "reason": "NEW_OFFICIAL_EVIDENCE"})
    return history[-50:]


def monitoring_priority(stage: str) -> str:
    if stage in {"CONSULTATION", "FINAL_GUIDE", "ANNOUNCED", "OPEN", "EVALUATION", "RESULTS"}:
        return "HIGH"
    if stage in {"CLOSED", "CONTRACTING"}:
        return "MEDIUM"
    return "LOW"


def main() -> int:
    decision = read_json(DECISION_PATH, {})
    mipe = read_json(MIPE_PATH, {})
    afir = read_json(AFIR_PATH, {})
    mysmis = load_mysmis()
    previous = read_json(PREVIOUS_PATH, {})
    observed_at = str(decision.get("generatedAt") or mipe.get("lastRun", {}).get("observedAt") or afir.get("generatedAt") or "")

    calls: list[dict[str, Any]] = []
    for dossier in decision.get("dossiers") or []:
        stage, stage_evidence = stage_from_dossier(dossier)
        match = mysmis_match(dossier, mysmis) if mysmis.get("status") == "OK_DIRECT" else None
        stage, mysmis_evidence = advance_with_mysmis(stage, match)
        result_links = result_sources(dossier, afir)
        if result_links and STAGE_RANK[stage] < STAGE_RANK["RESULTS"] and any(
            str(e.get("kind") or "").upper() == "RESULTS_PUBLISHED" for e in dossier.get("timeline") or []
        ):
            stage = "RESULTS"
        prior_call = next((x for x in previous.get("calls") or [] if x.get("dossierId") == dossier.get("id")), None)
        prior_stage = str(prior_call.get("stage") or "") if prior_call else ""
        if prior_stage in STAGE_RANK and STAGE_RANK[prior_stage] > STAGE_RANK[stage]:
            stage_evidence.append({
                "type": "MONOTONIC_HISTORY_PRESERVED",
                "previousStage": prior_stage,
                "candidateStage": stage,
                "reason": "Lipsa unei evidențe în snapshotul curent nu retrage o etapă administrativă confirmată anterior.",
            })
            stage = prior_stage
        source_urls = [s.get("url") for s in dossier.get("sources") or [] if s.get("url")]
        source_urls += [x.get("url") for x in result_links if x.get("url")]
        source_urls = list(dict.fromkeys(source_urls))[:30]
        result_tracking = {
            "winnerListConfirmed": bool(result_links and any(
                str(e.get("kind") or "").upper() == "RESULTS_PUBLISHED" for e in dossier.get("timeline") or []
            )),
            "winnerSources": result_links,
            "mysmis": None,
        }
        if match:
            result_tracking["mysmis"] = {
                "officialStatus": match.get("officialStatus"),
                "submitted": match.get("submitted"),
                "contracts": match.get("contracts"),
                "withdrawn": match.get("withdrawn"),
                "budgetRon": match.get("callBudgetRon"),
                "matchConfidence": match.get("confidence"),
                "note": "MySMIS confirmă agregate administrative; nu reprezintă o listă nominală de câștigători.",
            }
        calls.append({
            "id": evidence_id("lifecycle", dossier.get("id")),
            "dossierId": dossier.get("id"),
            "title": dossier.get("title"),
            "programme": dossier.get("programme"),
            "code": dossier.get("code"),
            "region": dossier.get("region"),
            "stage": stage,
            "stageLabel": STAGE_LABELS[stage],
            "maturityRank": STAGE_RANK[stage],
            "publicationState": dossier.get("publicationState"),
            "dossierCompleteness": dossier.get("quality", {}).get("completeness"),
            "stageEvidence": stage_evidence + mysmis_evidence,
            "transitions": lifecycle_history(previous, str(dossier.get("id")), stage, observed_at),
            "results": result_tracking,
            "monitoring": {
                "active": stage != "COMPLETED",
                "priority": monitoring_priority(stage),
                "nextExpectedEvents": NEXT_EVENTS[stage],
                "officialSources": source_urls,
                "officialHosts": list(dict.fromkeys(source_host(u) for u in source_urls if source_host(u))),
                "failClosed": True,
                "rule": "Etapa avansează numai pe evidență oficială explicită sau pe registrul public MySMIS cu potrivire de titlu peste pragul conservator.",
            },
            "updatedAt": observed_at,
        })

    summary = {stage: sum(1 for row in calls if row["stage"] == stage) for stage in STAGES}
    summary.update({
        "callCount": len(calls),
        "activelyMonitored": sum(1 for row in calls if row["monitoring"]["active"]),
        "withMySMISEvidence": sum(1 for row in calls if row["results"]["mysmis"]),
        "withWinnerSources": sum(1 for row in calls if row["results"]["winnerSources"]),
        "confirmedWinnerLists": sum(1 for row in calls if row["results"]["winnerListConfirmed"]),
    })
    payload = {
        "schemaVersion": 1,
        "generatedAt": observed_at,
        "policy": {
            "lifecycleFirst": True,
            "consultantIsDownstreamConsumer": True,
            "trackFromConsultationThroughResults": True,
            "winnerListsRequireExplicitOfficialEvidence": True,
            "mysmisAggregatesAreNotWinnerLists": True,
            "failClosed": True,
        },
        "summary": summary,
        "calls": calls,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text("window.PARTENER_CALL_LIFECYCLE=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
