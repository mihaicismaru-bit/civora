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
        "missing step main-ref guard",
        lambda: validator.validate_text(
            text.replace("        if: github.ref == 'refs/heads/main'\n", "", 1)
        ),
    )
    must_fail(
        "missing runtime main-ref assertion",
        lambda: validator.validate_text(
            text.replace('if [[ "${GITHUB_REF}" != "refs/heads/main" ]]; then', 'if [[ -z "${GITHUB_REF}" ]]; then', 1)
        ),
    )
    must_fail(
        "missing fresh main fetch",
        lambda: validator.validate_text(text.replace("git fetch origin main", "git status --short", 1)),
    )
    must_fail(
        "missing trigger ancestry guard",
        lambda: validator.validate_text(
            text.replace('git merge-base --is-ancestor "${GITHUB_SHA}" origin/main', "git merge-base origin/main HEAD", 1)
        ),
    )
    must_fail(
        "missing bounded rebase",
        lambda: validator.validate_text(text.replace("git rebase origin/main", "git status --short", 1)),
    )
    must_fail(
        "missing post-rebase diff guard",
        lambda: validator.validate_text(
            text.replace("git diff --name-only origin/main...HEAD", "git diff --name-only HEAD^...HEAD", 1)
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
    must_fail(
        "force push",
        lambda: validator.validate_text(text.replace("git push origin HEAD:main", "git push --force origin HEAD:main", 1)),
    )

    print("PASS: main writer serialization guard fails closed on cross-branch replay regressions")


if __name__ == "__main__":
    main()
