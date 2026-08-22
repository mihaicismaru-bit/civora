#!/usr/bin/env python3
"""Suppress repository churn caused only by explicitly volatile JSON fields.

For each tracked JSON path, compare the working-tree value with HEAD after
recursively removing an explicit persistence profile and/or caller-provided
volatile keys. If the normalized values are equal, restore the exact HEAD bytes
so a later ``git add`` produces no commit. Any semantic difference leaves the
newly generated file untouched.

This is deliberately conservative: there are no implicit ignored keys and list
ordering remains significant. Source hashes, counters, statuses and candidate
sets are preserved unless a named profile explicitly classifies a key as
volatile. Named profiles are kept in ``persistence_profiles.json`` so workflow
YAML does not duplicate timestamp policy.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

PROFILE_REGISTRY = Path(__file__).with_name("persistence_profiles.json")


def strip_keys(value: Any, ignored: set[str]) -> Any:
    if isinstance(value, dict):
        return {
            key: strip_keys(item, ignored)
            for key, item in value.items()
            if key not in ignored
        }
    if isinstance(value, list):
        return [strip_keys(item, ignored) for item in value]
    return value


def load_profiles(path: Path = PROFILE_REGISTRY) -> dict[str, set[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_profiles = data.get("profiles") if isinstance(data, dict) else None
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise RuntimeError(f"{path}: profiles must be a non-empty object")
    profiles: dict[str, set[str]] = {}
    for name, keys in raw_profiles.items():
        if not isinstance(name, str) or not name:
            raise RuntimeError(f"{path}: profile names must be non-empty strings")
        if not isinstance(keys, list) or not keys or not all(isinstance(key, str) and key for key in keys):
            raise RuntimeError(f"{path}: profile {name!r} must contain non-empty string keys")
        if len(keys) != len(set(keys)):
            raise RuntimeError(f"{path}: profile {name!r} contains duplicate keys")
        profiles[name] = set(keys)
    return profiles


def resolve_ignored(profile: str | None, explicit: list[str]) -> set[str]:
    ignored = {key for key in explicit if key}
    if profile:
        profiles = load_profiles()
        if profile not in profiles:
            raise RuntimeError(f"unknown persistence profile: {profile}")
        ignored.update(profiles[profile])
    return ignored


def head_bytes(path: Path) -> bytes | None:
    proc = subprocess.run(
        ["git", "show", f"HEAD:{path.as_posix()}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else None


def parse_json(raw: bytes, label: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:  # pragma: no cover - diagnostic path
        raise RuntimeError(f"{label} is not valid UTF-8 JSON: {exc}") from exc


def prune(path: Path, ignored: set[str]) -> str:
    if not path.is_file():
        return "MISSING"
    previous = head_bytes(path)
    if previous is None:
        return "UNTRACKED"
    current = path.read_bytes()
    if current == previous:
        return "IDENTICAL"
    old_obj = strip_keys(parse_json(previous, f"HEAD:{path}"), ignored)
    new_obj = strip_keys(parse_json(current, str(path)), ignored)
    if old_obj != new_obj:
        return "MATERIAL"
    path.write_bytes(previous)
    return "RESTORED_VOLATILE_ONLY"


def self_test() -> int:
    profiles = load_profiles()
    assert "source_signal_transaction" in profiles
    assert "last_seen_at" in profiles["source_signal_transaction"]
    assert "source_health" in profiles
    assert "semantic_sha256" not in profiles["source_health"]
    assert resolve_ignored("structured_alerts", []) == {"generated_at"}
    assert resolve_ignored("threads_state", ["temporary_test_key"]) == {
        "last_auth_verified_at", "temporary_test_key"
    }

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
        path = root / "state.json"
        path.write_text('{"generated_at":"old","items":[{"id":1,"value":"A"}]}\n', encoding="utf-8")
        subprocess.run(["git", "add", "state.json"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)

        path.write_text('{"generated_at":"new","items":[{"id":1,"value":"A"}]}\n', encoding="utf-8")
        here = Path.cwd()
        try:
            import os
            os.chdir(root)
            assert prune(Path("state.json"), {"generated_at"}) == "RESTORED_VOLATILE_ONLY"
            assert b'"old"' in path.read_bytes()
            path.write_text('{"generated_at":"new","items":[{"id":1,"value":"B"}]}\n', encoding="utf-8")
            assert prune(Path("state.json"), {"generated_at"}) == "MATERIAL"
            assert b'"B"' in path.read_bytes()
        finally:
            os.chdir(here)
    print("VÂLCEA CLAR volatile JSON write gate self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--profile")
    parser.add_argument("--ignore-key", action="append", default=[])
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.paths:
        parser.error("at least one JSON path is required")
    try:
        ignored = resolve_ignored(args.profile, args.ignore_key)
    except RuntimeError as exc:
        parser.error(str(exc))
    if not ignored:
        parser.error("at least one --profile or --ignore-key is required")
    summary: dict[str, str] = {}
    for raw_path in args.paths:
        path = Path(raw_path)
        summary[raw_path] = prune(path, ignored)
    print(json.dumps({
        "profile": args.profile,
        "ignored_keys": sorted(ignored),
        "paths": summary,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
