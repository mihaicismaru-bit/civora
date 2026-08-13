#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib

from candidate_staging import stage_candidates, validate_staging_ledger

ROOT = pathlib.Path(__file__).resolve().parent


def main() -> int:
    bundle = json.loads((ROOT / "opportunity_bundle.json").read_text(encoding="utf-8"))
    source = json.loads((ROOT / "staging_candidates.json").read_text(encoding="utf-8"))
    ledger = stage_candidates(bundle, source["candidates"], source["observed_at"])
    validate_staging_ledger(ledger)
    (ROOT / "staging_ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(ledger["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
