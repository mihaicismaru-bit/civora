#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "eucons"

BANNED_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    "htmlcov",
    "build",
    "dist",
}
BANNED_FILES = {".DS_Store", "Thumbs.db", "Desktop.ini"}
BANNED_SUFFIXES = {".pyc", ".pyo", ".tmp", ".temp", ".bak", ".orig", ".swp", ".swo"}


def violations() -> list[str]:
    found: list[str] = []
    for path in sorted(TARGET.rglob("*")):
        rel_target = path.relative_to(TARGET)
        rel_repo = path.relative_to(ROOT).as_posix()
        if any(part in BANNED_DIRS for part in rel_target.parts[:-1]):
            found.append(rel_repo)
            continue
        if path.is_dir() and path.name in BANNED_DIRS:
            found.append(rel_repo + "/")
            continue
        if path.is_file():
            if path.name in BANNED_FILES or path.suffix.lower() in BANNED_SUFFIXES or path.name.endswith("~"):
                found.append(rel_repo)
    return found


def main() -> None:
    found = violations()
    if found:
        print("EUCONS_REPO_HYGIENE=FAIL")
        for item in found:
            print(item)
        raise SystemExit(1)
    print("EUCONS_REPO_HYGIENE=PASS")


if __name__ == "__main__":
    main()
