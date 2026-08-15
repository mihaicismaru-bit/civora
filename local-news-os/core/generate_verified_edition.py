#!/usr/bin/env python3
"""CORE_GENERIC deterministic edition engine for LOCAL NEWS OS.

Consumes one or more structured fact registries and an instance config. It never
calls an LLM or paid API. Only facts that pass the evidence gates become public
edition items. The engine is deliberately presentation-agnostic; renderers consume
its JSON output.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
INSTANCES = ROOT / "local-news-os" / "instances"
ALLOWED_GATES = {
    "PASS", "PASS_DATE_ONLY", "PASS_TITLE_DATE_ONLY",
    "PASS_EXPLAINER_ONLY", "PASS_WITH_CAUTION",
}
ALLOWED_STATUSES = {"verified", "approved_carry_forward"}
PUBLISHABLE_STATUSES = {"auto_approved", "editor_approved"}
MIN_CONFIDENCE = 90


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: root must be object")
    return value


def instance_config(instance_id: str) -> dict:
    path = INSTANCES / instance_id / "instance.json"
    cfg = load_json(path)
    if cfg.get("instance_id") != instance_id:
        raise ValueError(f"{path}: instance_id mismatch")
    return cfg


def parse_dt(value: str, tz: ZoneInfo) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)


def choose_slot(now: datetime, requested: str) -> str:
    if requested != "auto":
        return requested
    return "morning" if now.hour < 15 else "evening"


def merge_registries(paths: list[Path]) -> dict:
    merged: dict[str, dict] = {}
    for path in paths:
        registry = load_json(path)
        for fact in registry.get("facts", []):
            if isinstance(fact, dict) and fact.get("id"):
                merged[str(fact["id"])] = fact
    return {"facts": list(merged.values())}


def eligible_facts(registry: dict, now: datetime, slot: str, tz: ZoneInfo) -> list[dict]:
    output: list[dict] = []
    for fact in registry.get("facts", []):
        if fact.get("status") not in ALLOWED_STATUSES:
            continue
        if int(fact.get("confidence") or 0) < MIN_CONFIDENCE:
            continue
        if fact.get("material_fact_gate") not in ALLOWED_GATES:
            continue
        if slot not in (fact.get("slots") or []):
            continue
        sources = fact.get("sources") or []
        if not sources or any(not isinstance(source, dict) or not source.get("url") for source in sources):
            continue
        try:
            valid_from = parse_dt(str(fact["valid_from"]), tz)
            valid_until = parse_dt(str(fact["valid_until"]), tz)
        except (KeyError, TypeError, ValueError):
            continue
        if not (valid_from <= now <= valid_until):
            continue
        output.append(fact)
    output.sort(key=lambda item: (-int(item.get("priority") or 0), str(item["id"])))
    return output


def compact_item(item: dict) -> dict:
    result = {
        "id": item["id"],
        "section": item.get("section", "LOCAL"),
        "priority": int(item.get("priority") or 0),
        "headline": str(item.get("headline") or "").strip(),
        "dek": str(item.get("dek") or "").strip(),
        "paragraphs": [str(p).strip() for p in item.get("paragraphs", []) if str(p).strip()],
        "confidence": int(item.get("confidence") or 0),
        "material_fact_gate": item["material_fact_gate"],
        "sources": item.get("sources", []),
    }
    if item.get("auto_generated"):
        result["auto_generated"] = True
        result["auto_scope"] = item.get("auto_scope")
    if item.get("visual"):
        result["visual"] = item["visual"]
    return result


def build_payload(instance_id: str, registry: dict, now: datetime, slot: str) -> dict:
    cfg = instance_config(instance_id)
    tz = ZoneInfo(str(cfg["timezone"]))
    local_now = now.astimezone(tz)
    selected = eligible_facts(registry, local_now, slot, tz)
    brand = str(cfg["brand"]["name"])
    publish = bool(selected)
    label = "dimineață" if slot == "morning" else "seară"
    return {
        "schema_version": "1.0",
        "contract": "LOCAL_NEWS_OS_EDITION_V1",
        "instance_id": instance_id,
        "canonical_domain": cfg["canonical_domain"],
        "edition_id": f"{local_now.date().isoformat()}-{slot}",
        "slot": slot,
        "title": f"{brand} — Ediția de {label}",
        "edition_date": local_now.date().isoformat(),
        "updated_local": local_now.isoformat(timespec="seconds"),
        "generator": "local_news_os_deterministic_edition_v1",
        "status": "auto_approved" if publish else "auto_hold",
        "publication_intent": "publish" if publish else "hold",
        "editorial_fact_count": len(selected),
        "items": [compact_item(item) for item in selected],
        "policy": {
            "llm_required": False,
            "external_paid_api_required": False,
            "verified_facts_only": True,
            "shorter_edition_when_evidence_is_sparse": True,
            "last_known_good_fallback": True,
            "material_detail_autopublish": False,
        },
    }


def pointer_is_publishable(pointer: dict) -> bool:
    return (
        pointer.get("status") in PUBLISHABLE_STATUSES
        and pointer.get("publication_intent") == "publish"
        and bool(pointer.get("edition_id"))
    )


def write_pointer(pointer_path: Path, payload: dict, edition_path: Path) -> str:
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    if payload["publication_intent"] == "publish":
        pointer = {
            "schema_version": "1.0",
            "contract": "LOCAL_NEWS_OS_POINTER_V1",
            "instance_id": payload["instance_id"],
            "edition_id": payload["edition_id"],
            "slot": payload["slot"],
            "status": payload["status"],
            "publication_intent": "publish",
            "updated_local": payload["updated_local"],
            "edition_json": str(edition_path.as_posix()),
            "selection_reason": "latest_publishable_verified_edition",
        }
        pointer_path.write_text(json.dumps(pointer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return "updated"
    if pointer_path.is_file():
        previous = load_json(pointer_path)
        if pointer_is_publishable(previous):
            return "preserved_last_known_good"
    pointer = {
        "schema_version": "1.0",
        "contract": "LOCAL_NEWS_OS_POINTER_V1",
        "instance_id": payload["instance_id"],
        "edition_id": payload["edition_id"],
        "slot": payload["slot"],
        "status": payload["status"],
        "publication_intent": "hold",
        "updated_local": payload["updated_local"],
        "edition_json": str(edition_path.as_posix()),
        "selection_reason": "no_publishable_edition_exists",
    }
    pointer_path.write_text(json.dumps(pointer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return "hold_written"


def synthetic_registry(instance_id: str, now: datetime) -> dict:
    return {"facts": [{
        "id": f"{instance_id}-fixture-fact",
        "status": "verified",
        "section": "LOCAL",
        "priority": 80,
        "confidence": 99,
        "valid_from": now.replace(hour=0, minute=0, second=0).isoformat(),
        "valid_until": now.replace(hour=23, minute=59, second=59).isoformat(),
        "slots": ["morning", "evening"],
        "headline": "Fapt local verificat pentru testul motorului generic",
        "dek": "Fixture exclusiv pentru verificarea izolării multi-instance.",
        "paragraphs": [],
        "material_fact_gate": "PASS_TITLE_DATE_ONLY",
        "sources": [{"name": "Fixture source", "url": "https://example.invalid/source", "tier": "T1"}],
    }]}


def self_test() -> int:
    now = datetime.fromisoformat("2026-08-15T08:00:00+03:00")
    valcea = build_payload("valcea", synthetic_registry("valcea", now), now, "morning")
    test = build_payload("test-local", synthetic_registry("test-local", now), now, "morning")
    assert valcea["instance_id"] == "valcea"
    assert test["instance_id"] == "test-local"
    assert valcea["canonical_domain"] != test["canonical_domain"]
    assert valcea["title"] != test["title"]
    assert valcea["publication_intent"] == "publish"
    assert test["publication_intent"] == "publish"
    serialized = json.dumps(test, ensure_ascii=False).lower()
    for forbidden in ("vâlcea", "valcea", "valceaclar.ro", "râmnicu", "ramnicu"):
        assert forbidden not in serialized, forbidden
    print("LOCAL NEWS OS generic edition engine self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", default="valcea")
    parser.add_argument("--facts", action="append", default=[])
    parser.add_argument("--slot", choices=["auto", "morning", "evening"], default="auto")
    parser.add_argument("--now", help="ISO datetime; defaults to current local time")
    parser.add_argument("--output")
    parser.add_argument("--pointer")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if not args.facts or not args.output:
        parser.error("--facts and --output are required")

    cfg = instance_config(args.instance)
    tz = ZoneInfo(str(cfg["timezone"]))
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    slot = choose_slot(now.astimezone(tz), args.slot)
    registry = merge_registries([Path(path) for path in args.facts])
    payload = build_payload(args.instance, registry, now, slot)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pointer_result = None
    if args.pointer:
        pointer_result = write_pointer(Path(args.pointer), payload, output)
    print(json.dumps({
        "status": "PASS",
        "instance_id": args.instance,
        "edition_id": payload["edition_id"],
        "publication_intent": payload["publication_intent"],
        "editorial_fact_count": payload["editorial_fact_count"],
        "pointer_result": pointer_result,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
