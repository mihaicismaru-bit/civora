#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.partener import material_fact_receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a Needs Factory receipt from PARTENER source-state")
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("source_id")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    checkpoint = json.loads(args.checkpoint.read_text(encoding="utf-8"))
    receipt = material_fact_receipt(checkpoint, args.source_id)
    rendered = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
