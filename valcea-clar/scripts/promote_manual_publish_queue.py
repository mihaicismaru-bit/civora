#!/usr/bin/env python3
"""Promote a human-approved manual story queue into the canonical facts registry.

This adapter never renders, archives or publishes a story. It validates manual
intake and, with --apply, upserts verified facts by id. A queue item may declare
explicit ``supersedes_ids`` when an earlier manual id must be retired during a
continuous-story consolidation. The Fact Kernel workflow is the only production
caller; Live Newsroom remains the only publication/runtime writer.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "editorial" / "manual_publish_queue.json"
REGISTRY = ROOT / "editorial" / "facts_registry.json"

REQUIRED = {
    "id",
    "status",
    "section",
    "priority",
    "confidence",
    "headline",
    "dek",
    "paragraphs",
    "material_fact_gate",
    "sources",
}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def validate_queue(doc: dict[str, Any]) -> list[dict[str, Any]]:
    facts = doc.get("facts") or []
    if not isinstance(facts, list) or not facts:
        raise ValueError("manual publish queue has no facts")
    seen: set[str] = set()
    clean: list[dict[str, Any]] = []
    for raw in facts:
        if not isinstance(raw, dict):
            raise ValueError("manual publish queue contains non-object fact")
        fact = dict(raw)
        missing = sorted(REQUIRED - set(fact))
        if missing:
            raise ValueError(f"{fact.get('id')}: missing {missing}")
        story_id = str(fact["id"]).strip()
        if not story_id or story_id in seen:
            raise ValueError(f"invalid or duplicate manual fact id: {story_id!r}")
        seen.add(story_id)
        fact["id"] = story_id
        if fact["status"] not in {"verified", "approved_carry_forward"}:
            raise ValueError(f"{story_id}: non-publishable status")
        if int(fact["confidence"]) < 90:
            raise ValueError(f"{story_id}: confidence below newsroom threshold")
        if not fact.get("paragraphs") or not fact.get("sources"):
            raise ValueError(f"{story_id}: body or sources missing")
        if any(not isinstance(row, dict) or not row.get("url") for row in fact["sources"]):
            raise ValueError(f"{story_id}: source URL missing")

        supersedes = fact.get("supersedes_ids", [])
        if supersedes is None:
            supersedes = []
        if not isinstance(supersedes, list):
            raise ValueError(f"{story_id}: supersedes_ids must be a list")
        normalized: list[str] = []
        for raw_old_id in supersedes:
            if not isinstance(raw_old_id, str):
                raise ValueError(f"{story_id}: supersedes_ids must contain strings")
            old_id = raw_old_id.strip()
            if not old_id or old_id == story_id or old_id in normalized:
                raise ValueError(f"{story_id}: invalid superseded id {old_id!r}")
            normalized.append(old_id)
        if normalized:
            fact["supersedes_ids"] = normalized
        else:
            fact.pop("supersedes_ids", None)
        clean.append(fact)

    queue_ids = {str(fact["id"]) for fact in clean}
    superseded_by: dict[str, str] = {}
    for fact in clean:
        story_id = str(fact["id"])
        for old_id in fact.get("supersedes_ids", []):
            if old_id in queue_ids:
                raise ValueError(f"{story_id}: cannot supersede active queue id {old_id}")
            prior = superseded_by.get(old_id)
            if prior and prior != story_id:
                raise ValueError(f"{old_id}: superseded by multiple queue facts")
            superseded_by[old_id] = story_id
    return clean


def promote(queue_path: Path, registry_path: Path, *, apply: bool) -> dict[str, Any]:
    if not queue_path.is_file():
        return {"status": "NO_QUEUE", "changed": False, "manual_ids": []}
    queue = load(queue_path)
    facts = validate_queue(queue)
    registry = load(registry_path)
    existing = {
        str(row.get("id")): row
        for row in registry.get("facts", [])
        if isinstance(row, dict) and row.get("id")
    }
    changed_ids: list[str] = []
    removed_ids: list[str] = []
    for fact in facts:
        story_id = str(fact["id"])
        for old_id in fact.get("supersedes_ids", []):
            if old_id in existing:
                existing.pop(old_id)
                removed_ids.append(old_id)
        if existing.get(story_id) != fact:
            changed_ids.append(story_id)
        existing[story_id] = fact
    registry["facts"] = list(existing.values())
    registry["manual_publish_bridge"] = {
        "enabled": True,
        "source": "editorial/manual_publish_queue.json",
        "policy": "human-approved verified facts are ingested by Fact Kernel; explicit supersedes_ids may retire only named stale manual ids; Live Newsroom still owns publication",
    }
    if apply:
        registry_path.write_text(
            json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return {
        "status": "APPLIED" if apply else "VALIDATED",
        "changed": bool(changed_ids or removed_ids),
        "manual_ids": [str(row["id"]) for row in facts],
        "changed_ids": changed_ids,
        "removed_ids": removed_ids,
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        queue = root / "queue.json"
        registry = root / "facts.json"
        registry.write_text(
            json.dumps({
                "facts": [{
                    "id": "stale-manual-id",
                    "status": "verified",
                    "section": "ACTUALITATE",
                    "priority": 80,
                    "confidence": 95,
                    "headline": "Stale",
                    "dek": "Stale",
                    "paragraphs": ["Stale."],
                    "material_fact_gate": "PASS",
                    "sources": [{"url": "https://example.com/old"}],
                }]
            }) + "\n",
            encoding="utf-8",
        )
        queue.write_text(
            json.dumps({
                "facts": [{
                    "id": "manual-test",
                    "status": "verified",
                    "section": "ACTUALITATE",
                    "priority": 80,
                    "confidence": 95,
                    "headline": "Test manual",
                    "dek": "Context verificat",
                    "paragraphs": ["Corpul verificat al știrii."],
                    "material_fact_gate": "PASS",
                    "sources": [{"url": "https://example.com/source"}],
                    "supersedes_ids": ["stale-manual-id"],
                }]
            }),
            encoding="utf-8",
        )
        preview = promote(queue, registry, apply=False)
        assert preview["status"] == "VALIDATED" and preview["changed"] is True
        assert preview["removed_ids"] == ["stale-manual-id"]
        result = promote(queue, registry, apply=True)
        assert result["status"] == "APPLIED"
        saved = load(registry)
        ids = {row["id"] for row in saved["facts"]}
        assert ids == {"manual-test"}
        assert saved["manual_publish_bridge"]["enabled"] is True
        again = promote(queue, registry, apply=False)
        assert again["changed"] is False and again["removed_ids"] == []
    print("VÂLCEA CLAR manual publish intake adapter self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, default=QUEUE)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    result = promote(args.queue, args.registry, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
