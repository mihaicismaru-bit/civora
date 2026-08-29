#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "local-news-os-vnext-valcea-shadow-migration.yml"
PERSIST_MARKER = "      - name: Persist harness repair and latest shadow acceptance receipt\n"
NEXT_MARKER = "\n      - name: Enforce shadow acceptance result\n"
ALLOWED_PATH_GUARD = (
    "grep -Ev '^(local-news-os/vnext/instances/valcea/migration/p18_shadow_migration\\.py|"
    "local-news-os/vnext/acceptance/valcea-p18-shadow-latest\\.json)$'"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def persist_block(text: str) -> str:
    require(PERSIST_MARKER in text, "shadow writer persist step missing")
    start = text.index(PERSIST_MARKER)
    end = text.find(NEXT_MARKER, start)
    require(end > start, "shadow writer persist step boundary missing")
    return text[start:end]


def validate_text(text: str) -> None:
    require(
        "  push:\n    branches: [main]\n    paths:\n" in text,
        "shadow workflow push trigger is not main-only",
    )
    block = persist_block(text)
    require(
        "        if: github.ref == 'refs/heads/main'\n" in block,
        "shadow writer persist step lacks explicit main-ref guard",
    )
    require(
        'if [[ "${GITHUB_REF}" != "refs/heads/main" ]]; then' in block,
        "shadow writer lacks runtime main-ref assertion",
    )
    require("git fetch origin main" in block, "shadow writer lacks fresh main fetch")
    require(
        'git merge-base --is-ancestor "${GITHUB_SHA}" origin/main' in block,
        "shadow writer lacks trigger-SHA ancestry guard",
    )
    require("git rebase origin/main" in block, "shadow writer lacks bounded rebase onto fresh main")
    require(
        "git diff --name-only origin/main...HEAD" in block,
        "shadow writer lacks post-rebase diff inspection",
    )
    require(ALLOWED_PATH_GUARD in block, "shadow writer allowed-path guard missing or broadened")
    require("git push origin HEAD:main" in block, "shadow writer main push missing")
    require("git pull --rebase origin main" not in block, "unsafe pull/rebase writer replay pattern restored")
    require("git push --force" not in block and "git push -f" not in block, "force push is forbidden")
    require(text.count("git push origin HEAD:main") == 1, "shadow workflow has multiple main push sites")


def main() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    validate_text(text)
    print("PASS: shadow migration writer is main-only, ancestry-bound and path-bounded")


if __name__ == "__main__":
    main()
