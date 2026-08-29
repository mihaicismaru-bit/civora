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
CHECKOUT_REF = "ref: ${{ github.event_name == 'pull_request' && github.event.pull_request.head.sha || 'main' }}"


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
    require(CHECKOUT_REF in text, "shadow workflow does not pin writer events to canonical main")
    require(
        'run: echo "CHECKOUT_HEAD_SHA=$(git rev-parse HEAD)" >> "$GITHUB_ENV"' in text,
        "shadow workflow does not capture the exact checkout head",
    )

    block = persist_block(text)
    require(
        "        if: github.event_name != 'pull_request'\n" in block,
        "shadow writer persist step is not explicitly disabled for pull requests",
    )
    require("git fetch origin main" in block, "shadow writer lacks fresh main fetch")
    require(
        'local_head="$(git rev-parse HEAD)"' in block,
        "shadow writer lacks local-head capture",
    )
    require(
        'remote_main="$(git rev-parse origin/main)"' in block,
        "shadow writer lacks remote-main capture",
    )
    require(
        'if [ "$local_head" != "$remote_main" ]; then' in block,
        "shadow writer lacks exact-current-main equality guard",
    )
    require(
        'exit 2' in block,
        "shadow writer exact-current-main guard does not fail closed",
    )
    require(ALLOWED_PATH_GUARD in block, "shadow writer allowed-path guard missing or broadened")
    require("git push origin HEAD:main" in block, "shadow writer main push missing")
    require("git pull --rebase origin main" not in block, "unsafe pull/rebase writer replay pattern restored")
    require("git rebase origin/main" not in block, "writer rebase onto moving main is forbidden")
    require("git push --force" not in block and "git push -f" not in block, "force push is forbidden")
    require(text.count("git push origin HEAD:main") == 1, "shadow workflow has multiple main push sites")


def main() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    validate_text(text)
    print("PASS: shadow migration writer is main-only, exact-current-main-bound and path-bounded")


if __name__ == "__main__":
    main()
