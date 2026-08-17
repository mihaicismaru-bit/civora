#!/usr/bin/env python3
"""Remove AFIR document-level pseudo-dossiers while preserving real interventions."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "partener-eu/ingest/state/decision_products.json"
OUT_JS = ROOT / "partener-eu/web/decision-products.js"

ADMIN = (
    "rof selectie", "rof selecție", "contestatii", "contestații", "manual de procedura",
    "manual de procedură", "procedura de selectie", "procedură de selecție", "ordin madr",
    "omadr", "regulament de organizare", "metodologie de selectie", "metodologie de selecție",
    "fisa postului", "fișa postului", "organigrama", "raport anual",
)
STRONG_CALL_TERMS = (
    "schema de energie", "investalim", "transfer de cunostinte", "transfer de cunoștințe",
    "sesiune depunere", "sesiune primire", "interventie", "intervenție", "apel de proiecte",
    "ghidul solicitantului",
)
FILELIKE = re.compile(r"\.(?:pdf|docx?|xlsx?|zip|rar|7z)$", re.I)
DR_CODE = re.compile(r"(?:^|\b)dr[-\s]?\d{1,3}(?:\b|$)", re.I)


def fold(value: Any) -> str:
    text = "".join(ch for ch in unicodedata.normalize("NFKD", str(value or "")) if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9.-]+", " ", text.lower()).strip()


def keep(dossier: dict[str, Any]) -> tuple[bool, str]:
    if not str(dossier.get("sourceType") or "").startswith("AFIR"):
        return True, "NOT_AFIR"
    title = fold(dossier.get("title"))
    code = fold(dossier.get("code"))
    title_has_call_identity = bool(DR_CODE.search(title) or DR_CODE.search(code)) or any(
        fold(term) in title for term in STRONG_CALL_TERMS
    )
    administrative = any(fold(term) in title for term in ADMIN)
    file_like = bool(FILELIKE.search(title)) or title.startswith((
        "omadr-", "ordin-", "manual-", "procedura-", "metodologie-", "rof-"
    ))
    if administrative and not title_has_call_identity:
        return False, "ADMINISTRATIVE_DOCUMENT"
    if file_like and not title_has_call_identity:
        return False, "FILE_LEVEL_EVIDENCE_NOT_CALL"
    return True, "CALL_OR_INTERVENTION"


def main() -> int:
    products = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    kept = []
    removed = []
    for dossier in products.get("dossiers") or []:
        ok, reason = keep(dossier)
        if ok:
            kept.append(dossier)
        else:
            removed.append({
                "id": dossier.get("id"), "title": dossier.get("title"), "reason": reason,
                "sources": [s.get("url") for s in dossier.get("sources") or [] if s.get("url")][:10],
            })
    products["dossiers"] = kept
    valid_ids = {d.get("id") for d in kept}
    home = products.setdefault("home", {})
    for key in ("openDossierIds", "prepareDossierIds"):
        home[key] = [x for x in home.get(key) or [] if x in valid_ids]
    summary = products.setdefault("summary", {})
    summary["dossierCount"] = len(kept)
    summary["openCount"] = sum(1 for d in kept if d.get("status") == "OPEN")
    summary["prepareCount"] = sum(1 for d in kept if d.get("status") in {"EXPECTED", "PUBLIC_CONSULTATION", "REVIEW"})
    summary["highCompletenessCount"] = sum(1 for d in kept if (d.get("quality", {}).get("completeness") or 0) >= 70)
    afir = products.setdefault("coverage", {}).setdefault("afir", {})
    afir["administrativeDossiersRemoved"] = len(removed)
    afir["publishedDossiers"] = sum(1 for d in kept if str(d.get("sourceType") or "").startswith("AFIR") or "AFIR" in str(d.get("programme") or "").upper())

    # This cleanup changes the final public dossier cardinality. Any aggregate
    # contract coverage computed by an earlier stage must therefore be
    # recomputed here against the final kept set, rather than left stale.
    quality = products.setdefault("qualityPass", {})
    quality["afirAdministrativeDossiersRemoved"] = removed
    quality["executiveSummaryCoverage"] = sum(
        1 for dossier in kept if dossier.get("executiveSummary")
    )
    quality["strictApplicantListCoverage"] = sum(
        1
        for dossier in kept
        if (dossier.get("quality") or {}).get("applicantListPolicy") == "GUIDE_EXPLICIT_ONLY"
    )

    products.setdefault("policy", {})["afirDocumentsAreEvidenceNotCalls"] = True
    PRODUCTS.write_text(json.dumps(products, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text(
        "window.PARTENER_DECISION_PRODUCTS=" + json.dumps(products, ensure_ascii=False, separators=(",", ":"))
        + ";\nwindow.PARTENER_DATA=window.PARTENER_DATA||{};\nwindow.PARTENER_DATA.decisionProducts=window.PARTENER_DECISION_PRODUCTS;\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "kept": len(kept),
        "removed": len(removed),
        "executiveSummaryCoverage": quality["executiveSummaryCoverage"],
        "strictApplicantListCoverage": quality["strictApplicantListCoverage"],
        "sample": removed[:8],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
