#!/usr/bin/env python3
"""Temporal-safe finalizer for the Râmnicu Vâlcea gambling explainer.

The v1 dossier enricher builds the sourced article. This finalizer applies the
LOCAL NEWS OS durable-language contract before the article is handed to Live
Newsroom, so an update of an existing canonical story cannot disappear merely
because a relative-time word entered otherwise valid copy.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
CORE = REPO_ROOT / "local-news-os" / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import gambling_dossier_enricher as base  # noqa: E402
from temporal_freshness import durable_story_temporal_violations  # noqa: E402

FACTS = ROOT / "editorial" / "facts_registry.json"
DOSSIER = ROOT / "editorial" / "gambling_ramnicu_2026_dossier.json"
TARGET_ID = base.TARGET_ID

RELATIVE = (
    "dar nu oferă un suport suficient de solid pentru ca VÂLCEA CLAR să publice acum "
    "numele complete ale beneficiarilor sau asociaților."
)
ABSOLUTE = (
    "dar nu oferă un suport suficient de solid pentru publicarea, în versiunea verificată "
    "la 18 august 2026, a numelor complete ale beneficiarilor sau asociaților."
)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def temporal_finalize(target: dict[str, Any]) -> None:
    target["paragraphs"] = [str(value).replace(RELATIVE, ABSOLUTE) for value in target.get("paragraphs") or []]
    kernel = target.get("fact_kernel") if isinstance(target.get("fact_kernel"), dict) else {}
    for claim in kernel.get("claims") or []:
        if isinstance(claim, dict) and isinstance(claim.get("text"), str):
            claim["text"] = claim["text"].replace(RELATIVE, ABSOLUTE)

    violations = durable_story_temporal_violations(target, "ro-RO")
    if violations:
        raise ValueError("durable_temporal_language_violation:" + json.dumps(violations, ensure_ascii=False))
    target.setdefault("dossier_enrichment", {})["durable_temporal_language_checked"] = "2026-08-18"


def enrich(doc: dict[str, Any], dossier: dict[str, Any]) -> bool:
    changed = base.enrich(doc, dossier)
    if not changed:
        return False
    target = next((row for row in doc.get("facts") or [] if row.get("id") == TARGET_ID), None)
    if not isinstance(target, dict):
        return False
    temporal_finalize(target)
    return True


def self_test() -> int:
    sample = {
        "headline": "Material verificat la 18 august 2026",
        "dek": "Documentarea folosește date absolute și rămâne valabilă în arhivă.",
        "paragraphs": ["Sursele nu permit ca VÂLCEA CLAR să publice acum numele complete ale persoanelor."],
        "fact_kernel": {"claims": []},
    }
    sample["paragraphs"][0] = sample["paragraphs"][0].replace(
        "să publice acum numele complete ale persoanelor",
        "să publice, în versiunea verificată la 18 august 2026, numele complete ale persoanelor",
    )
    assert durable_story_temporal_violations(sample, "ro-RO") == []
    dossier = load(DOSSIER)
    assert dossier["target_story_id"] == TARGET_ID
    print("VÂLCEA CLAR gambling dossier temporal-safe enricher v2: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    doc = load(FACTS)
    dossier = load(DOSSIER)
    if not enrich(doc, dossier):
        raise SystemExit("canonical verified gambling fact unavailable")
    target = next(row for row in doc["facts"] if row.get("id") == TARGET_ID)
    violations = durable_story_temporal_violations(target, "ro-RO")
    if violations:
        raise SystemExit(json.dumps({"status": "HOLD", "violations": violations}, ensure_ascii=False))
    if args.check:
        print(json.dumps({"status": "PASS", "story_id": TARGET_ID, "claims": len(target["fact_kernel"]["claims"])}))
        return 0
    FACTS.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "UPDATED", "story_id": TARGET_ID, "claims": len(target["fact_kernel"]["claims"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
