#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_CONFIG = Path("local-news-os/persistence/repository_scope.json")


class ScopeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScopeConfig:
    scope_id: str
    include: tuple[str, ...]
    exclude: tuple[str, ...]


def _run_git(args: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise ScopeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout


def _load_config(path: Path) -> tuple[ScopeConfig, str]:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("schema_version") != 1:
        raise ScopeError("repository scope schema_version must be 1")
    scope_id = str(payload.get("scope_id") or "").strip()
    include = tuple(str(v).strip() for v in payload.get("include", []) if str(v).strip())
    exclude = tuple(str(v).strip() for v in payload.get("exclude", []) if str(v).strip())
    if not scope_id or not include:
        raise ScopeError("repository scope requires scope_id and at least one include pattern")
    return ScopeConfig(scope_id=scope_id, include=include, exclude=exclude), hashlib.sha256(raw).hexdigest()


def _matches(path: str, config: ScopeConfig) -> bool:
    included = any(fnmatch.fnmatchcase(path, pattern) for pattern in config.include)
    if not included:
        return False
    return not any(fnmatch.fnmatchcase(path, pattern) for pattern in config.exclude)


def _tree_entries(ref: str, config: ScopeConfig, cwd: Path | None = None) -> list[tuple[str, str]]:
    output = _run_git(["ls-tree", "-r", "--full-tree", ref], cwd=cwd)
    entries: list[tuple[str, str]] = []
    for line in output.splitlines():
        try:
            meta, path = line.split("\t", 1)
            _mode, obj_type, sha = meta.split(" ", 2)
        except ValueError as exc:
            raise ScopeError(f"malformed git ls-tree line: {line!r}") from exc
        if obj_type == "blob" and _matches(path, config):
            entries.append((path, sha))
    entries.sort()
    return entries


def _fingerprint(entries: Iterable[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for path, sha in entries:
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def describe(ref: str, config: ScopeConfig, config_sha256: str, cwd: Path | None = None) -> dict:
    head = _run_git(["rev-parse", ref], cwd=cwd).strip()
    entries = _tree_entries(ref, config, cwd=cwd)
    return {
        "schema_version": 1,
        "scope_id": config.scope_id,
        "repository_head": head,
        "scope_fingerprint_sha256": _fingerprint(entries),
        "scope_entry_count": len(entries),
        "scope_config_sha256": config_sha256,
    }


def compare(base_ref: str, current_ref: str, config: ScopeConfig, config_sha256: str, cwd: Path | None = None) -> dict:
    base = describe(base_ref, config, config_sha256, cwd=cwd)
    current = describe(current_ref, config, config_sha256, cwd=cwd)
    scope_changed = base["scope_fingerprint_sha256"] != current["scope_fingerprint_sha256"]
    return {
        "schema_version": 1,
        "scope_id": config.scope_id,
        "base": base,
        "current": current,
        "repository_changed": base["repository_head"] != current["repository_head"],
        "scope_changed": scope_changed,
        "reconciliation_required": scope_changed,
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="civora-scope-") as td:
        root = Path(td)
        _run_git(["init", "-q"], cwd=root)
        _run_git(["config", "user.email", "scope-test@example.invalid"], cwd=root)
        _run_git(["config", "user.name", "Scope Test"], cwd=root)
        (root / "local-news-os/core").mkdir(parents=True)
        (root / "valcea-clar/site").mkdir(parents=True)
        (root / "partener-eu").mkdir(parents=True)
        (root / ".github/workflows").mkdir(parents=True)
        (root / "local-news-os/core/engine.py").write_text("x=1\n", encoding="utf-8")
        (root / "valcea-clar/site/integration.json").write_text("{}\n", encoding="utf-8")
        (root / "partener-eu/state.json").write_text('{"n":1}\n', encoding="utf-8")
        (root / ".github/workflows/local-news-os-core.yml").write_text("name: core\n", encoding="utf-8")
        _run_git(["add", "."], cwd=root)
        _run_git(["commit", "-q", "-m", "base"], cwd=root)
        base = _run_git(["rev-parse", "HEAD"], cwd=root).strip()

        config = ScopeConfig(
            scope_id="test-scope",
            include=(
                "local-news-os/**",
                "valcea-clar/**",
                ".github/workflows/local-news-os-*.yml",
                ".github/workflows/valcea-clar-*.yml",
            ),
            exclude=(),
        )
        config_sha = "self-test"
        first = describe("HEAD", config, config_sha, cwd=root)
        second = describe("HEAD", config, config_sha, cwd=root)
        assert first == second

        (root / "partener-eu/state.json").write_text('{"n":2}\n', encoding="utf-8")
        _run_git(["add", "."], cwd=root)
        _run_git(["commit", "-q", "-m", "unrelated"], cwd=root)
        unrelated = compare(base, "HEAD", config, config_sha, cwd=root)
        assert unrelated["repository_changed"] is True
        assert unrelated["scope_changed"] is False
        unrelated_head = _run_git(["rev-parse", "HEAD"], cwd=root).strip()

        (root / "local-news-os/core/engine.py").write_text("x=2\n", encoding="utf-8")
        _run_git(["add", "."], cwd=root)
        _run_git(["commit", "-q", "-m", "relevant"], cwd=root)
        relevant = compare(unrelated_head, "HEAD", config, config_sha, cwd=root)
        assert relevant["repository_changed"] is True
        assert relevant["scope_changed"] is True
        assert relevant["reconciliation_required"] is True

        print("REPOSITORY_SCOPE_FINGERPRINT_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute a deterministic repository fingerprint for a configured product scope.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--base-ref")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    config, config_sha = _load_config(args.config)
    payload = compare(args.base_ref, args.ref, config, config_sha) if args.base_ref else describe(args.ref, config, config_sha)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
