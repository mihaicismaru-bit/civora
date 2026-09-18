from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def _site_index(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("expected_story_id") or ""): row
        for row in doc.get("results") or []
        if isinstance(row, dict) and row.get("expected_story_id")
    }


def _meta_index(doc: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (str(row.get("story_id") or ""), str(row.get("channel") or "")): row
        for row in doc.get("results") or []
        if isinstance(row, dict) and row.get("story_id") and row.get("channel")
    }


def _site_receipt(row: dict[str, Any] | None, canonical_url: str | None) -> dict[str, Any]:
    row = row or {}
    ok = row.get("readback_ok") is True
    return {
        "channel": "site",
        "status": "DELIVERED" if ok else "FAILED",
        "canonical_url": row.get("canonical_url") or canonical_url,
        "remote_id": None,
        "receipt_id": None,
        "readback_ok": ok,
        "http_status": row.get("http_status"),
        "final_url": row.get("final_url"),
        "newsarticle_story_match": row.get("newsarticle_story_match") is True,
    }


def _social_receipt(channel: str, row: dict[str, Any] | None, remote_id: str | None) -> dict[str, Any]:
    row = row or {}
    ok = row.get("readback_ok") is True and bool(row.get("permalink"))
    status = "DELIVERED" if ok else str(row.get("status") or ("NOT_DELIVERED" if not remote_id else "FAILED"))
    return {
        "channel": channel,
        "status": status,
        "canonical_url": None,
        "remote_id": row.get("observed_remote_id") or remote_id,
        "receipt_id": row.get("permalink") if ok else None,
        "readback_ok": ok,
        "permalink": row.get("permalink"),
        "reason": row.get("reason"),
        "error": row.get("error"),
    }


def materialize(candidates: dict[str, Any], site: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    site_by_story = _site_index(site)
    meta_by_story = _meta_index(meta)
    candidate_ids = set(candidates.get("first_ten_candidate_ids") or [])
    rows = []
    externally_verified_ids: list[str] = []

    for candidate in candidates.get("rows") or []:
        if not isinstance(candidate, dict):
            continue
        story_id = str(candidate.get("story_id") or "")
        if not story_id or story_id not in candidate_ids:
            continue
        receipts = {
            "site": _site_receipt(site_by_story.get(story_id), candidate.get("canonical_url")),
            "facebook": _social_receipt(
                "facebook",
                meta_by_story.get((story_id, "facebook")),
                candidate.get("facebook_remote_id_internal"),
            ),
            "instagram": _social_receipt(
                "instagram",
                meta_by_story.get((story_id, "instagram")),
                candidate.get("instagram_remote_id_internal"),
            ),
        }
        externally_verified = (
            candidate.get("real_visual_internal_evidence") is True
            and all(receipt.get("status") == "DELIVERED" and receipt.get("readback_ok") is True for receipt in receipts.values())
        )
        if externally_verified:
            externally_verified_ids.append(story_id)
        rows.append(
            {
                "story_id": story_id,
                "material_signal": True,
                "real_visual_internal_evidence": candidate.get("real_visual_internal_evidence") is True,
                "visual_source_url": candidate.get("visual_source_url"),
                "visual_rights_basis": candidate.get("visual_rights_basis"),
                "receipts": receipts,
                "external_delivery_truth": "VERIFIED" if externally_verified else "BLOCKED",
                "acceptance_state": (
                    "EXTERNAL_DELIVERY_REPLAY_VERIFIED"
                    if externally_verified
                    else "BLOCKED_EXTERNAL_DELIVERY_EVIDENCE"
                ),
                "publication_authority": "NONE",
            }
        )

    return {
        "schema_version": "1.0",
        "mode": "SHADOW_RECEIPT_LEDGER",
        "publication_authority": "NONE",
        "truth_rule": "Only independent external readback can upgrade an internal remote ID to delivered evidence.",
        "candidate_count": len(rows),
        "externally_verified_count": len(externally_verified_ids),
        "externally_verified_story_ids": externally_verified_ids,
        "ten_story_external_delivery_ready": len(externally_verified_ids) >= 10,
        "acceptance_ready": False,
        "acceptance_blocker": "full StoryTransaction fact/article/audit gates remain required even when delivery replay is externally verified",
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize read-only Core v2 shadow delivery receipts")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--site-readback", required=True)
    parser.add_argument("--meta-readback", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = materialize(_load(args.candidates), _load(args.site_readback), _load(args.meta_readback))
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "candidate_count": result["candidate_count"],
                "externally_verified_count": result["externally_verified_count"],
                "ten_story_external_delivery_ready": result["ten_story_external_delivery_ready"],
                "acceptance_ready": result["acceptance_ready"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
