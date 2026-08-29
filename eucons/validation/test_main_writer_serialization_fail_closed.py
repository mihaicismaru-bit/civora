#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = ROOT / "eucons" / "validation" / "validate_main_writer_serialization.py"
WORKFLOW = ROOT / ".github" / "workflows" / "local-news-os-vnext-valcea-shadow-migration.yml"


def load_validator():
    spec = importlib.util.spec_from_file_location("eucons_main_writer_serialization", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load main writer serialization validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def must_fail(label: str, fn) -> None:
    try:
        fn()
    except ValueError:
        return
    raise AssertionError(f"{label} failed open")


def main() -> None:
    validator = load_validator()
    text = WORKFLOW.read_text(encoding="utf-8")
    validator.validate_text(text)

    must_fail(
        "non-main push trigger",
        lambda: validator.validate_text(text.replace("    branches: [main]\n", "", 1)),
    )
    must_fail(
        "writer checkout not pinned to canonical main",
        lambda: validator.validate_text(text.replace(validator.CHECKOUT_REF, "ref: ${{ github.sha }}", 1)),
    )
    must_fail(
        "missing exact checkout capture",
        lambda: validator.validate_text(
            text.replace('run: echo "CHECKOUT_HEAD_SHA=$(git rev-parse HEAD)" >> "$GITHUB_ENV"', 'run: echo "CHECKOUT_HEAD_SHA=${{ github.sha }}" >> "$GITHUB_ENV"', 1)
        ),
    )
    must_fail(
        "pull-request persistence not disabled",
        lambda: validator.validate_text(
            text.replace("        if: github.event_name != 'pull_request'\n", "", 1)
        ),
    )
    must_fail(
        "missing fresh main fetch",
        lambda: validator.validate_text(text.replace("git fetch origin main", "git status --short", 1)),
    )
    must_fail(
        "missing local head capture",
        lambda: validator.validate_text(
            text.replace('local_head="$(git rev-parse HEAD)"', 'local_head="${GITHUB_SHA}"', 1)
        ),
    )
    must_fail(
        "missing remote main capture",
        lambda: validator.validate_text(
            text.replace('remote_main="$(git rev-parse origin/main)"', 'remote_main="${GITHUB_SHA}"', 1)
        ),
    )
    must_fail(
        "missing exact-current-main guard",
        lambda: validator.validate_text(
            text.replace('if [ "$local_head" != "$remote_main" ]; then', 'if [ -z "$remote_main" ]; then', 1)
        ),
    )
    must_fail(
        "broadened allowed paths",
        lambda: validator.validate_text(text.replace(validator.ALLOWED_PATH_GUARD, "grep -Ev '^$'", 1)),
    )
    persist = validator.persist_block(text)
    unsafe_pull = persist.replace("git fetch origin main", "git pull --rebase origin main\n          git fetch origin main", 1)
    must_fail(
        "unsafe pull-rebase replay",
        lambda: validator.validate_text(text.replace(persist, unsafe_pull, 1)),
    )
    unsafe_rebase = persist.replace("git push origin HEAD:main", "git rebase origin/main\n          git push origin HEAD:main", 1)
    must_fail(
        "writer rebase restored",
        lambda: validator.validate_text(text.replace(persist, unsafe_rebase, 1)),
    )
    must_fail(
        "force push",
        lambda: validator.validate_text(text.replace("git push origin HEAD:main", "git push --force origin HEAD:main", 1)),
    )

    print("PASS: main writer serialization guard fails closed on cross-branch replay regressions")


if __name__ == "__main__":
    main()
