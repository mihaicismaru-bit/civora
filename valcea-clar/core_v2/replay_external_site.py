from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_shadow_candidate_ledger import build
from external_readback import read_site


def replay(limit: int = 10) -> dict[str, object]:
    ledger = build()
    candidate_ids = set(ledger.get("first_ten_candidate_ids") or [])
    rows = [row for row in ledger.get("rows") or [] if row.get("story_id") in candidate_ids][:limit]
    results = []
    for row in rows:
        story_id = str(row["story_id"])
        url = str(row.get("canonical_url") or f"https://valceaclar.ro/stiri/{story_id}/")
        results.append(read_site(url, story_id))
    passed = sum(1 for row in results if row.get("readback_ok") is True)
    return {
        "schema_version": "1.0",
        "mode": "READ_ONLY_EXTERNAL_REPLAY",
        "publication_authority": "NONE",
        "candidate_count": len(results),
        "site_readback_passed": passed,
        "site_readback_failed": len(results) - passed,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only external site replay for Core v2 candidates")
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    result = replay(max(0, min(args.limit, 10)))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("candidate_count", "site_readback_passed", "site_readback_failed")}, sort_keys=True))
    # Truth failures are evidence, not CI/code failures. Acceptance remains fail-closed elsewhere.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
