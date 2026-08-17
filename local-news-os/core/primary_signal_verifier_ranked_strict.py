#!/usr/bin/env python3
"""Production entrypoint: ranked primary retrieval + strict corroboration gate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

CORE = Path(__file__).resolve().parent
import sys
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import primary_signal_verifier_ranked as ranked  # noqa: E402
import primary_signal_verifier_strict as strict  # noqa: E402


def install(instance_id: str) -> None:
    ranked.install_ranking()
    strict.install_strict_guard(instance_id)


def validate(instance_id: str) -> dict:
    install(instance_id)
    base = strict.validate(instance_id)
    rank = ranked.validate(instance_id)
    return {
        **base,
        "candidate_ranking": rank["ranking"],
        "targets_with_path_hints": rank["targets_with_path_hints"],
        "publication_authority": "NONE",
    }


def run(instance_id: str, *, write: bool) -> dict:
    install(instance_id)
    state = strict.run(instance_id, write=write)
    state["verification_policy"]["primary_candidate_ranking"] = "LISTING_PATH_THEN_SOURCE_HINTS_THEN_NEWS_STRUCTURE"
    if write:
        import signal_radar as radar
        config, _ = radar.load_config(instance_id)
        output = ranked.ROOT / str(config["primary_verification_state_path"])
        output.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return state


def self_test() -> int:
    assert ranked.self_test() == 0
    assert strict.self_test() == 0
    print("LOCAL NEWS OS ranked strict primary verifier self-test: PASS")
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
        "candidate_ranking": "ENABLED",
        "publication_authority": "NONE",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
