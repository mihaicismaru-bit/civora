#!/usr/bin/env python3
"""Fail closed if the active VÂLCEA CLAR product regains a GPT Sites surface.

Historical evidence and validation ledgers are deliberately outside this scan.
The guard covers active workflows, scripts, public-site configuration/runtime,
and reader assets so a generator, bridge, build target, or deployment reference
cannot silently recreate the retired surface.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ACTIVE_ROOTS = (
    REPO / ".github" / "workflows",
    REPO / "valcea-clar" / "scripts",
    REPO / "valcea-clar" / "site",
    REPO / "valcea-clar" / "web",
)
TEXT_SUFFIXES = {
    ".css", ".html", ".js", ".json", ".md", ".mjs", ".py", ".sh",
    ".txt", ".yaml", ".yml",
}
MARKERS = (
    "chatgpt-sites",
    "chatgpt sites",
    "gpt-sites",
    "gpt sites",
    "chatgpt_sites",
    "gpt_sites",
    "build_sites_export.py",
    "build_chatgpt_sites_overlay.py",
    "overlay_runtime_export.py",
    "public_ux_export_contract.py",
    "public_ux_overlay.py",
    "chatgpt-sites-live-bridge",
    "chatgpt-sites-route-bridge",
)
SELF = Path(__file__).resolve()


def candidates() -> list[Path]:
    rows: list[Path] = []
    for root in ACTIVE_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.resolve() == SELF:
                continue
            if path.suffix.lower() in TEXT_SUFFIXES:
                rows.append(path)
    return sorted(rows)


def main() -> int:
    hits: list[str] = []
    for path in candidates():
        rel = path.relative_to(REPO).as_posix()
        lowered_path = rel.lower()
        path_markers = [marker for marker in MARKERS if marker in lowered_path]
        if path_markers:
            hits.append(f"{rel}: path contains {', '.join(sorted(set(path_markers)))}")
        try:
            text = path.read_text(encoding="utf-8", errors="replace").lower()
        except OSError as exc:
            hits.append(f"{rel}: unreadable ({exc})")
            continue
        content_markers = [marker for marker in MARKERS if marker in text]
        if content_markers:
            hits.append(f"{rel}: content contains {', '.join(sorted(set(content_markers)))}")

    if hits:
        print("Active GPT Sites surface detected:")
        for hit in hits:
            print(f"- {hit}")
        return 1

    print("VÂLCEA CLAR active GPT Sites surface: ABSENT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
