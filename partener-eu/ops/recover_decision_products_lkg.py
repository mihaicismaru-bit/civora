#!/usr/bin/env python3
"""Recover missing public dossiers from the strongest recent localized LKG."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
LOCALIZE = ROOT / "partener-eu" / "ingest" / "localize_decision_products.py"
REPO_PATH = "partener-eu/ingest/state/decision_products.json"
AFIR_SOURCE_TYPES = {"AFIR_INGESTED_PROVISIONAL"}


def protected_count(payload: dict[str, Any]) -> int:
    return sum(
        1
        for row in payload.get("dossiers") or []
        if row.get("id") and row.get("sourceType") not in AFIR_SOURCE_TYPES
    )


def localized(payload: dict[str, Any]) -> bool:
    policy = payload.get("policy") or {}
    if policy.get("romanianPublicLanguage") is not True:
        return False
    if policy.get("rawStructuredObjectsVisible") is not False:
        return False
    for dossier in payload.get("dossiers") or []:
        for fact in dossier.get("quickFacts") or []:
            value = fact.get("value")
            text = str(value or "").lstrip()
            if isinstance(value, (dict, list)) or text.startswith(("{", "[")) or "{'" in text:
                return False
    return True


def history(limit: int) -> list[tuple[str, dict[str, Any]]]:
    result = subprocess.run(
        ["git", "log", f"-{limit}", "--format=%H", "--", REPO_PATH],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    rows: list[tuple[str, dict[str, Any]]] = []
    for sha in result.stdout.split():
        shown = subprocess.run(
            ["git", "show", f"{sha}:{REPO_PATH}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if shown.returncode:
            continue
        try:
            payload = json.loads(shown.stdout)
        except json.JSONDecodeError:
            continue
        if localized(payload):
            rows.append((sha, payload))
    return rows


def merge_lkg(current: dict[str, Any], historical: dict[str, Any], source_sha: str) -> dict[str, Any]:
    dossiers = list(current.get("dossiers") or [])
    dossier_ids = {str(row.get("id")) for row in dossiers if row.get("id")}
    recovered_ids: list[str] = []
    for row in historical.get("dossiers") or []:
        dossier_id = str(row.get("id") or "")
        if dossier_id and dossier_id not in dossier_ids:
            dossiers.append(row)
            dossier_ids.add(dossier_id)
            recovered_ids.append(dossier_id)

    news = list(current.get("news") or [])
    news_ids = {str(row.get("id")) for row in news if row.get("id")}
    for row in historical.get("news") or []:
        row_id = str(row.get("id") or "")
        if row_id and row_id not in news_ids:
            news.append(row)
            news_ids.add(row_id)
    news.sort(key=lambda row: (str(row.get("date") or ""), int(row.get("utilityScore") or 0)), reverse=True)
    news = news[:60]

    current["dossiers"] = dossiers
    current["news"] = news
    summary = current.setdefault("summary", {})
    summary.update({
        "dossierCount": len(dossiers),
        "openCount": sum(1 for row in dossiers if row.get("status") == "OPEN"),
        "prepareCount": sum(1 for row in dossiers if row.get("status") in {"EXPECTED", "PUBLIC_CONSULTATION", "REVIEW"}),
        "newsCount": len(news),
        "highCompletenessCount": sum(1 for row in dossiers if (row.get("quality") or {}).get("completeness", 0) >= 70),
        "completeDossierCount": sum(1 for row in dossiers if (row.get("dossierConstruction") or {}).get("level") == "DOSAR COMPLET"),
        "advancedDossierCount": sum(1 for row in dossiers if (row.get("dossierConstruction") or {}).get("level") == "DOSAR AVANSAT"),
        "constructionDossierCount": sum(1 for row in dossiers if (row.get("dossierConstruction") or {}).get("level") == "DOSAR ÎN CONSTRUCȚIE"),
        "identificationDossierCount": sum(1 for row in dossiers if (row.get("dossierConstruction") or {}).get("level") == "DOSAR DE IDENTIFICARE"),
        "needsEnrichmentCount": sum(1 for row in dossiers if (row.get("dossierConstruction") or {}).get("missing")),
    })
    quality_pass = current.setdefault("qualityPass", {})
    quality_pass["executiveSummaryCoverage"] = len(dossiers)
    quality_pass["strictApplicantListCoverage"] = len(dossiers)

    home = current.setdefault("home", {})
    for key, historical_key in (
        ("openDossierIds", "openDossierIds"),
        ("prepareDossierIds", "prepareDossierIds"),
        ("changeNewsIds", "changeNewsIds"),
    ):
        values = list(home.get(key) or [])
        for row_id in (historical.get("home") or {}).get(historical_key) or []:
            if row_id not in values:
                values.append(row_id)
        home[key] = values[:8]

    current.setdefault("policy", {})["lastKnownGoodRecovery"] = {
        "sourceCommit": source_sha,
        "recoveredDossierCount": len(recovered_ids),
        "preservedCurrentDossiers": True,
    }
    return current


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-limit", type=int, default=80)
    args = parser.parse_args()
    current = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    candidates = history(args.history_limit)
    if not candidates:
        raise SystemExit("No localized historical decision-products LKG found")
    source_sha, strongest = max(
        candidates,
        key=lambda item: (protected_count(item[1]), len(item[1].get("dossiers") or []), str(item[1].get("generatedAt") or "")),
    )
    before = len(current.get("dossiers") or [])
    merged = merge_lkg(current, strongest, source_sha)
    PRODUCTS.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    subprocess.run([sys.executable, str(LOCALIZE)], cwd=ROOT, check=True)
    print(json.dumps({
        "status": "RECOVERED" if len(merged.get("dossiers") or []) > before else "CURRENT_LKG_PRESERVED",
        "sourceCommit": source_sha,
        "beforeDossiers": before,
        "afterDossiers": len(merged.get("dossiers") or []),
        "protectedDossiers": protected_count(merged),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
