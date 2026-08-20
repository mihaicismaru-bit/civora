#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.partener_call import normalize_call_intelligence
from core.research_requirements import build_research_request


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a deterministic Needs Factory research request from minimal project/call intake")
    parser.add_argument("intake", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    intake = json.loads(args.intake.read_text(encoding="utf-8"))
    profile_ref = Path(str(intake["profile"]))
    profile_path = profile_ref if profile_ref.is_absolute() else ROOT / profile_ref
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    call_intelligence = normalize_call_intelligence(intake["call_record"])
    request = build_research_request(
        intake["project_input"],
        call_intelligence,
        profile,
        historical_cutoff=intake.get("historical_cutoff"),
    )
    result = {
        "schema_version": "nf.research_request_build.v0.1",
        "call_intelligence": call_intelligence,
        "research_request": request,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
