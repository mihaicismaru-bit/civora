#!/usr/bin/env python3
"""Final deterministic cleanup for PARTENER.EU decision products."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "partener-eu" / "ingest" / "state" / "decision_products.json"
OUT_JS = ROOT / "partener-eu" / "web" / "decision-products.js"


def norm(value: Any) -> str:
    text = "".join(ch for ch in unicodedata.normalize("NFKD", str(value or "")) if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9]+", " ", text).lower()).strip()


def urls(dossier: dict[str, Any]) -> set[str]:
    return {source.get("url") for source in dossier.get("sources") or [] if source.get("url")}


def merge(target: dict[str, Any], duplicate: dict[str, Any]) -> None:
    seen = urls(target)
    for source in duplicate.get("sources") or []:
        if source.get("url") and source["url"] not in seen:
            target.setdefault("sources", []).append(source)
            seen.add(source["url"])
    timeline_seen = {(row.get("date"), row.get("kind"), row.get("text")) for row in target.get("timeline") or []}
    for row in duplicate.get("timeline") or []:
        key = (row.get("date"), row.get("kind"), row.get("text"))
        if key not in timeline_seen:
            target.setdefault("timeline", []).append(row)
            timeline_seen.add(key)
    target.setdefault("sourceLinks", []).extend(duplicate.get("sourceLinks") or [])


def same_opportunity(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if urls(a) & urls(b):
        return True
    title_a, title_b = norm(a.get("title")), norm(b.get("title"))
    if title_a == "schema de energie" and all(token in title_b for token in ("energie", "autoconsum")):
        return True
    if title_b == "schema de energie" and all(token in title_a for token in ("energie", "autoconsum")):
        return True
    code_a, code_b = norm(a.get("code")), norm(b.get("code"))
    if code_a and code_b and code_a not in {"—", ""} and code_a == code_b:
        return True
    return False


def main() -> int:
    payload = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    dossiers = payload.get("dossiers") or []
    canonical = [row for row in dossiers if not row.get("sourceType", "").endswith("PROVISIONAL")]
    provisional = [row for row in dossiers if row.get("sourceType", "").endswith("PROVISIONAL")]
    kept = list(canonical)
    merged_ids: list[str] = []

    for candidate in provisional:
        target = next((row for row in canonical if same_opportunity(candidate, row)), None)
        if target:
            merge(target, candidate)
            merged_ids.append(candidate.get("id"))
        else:
            kept.append(candidate)

    rank = {"OPEN": 0, "EXPECTED": 1, "PUBLIC_CONSULTATION": 2, "REVIEW": 3, "CLOSED": 6}
    kept.sort(key=lambda row: (rank.get(row.get("status"), 4), -(row.get("quality", {}).get("completeness") or 0), row.get("title") or ""))
    valid = {row.get("id") for row in kept}
    news = [row for row in payload.get("news") or [] if not row.get("dossierId") or row.get("dossierId") in valid]

    payload["dossiers"] = kept
    payload["news"] = news
    quality = payload.setdefault("qualityPass", {})
    previous = set(quality.get("mergedIds") or [])
    previous.update(merged_ids)
    quality["mergedIds"] = sorted(previous)
    quality["duplicateDossiersMerged"] = len(previous)
    payload.setdefault("coverage", {}).setdefault("afir", {})["mergedDuplicates"] = len(previous)
    payload["coverage"]["afir"]["publishedDossiers"] = sum(
        1
        for row in kept
        if row.get("sourceType", "").startswith("AFIR_")
        or any("afir.ro" in str(source.get("url")) for source in row.get("sources") or [])
    )
    payload.setdefault("summary", {}).update({
        "dossierCount": len(kept),
        "openCount": sum(1 for row in kept if row.get("status") == "OPEN"),
        "prepareCount": sum(1 for row in kept if row.get("status") in {"EXPECTED", "PUBLIC_CONSULTATION", "REVIEW"}),
        "newsCount": len(news),
        "highCompletenessCount": sum(1 for row in kept if row.get("quality", {}).get("completeness", 0) >= 70),
    })
    payload["home"] = {
        "openDossierIds": [row["id"] for row in kept if row.get("status") == "OPEN" and row.get("quality", {}).get("completeness", 0) >= 40][:8],
        "prepareDossierIds": [row["id"] for row in kept if row.get("status") in {"EXPECTED", "PUBLIC_CONSULTATION", "REVIEW"}][:8],
        "changeNewsIds": [row["id"] for row in news[:8]],
    }

    PRODUCTS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text(
        "window.PARTENER_DECISION_PRODUCTS="
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\nwindow.PARTENER_DATA=window.PARTENER_DATA||{};\n"
        + "window.PARTENER_DATA.decisionProducts=window.PARTENER_DECISION_PRODUCTS;\n",
        encoding="utf-8",
    )
    print(json.dumps({"dossiers": len(kept), "merged": merged_ids}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
