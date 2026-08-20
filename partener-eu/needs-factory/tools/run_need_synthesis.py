#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.semantic_provider import CommandNeedDecisionProvider
from core.need_synthesis import build_need_hypotheses
from core.semantic_orchestrator import run_need_synthesis


def main() -> int:
    parser = argparse.ArgumentParser(description="Run evidence-bound semantic need synthesis")
    parser.add_argument("research_request", type=Path)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("policy", type=Path)
    parser.add_argument("--provider-command-json", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    request_payload = json.loads(args.research_request.read_text(encoding="utf-8"))
    request = request_payload.get("research_request", request_payload)
    evidence_payload = json.loads(args.evidence.read_text(encoding="utf-8"))
    evidence = evidence_payload.get("evidence", evidence_payload)
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    hypotheses = build_need_hypotheses(request, evidence, policy)
    argv = json.loads(args.provider_command_json)
    provider = CommandNeedDecisionProvider(argv)
    result = run_need_synthesis(hypotheses, evidence, provider)
    output = {"hypotheses": hypotheses, "decision_set": result}
    rendered = json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if result["state"] in {"READY_FOR_RANKING", "NO_SUPPORTED_NEEDS"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
