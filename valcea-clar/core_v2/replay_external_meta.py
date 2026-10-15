from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from build_shadow_candidate_ledger import build
from meta_readback import read_meta


def _token() -> str:
    return (
        os.getenv("VALCEA_META_PAGE_ACCESS_TOKEN", "")
        or os.getenv("VALCEA_FB_PAGE_ACCESS_TOKEN", "")
    )


def replay(limit: int = 10, graph_version: str = "v26.0") -> dict[str, Any]:
    ledger = build()
    candidate_ids = list(ledger.get("first_ten_candidate_ids") or [])[:limit]
    wanted = set(candidate_ids)
    rows = [row for row in ledger.get("rows") or [] if row.get("story_id") in wanted]
    token = _token()

    results: list[dict[str, Any]] = []
    for row in rows:
        story_id = str(row.get("story_id") or "")
        for channel, field in (
            ("facebook", "facebook_remote_id_internal"),
            ("instagram", "instagram_remote_id_internal"),
        ):
            remote_id = str(row.get(field) or "")
            if not remote_id:
                results.append(
                    {
                        "story_id": story_id,
                        "channel": channel,
                        "remote_id": None,
                        "status": "NOT_DELIVERED",
                        "reason": "missing_internal_remote_id",
                        "readback_ok": False,
                        "publication_authority": "NONE",
                    }
                )
                continue
            result = read_meta(channel, remote_id, token, graph_version)
            result = {"story_id": story_id, **result}
            results.append(result)

    def count(channel: str, status: str | None = None, readback: bool | None = None) -> int:
        values = [row for row in results if row.get("channel") == channel]
        if status is not None:
            values = [row for row in values if row.get("status") == status]
        if readback is not None:
            values = [row for row in values if row.get("readback_ok") is readback]
        return len(values)

    verified_ids: list[str] = []
    by_story: dict[str, dict[str, dict[str, Any]]] = {}
    for row in results:
        by_story.setdefault(str(row.get("story_id") or ""), {})[str(row.get("channel") or "")] = row
    for story_id in candidate_ids:
        pair = by_story.get(story_id) or {}
        if (
            (pair.get("facebook") or {}).get("readback_ok") is True
            and (pair.get("instagram") or {}).get("readback_ok") is True
        ):
            verified_ids.append(story_id)

    return {
        "schema_version": "1.0",
        "mode": "READ_ONLY_META_REPLAY",
        "publication_authority": "NONE",
        "token_present": bool(token),
        "candidate_count": len(rows),
        "facebook": {
            "passed": count("facebook", readback=True),
            "failed": count("facebook", "FAILED"),
            "blocked": count("facebook", "BLOCKED"),
            "not_delivered": count("facebook", "NOT_DELIVERED"),
        },
        "instagram": {
            "passed": count("instagram", readback=True),
            "failed": count("instagram", "FAILED"),
            "blocked": count("instagram", "BLOCKED"),
            "not_delivered": count("instagram", "NOT_DELIVERED"),
        },
        "both_channels_verified_count": len(verified_ids),
        "both_channels_verified_story_ids": verified_ids,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Meta replay for Core v2 shadow candidates")
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--graph-version", default="v26.0")
    args = parser.parse_args()
    result = replay(max(0, min(args.limit, 10)), args.graph_version)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "candidate_count": result["candidate_count"],
                "token_present": result["token_present"],
                "facebook_passed": result["facebook"]["passed"],
                "instagram_passed": result["instagram"]["passed"],
                "both_channels_verified_count": result["both_channels_verified_count"],
            },
            sort_keys=True,
        )
    )
    # External truth failures are evidence, not code failures. Acceptance remains fail-closed.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
