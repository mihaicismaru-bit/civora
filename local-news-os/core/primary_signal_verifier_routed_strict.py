#!/usr/bin/env python3
"""Production primary verifier with boundary-safe routing and dedicated targets.

This adapter preserves the ranked strict corroboration gate and adds only a
config-driven primary-target registry. It grants no Fact Kernel or publication
authority.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

CORE = Path(__file__).resolve().parent
ROOT = CORE.parents[1]
import sys
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import primary_signal_verifier as base  # noqa: E402
import primary_signal_verifier_ranked as ranked  # noqa: E402
import primary_signal_verifier_strict as strict  # noqa: E402
import signal_radar as radar  # noqa: E402
import signal_routing_contract as routing  # noqa: E402


def extended_target_registry(config: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result = ranked.ranked_target_registry(config)
    for sid, row in routing.load_primary_targets(config).items():
        result[("primary_target_id", sid)] = {
            "ref_type": "primary_target_id",
            "id": sid,
            "name": str(row.get("publisher") or sid),
            "url": str(row["url"]),
            "tier": str(row.get("tier") or "T1"),
            "status": row.get("status"),
            "enabled": row.get("enabled", True),
            "path_hints": [str(value).casefold() for value in row.get("path_hints") or [] if str(value).strip()],
        }
    return result


def install(instance_id: str) -> None:
    routing.install()
    ranked.install_ranking()
    strict.install_strict_guard(instance_id)
    # Ranking installs its own two-registry target loader. Extend it only after
    # ranking/strict installation so dedicated config targets survive.
    base.target_registry = extended_target_registry


def validate(instance_id: str) -> dict[str, Any]:
    install(instance_id)
    report = base.validate(instance_id)
    config, _ = radar.load_config(instance_id)
    registry = base.target_registry(config)
    hinted = sum(1 for row in registry.values() if row.get("path_hints"))
    return {
        **report,
        "strict_false_positive_guard": True,
        "primary_published_at_required": True,
        "title_event_overlap_required": True,
        "candidate_ranking": "LISTING_PATH_THEN_SOURCE_HINTS_THEN_NEWS_STRUCTURE",
        "registered_targets": len(registry),
        "targets_with_path_hints": hinted,
        "dedicated_primary_targets": len(routing.load_primary_targets(config)),
        "publication_authority": "NONE",
    }


def run(instance_id: str, *, write: bool) -> dict[str, Any]:
    install(instance_id)
    state = base.run(instance_id, write=False)
    state["verification_policy"] = {
        "strict_false_positive_guard": True,
        "primary_published_at_required": True,
        "max_publication_time_delta_hours": 36,
        "title_event_overlap_required": True,
        "instance_identity_is_not_event_evidence": True,
        "body_only_similarity_rejected": True,
        "primary_candidate_ranking": "LISTING_PATH_THEN_SOURCE_HINTS_THEN_NEWS_STRUCTURE",
        "boundary_safe_signal_routing": True,
        "dedicated_primary_target_registry": True,
    }
    if write:
        config, _ = radar.load_config(instance_id)
        output = ROOT / str(config["primary_verification_state_path"])
        output.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return state


def self_test() -> int:
    assert routing.self_test() == 0
    assert ranked.self_test() == 0
    assert strict.self_test() == 0
    print("LOCAL NEWS OS routed ranked strict primary verifier self-test: PASS")
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
    state = run(args.instance, write=not args.no_write)
    print(json.dumps({
        "status": "PASS",
        "task_count": state["task_count"],
        "primary_match_count": state["primary_match_count"],
        "no_match_count": state["no_match_count"],
        "unrouted_count": state["unrouted_count"],
        "targets_ok": state["targets_ok"],
        "target_count": state["target_count"],
        "strict_false_positive_guard": True,
        "boundary_safe_signal_routing": True,
        "publication_authority": "NONE",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
