#!/usr/bin/env python3
"""Promote only fully verified generated fact kernels into facts_registry.json.

Generated kernels are probationary until their builder marks them `verified`.
Promotion is idempotent and ownership-safe: a builder may update its own prior
item, but may never overwrite a manually owned fact with the same id.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
KERNELS = ROOT / "editorial" / "fact_kernel_registry.json"
FACTS = ROOT / "editorial" / "facts_registry.json"
ALLOWED_BUILDERS = {"council_fact_kernel_v1"}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def owner(item: dict[str, Any]) -> str | None:
    provenance = item.get("kernel_provenance")
    if isinstance(provenance, dict):
        value = str(provenance.get("builder_id") or "").strip()
        return value or None
    return None


def promotable(item: dict[str, Any]) -> tuple[bool, str]:
    builder = owner(item)
    provenance = item.get("kernel_provenance") or {}
    if builder not in ALLOWED_BUILDERS:
        return False, "builder_not_allowed"
    if item.get("status") != "verified":
        return False, "kernel_not_verified"
    if provenance.get("evidence_complete") is not True:
        return False, "evidence_incomplete"
    if float(provenance.get("coverage") or 0) != 1.0:
        return False, "coverage_not_complete"
    if item.get("material_fact_gate") not in {"PASS", "PASS_EXPLAINER_ONLY", "PASS_WITH_CAUTION"}:
        return False, "material_fact_gate_not_publishable"
    kernel = item.get("fact_kernel")
    if not isinstance(kernel, dict) or not kernel.get("claims"):
        return False, "fact_kernel_missing"
    if not item.get("sources"):
        return False, "sources_missing"
    return True, "verified_kernel"


def merge(facts_doc: dict[str, Any], kernels_doc: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    output = copy.deepcopy(facts_doc)
    existing = [row for row in output.get("facts") or [] if isinstance(row, dict)]
    by_id = {str(row.get("id") or ""): index for index, row in enumerate(existing) if row.get("id")}
    promoted = 0
    updated = 0
    skipped: list[dict[str, str]] = []

    for item in kernels_doc.get("facts") or []:
        if not isinstance(item, dict):
            continue
        fact_id = str(item.get("id") or "").strip()
        ok, reason = promotable(item)
        if not fact_id or not ok:
            skipped.append({"id": fact_id or "<missing>", "reason": reason if fact_id else "id_missing"})
            continue
        builder = owner(item)
        if fact_id in by_id:
            current = existing[by_id[fact_id]]
            current_owner = owner(current)
            if current_owner != builder:
                raise SystemExit(
                    f"FACT KERNEL PROMOTION FAIL: refusing to overwrite non-builder fact {fact_id!r}; "
                    f"existing_owner={current_owner!r}, incoming_owner={builder!r}"
                )
            if current != item:
                existing[by_id[fact_id]] = copy.deepcopy(item)
                updated += 1
        else:
            by_id[fact_id] = len(existing)
            existing.append(copy.deepcopy(item))
            promoted += 1

    output["facts"] = existing
    report = {
        "status": "PASS",
        "promoted": promoted,
        "updated": updated,
        "skipped": skipped,
        "changed": bool(promoted or updated),
    }
    return output, report


def self_test() -> int:
    manual = {"schema_version": "1", "facts": [{"id": "manual", "status": "verified"}]}
    verified = {
        "id": "generated",
        "status": "verified",
        "material_fact_gate": "PASS_EXPLAINER_ONLY",
        "sources": [{"name": "S", "url": "https://example.test", "tier": "T1"}],
        "fact_kernel": {"claims": [{"id": "c"}]},
        "kernel_provenance": {"builder_id": "council_fact_kernel_v1", "evidence_complete": True, "coverage": 1.0},
    }
    held = copy.deepcopy(verified)
    held["id"] = "held"
    held["status"] = "candidate_hold"
    merged, report = merge(manual, {"facts": [verified, held]})
    assert report["promoted"] == 1
    assert {row["id"] for row in merged["facts"]} == {"manual", "generated"}
    collision = copy.deepcopy(verified)
    collision["id"] = "manual"
    try:
        merge(manual, {"facts": [collision]})
    except SystemExit:
        pass
    else:
        raise AssertionError("manual fact collision must fail closed")
    print("VÂLCEA CLAR fact kernel promotion self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    facts_doc = load(FACTS)
    kernels_doc = load(KERNELS)
    merged, report = merge(facts_doc, kernels_doc)
    if args.apply and report["changed"]:
        FACTS.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
