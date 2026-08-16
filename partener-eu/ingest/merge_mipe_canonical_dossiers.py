#!/usr/bin/env python3
"""Merge canonical MIPE call objects into PARTENER.EU decision products.

This is the publication bridge: canonical call identity is resolved first, then
one dossier is created or enriched. Raw crawl pages never become independent
public dossiers when they belong to the same financing call.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
INGEST_DIR = ROOT / "partener-eu/ingest"
sys.path.insert(0, str(INGEST_DIR))
import build_decision_products as bdp  # noqa: E402

CANONICAL = ROOT / "partener-eu/ingest/state/mipe_canonical_calls.json"
PRODUCTS = ROOT / "partener-eu/ingest/state/decision_products.json"
OUT_JS = ROOT / "partener-eu/web/decision-products.js"


def source_key(source: dict[str, Any]) -> str:
    return str(source.get("url") or "")


def merge_sections(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    by_title = {s.get("title"): s for s in target.get("sections") or []}
    for section in incoming.get("sections") or []:
        title = section.get("title")
        if not title:
            continue
        current = by_title.get(title)
        if current is None:
            target.setdefault("sections", []).append(section)
            by_title[title] = section
            continue
        current_real = [] if current.get("empty") else list(current.get("items") or [])
        incoming_real = [] if section.get("empty") else list(section.get("items") or [])
        if incoming_real:
            combined = []
            seen = set()
            for item in [*current_real, *incoming_real]:
                key = bdp.norm_text(item)
                if not key or key in seen:
                    continue
                seen.add(key); combined.append(item)
            current["items"] = combined[:40]
            current["empty"] = False


def merge_quickfacts(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    by_label = {x.get("label"): x for x in target.get("quickFacts") or []}
    for fact in incoming.get("quickFacts") or []:
        label = fact.get("label")
        if not label:
            continue
        current = by_label.get(label)
        if current is None:
            target.setdefault("quickFacts", []).append(fact)
            by_label[label] = fact
            continue
        current_unknown = current.get("confidence") in {"UNKNOWN", "REVIEW", None} or current.get("value") in {None, "", "Neconfirmat"}
        incoming_good = fact.get("confidence") not in {"UNKNOWN", "REVIEW", None} and fact.get("value") not in {None, "", "Neconfirmat"}
        if current_unknown and incoming_good:
            current.update(fact)


def merge_dossier(target: dict[str, Any], incoming: dict[str, Any], call: dict[str, Any], score: float) -> None:
    # Sources and timeline are additive and deduplicated.
    existing_sources = {source_key(x) for x in target.get("sources") or []}
    for source in incoming.get("sources") or []:
        if source_key(source) and source_key(source) not in existing_sources:
            target.setdefault("sources", []).append(source)
            existing_sources.add(source_key(source))
    timeline_seen = {(x.get("kind"), x.get("text"), x.get("date")) for x in target.get("timeline") or []}
    for row in incoming.get("timeline") or []:
        key = (row.get("kind"), row.get("text"), row.get("date"))
        if key not in timeline_seen:
            target.setdefault("timeline", []).append(row); timeline_seen.add(key)

    merge_sections(target, incoming)
    merge_quickfacts(target, incoming)
    target.setdefault("canonicalLinks", []).append({
        "source": "MIPE_CANONICAL_V1", "callId": call.get("id"), "matchScore": round(score, 3)
    })

    tq = target.setdefault("quality", {})
    iq = incoming.get("quality") or {}
    verified = sorted(set((tq.get("verifiedFactClasses") or []) + (iq.get("verifiedFactClasses") or [])))
    tq["verifiedFactClasses"] = verified
    tq["blockedFactClasses"] = [x for x in bdp.CRITICAL_FACTS if x not in verified]
    tq["completeness"] = round(100 * len(set(verified) & set(bdp.CRITICAL_FACTS)) / len(bdp.CRITICAL_FACTS))
    tq["evidenceCount"] = len(target.get("sources") or [])
    tq["failClosed"] = True

    # Fresh explicit MIPE lifecycle evidence may advance stale generic states.
    rank = {"REVIEW": 0, "EXPECTED": 1, "PUBLIC_CONSULTATION": 2, "OPEN": 3, "CLOSED": 4}
    if rank.get(call.get("status"), 0) > rank.get(target.get("status"), 0):
        target["status"] = call.get("status")
        label, decision, action = bdp.status_view(call.get("status"))
        target["statusLabel"] = label; target["decision"] = decision; target["decisionAction"] = action
    target["updatedAt"] = max(str(target.get("updatedAt") or ""), str(call.get("asOf") or ""))


def main() -> int:
    products = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    canonical = json.loads(CANONICAL.read_text(encoding="utf-8"))
    dossiers = products.get("dossiers") or []
    coverage = products.setdefault("coverage", {}).setdefault("mipe", {})
    coverage.update({"candidates": len(canonical.get("calls") or []), "matched": 0, "provisional": 0, "canonical": len(canonical.get("calls") or [])})

    for call in canonical.get("calls") or []:
        incoming = bdp.build_p11_dossier(call, products.get("generatedAt"))
        incoming["sourceType"] = "MIPE_CANONICAL_V1"
        incoming["canonicalGroup"] = call.get("canonicalGroup")
        incoming["publicationState"] = call.get("publicationState") or incoming.get("publicationState")
        match, score = bdp.best_match(call.get("title") or "", dossiers, None if call.get("code") == "—" else call.get("code"))
        # Never self-match a dossier just appended by this loop under an unrelated weak title.
        if match and score >= 0.46:
            coverage["matched"] += 1
            merge_dossier(match, incoming, call, score)
        else:
            dossiers.append(incoming)
            coverage["provisional"] += 1

    # Deduplicate only on canonical id and then sort using public status semantics.
    by_id: dict[str, dict[str, Any]] = {}
    for dossier in dossiers:
        by_id[dossier["id"]] = dossier
    dossiers = list(by_id.values())
    rank = {"OPEN": 0, "PUBLIC_CONSULTATION": 1, "EXPECTED": 2, "REVIEW": 3, "CLOSED": 6}
    dossiers.sort(key=lambda d: (rank.get(d.get("status"), 4), -(d.get("quality", {}).get("completeness") or 0), d.get("title") or ""))
    products["dossiers"] = dossiers
    products["summary"]["dossierCount"] = len(dossiers)
    products["summary"]["openCount"] = sum(1 for d in dossiers if d.get("status") == "OPEN")
    products["summary"]["prepareCount"] = sum(1 for d in dossiers if d.get("status") in {"EXPECTED", "PUBLIC_CONSULTATION", "REVIEW"})
    products["summary"]["highCompletenessCount"] = sum(1 for d in dossiers if (d.get("quality", {}).get("completeness") or 0) >= 70)
    products["home"]["openDossierIds"] = [d["id"] for d in dossiers if d.get("status") == "OPEN" and (d.get("quality", {}).get("completeness") or 0) >= 40][:8]
    products["home"]["prepareDossierIds"] = [d["id"] for d in dossiers if d.get("status") in {"EXPECTED", "PUBLIC_CONSULTATION", "REVIEW"}][:8]
    products.setdefault("policy", {})["mipeCanonicalBeforePublication"] = True
    products["policy"]["groupPagesCorrigendaDocumentsPerCall"] = True

    PRODUCTS.write_text(json.dumps(products, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text(
        "window.PARTENER_DECISION_PRODUCTS=" + json.dumps(products, ensure_ascii=False, separators=(",", ":"))
        + ";\nwindow.PARTENER_DATA=window.PARTENER_DATA||{};\nwindow.PARTENER_DATA.decisionProducts=window.PARTENER_DECISION_PRODUCTS;\n",
        encoding="utf-8",
    )
    print(json.dumps({"summary": products["summary"], "mipeCoverage": coverage}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
