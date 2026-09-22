#!/usr/bin/env python3
"""Build a deterministic fail-closed queue for AFIR material-change candidates.

The AFIR crawler detects record-level changes that may affect material funding
facts. This builder makes those candidates first-class operational work without
promoting dossier facts. A candidate may be marked RESOLVED only when a
bounded authoritative resolver proves the exact same AFIR source fingerprint.
For the live available-funds counter, resolution means that the dedicated
structured snapshot is trustworthy; it does NOT authorize deadline, budget,
eligibility, scoring, beneficiary or lifecycle changes in the general dossier.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_CORPUS = ROOT / "state" / "afir_corpus.json"
DEFAULT_OUTPUT = ROOT / "state" / "afir_material_resolution_queue.json"
DEFAULT_LIVE_FUNDS = ROOT / "state" / "afir_live_funds.json"
COUNTER_PATH = "/finantare/contor-fonduri-disponibile"

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


def load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return load_json(path)


def normalize_url(url: str) -> str:
    return str(url or "").strip().rstrip("/").lower()


def matching_live_funds_resolution(
    item: dict[str, Any], live_funds: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Resolve only the counter candidate proven by the exact source fingerprint."""
    if not live_funds or live_funds.get("status") != "PASS":
        return None

    item_url = normalize_url(item.get("url"))
    snapshot_url = normalize_url(live_funds.get("canonicalUrl"))
    if not item_url.endswith(COUNTER_PATH) or snapshot_url != item_url:
        return None

    item_fingerprint = str(item.get("sha256") or item.get("fingerprint") or "").strip()
    source_fingerprint = str(live_funds.get("sourceFingerprint") or "").strip()
    corpus_fingerprint = str(live_funds.get("corpusFingerprint") or "").strip()
    if not item_fingerprint or source_fingerprint != item_fingerprint or corpus_fingerprint != item_fingerprint:
        return None
    if live_funds.get("sourceFingerprintMatchesCorpus") is not True:
        return None

    policy = live_funds.get("policy") or {}
    summary = live_funds.get("summary") or {}
    row_count = summary.get("rowCount")
    if (
        policy.get("publishableDedicatedSnapshot") is not True
        or policy.get("autoPromoteIntoDossierBudget") is not False
        or not isinstance(row_count, int)
        or row_count < 1
    ):
        return None

    return {
        "status": "RESOLVED",
        "requiresReconciliation": False,
        "publishMaterialFacts": False,
        "materialFactAction": "NONE_DOSSIER_FIELDS_REMAIN_BLOCKED",
        "resolutionType": "STRUCTURED_AUTHORITATIVE_LIVE_FUNDS_SNAPSHOT",
        "resolvedAt": live_funds.get("generatedAt") or live_funds.get("sourceObservedAt"),
        "dedicatedSnapshotPublishable": True,
        "resolutionEvidence": {
            "canonicalUrl": live_funds.get("canonicalUrl"),
            "sourceFingerprint": source_fingerprint,
            "snapshotFingerprint": live_funds.get("snapshotFingerprint"),
            "rowCount": row_count,
            "interventions": summary.get("interventions") or [],
        },
    }


def candidate_from_item(
    item: dict[str, Any], live_funds: dict[str, Any] | None = None
) -> dict[str, Any]:
    url = str(item.get("url") or "").strip()
    title = str(item.get("title") or url or "AFIR material change").strip()
    fingerprint = str(item.get("sha256") or item.get("fingerprint") or "").strip()
    observed_at = str(item.get("observedAt") or "").strip() or None

    candidate: dict[str, Any] = {
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

    resolution = matching_live_funds_resolution(item, live_funds)
    if resolution:
        candidate.update(resolution)
    return candidate


def build_queue(
    corpus: dict[str, Any], live_funds: dict[str, Any] | None = None
) -> dict[str, Any]:
    items = corpus.get("items") or []
    if not isinstance(items, list):
        raise ValueError("AFIR corpus items must be a list")

    candidates: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("materialChangeCandidate") is True:
            candidates.append(candidate_from_item(item, live_funds))

    candidates.sort(key=lambda row: (row["canonicalUrl"], row["fingerprint"], row["title"]))
    generated_at = corpus.get("generatedAt") or corpus.get("lastSuccessfulAt") or corpus.get("lastRun", {}).get("observedAt")
    unresolved = sum(1 for row in candidates if row.get("status") != "RESOLVED")

    return {
        "schemaVersion": 1,
        "source": "AFIR",
        "generatedAt": generated_at,
        "policy": {
            "purpose": "record-level-material-change-resolution",
            "failClosed": True,
            "materialFactsAutopromoted": False,
            "lastKnownGoodPreservedUntilReconciled": True,
            "dedicatedStructuredSnapshotsMayResolveExactCandidates": True,
        },
        "summary": {
            "candidateCount": len(candidates),
            "unresolvedCount": unresolved,
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
    parser.add_argument("--live-funds", type=Path, default=DEFAULT_LIVE_FUNDS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    corpus = load_json(args.corpus)
    live_funds = load_optional_json(args.live_funds)
    queue = build_queue(corpus, live_funds)
    write_json(args.output, queue)
    print(json.dumps(queue["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
