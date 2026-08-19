#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    engine = load_module("e28_closed_dev", EUCONS / "acceptance" / "closed_dev.py")
    contract = json.loads((EUCONS / "acceptance" / "closed_dev_contract.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as td:
        receipt = engine.build_closed_dev(Path(td) / "production-ready", contract)

    if receipt["status"] != "PASS" or receipt["target_state"] != "BLOCKED_EXTERNAL_ONLY":
        raise SystemExit("E28 terminal state not reached")
    if receipt["internal_development_blockers"]:
        raise SystemExit("E28 still contains internal development blockers")
    if receipt["production_side_effects_enabled"] is not False:
        raise SystemExit("E28 production side effects failed open")
    if len(receipt["prerequisites"]) != 28:
        raise SystemExit("E28 prerequisite receipt chain incomplete")
    if receipt["public_content"] != {"services": 8, "people": 2, "cases": 2}:
        raise SystemExit(f"E28 public content closure drift: {receipt['public_content']}")
    if receipt["production_build"]["pages"] != 26 or receipt["production_build"]["sitemap_entries"] != 26:
        raise SystemExit("E28 production build route closure failed")
    if receipt["production_build"]["production_deployed"] is not False:
        raise SystemExit("E28 may not deploy production")
    if receipt["runtime"] != {"lead_route": "POST /api/leads", "production_enabled": False, "provider_neutral": True}:
        raise SystemExit("E28 runtime activation contract drift")
    if receipt["external_handoff"]["actions"] != ["domain_and_hosting", "linkedin", "facebook", "commercial_mailbox"]:
        raise SystemExit("E28 external-only handoff drift")
    if receipt["external_handoff"]["owner_development_actions_required"] is not False:
        raise SystemExit("E28 wrongly defers development work to owner")
    if not re.fullmatch(r"[0-9a-f]{64}", receipt["production_build"]["artifact_sha256"]):
        raise SystemExit("E28 production artifact hash missing")
    if not re.fullmatch(r"[0-9a-f]{64}", receipt["full_acceptance_replay_sha256"]):
        raise SystemExit("E28 full-acceptance replay hash missing")
    body = {key: value for key, value in receipt.items() if key != "receipt_hash"}
    if receipt["receipt_hash"] != engine.sha256_json(body):
        raise SystemExit("E28 immutable receipt digest mismatch")

    print(json.dumps({
        "status": "PASS",
        "phase": "E28",
        "target_state": receipt["target_state"],
        "prerequisite_phases": len(receipt["prerequisites"]),
        "public_services": receipt["public_content"]["services"],
        "public_people": receipt["public_content"]["people"],
        "public_cases": receipt["public_content"]["cases"],
        "production_pages": receipt["production_build"]["pages"],
        "external_actions": len(receipt["external_handoff"]["actions"]),
        "internal_blockers": 0,
        "production_side_effects": "DISABLED"
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
