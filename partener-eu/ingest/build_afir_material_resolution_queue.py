#!/usr/bin/env python3
"""Build a deterministic fail-closed queue for AFIR material-change candidates.

The AFIR crawler already detects record-level changes that may affect material
funding facts.  This builder makes those candidates first-class operational
work without promoting any fact.  Every queued item remains blocked until it
is reconciled against authoritative AFIR evidence by a later bounded step.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_CORPUS = ROOT / "state" / "afir_corpus.json"
DEFAULT_OUTPUT = ROOT / "state" / "afir_material_resolution_queue.json"

BLOCKED_FACT_CLASSES = [
    "deadline",
    "eligibility",
    "budget",
    "scoring",
    "beneficiaries",
    "material_call_status",
]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def candidate_from_item(item: dict[str, Any]) -> dict[str, Any]:
    url = str(item.get("url") or "").strip()
    title = str(item.get("title") or url or "AFIR material change").strip()
    fingerprint = str(item.get("sha256") or item.get("fingerprint") or "").strip()
    observed_at = str(item.get("observedAt") or "").strip() or None

    return {
        "sourceId": "AFIR_CORPUS",
        "sourceTier": "T1",
        "title": title,
        "canonicalUrl": url,
        "fingerprint": fingerprint,
        "observedAt": observed_at,
        "status": "OPEN",
        "reason": "AFIR_RECORD_MATERIAL_CHANGE_CANDIDATE",
        "blockedFactClasses": list(BLOCKED_FACT_CLASSES),
        "requiresReconciliation": True,
        "publishMaterialFacts": False,
        "materialFactAction": "RECONCILE_OFFICIAL_AFIR_MATERIAL_CHANGE",
        "lastKnownGoodPolicy": "PRESERVE_UNTIL_RECONCILED",
    }


def build_queue(corpus: dict[str, Any]) -> dict[str, Any]:
    items = corpus.get("items") or []
    if not isinstance(items, list):
        raise ValueError("AFIR corpus items must be a list")

    candidates: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("materialChangeCandidate") is True:
            candidates.append(candidate_from_item(item))

    candidates.sort(key=lambda row: (row["canonicalUrl"], row["fingerprint"], row["title"]))
    generated_at = corpus.get("generatedAt") or corpus.get("lastSuccessfulAt") or corpus.get("lastRun", {}).get("observedAt")

    return {
        "schemaVersion": 1,
        "source": "AFIR",
        "generatedAt": generated_at,
        "policy": {
            "purpose": "record-level-material-change-resolution",
            "failClosed": True,
            "materialFactsAutopromoted": False,
            "lastKnownGoodPreservedUntilReconciled": True,
        },
        "summary": {
            "candidateCount": len(candidates),
            "unresolvedCount": len(candidates),
            "publishableMaterialFactCount": 0,
        },
        "items": candidates,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(encoded, encoding="utf-8")
    tmp.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    corpus = load_json(args.corpus)
    queue = build_queue(corpus)
    write_json(args.output, queue)
    print(json.dumps(queue["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
