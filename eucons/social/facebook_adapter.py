#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "social" / "facebook_contract.json"


class FacebookAdapterError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def _knowledge_index(knowledge: dict[str, Any], contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if knowledge.get("product") != contract["input"]["required_product"]:
        raise FacebookAdapterError("unknown knowledge product")
    if knowledge.get("engine_id") != contract["input"]["required_knowledge_engine_id"]:
        raise FacebookAdapterError("unknown knowledge engine")
    if knowledge.get("runtime_publication_enabled") is not False:
        raise FacebookAdapterError("Facebook adapter requires E14 runtime publication disabled")
    index: dict[str, dict[str, Any]] = {}
    for row in knowledge.get("records") or []:
        rid = str(row.get("id") or "").strip()
        if not rid or rid in index:
            raise FacebookAdapterError("knowledge records require unique non-empty ids")
        index[rid] = row
    return index


def _canonical_url(record: dict[str, Any], contract: dict[str, Any]) -> str:
    rtype = str(record.get("type") or "")
    source_ref = str(record.get("source_ref") or "").strip()
    if rtype not in contract["presentation"]["route_templates"]:
        raise FacebookAdapterError("unknown Facebook content type")
    return contract["presentation"]["canonical_base"].rstrip("/") + contract["presentation"]["route_templates"][rtype].format(source_ref=source_ref)


def _body(record: dict[str, Any], canonical_url: str, contract: dict[str, Any]) -> str:
    rtype = str(record.get("type") or "")
    title = str(record.get("title") or "").strip()
    summary = str(record.get("summary") or "").strip()
    if not title or not summary:
        raise FacebookAdapterError("Facebook READY record requires title and summary")
    if rtype == "ANALYSIS" and not str(record.get("analysis_label") or "").strip():
        raise FacebookAdapterError("analysis record requires analysis label")
    if rtype == "OPPORTUNITY":
        if not isinstance(record.get("material_facts"), dict) or not record.get("material_facts"):
            raise FacebookAdapterError("opportunity requires material facts")
        if not (record.get("verified_fact_classes") or []):
            raise FacebookAdapterError("opportunity requires verified fact classes")

    parts = [contract["presentation"]["lead_in_by_type"][rtype], "", title, summary]
    if rtype == "ANALYSIS":
        parts.extend(["", str(record["analysis_label"]).strip()])
    parts.extend(["", contract["presentation"]["cta_by_type"][rtype], canonical_url])
    body = "\n".join(parts).strip()
    if len(body) > int(contract["presentation"]["max_body_chars"]):
        raise FacebookAdapterError("Facebook body exceeds deterministic maximum")
    if "#" in body and contract["presentation"]["hashtags_default"] is False:
        raise FacebookAdapterError("hashtags are disabled by default")
    return body


def _item_id(editorial_id: str, content_hash: str) -> str:
    return "FB-" + hashlib.sha256(f"{editorial_id}|{content_hash}|facebook".encode("utf-8")).hexdigest()[:24]


def _receipt(item: dict[str, Any]) -> dict[str, Any]:
    body = {
        "schema_version": 1,
        "platform": "facebook",
        "item_id": item["item_id"],
        "editorial_id": item["editorial_id"],
        "content_hash": item["content_hash"],
        "dispatch_state": item["dispatch_state"],
        "published": False,
        "provider_message_id": None,
    }
    body["receipt_id"] = "RCP-E18-" + hashlib.sha256(stable_json(body).encode("utf-8")).hexdigest()[:24]
    body["receipt_hash"] = sha256_json(body)
    return body


def build_outbox(editorial: dict[str, Any], knowledge: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    if editorial.get("product") != contract["input"]["required_product"]:
        raise FacebookAdapterError("unknown editorial product")
    if editorial.get("engine_id") != contract["input"]["required_editorial_engine_id"]:
        raise FacebookAdapterError("unknown editorial engine")
    if editorial.get("dispatch_enabled") is not False or editorial.get("runtime_publication_enabled") is not False:
        raise FacebookAdapterError("E18 requires E15 dispatch/runtime publication disabled")

    knowledge_by_id = _knowledge_index(knowledge, contract)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for decision in editorial.get("decisions") or []:
        if decision.get("decision") != contract["input"]["required_editorial_decision"]:
            continue
        editorial_id = str(decision.get("editorial_id") or "").strip()
        knowledge_id = str(decision.get("knowledge_id") or "").strip()
        if not editorial_id or editorial_id in seen:
            raise FacebookAdapterError("READY editorial decisions require unique ids")
        seen.add(editorial_id)
        record = knowledge_by_id.get(knowledge_id)
        if not record:
            raise FacebookAdapterError("READY editorial decision missing knowledge record")
        if record.get("publication_state") != "PUBLISHABLE":
            raise FacebookAdapterError("READY editorial decision points to non-publishable knowledge")
        if record.get("type") not in contract["input"]["allowed_types"]:
            raise FacebookAdapterError("unknown Facebook content type")
        if decision.get("source_ref") != record.get("source_ref") or decision.get("type") != record.get("type"):
            raise FacebookAdapterError("editorial/knowledge identity mismatch")
        content_hash = str((decision.get("fact_kernel") or {}).get("content_hash") or "").strip()
        if not content_hash:
            raise FacebookAdapterError("READY editorial decision missing content hash")
        canonical_url = _canonical_url(record, contract)
        item_id = _item_id(editorial_id, content_hash)
        items.append({
            "schema_version": 1,
            "platform": "facebook",
            "item_id": item_id,
            "editorial_id": editorial_id,
            "knowledge_id": knowledge_id,
            "type": record["type"],
            "source_ref": record["source_ref"],
            "content_hash": content_hash,
            "canonical_url": canonical_url,
            "body": _body(record, canonical_url, contract),
            "hashtags_default": contract["presentation"]["hashtags_default"],
            "verbatim_cross_platform_reuse_allowed": False,
            "dispatch_state": contract["dispatch"]["dry_run_state"],
            "published": False,
            "provider_message_id": None,
            "attempts": 0,
            "max_attempts": int(contract["dispatch"]["max_attempts"]),
            "idempotency_key": item_id,
        })

    items.sort(key=lambda row: (row["type"], row["source_ref"], row["editorial_id"]))
    return {
        "schema_version": contract["output"]["schema_version"],
        "product": contract["output"]["product"],
        "engine_id": contract["engine_id"],
        "platform": "facebook",
        "provider_neutral": True,
        "authorization_required": True,
        "direct_publication_enabled": False,
        "dry_run": True,
        "summary": {"ready_items": len(items), "published": 0, "held_for_external_authorization": len(items)},
        "items": items,
        "receipts": [_receipt(item) for item in items],
    }


def assert_output_path_safe(path: Path) -> None:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return
    raise FacebookAdapterError("runtime Facebook outbox cannot be written under repository root")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--editorial", required=True)
    parser.add_argument("--knowledge", required=True)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    result = build_outbox(load_json(Path(args.editorial)), load_json(Path(args.knowledge)), load_json(Path(args.contract)))
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        assert_output_path_safe(output)
        output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
