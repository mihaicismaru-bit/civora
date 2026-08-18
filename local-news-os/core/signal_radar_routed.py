#!/usr/bin/env python3
"""Production signal-radar entrypoint with boundary-safe configurable routing."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

CORE = Path(__file__).resolve().parent
import sys
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import signal_radar as radar  # noqa: E402
import signal_routing_contract as routing  # noqa: E402


def install() -> None:
    routing.install()


def validate(instance_id: str) -> dict:
    install()
    report = radar.validate(instance_id)
    config, _ = radar.load_config(instance_id)
    return {
        **report,
        "routing": "BOUNDARY_SAFE_CONFIG_DRIVEN",
        "dedicated_primary_targets": len(routing.load_primary_targets(config)),
    }


def run(instance_id: str, *, write: bool) -> dict:
    install()
    return radar.run(instance_id, write=write)


def self_test() -> int:
    assert radar.self_test() == 0
    assert routing.self_test() == 0
    print("LOCAL NEWS OS routed signal radar self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.instance:
        parser.error("--instance is required")
    if args.validate_only:
        print(json.dumps(validate(args.instance), ensure_ascii=False))
        return 0
    result = run(args.instance, write=not args.no_write)
    print(json.dumps({
        "status": result["status"],
        "health": result["state"]["health"],
        "sources_ok": result["state"]["sources_ok"],
        "source_count": result["state"]["source_count"],
        "pending_verification": result["queue"]["pending_count"],
        "today_signals": result["queue"]["today_signal_count"],
        "routing": "BOUNDARY_SAFE_CONFIG_DRIVEN",
        "publication_authority": "NONE",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
