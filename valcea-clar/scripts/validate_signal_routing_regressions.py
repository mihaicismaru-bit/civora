#!/usr/bin/env python3
"""Validate VÂLCEA CLAR-owned signal routing regression examples."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "local-news-os" / "core"
import sys
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import signal_radar as radar  # noqa: E402
import signal_routing_contract as routing  # noqa: E402


def main() -> int:
    routing.install()
    config, _ = radar.load_config("valcea")
    cases = json.loads((ROOT / "valcea-clar/editorial/signal_routing_regressions.json").read_text(encoding="utf-8"))
    failures = []
    for case in cases.get("cases") or []:
        route, _ = radar.classify(str(case["title"]), config)
        if route != case.get("expected_route"):
            failures.append(f"{case['id']}: expected {case.get('expected_route')}, got {route}")
        if case.get("forbidden_route") and route == case.get("forbidden_route"):
            failures.append(f"{case['id']}: forbidden route selected: {route}")
    if failures:
        raise SystemExit("Signal routing regression FAIL: " + "; ".join(failures))
    print(f"Signal routing regressions: PASS ({len(cases.get('cases') or [])} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
