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
        "missing PR read-only validation",
        lambda: validator.validate_text(text.replace("  pull_request:\n", "  pull_request_disabled:\n", 1)),
    )
    must_fail(
        "non-main push trigger",
        lambda: validator.validate_text(text.replace("    branches: [main]\n", "    branches: ['**']\n", 1)),
    )
    must_fail(
        "unpinned checkout",
        lambda: validator.validate_text(text.replace(validator.CHECKOUT_REF, "          ref: ${{ github.sha }}\n", 1)),
    )
    must_fail(
        "shallow checkout",
        lambda: validator.validate_text(text.replace("          fetch-depth: 0\n", "          fetch-depth: 1\n", 1)),
    )
    must_fail(
        "PR persistence enabled",
        lambda: validator.validate_text(text.replace("        if: github.event_name != 'pull_request'\n", "        if: always()\n", 1)),
    )
    must_fail(
        "missing fresh main fetch",
        lambda: validator.validate_text(text.replace("git fetch origin main", "git status --short", 1)),
    )
    must_fail(
        "weakened exact-main equality",
        lambda: validator.validate_text(
            text.replace('if [ "$local_head" != "$remote_main" ]; then', 'if [ -z "$local_head" ]; then', 1)
        ),
    )
    must_fail(
        "missing staged-path allowlist",
        lambda: validator.validate_text(text.replace("grep -Ev", "grep -E", 1)),
    )

    persist = validator.persist_block(text)
    with_rebase = persist.replace("git commit -m", "git rebase origin/main\n          git commit -m", 1)
    must_fail("rebase replay restored", lambda: validator.validate_text(text.replace(persist, with_rebase, 1)))

    must_fail(
        "force push",
        lambda: validator.validate_text(text.replace("git push origin HEAD:main", "git push --force origin HEAD:main", 1)),
    )
    must_fail(
        "duplicate push site",
        lambda: validator.validate_text(text.replace("git push origin HEAD:main", "git push origin HEAD:main\n          git push origin HEAD:main", 1)),
    )

    print("PASS: strict main-writer serialization guard fails closed on cross-branch and moving-main regressions")


if __name__ == "__main__":
    main()
