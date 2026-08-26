#!/usr/bin/env python3
"""Audit tracked repository weight without deleting anything.

Reports definite tracked junk, large files/media, and duplicate paths that point to
an identical Git blob. Protected operational/evidence paths are labelled so a
cleanup review does not accidentally remove canonical or deployment state.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
import subprocess
import sys
from typing import Iterable

DEFAULT_LARGE_BYTES = 512 * 1024

PROTECTED_PREFIXES = (
    "valcea-clar/site/runtime/",
    "valcea-clar/dist/",
    "valcea-clar/validation/",
    "valcea-clar/private-evidence/",
    "partener-eu/validation/",
    "partener-eu/private-evidence/",
    "private-evidence/",
)

JUNK_DIR_COMPONENTS = {
    "__pycache__",
    "node_modules",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".turbo",
    ".parcel-cache",
    ".cache",
    ".vite",
    ".nyc_output",
    ".idea",
    ".vscode-test",
}

JUNK_EXACT_NAMES = {
    ".DS_Store",
    "Thumbs.db",
    "Desktop.ini",
}

JUNK_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".bak",
    ".backup",
    ".orig",
    ".rej",
    ".tmp",
    ".temp",
    ".swp",
    ".swo",
)

MEDIA_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".svg",
    ".ico",
    ".mp4",
    ".mov",
    ".webm",
    ".mp3",
    ".wav",
    ".pdf",
    ".zip",
}


@dataclass(frozen=True)
class TrackedFile:
    path: str
    sha: str
    size: int
    protected: bool
    junk: bool
    media: bool


def git(*args: str, input_text: str | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout


def is_protected(path: str) -> bool:
    return path.startswith(PROTECTED_PREFIXES)


def is_junk(path: str) -> bool:
    p = PurePosixPath(path)
    if any(part in JUNK_DIR_COMPONENTS for part in p.parts):
        return True
    name = p.name
    if name in JUNK_EXACT_NAMES or name.startswith("._"):
        return True
    lower = name.lower()
    if lower.endswith(JUNK_SUFFIXES) or lower.endswith("~"):
        return True
    return False


def is_media(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in MEDIA_SUFFIXES


def tracked_entries() -> list[tuple[str, str]]:
    raw = git("ls-files", "-s", "-z")
    entries: list[tuple[str, str]] = []
    for record in raw.split("\0"):
        if not record:
            continue
        metadata, path = record.split("\t", 1)
        _mode, sha, _stage = metadata.split(" ", 2)
        entries.append((path, sha))
    return entries


def object_sizes(shas: Iterable[str]) -> dict[str, int]:
    unique = sorted(set(shas))
    if not unique:
        return {}
    output = git(
        "cat-file",
        "--batch-check=%(objectname) %(objecttype) %(objectsize)",
        input_text="\n".join(unique) + "\n",
    )
    result: dict[str, int] = {}
    for line in output.splitlines():
        sha, obj_type, size_text = line.split(" ", 2)
        if obj_type != "blob":
            continue
        result[sha] = int(size_text)
    return result


def human_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.2f} {unit}"
        amount /= 1024
    return f"{value} B"


def build_report(large_bytes: int) -> dict[str, object]:
    entries = tracked_entries()
    sizes = object_sizes(sha for _, sha in entries)

    files = [
        TrackedFile(
            path=path,
            sha=sha,
            size=sizes.get(sha, 0),
            protected=is_protected(path),
            junk=is_junk(path),
            media=is_media(path),
        )
        for path, sha in entries
    ]

    by_sha: dict[str, list[TrackedFile]] = defaultdict(list)
    for item in files:
        by_sha[item.sha].append(item)

    duplicate_groups = []
    for sha, group in by_sha.items():
        if len(group) < 2:
            continue
        duplicate_groups.append(
            {
                "sha": sha,
                "blob_bytes": group[0].size,
                "paths": sorted(item.path for item in group),
                "protected_paths": sorted(item.path for item in group if item.protected),
            }
        )

    junk = sorted((item for item in files if item.junk), key=lambda x: (-x.size, x.path))
    large = sorted((item for item in files if item.size >= large_bytes), key=lambda x: (-x.size, x.path))
    large_media = [item for item in large if item.media]

    return {
        "tracked_path_count": len(files),
        "tracked_apparent_bytes": sum(item.size for item in files),
        "unique_current_tree_blob_bytes": sum(sizes.values()),
        "definite_junk": [asdict(item) for item in junk],
        "large_files": [asdict(item) for item in large],
        "large_media": [asdict(item) for item in large_media],
        "duplicate_blob_groups": sorted(
            duplicate_groups,
            key=lambda group: (-int(group["blob_bytes"]), group["paths"]),
        ),
        "large_threshold_bytes": large_bytes,
        "protected_prefixes": list(PROTECTED_PREFIXES),
    }


def print_text(report: dict[str, object]) -> None:
    print("Repository tracked-weight audit")
    print(f"tracked paths: {report['tracked_path_count']}")
    print(f"apparent bytes across paths: {human_bytes(int(report['tracked_apparent_bytes']))}")
    print(f"unique current-tree blob bytes: {human_bytes(int(report['unique_current_tree_blob_bytes']))}")
    print(f"large threshold: {human_bytes(int(report['large_threshold_bytes']))}")

    junk = report["definite_junk"]
    assert isinstance(junk, list)
    print(f"\ndefinite tracked junk: {len(junk)}")
    for item in junk:
        print(f"  {human_bytes(int(item['size'])):>10}  {item['path']}")

    large_media = report["large_media"]
    assert isinstance(large_media, list)
    print(f"\nlarge tracked media/binaries: {len(large_media)}")
    for item in large_media:
        flag = " [PROTECTED]" if item["protected"] else ""
        print(f"  {human_bytes(int(item['size'])):>10}  {item['path']}{flag}")

    dupes = report["duplicate_blob_groups"]
    assert isinstance(dupes, list)
    print(f"\nduplicate current-tree blob groups: {len(dupes)}")
    for group in dupes:
        print(f"  {human_bytes(int(group['blob_bytes'])):>10}  {group['sha'][:12]}  x{len(group['paths'])}")
        for path in group["paths"]:
            print(f"              {path}")
    print("\nNote: identical paths sharing one blob SHA do not multiply Git object-store bytes.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--large-bytes",
        type=int,
        default=DEFAULT_LARGE_BYTES,
        help=f"large-file threshold in bytes (default: {DEFAULT_LARGE_BYTES})",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    parser.add_argument(
        "--fail-on-junk",
        action="store_true",
        help="exit 1 when definite tracked junk is found",
    )
    args = parser.parse_args()
    if args.large_bytes < 1:
        parser.error("--large-bytes must be >= 1")

    try:
        report = build_report(args.large_bytes)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_text(report)

    if args.fail_on_junk and report["definite_junk"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
