#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.civora_provider import CivoraCommandProvider
from adapters.partener_source_gate import (
    DEFAULT_SOURCE_REGISTRY_PATH,
    PartenerSourceGateProvider,
)
from core.research_orchestrator import run_research_cycle


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Execute a Needs Factory research request through an existing CIVORA "
            "discovery provider, gated by PARTENER.EU source health"
        )
    )
    parser.add_argument("research_request", type=Path)
    parser.add_argument(
        "--provider-command-json",
        required=True,
        help="JSON array argv for the existing CIVORA discovery provider command",
    )
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument(
        "--source-registry",
        type=Path,
        default=DEFAULT_SOURCE_REGISTRY_PATH,
        help="Canonical PARTENER.EU source_registry_health.json snapshot",
    )
    parser.add_argument(
        "--max-source-registry-age-hours",
        type=float,
        default=6.0,
        help="Fail closed when the PARTENER source-health snapshot is older than this",
    )
    parser.add_argument(
        "--fixture-provider-no-source-gate",
        action="store_true",
        help="TEST FIXTURES ONLY: bypass PARTENER source-health reconciliation",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.research_request.read_text(encoding="utf-8"))
    request = payload.get("research_request", payload)
    argv = json.loads(args.provider_command_json)
    if not isinstance(argv, list) or not argv:
        raise SystemExit("--provider-command-json must be a non-empty JSON array")

    provider = CivoraCommandProvider(argv, timeout_seconds=args.timeout_seconds)
    gate_enabled = not args.fixture_provider_no_source_gate
    if gate_enabled:
        provider = PartenerSourceGateProvider(
            provider,
            registry_path=args.source_registry,
            max_registry_age_hours=args.max_source_registry_age_hours,
        )

    result = run_research_cycle(request, provider)
    result["provider_binding"] = {
        "provider": "CIVORA_COMMAND",
        "partener_source_registry_gate": "ENABLED" if gate_enabled else "BYPASSED_FIXTURE_ONLY",
        "source_registry": str(args.source_registry) if gate_enabled else None,
        "policy": "reuse_existing_control_plane_no_parallel_crawler",
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if result["state"] != "BLOCKED_DISCOVERY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
