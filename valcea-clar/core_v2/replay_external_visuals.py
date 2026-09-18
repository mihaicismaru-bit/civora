from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_shadow_candidate_ledger import build
from visual_readback import read_visual


def replay(limit: int = 10) -> dict[str, Any]:
    ledger = build()
    candidate_ids = list(ledger.get("first_ten_candidate_ids") or [])[:limit]
    wanted = set(candidate_ids)
    rows = [row for row in ledger.get("rows") or [] if row.get("story_id") in wanted]
    results: list[dict[str, Any]] = []

    for row in rows:
        story_id = str(row.get("story_id") or "")
        article_url = str(row.get("canonical_url") or "")
        image_path = str(row.get("visual_image_path") or "")
        source_url = str(row.get("visual_source_url") or "")
        rights_basis = str(row.get("visual_rights_basis") or "")
        if not article_url or not image_path or not source_url or not rights_basis:
            results.append(
                {
                    "story_id": story_id,
                    "status": "BLOCKED",
                    "reason": "missing_visual_provenance_fields",
                    "readback_ok": False,
                    "publication_authority": "NONE",
                }
            )
            continue
        result = read_visual(
            article_url=article_url,
            image_path=image_path,
            source_url=source_url,
            direct_source_url=row.get("visual_direct_source_url"),
            rights_basis=rights_basis,
            internal_real_visual_evidence=row.get("real_visual_internal_evidence") is True,
        )
        results.append({"story_id": story_id, **result})

    passed = sum(1 for row in results if row.get("readback_ok") is True)
    return {
        "schema_version": "1.0",
        "mode": "READ_ONLY_VISUAL_REPLAY",
        "publication_authority": "NONE",
        "candidate_count": len(rows),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only visual replay for Core v2 shadow candidates")
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    result = replay(max(0, min(args.limit, 10)))
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"candidate_count": result["candidate_count"], "passed": result["passed"], "failed": result["failed"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
