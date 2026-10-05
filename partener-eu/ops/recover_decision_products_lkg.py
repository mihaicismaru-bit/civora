#!/usr/bin/env python3
"""Recover missing public dossiers from the strongest recent localized LKG."""
from __future__ import annotations

import argparse
import copy
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


def recover_or_preserve(current: dict[str, Any], historical: dict[str, Any] | None, source_sha: str | None, allow_dossier_resurrection: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    """Preserve current canonical membership unless an emergency override is explicit."""
    if not localized(current):
        raise RuntimeError("current decision-products projection is not localized/public-safe")
    current_dossiers = list(current.get("dossiers") or [])
    if not current_dossiers:
        raise RuntimeError("current decision-products projection has zero dossiers")

    current_ids = {str(row.get("id")) for row in current_dossiers if row.get("id")}
    historical_ids = {str(row.get("id")) for row in ((historical or {}).get("dossiers") or []) if row.get("id")}
    missing_historical_ids = sorted(historical_ids - current_ids)
    before = len(current_dossiers)

    if allow_dossier_resurrection:
        if historical is None or source_sha is None:
            raise RuntimeError("explicit dossier resurrection requested but no localized historical LKG is available")
        merged = merge_lkg(current, historical, source_sha)
        return merged, {
            "status": "RECOVERED_EXPLICIT_OVERRIDE" if len(merged.get("dossiers") or []) > before else "CURRENT_LKG_PRESERVED",
            "sourceCommit": source_sha,
            "beforeDossiers": before,
            "afterDossiers": len(merged.get("dossiers") or []),
            "historicalMissingDossierCount": len(missing_historical_ids),
            "protectedDossiers": protected_count(merged),
            "automaticResurrection": False,
            "explicitOverride": True,
        }

    current.setdefault("policy", {})["lastKnownGoodRecovery"] = {
        "sourceCommit": source_sha,
        "recoveredDossierCount": 0,
        "historicalMissingDossierCount": len(missing_historical_ids),
        "preservedCurrentDossiers": True,
        "mode": "PRESERVE_CURRENT_FAIL_CLOSED",
        "automaticResurrectionAllowed": False,
    }
    return current, {
        "status": "CURRENT_LKG_PRESERVED",
        "sourceCommit": source_sha,
        "beforeDossiers": before,
        "afterDossiers": before,
        "historicalMissingDossierCount": len(missing_historical_ids),
        "protectedDossiers": protected_count(current),
        "automaticResurrection": False,
        "explicitOverride": False,
    }


def run_self_test() -> int:
    policy = {"romanianPublicLanguage": True, "rawStructuredObjectsVisible": False}
    current = {
        "policy": dict(policy),
        "dossiers": [{"id": "current-a", "sourceType": "MIPE_CANONICAL_V1", "quickFacts": []}],
        "news": [{"id": "news-current", "date": "2026-10-05", "utilityScore": 10}],
        "home": {"prepareDossierIds": ["current-a"]},
    }
    historical = {
        "policy": dict(policy),
        "dossiers": [
            {"id": "current-a", "sourceType": "MIPE_CANONICAL_V1", "quickFacts": []},
            {"id": "historical-b", "sourceType": "MIPE_CANONICAL_V1", "quickFacts": []},
        ],
        "news": [{"id": "news-old", "date": "2026-09-01", "utilityScore": 1}],
        "home": {"prepareDossierIds": ["historical-b"]},
    }
    preserved, diagnostic = recover_or_preserve(copy.deepcopy(current), historical, "test-sha", False)
    assert [row["id"] for row in preserved["dossiers"]] == ["current-a"]
    assert [row["id"] for row in preserved["news"]] == ["news-current"]
    assert preserved["home"]["prepareDossierIds"] == ["current-a"]
    assert diagnostic["historicalMissingDossierCount"] == 1
    recovered, override = recover_or_preserve(copy.deepcopy(current), historical, "test-sha", True)
    assert {row["id"] for row in recovered["dossiers"]} == {"current-a", "historical-b"}
    assert override["status"] == "RECOVERED_EXPLICIT_OVERRIDE"
    print(json.dumps({"status": "PASS", "defaultDossiers": 1, "overrideDossiers": 2}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-limit", type=int, default=80)
    parser.add_argument("--allow-dossier-resurrection", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return run_self_test()

    current = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    candidates = history(args.history_limit)
    source_sha: str | None = None
    strongest: dict[str, Any] | None = None
    if candidates:
        source_sha, strongest = max(
            candidates,
            key=lambda item: (protected_count(item[1]), len(item[1].get("dossiers") or []), str(item[1].get("generatedAt") or "")),
        )

    try:
        output, diagnostic = recover_or_preserve(current, strongest, source_sha, args.allow_dossier_resurrection)
    except RuntimeError as exc:
        raise SystemExit(f"Fail closed: {exc}. Existing deployed Pages LKG must be preserved.") from exc

    PRODUCTS.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    subprocess.run([sys.executable, str(LOCALIZE)], cwd=ROOT, check=True)
    print(json.dumps(diagnostic, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
