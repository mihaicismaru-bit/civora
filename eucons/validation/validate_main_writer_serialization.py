#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "local-news-os-vnext-valcea-shadow-migration.yml"
PERSIST_MARKER = "      - name: Persist harness repair and latest shadow acceptance receipt\n"
NEXT_MARKER = "\n      - name: Enforce shadow acceptance result\n"
CHECKOUT_REF = "          ref: ${{ github.event_name == 'pull_request' && github.event.pull_request.head.sha || 'main' }}\n"
ALLOWED_P18_PATHS = (
    "local-news-os/vnext/instances/valcea/migration/p18_shadow_migration.py",
    "local-news-os/vnext/acceptance/valcea-p18-shadow-latest.json",
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
    require("  pull_request:\n" in text, "shadow workflow lost read-only pull-request validation")
    require(
        "  push:\n    branches: [main]\n    paths:\n" in text,
        "shadow workflow push trigger is not main-only",
    )
    require("          fetch-depth: 0\n" in text, "shadow checkout must retain full ancestry")
    require(CHECKOUT_REF in text, "shadow checkout is not pinned to PR exact-head or canonical main")
    require(
        'run: echo "CHECKOUT_HEAD_SHA=$(git rev-parse HEAD)" >> "$GITHUB_ENV"' in text,
        "shadow workflow no longer captures exact checkout head",
    )

    block = persist_block(text)
    require(
        "        if: github.event_name != 'pull_request'\n" in block,
        "pull requests can reach the persistence step",
    )
    require("git fetch origin main" in block, "shadow writer lacks fresh canonical main fetch")
    require('local_head="$(git rev-parse HEAD)"' in block, "shadow writer lacks local head readback")
    require('remote_main="$(git rev-parse origin/main)"' in block, "shadow writer lacks remote main readback")
    require(
        'if [ "$local_head" != "$remote_main" ]; then' in block,
        "shadow writer no longer requires exact canonical-main equality",
    )
    require(
        'FAIL canonical main moved during shadow run: checkout=$local_head remote=$remote_main' in block,
        "canonical-main drift no longer fails closed",
    )
    require("exit 2" in block, "canonical-main drift lacks hard failure")
    require("git diff --cached --name-only" in block and "grep -Ev" in block, "staged write allowlist guard missing")
    for path in ALLOWED_P18_PATHS:
        require(path in block, f"owned P18 path missing from persist block: {path}")
    require("FAIL P18 persistence escaped allowlist:" in block, "unexpected-path failure marker missing")
    require("git push origin HEAD:main" in block, "shadow writer main push missing")

    require("git pull --rebase origin main" not in block, "unsafe pull/rebase writer replay pattern restored")
    require("git rebase origin/main" not in block, "writer must not rebase generated commits onto moving main")
    require("git push --force" not in block and "git push -f" not in block, "force push is forbidden")
    require(text.count("git push origin HEAD:main") == 1, "shadow workflow has multiple main push sites")


def main() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    validate_text(text)
    print("PASS: shadow writer is PR-read-only, exact-main-bound, path-bounded and non-rebasing")


if __name__ == "__main__":
    main()
