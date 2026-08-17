#!/usr/bin/env python3
"""Score public funding dossiers by analytical depth and build an autonomous queue.

The score is not a probability of approval. It measures how much of the
canonical dossier structure is supported and populated. Missing dimensions are
persisted as an enrichment queue so subsequent ingest cycles know what evidence
to seek next.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "partener-eu/ingest/state/decision_products.json"
QUEUE = ROOT / "partener-eu/ingest/state/dossier_enrichment_queue.json"
OUT_JS = ROOT / "partener-eu/web/decision-products.js"

SECTION_DIMENSIONS = {
    "beneficiaries": "Cine poate aplica",
    "activities": "Ce finanțează și în ce condiții",
    "costs": "Costuri, cofinanțare și ajutor de stat",
    "documents": "Documente de pregătit",
    "scoring": "Cum se punctează",
    "indicators": "Indicatori și obligații",
    "risks": "Riscuri de respingere sau implementare",
    "actions": "Ce trebuie făcut acum",
}


def section_ok(dossier: dict[str, Any], title: str) -> bool:
    row = next((s for s in dossier.get("sections") or [] if s.get("title") == title), None)
    return bool(row and not row.get("empty") and row.get("items"))


def fact_ok(dossier: dict[str, Any], label: str) -> bool:
    row = next((x for x in dossier.get("quickFacts") or [] if x.get("label") == label), None)
    if not row:
        return False
    return row.get("value") not in (None, "", "Neconfirmat", "—") and row.get("confidence") not in {"UNKNOWN", "REVIEW", None}


def priority(dossier: dict[str, Any], score: int) -> int:
    stage_weight = {"OPEN": 100, "PUBLIC_CONSULTATION": 90, "EXPECTED": 80, "REVIEW": 70, "CLOSED": 40}.get(str(dossier.get("status") or "REVIEW"), 50)
    source_weight = 12 if str(dossier.get("sourceType") or "").startswith("MIPE") else (8 if "AFIR" in str(dossier.get("sourceType") or "") else 0)
    return stage_weight + source_weight + (100 - score)


def main() -> int:
    products = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    queue_rows = []
    advanced = complete = construction = identification = 0

    for dossier in products.get("dossiers") or []:
        dimensions = {
            "status": fact_ok(dossier, "Status"),
            "deadline": fact_ok(dossier, "Termen"),
            "financing": fact_ok(dossier, "Grant") or fact_ok(dossier, "Buget") or fact_ok(dossier, "Finanțare"),
            "provenance": bool(dossier.get("sources")),
        }
        for key, title in SECTION_DIMENSIONS.items():
            dimensions[key] = section_ok(dossier, title)
        score = round(100 * sum(dimensions.values()) / len(dimensions))
        missing = [key for key, ok in dimensions.items() if not ok]
        if score >= 90:
            level = "DOSAR COMPLET"
            complete += 1
        elif score >= 70:
            level = "DOSAR AVANSAT"
            advanced += 1
        elif score >= 40:
            level = "DOSAR ÎN CONSTRUCȚIE"
            construction += 1
        else:
            level = "DOSAR DE IDENTIFICARE"
            identification += 1
        quality = dossier.setdefault("quality", {})
        quality["depthCompleteness"] = score
        quality["dossierLevel"] = level
        quality["depthDimensions"] = dimensions
        quality["missingDepthClasses"] = missing
        quality["failClosed"] = True
        dossier["dossierConstruction"] = {
            "autonomous": True,
            "depthCompleteness": score,
            "level": level,
            "missing": missing,
            "nextPass": "SEARCH_OFFICIAL_EVIDENCE" if missing else "MONITOR_LIFECYCLE",
        }
        if missing:
            queue_rows.append({
                "dossierId": dossier.get("id"),
                "title": dossier.get("title"),
                "programme": dossier.get("programme"),
                "sourceType": dossier.get("sourceType"),
                "status": dossier.get("status"),
                "depthCompleteness": score,
                "missing": missing,
                "priority": priority(dossier, score),
                "officialSources": [s.get("url") for s in dossier.get("sources") or [] if s.get("url")][:20],
                "action": "Completează numai din surse oficiale; păstrează necunoscut ce nu poate fi demonstrat.",
            })

    queue_rows.sort(key=lambda x: (-x["priority"], x["depthCompleteness"], x.get("title") or ""))
    summary = products.setdefault("summary", {})
    summary["completeDossierCount"] = complete
    summary["advancedDossierCount"] = advanced
    summary["constructionDossierCount"] = construction
    summary["identificationDossierCount"] = identification
    summary["needsEnrichmentCount"] = len(queue_rows)
    products.setdefault("policy", {})["autonomousDossierConstruction"] = True
    products["policy"]["dossierDepthIsNotApprovalProbability"] = True

    queue_payload = {
        "schemaVersion": 1,
        "generatedAt": products.get("generatedAt"),
        "policy": {
            "officialEvidenceOnly": True,
            "openAndConsultationFirst": True,
            "failClosed": True,
            "depthScoreIsNotApprovalProbability": True,
        },
        "summary": {
            "dossiers": len(products.get("dossiers") or []),
            "complete": complete,
            "advanced": advanced,
            "construction": construction,
            "identification": identification,
            "queued": len(queue_rows),
        },
        "queue": queue_rows[:100],
    }
    PRODUCTS.write_text(json.dumps(products, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    QUEUE.write_text(json.dumps(queue_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text(
        "window.PARTENER_DECISION_PRODUCTS=" + json.dumps(products, ensure_ascii=False, separators=(",", ":"))
        + ";\nwindow.PARTENER_DATA=window.PARTENER_DATA||{};\nwindow.PARTENER_DATA.decisionProducts=window.PARTENER_DECISION_PRODUCTS;\n",
        encoding="utf-8",
    )
    print(json.dumps(queue_payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
