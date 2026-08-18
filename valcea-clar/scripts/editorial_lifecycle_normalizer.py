#!/usr/bin/env python3
"""Normalize durable VÂLCEA CLAR article lifecycle.

Transient alerts describe a condition whose publication usefulness expires.
Documentary explainers, adopted-HCL articles and durable dossiers do not become
false merely because the underlying decision is old.  They remain in the
publication archive while their event/document date stays explicit in copy.

This normalizer never changes breaking/service facts unless they explicitly opt
into evergreen lifecycle.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "editorial" / "facts_registry.json"
EVERGREEN_UNTIL = "2099-12-31T23:59:59+03:00"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def should_be_evergreen(item: dict[str, Any]) -> bool:
    lifecycle = str(item.get("publication_lifecycle") or "").strip().lower()
    if lifecycle == "time_bounded":
        return False
    if lifecycle == "evergreen":
        return True
    if isinstance(item.get("council_decision"), dict):
        return True
    if str(item.get("editorial_type") or "").strip().lower() in {"explainer", "analysis"}:
        return True
    if str(item.get("material_fact_gate") or "").strip().upper() == "PASS_EXPLAINER_ONLY":
        return True
    return False


def normalize(doc: dict[str, Any]) -> tuple[int, list[str]]:
    changed: list[str] = []
    for item in doc.get("facts") or []:
        if not isinstance(item, dict) or not item.get("id") or not should_be_evergreen(item):
            continue
        before = str(item.get("valid_until") or "")
        if before and before != EVERGREEN_UNTIL:
            item.setdefault("publication_validity", {})["original_valid_until"] = before
        if item.get("publication_lifecycle") != "evergreen" or item.get("valid_until") != EVERGREEN_UNTIL:
            item["publication_lifecycle"] = "evergreen"
            item["valid_until"] = EVERGREEN_UNTIL
            item.setdefault("publication_validity", {})["meaning"] = "article_remains_archive_publishable; current-status claims still require current evidence"
            changed.append(str(item["id"]))
    doc.setdefault("policy", {})["evergreen_explainers_do_not_expire_like_service_alerts"] = True
    doc["policy"]["current_status_claims_still_require_current_evidence"] = True
    return len(changed), changed


def self_test() -> int:
    doc = {"facts": [
        {"id":"a","editorial_type":"explainer","valid_until":"2026-09-01"},
        {"id":"b","editorial_type":"service","valid_until":"2026-09-01","publication_lifecycle":"time_bounded"},
        {"id":"c","council_decision":{},"valid_until":"2026-09-01"},
    ]}
    count, ids = normalize(doc)
    assert count == 2 and set(ids) == {"a","c"}
    assert doc["facts"][0]["valid_until"] == EVERGREEN_UNTIL
    assert doc["facts"][1]["valid_until"] == "2026-09-01"
    print("VÂLCEA CLAR editorial lifecycle normalizer self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    doc = load(FACTS)
    count, ids = normalize(doc)
    if args.apply and count:
        FACTS.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status":"UPDATED" if args.apply and count else "NO_CHANGE","changed":count,"story_ids":ids}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
